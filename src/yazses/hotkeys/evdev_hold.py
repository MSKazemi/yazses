import logging
import os
import select
import time
from collections.abc import Callable

import evdev
from evdev import ecodes

from yazses.hotkeys.hold_detector import HoldDetector

log = logging.getLogger(__name__)

# Substrings that mark a device as a virtual/injected input rather than a real
# keyboard. Injection tools (ydotool, wtype) create uinput devices that
# advertise the full key range, so they must never be chosen as the hotkey
# source — they only ever carry synthetic events, never the user's keypresses.
_VIRTUAL_NAME_MARKERS = ("ydotool", "uinput", "virtual", "wtype", "yazses")

# How often the running listener re-reads /dev/input for keyboards plugged in
# after it started (a USB keyboard docked to a laptop). A rescan is one glob plus
# one stat per node, and a node already judged is not reopened, so polling is
# cheap and needs no udev dependency.
_RESCAN_INTERVAL_S = 1.0


def _is_virtual_device(dev: "evdev.InputDevice") -> bool:
    name = (dev.name or "").lower()
    return any(marker in name for marker in _VIRTUAL_NAME_MARKERS)


def _node_identity(path: str) -> int | None:
    """The inode of a device node, or None if it has gone.

    A node removed and recreated under the same name (``event15`` unplugged and a
    different device plugged in) gets a new inode, so a device refused once is
    judged again rather than staying refused under a reused name.
    """
    try:
        return os.stat(path).st_ino
    except OSError:
        return None


def _looks_like_keyboard(dev: "evdev.InputDevice") -> bool:
    """True if the device exposes a full letter row plus Enter (a real keyboard,
    not a power button, hotkey block, or partial keypad)."""
    keys = set(dev.capabilities().get(ecodes.EV_KEY, ()))
    letters = {getattr(ecodes, f"KEY_{c}") for c in "QWERTYUIOPASDFGHJKLZXCVBNM"}
    return ecodes.KEY_ENTER in keys and letters.issubset(keys)


class EvdevHoldListener:
    def __init__(
        self,
        threshold_ms: int,
        on_hold_start: Callable[[int], None],
        on_hold_end: Callable[[], None],
        key_code: int = ecodes.KEY_SPACE,
        produces_char: bool = False,
    ) -> None:
        self._detector = HoldDetector(threshold_ms=threshold_ms)
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._key_code = key_code
        # Character-producing keys (e.g. space) type a character before we can
        # tell a hold from a tap, so they use the hold-threshold gate and the
        # leaked-character cleanup. Modifier keys (right_alt, right_ctrl, …) type
        # nothing, so we start the instant they go down — waiting for the
        # threshold there only clips the first words of speech (the threshold
        # fires on a kernel key-repeat event ~0.5 s after the press).
        self._produces_char = produces_char
        self._recording = False
        self._stopping = False
        # Open devices by the fd they were opened with: stop() closes them from
        # another thread, which resets ``dev.fd`` to -1 under us.
        self._keyboards: dict[int, evdev.InputDevice] = {}
        self._full: set[int] = set()  # fds of devices that look like full keyboards
        self._rejected: dict[str, int] = {}  # path -> inode of a node judged and refused
        self._held_on: int | None = None  # fd the hotkey went down on

    def _find_keyboards(self) -> list[evdev.InputDevice]:
        """Every real keyboard that exposes the hotkey.

        Listening on all of them (not just one) means the hotkey works no matter
        which keyboard the user types on — a laptop with its built-in keyboard
        *and* an external USB keyboard is a normal setup, and a single physical
        key press only ever emits on the one device it came from, so there is no
        double-fire. Virtual injector devices (ydotool/wtype uinput) are excluded
        because they only carry synthetic events, never real keypresses.
        """
        devices = []
        for p in sorted(evdev.list_devices()):
            try:
                devices.append(evdev.InputDevice(p))
            except OSError:
                # A node we can't open (permissions, disappeared) must not abort
                # discovery of the rest.
                continue
        candidates = [
            dev
            for dev in devices
            if ecodes.EV_KEY in dev.capabilities()
            and self._key_code in dev.capabilities()[ecodes.EV_KEY]
        ]
        real = [dev for dev in candidates if not _is_virtual_device(dev)]
        full = [dev for dev in real if _looks_like_keyboard(dev)]

        # Prefer every real device that looks like a full keyboard; else every
        # real device exposing the key; else (with a warning) a virtual one.
        chosen = full or real
        if chosen:
            for dev in chosen:
                log.info("Listening on keyboard device: %s (%s)", dev.name, dev.path)
            return chosen
        if candidates:
            dev = candidates[0]
            log.warning(
                "Only a virtual input device (%s) exposes the hotkey; real key "
                "presses may not be detected. Ensure your hardware keyboard is "
                "in /dev/input and you are in the 'input' group.",
                dev.name,
            )
            return [dev]
        raise RuntimeError(
            "No keyboard device found in /dev/input. "
            "Ensure you are in the 'input' group: sudo usermod -aG input $USER"
        )

    def _find_keyboard(self) -> evdev.InputDevice:
        """The single preferred keyboard (first of :meth:`_find_keyboards`).

        Kept for callers that want one representative device (e.g. ``doctor``);
        the listener itself watches all of them.
        """
        return self._find_keyboards()[0]

    def _handle_event(self, value: int, t: float) -> None:
        """Process one EV_KEY event for the hotkey. Extracted from run() so the
        press/repeat/release state machine is unit-testable without evdev."""
        if value in (1, 2):  # press (1) or key-repeat (2)
            if value == 1:  # only the initial press counts as a leaked char
                self._detector.on_press(t)
            if self._recording:
                return
            if self._produces_char:
                # Tap vs hold can only be told after the threshold (the typed
                # character is cleaned up via leaked_count).
                if self._detector.check(t):
                    leaked = self._detector.leaked_count
                    self._recording = True
                    log.debug("Hold detected, leaked count: %d", leaked)
                    self._on_hold_start(leaked)
            elif value == 1:
                # Modifier key: start on key-down so voice onset isn't clipped.
                self._recording = True
                log.debug("Hold start (modifier key, no leaked chars)")
                self._on_hold_start(0)

        elif value == 0:  # release
            was_recording = self._recording
            self._recording = False
            self._detector.reset()
            if was_recording:
                self._on_hold_end()

    def run(self) -> None:
        for kb in self._find_keyboards():
            self._add(kb)
        next_scan = time.monotonic() + _RESCAN_INTERVAL_S
        while not self._stopping:
            # A short timeout lets stop() take effect promptly even when no
            # keys are pressed, and paces the hotplug rescan.
            try:
                readable, _, _ = select.select(list(self._keyboards), [], [], 0.5)
            except OSError:
                # stop() closes the device fds, which makes select raise.
                if self._stopping:
                    return
                raise
            for fd in readable:
                dev = self._keyboards.get(fd)
                if dev is None:
                    continue
                try:
                    events = list(dev.read())
                except OSError:
                    if self._stopping:
                        return
                    # ENODEV: the keyboard was unplugged. Losing one keyboard
                    # must not take the daemon down with it.
                    self._drop(fd)
                    continue
                for event in events:
                    if event.type != ecodes.EV_KEY or event.code != self._key_code:
                        continue
                    if event.value == 1:
                        self._held_on = fd
                    self._handle_event(event.value, time.monotonic())
            now = time.monotonic()
            if now >= next_scan:
                self._rescan()
                next_scan = now + _RESCAN_INTERVAL_S

    def _add(self, dev: evdev.InputDevice) -> None:
        self._keyboards[dev.fd] = dev
        if _looks_like_keyboard(dev):
            self._full.add(dev.fd)

    def _accepts_hotplugged(self, dev: evdev.InputDevice) -> bool:
        """The startup policy, applied to one device that appeared later: a real
        device exposing the hotkey, and a full keyboard if one is already held.
        A virtual device is never taken on hotplug — it is only a startup
        fallback for when nothing real exists."""
        if _is_virtual_device(dev):
            return False
        if self._key_code not in dev.capabilities().get(ecodes.EV_KEY, ()):
            return False
        return not self._full or _looks_like_keyboard(dev)

    def _rescan(self) -> None:
        """Open keyboards plugged in since the last scan."""
        held = {dev.path for dev in self._keyboards.values()}
        present = set()
        for path in evdev.list_devices():
            present.add(path)
            if path in held:
                continue
            ident = _node_identity(path)
            if ident is None or self._rejected.get(path) == ident:
                continue
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                # udev may not have applied the node's permissions yet; it is
                # tried again on the next scan.
                continue
            try:
                accepted = self._accepts_hotplugged(dev)
            except OSError:
                dev.close()
                continue
            if not accepted or self._stopping:
                self._rejected[path] = ident
                dev.close()
                continue
            self._add(dev)
            log.info("Keyboard connected, now listening on: %s (%s)", dev.name, dev.path)
        for path in list(self._rejected):
            if path not in present:
                del self._rejected[path]

    def _drop(self, fd: int) -> None:
        """Forget a keyboard that went away."""
        dev = self._keyboards.pop(fd, None)
        self._full.discard(fd)
        if dev is None:
            return
        log.info("Keyboard disconnected: %s (%s)", dev.name, dev.path)
        try:
            dev.close()
        except OSError:
            pass
        # A device refused because a full keyboard was held may be the best one
        # left now; judge every node again on the next scan.
        self._rejected.clear()
        if self._held_on == fd:
            self._held_on = None
            if self._recording:
                # The key can never come up on a device that is gone: end the
                # recording now rather than leave it running.
                self._handle_event(0, time.monotonic())
        if not self._keyboards:
            log.warning(
                "No keyboard with the hotkey is connected; waiting for one to be "
                "plugged in."
            )

    def stop(self) -> None:
        self._stopping = True
        for kb in list(self._keyboards.values()):
            try:
                kb.close()
            except OSError:
                pass
        self._keyboards = {}
        self._full = set()
