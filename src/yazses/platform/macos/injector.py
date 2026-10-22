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

# macOS virtual keycodes (Carbon `HIToolbox/Events.h`, kVK_*) for the key names the
# command dispatcher and the spoken capabilities send. Those names are X11-style and
# capitalised ("Return", "BackSpace", "Page_Down"), so the table is keyed lower-case
# and every lookup is lower-cased to match -- as `platform/windows/injector.py` does.
# It used to be keyed "Return"/"Left"/"BackSpace" and looked up lower-cased, so every
# named key missed and fell back to keycode 0, which is the "a" key.
_KEYCODE: dict[str, int] = {
    "return": 0x24, "enter": 0x24,
    "tab": 0x30,
    "space": 0x31,
    "backspace": KVK_DELETE,
    "escape": 0x35, "esc": 0x35,
    "delete": 0x75,  # kVK_ForwardDelete
    "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
    "home": 0x73, "end": 0x77,
    "page_up": 0x74, "prior": 0x74,
    "page_down": 0x79, "next": 0x79,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
    "a": 0x00, "b": 0x0B, "c": 0x08, "d": 0x02, "e": 0x0E,
    "f": 0x03, "g": 0x05, "h": 0x04, "i": 0x22, "j": 0x26,
    "k": 0x28, "l": 0x25, "m": 0x2E, "n": 0x2D, "o": 0x1F,
    "p": 0x23, "q": 0x0C, "r": 0x0F, "s": 0x01, "t": 0x11,
    "u": 0x20, "v": 0x09, "w": 0x0D, "x": 0x07, "y": 0x10, "z": 0x06,
    "slash": 0x2C,
    "0": 0x1D, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
    "5": 0x17, "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19,
}

# Modifier names -> the four CGEvent flag roles. "meta"/"super" are the Command key,
# which sits where a PC keyboard has Super/Windows; "option" is Alt.
_MODIFIER: dict[str, str] = {
    "ctrl": "ctrl", "control": "ctrl",
    "shift": "shift",
    "alt": "alt", "option": "alt",
    "cmd": "cmd", "command": "cmd", "meta": "cmd", "super": "cmd",
}


def resolve_key_combo(combo: str) -> tuple[int, tuple[str, ...]] | None:
    """Resolve ``"cmd+shift+Down"`` to ``(0x7D, ("cmd", "shift"))``. Pure.

    ``None`` when the key or a modifier is unknown, so the caller skips the combo
    rather than pressing keycode 0 (the "a" key).
    """
    parts = [p for p in combo.split("+") if p]
    if not parts:
        return None
    keycode = _KEYCODE.get(parts[-1].lower())
    if keycode is None:
        return None
    mods: list[str] = []
    for raw in parts[:-1]:
        mod = _MODIFIER.get(raw.lower())
        if mod is None:
            return None
        if mod not in mods:
            mods.append(mod)
    return keycode, tuple(mods)


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

        flag_for = {
            "ctrl": kCGEventFlagMaskControl,
            "shift": kCGEventFlagMaskShift,
            "alt": kCGEventFlagMaskAlternate,
            "cmd": kCGEventFlagMaskCommand,
        }

        for combo in keys:
            resolved = resolve_key_combo(combo)
            if resolved is None:
                # Skipped, never sent as keycode 0: that is the "a" key, so an unknown
                # name used to type a stray "a" (or Cmd+A) into the focused app.
                log.warning("macOS injector: cannot express key %r; skipped", combo)
                continue
            keycode, mods = resolved
            flags = 0
            for mod in mods:
                flags |= flag_for[mod]
            for is_down in (True, False):
                event = CGEventCreateKeyboardEvent(None, keycode, is_down)
                if event is None:
                    continue
                if flags:
                    CGEventSetFlags(event, flags)
                CGEventPost(kCGHIDEventTap, event)
