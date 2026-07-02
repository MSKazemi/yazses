"""Spoken key-chord parsing (pure) — ADR-v2-085.

Turn "press control shift P" / "escape twice" / "hit F5" into injectable key chords. Pure and
deterministic; the injector consumes :func:`render_chord` output.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_MODS = {
    "control": "ctrl", "ctrl": "ctrl", "alt": "alt", "option": "alt",
    "shift": "shift", "super": "super", "meta": "super", "command": "super",
    "cmd": "super", "windows": "super", "win": "super",
}
_NAMED = {
    "enter": "Return", "return": "Return", "escape": "Escape", "esc": "Escape",
    "tab": "Tab", "space": "space", "backspace": "BackSpace", "delete": "Delete",
    "up": "Up", "down": "Down", "left": "Left", "right": "Right",
    "home": "Home", "end": "End", "insert": "Insert",
}
_NAMED2 = {"page up": "Prior", "page down": "Next"}
_REPEAT = {"once": 1, "twice": 2, "thrice": 3, "two times": 2, "three times": 3,
           "four times": 4, "five times": 5}


@dataclass(frozen=True)
class KeyChord:
    """A key chord: ``mods`` (ctrl/alt/shift/super) plus a base ``key``."""
    mods: tuple
    key: str


def _resolve_key(rest: str):
    r = rest.strip().lower()
    if not r:
        return None
    if r in _NAMED2:
        return _NAMED2[r]
    if r in _NAMED:
        return _NAMED[r]
    m = re.fullmatch(r"(?:f|function\s+)(\d{1,2})", r)
    if m:
        return f"F{m.group(1)}"
    if len(r) == 1 and (r.isalnum()):
        return r
    return None


def parse_chord(text: str):
    """Parse a spoken chord into a list of :class:`KeyChord` (repeated), or ``None``. Pure."""
    t = (text or "").strip().lower()
    t = re.sub(r"^(?:press|hit|type|key|do|send)\s+", "", t)

    repeat = 1
    m = re.search(r"\s+(once|twice|thrice|two times|three times|four times|five times|(\d+)\s+times)$", t)
    if m:
        if m.group(2):
            repeat = int(m.group(2))
        else:
            repeat = _REPEAT.get(m.group(1), 1)
        t = t[:m.start()].strip()

    tokens = t.split()
    mods = []
    i = 0
    while i < len(tokens) and tokens[i] in _MODS:
        mods.append(_MODS[tokens[i]])
        i += 1
    key = _resolve_key(" ".join(tokens[i:]))
    if key is None:
        return None
    # de-dup modifiers, preserve order
    uniq = tuple(dict.fromkeys(mods))
    return [KeyChord(uniq, key)] * max(1, repeat)


def render_chord(chord: KeyChord) -> str:
    """Render a :class:`KeyChord` as the ``ctrl+shift+p`` form the injector consumes. Pure."""
    return "+".join(list(chord.mods) + [chord.key])
