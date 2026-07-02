"""Table-driven transliteration + scheme gate (pure) — ADR-v2-116.

Map romanized input to a native script by longest-match table lookup, and gate on all-ASCII text.
Pure and deterministic; the built-in table is Finglish → Persian.
"""
from __future__ import annotations

# Finglish (romanized Persian) → Persian script. Longest keys matched first.
_FINGLISH = {
    "kh": "خ", "gh": "ق", "ch": "چ", "sh": "ش", "zh": "ژ", "aa": "آ", "oo": "و",
    "ou": "و", "ee": "ی",
    "a": "ا", "b": "ب", "p": "پ", "t": "ت", "s": "س", "j": "ج", "h": "ه", "d": "د",
    "r": "ر", "z": "ز", "f": "ف", "q": "ق", "k": "ک", "g": "گ", "l": "ل", "m": "م",
    "n": "ن", "v": "و", "o": "و", "u": "و", "e": "ه", "i": "ی", "y": "ی", "w": "و",
}
_SCHEMES = {"finglish": _FINGLISH}
_MAX_KEY = 2


def transliterate(latin: str, scheme: str = "finglish") -> str:
    """Transliterate romanized ``latin`` to a native script by longest-match table lookup. Pure."""
    table = _SCHEMES.get(scheme)
    if table is None:
        return latin or ""
    s = latin or ""
    out = []
    i = 0
    while i < len(s):
        if not s[i].isalpha():
            out.append(s[i])
            i += 1
            continue
        matched = False
        for length in range(_MAX_KEY, 0, -1):
            seg = s[i:i + length].lower()
            if seg in table:
                out.append(table[seg])
                i += length
                matched = True
                break
        if not matched:
            out.append(s[i])
            i += 1
    return "".join(out)


def detect_scheme(text: str, enabled_scheme: str = "finglish"):
    """Return ``enabled_scheme`` if ``text`` is all-ASCII letters (so English passes through), else None. Pure."""
    letters = [c for c in (text or "") if c.isalpha()]
    if letters and all(ord(c) < 128 for c in letters):
        return enabled_scheme
    return None
