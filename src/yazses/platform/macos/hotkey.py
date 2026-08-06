"""macOS hotkey backend via CGEventTap.

The tap is created with ``kCGEventTapOptionListenOnly`` so the key still
reaches the focused application — same model as Linux's monitor-mode evdev.
For non-character modifier keys (Right Option, Right Ctrl) the leaked-character
backspace workaround is unnecessary and is suppressed at this layer.

Threading: ``run()`` is intended to be called on the daemon's main thread; it
installs a runloop source and calls ``CFRunLoopRun()`` which blocks. Other
threads can call ``stop()`` to break out via ``CFRunLoopStop``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from yazses.hotkeys.hold_detector import HoldDetector

log = logging.getLogger(__name__)


# IOKit/IOLLEvent.h modifier bits (NX_DEVICE*KEYMASK). CGEventGetFlags returns
# a 64-bit mask whose low bits include these device-specific flags.
NX_DEVICELCTLKEYMASK = 0x00000001
NX_DEVICELSHIFTKEYMASK = 0x00000002
NX_DEVICERSHIFTKEYMASK = 0x00000004
NX_DEVICELCMDKEYMASK = 0x00000008
NX_DEVICERCMDKEYMASK = 0x00000010
NX_DEVICELALTKEYMASK = 0x00000020
NX_DEVICERALTKEYMASK = 0x00000040
NX_DEVICERCTLKEYMASK = 0x00002000

# Virtual key codes from HIToolbox/Events.h.
KVK_SPACE = 0x31


# key_id strings → either ("modifier", flag_mask) or ("key", virtual_keycode).
_KEY_MAP: dict[str, tuple[str, int]] = {
    "space": ("key", KVK_SPACE),
    "right_option": ("modifier", NX_DEVICERALTKEYMASK),
    "left_option": ("modifier", NX_DEVICELALTKEYMASK),
    "right_ctrl": ("modifier", NX_DEVICERCTLKEYMASK),
    "left_ctrl": ("modifier", NX_DEVICELCTLKEYMASK),
    "right_shift": ("modifier", NX_DEVICERSHIFTKEYMASK),
    "left_shift": ("modifier", NX_DEVICELSHIFTKEYMASK),
    "right_meta": ("modifier", NX_DEVICERCMDKEYMASK),
    "left_meta": ("modifier", NX_DEVICELCMDKEYMASK),
    # Linux compatibility aliases.
    "right_alt": ("modifier", NX_DEVICERALTKEYMASK),
    "left_alt": ("modifier", NX_DEVICELALTKEYMASK),
}


_CHARACTER_KEYS: frozenset[str] = frozenset({"space"})


def resolve_key_id(key_id: str, default: str = "right_option") -> tuple[str, str, int]:
    """Return (canonical_key_id, kind, value). 'auto' resolves to default."""
    name = key_id.lower()
    if name == "auto":
        name = default
    if name not in _KEY_MAP:
        raise ValueError(
            f"Unknown hotkey {key_id!r}. Supported: {sorted(_KEY_MAP)} or 'auto'."
        )
    kind, value = _KEY_MAP[name]
    return name, kind, value


class MacosHotkey:
    """HotkeyBackend implementation for macOS using CGEventTap."""

    def __init__(
        self,
        key_id: str,
        threshold_ms: int,
        on_hold_start: Callable[[int], None],
        on_hold_end: Callable[[], None],
    ) -> None:
        self._key_id, self._kind, self._value = resolve_key_id(key_id)
        self._produces_char = self._key_id in _CHARACTER_KEYS

        self._detector = HoldDetector(threshold_ms=threshold_ms)
        self._on_hold_start = on_hold_start
        self._on_hold_end = on_hold_end
        self._recording = False

        # Tracks the previous flagsChanged mask so we can derive press/release
        # for modifier keys.
        self._prev_flags: int = 0

        self._runloop = None  # Set when run() starts.
        self._tap = None
        self._loop_source = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # HotkeyBackend interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        from Quartz import (  # type: ignore[import-not-found]
            CFMachPortCreateRunLoopSource,
            CFRunLoopAddSource,
            CFRunLoopGetCurrent,
            CFRunLoopRun,
            CFRunLoopStop,  # noqa: F401  (used by stop())
            CGEventMaskBit,
            CGEventTapCreate,
            CGEventTapEnable,
            kCFRunLoopCommonModes,
            kCGEventFlagsChanged,
            kCGEventKeyDown,
            kCGEventKeyUp,
            kCGEventTapOptionListenOnly,
            kCGHeadInsertEventTap,
            kCGSessionEventTap,
        )

        if self._kind == "modifier":
            event_mask = CGEventMaskBit(kCGEventFlagsChanged)
        else:
            event_mask = CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp)

        self._tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionListenOnly,
            event_mask,
            self._on_event,
            None,
        )
        if not self._tap:
            raise RuntimeError(
                "CGEventTapCreate returned NULL. Grant Accessibility permission to "
                "this process in System Settings → Privacy & Security → Accessibility."
            )

        self._loop_source = CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._runloop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(self._runloop, self._loop_source, kCFRunLoopCommonModes)
        CGEventTapEnable(self._tap, True)
        log.info("CGEventTap enabled for key_id=%s (%s)", self._key_id, self._kind)
        try:
            CFRunLoopRun()
        finally:
            self._teardown()

    def stop(self) -> None:
        self._stop_event.set()
        if self._runloop is not None:
            try:
                from Quartz import CFRunLoopStop  # type: ignore[import-not-found]

                CFRunLoopStop(self._runloop)
            except Exception:
                log.exception("CFRunLoopStop raised")

    @property
    def key_id(self) -> str:
        return self._key_id

    # ------------------------------------------------------------------
    # CGEventTap callback
    # ------------------------------------------------------------------

    def _on_event(self, _proxy, event_type: int, event, _refcon):  # noqa: ANN001
        # Quartz sometimes disables the tap after timeouts; re-enable it so
        # we keep receiving events.
        try:
            from Quartz import (  # type: ignore[import-not-found]
                CGEventTapEnable,
                kCGEventTapDisabledByTimeout,
                kCGEventTapDisabledByUserInput,
            )

            if event_type in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
                if self._tap is not None:
                    CGEventTapEnable(self._tap, True)
                return event
        except ImportError:
            pass

        try:
            self._dispatch(event_type, event)
        except Exception:
            log.exception("Hotkey event dispatch raised")
        return event  # listen-only: pass the event through unchanged

    def _dispatch(self, event_type: int, event) -> None:  # noqa: ANN001
        from Quartz import (  # type: ignore[import-not-found]
            CGEventGetFlags,
            CGEventGetIntegerValueField,
            kCGEventFlagsChanged,
            kCGEventKeyDown,
            kCGEventKeyUp,
            kCGKeyboardEventKeycode,
        )

        if self._kind == "modifier" and event_type == kCGEventFlagsChanged:
            flags = int(CGEventGetFlags(event))
            was_set = bool(self._prev_flags & self._value)
            now_set = bool(flags & self._value)
            self._prev_flags = flags
            if now_set and not was_set:
                self._press()
            elif was_set and not now_set:
                self._release()
        elif self._kind == "key":
            if event_type not in (kCGEventKeyDown, kCGEventKeyUp):
                return
            keycode = int(CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode))
            if keycode != self._value:
                return
            if event_type == kCGEventKeyDown:
                self._press()
            elif event_type == kCGEventKeyUp:
                self._release()

    def _press(self) -> None:
        t = time.monotonic()
        self._detector.on_press(t)
        if not self._recording and self._detector.check(t):
            self._recording = True
            leaked = self._detector.leaked_count if self._produces_char else 0
            self._on_hold_start(leaked)

    def _release(self) -> None:
        was_recording = self._recording
        self._recording = False
        self._detector.reset()
        if was_recording:
            self._on_hold_end()

    def _teardown(self) -> None:
        try:
            from Quartz import (  # type: ignore[import-not-found]
                CFRunLoopRemoveSource,
                CGEventTapEnable,
                kCFRunLoopCommonModes,
            )
        except ImportError:
            return
        if self._tap is not None:
            try:
                CGEventTapEnable(self._tap, False)
            except Exception:
                pass
        if self._loop_source is not None and self._runloop is not None:
            try:
                CFRunLoopRemoveSource(self._runloop, self._loop_source, kCFRunLoopCommonModes)
            except Exception:
                pass
        self._tap = None
        self._loop_source = None
        self._runloop = None
