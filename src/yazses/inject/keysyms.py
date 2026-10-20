"""Character and key-name to X11 keysym mapping.

The RemoteDesktop portal's ``NotifyKeyboardKeysym`` takes an **X11 keysym**, not
a kernel keycode. That is the reason this path can type at all: a keycode names a
*physical* key and therefore depends on the user's layout -- pressing keycode 16
yields ``q`` on QWERTY and ``a`` on AZERTY -- while a keysym names the *character*
and the compositor works out how to produce it. Dictation knows the characters it
wants and nothing whatever about the keyboard in front of the user, so the keysym
call is the only one that can be correct on a layout we never asked about.

Pure and dependency-free so the mapping is testable without a session bus, a
compositor, or a portal -- none of which exist in CI.
"""

from __future__ import annotations

# Keysyms for keys that have no character of their own. Values are from
# X11's keysymdef.h, which is frozen: these numbers are a wire protocol
# shared by X11, XKB, Wayland's xkbcommon and the portal, and cannot change.
_NAMED: dict[str, int] = {
    "backspace": 0xFF08,
    "tab": 0xFF09,
    "return": 0xFF0D,
    "enter": 0xFF0D,
    "escape": 0xFF1B,
    "esc": 0xFF1B,
    "space": 0x0020,
    "delete": 0xFFFF,
    "home": 0xFF50,
    "left": 0xFF51,
    "up": 0xFF52,
    "right": 0xFF53,
    "down": 0xFF54,
    "page_up": 0xFF55,
    "prior": 0xFF55,
    "page_down": 0xFF56,
    "next": 0xFF56,
    "end": 0xFF57,
    "insert": 0xFF63,
}

# Modifier keysyms. Left-hand variants throughout: a compositor treats the two
# as equivalent for the purpose of latching a modifier, and picking one keeps
# press/release symmetric.
_MODIFIERS: dict[str, int] = {
    "shift": 0xFFE1,
    "ctrl": 0xFFE3,
    "control": 0xFFE3,
    "alt": 0xFFE9,
    "meta": 0xFFE9,
    "super": 0xFFEB,
    "cmd": 0xFFEB,
    "win": 0xFFEB,
    "altgr": 0xFFEA,
}

for _i in range(1, 13):  # F1..F12 are contiguous from 0xFFBE.
    _NAMED[f"f{_i}"] = 0xFFBD + _i

# The Unicode escape hatch: any codepoint with no legacy keysym is expressed as
# codepoint | 0x01000000. Below it, two legacy ranges map to the codepoint
# itself -- ASCII printable and Latin-1 -- and must NOT be given the prefix,
# because a compositor looking up 0x01000041 where it expects 0x41 finds nothing.
_UNICODE_FLAG = 0x0100_0000
_LATIN1_MAX = 0x00FF


def char_to_keysym(char: str) -> int:
    """The keysym that produces ``char``.

    Newline and tab are returned as the *named* keys rather than as control
    codepoints: a dictated line break has to behave like pressing Return, and
    0x0A is not a keysym any compositor will act on.
    """
    if len(char) != 1:
        raise ValueError(f"expected a single character, got {len(char)}")
    if char == "\n" or char == "\r":
        return _NAMED["return"]
    if char == "\t":
        return _NAMED["tab"]
    code = ord(char)
    if 0x20 <= code <= 0x7E or 0xA0 <= code <= _LATIN1_MAX:
        return code
    return code | _UNICODE_FLAG


def name_to_keysym(name: str) -> int | None:
    """The keysym for a key *name* (``"Return"``, ``"shift"``, ``"a"``).

    ``None`` rather than an exception for an unknown name: this resolves spoken
    command grammar, where an unrecognised key must degrade to "do nothing"
    rather than take down the daemon thread that called it.
    """
    key = name.strip().lower()
    if not key:
        return None
    if key in _MODIFIERS:
        return _MODIFIERS[key]
    if key in _NAMED:
        return _NAMED[key]
    if len(key) == 1:
        # Single characters keep the caller's case: "A" must be the shifted
        # keysym, not "a". `key` was lowercased for the table lookups above,
        # so read the original.
        return char_to_keysym(name.strip())
    return None


def is_modifier(name: str) -> bool:
    """True when ``name`` names a modifier rather than a key that emits text."""
    return name.strip().lower() in _MODIFIERS


def parse_combo(combo: str) -> tuple[list[int], int] | None:
    """Split ``"ctrl+shift+Left"`` into (modifier keysyms, key keysym).

    ``None`` when the final key is unrecognised -- an unknown *modifier* is
    dropped rather than failing the whole combo, because losing a modifier
    still presses something the user can see and correct, whereas dropping the
    key silently does nothing at all.
    """
    parts = [p for p in combo.split("+") if p.strip()]
    if not parts:
        return None
    key = name_to_keysym(parts[-1])
    if key is None:
        return None
    mods = [m for m in (name_to_keysym(p) for p in parts[:-1]) if m is not None]
    return mods, key


__all__ = ["char_to_keysym", "is_modifier", "name_to_keysym", "parse_combo"]
