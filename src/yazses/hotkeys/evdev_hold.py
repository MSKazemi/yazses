import logging
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


def _is_virtual_device(dev: "evdev.InputDevice") -> bool:
    name = (dev.name or "").lower()
    return any(marker in name for marker in _VIRTUAL_NAME_MARKERS)


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
        self._keyboards: list[evdev.InputDevice] = []

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
        self._keyboards = self._find_keyboards()
        by_fd = {dev.fd: dev for dev in self._keyboards}
        try:
            while not self._stopping:
                # A short timeout lets stop() take effect promptly even when no
                # keys are pressed.
                readable, _, _ = select.select(list(by_fd), [], [], 0.5)
                for fd in readable:
                    dev = by_fd.get(fd)
                    if dev is None:
                        continue
                    for event in dev.read():
                        if event.type != ecodes.EV_KEY or event.code != self._key_code:
                            continue
                        self._handle_event(event.value, time.monotonic())
        except OSError:
            # stop() closes the device fds, which makes select/read raise.
            if not self._stopping:
                raise

    def stop(self) -> None:
        self._stopping = True
        for kb in self._keyboards:
            try:
                kb.close()
            except OSError:
                pass
        self._keyboards = []
