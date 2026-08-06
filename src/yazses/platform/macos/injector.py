"""macOS injector — synthesizes keyboard events via CGEvent.

Text injection uses ``CGEventKeyboardSetUnicodeString`` so any Unicode the STT
engine produces (em-dashes, smart quotes, accented characters) goes through
unchanged. Each CGEvent can carry at most ~20 UTF-16 code units, so the input
is chunked.

Backspace uses the macOS Delete virtual keycode (``kVK_Delete = 0x33``), which
is what every Mac keyboard labels as "Backspace".
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# CGEvent's Unicode string length cap per event.
_CHUNK = 20

KVK_DELETE = 0x33  # macOS "Delete" / "Backspace"


def _utf16_chunks(text: str) -> list[list[int]]:
    """Split *text* into chunks of UTF-16 code units, never splitting a
    surrogate pair across two chunks."""
    if not text:
        return []
    encoded = text.encode("utf-16-le")
    units = [int.from_bytes(encoded[i : i + 2], "little") for i in range(0, len(encoded), 2)]

    chunks: list[list[int]] = []
    i = 0
    while i < len(units):
        end = min(i + _CHUNK, len(units))
        # If we'd split a high surrogate from its low surrogate, back off by one.
        if end < len(units) and 0xD800 <= units[end - 1] <= 0xDBFF:
            end -= 1
        chunks.append(units[i:end])
        i = end
    return chunks


class MacosInjector:
    """InjectorBackend for macOS."""

    def inject(self, text: str) -> None:
        if not text:
            return
        from Quartz import (  # type: ignore[import-not-found]
            CGEventCreateKeyboardEvent,
            CGEventKeyboardSetUnicodeString,
            CGEventPost,
            kCGHIDEventTap,
        )

        for chunk in _utf16_chunks(text):
            for is_down in (True, False):
                event = CGEventCreateKeyboardEvent(None, 0, is_down)
                if event is None:
                    log.warning("CGEventCreateKeyboardEvent returned NULL")
                    return
                CGEventKeyboardSetUnicodeString(event, len(chunk), chunk)
                CGEventPost(kCGHIDEventTap, event)

    def inject_backspaces(self, count: int) -> None:
        if count <= 0:
            return
        from Quartz import (  # type: ignore[import-not-found]
            CGEventCreateKeyboardEvent,
            CGEventPost,
            kCGHIDEventTap,
        )

        for _ in range(count):
            for is_down in (True, False):
                event = CGEventCreateKeyboardEvent(None, KVK_DELETE, is_down)
                if event is None:
                    return
                CGEventPost(kCGHIDEventTap, event)

    def inject_key_sequence(self, keys: list[str]) -> None:
        if not keys:
            return
        from Quartz import (  # type: ignore[import-not-found]
            CGEventCreateKeyboardEvent,
            CGEventPost,
            CGEventSetFlags,
            kCGEventFlagMaskAlternate,
            kCGEventFlagMaskCommand,
            kCGEventFlagMaskControl,
            kCGEventFlagMaskShift,
            kCGHIDEventTap,
        )

        # macOS virtual keycodes for special keys.
        _KEYCODE: dict[str, int] = {
            "Return": 0x24,
            "Left": 0x7B,
            "Right": 0x7C,
            "Down": 0x7D,
            "Up": 0x7E,
            "BackSpace": KVK_DELETE,
            "Tab": 0x30,
            "Escape": 0x35,
            "a": 0x00, "b": 0x0B, "c": 0x08, "d": 0x02, "e": 0x0E,
            "f": 0x03, "g": 0x05, "h": 0x04, "i": 0x22, "j": 0x26,
            "k": 0x28, "l": 0x25, "m": 0x2E, "n": 0x2D, "o": 0x1F,
            "p": 0x23, "q": 0x0C, "r": 0x0F, "s": 0x01, "t": 0x11,
            "u": 0x20, "v": 0x09, "w": 0x0D, "x": 0x07, "y": 0x10, "z": 0x06,
            "slash": 0x2C,
            "0": 0x1D, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
            "5": 0x17, "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19,
        }
        _MOD_FLAGS: dict[str, int] = {
            "ctrl": kCGEventFlagMaskControl,
            "shift": kCGEventFlagMaskShift,
            "alt": kCGEventFlagMaskAlternate,
            "meta": kCGEventFlagMaskCommand,
            "cmd": kCGEventFlagMaskCommand,
        }

        for combo in keys:
            parts = combo.split("+")
            key_name = parts[-1].lower()
            mods = parts[:-1]
            keycode = _KEYCODE.get(key_name, 0)
            flags = 0
            for mod in mods:
                flags |= _MOD_FLAGS.get(mod.lower(), 0)
            for is_down in (True, False):
                event = CGEventCreateKeyboardEvent(None, keycode, is_down)
                if event is None:
                    continue
                if flags:
                    CGEventSetFlags(event, flags)
                CGEventPost(kCGHIDEventTap, event)
