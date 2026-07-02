"""NATO phonetic spelling → exact characters (pure) — ADR-v2-075.

Map spoken NATO words, digits and symbols to a precise character string, honouring case and
repeat modifiers. Pure and deterministic; the optional biased decode lives elsewhere.
"""
from __future__ import annotations

_NATO = {
    "alpha": "a", "alfa": "a", "bravo": "b", "charlie": "c", "delta": "d", "echo": "e",
    "foxtrot": "f", "golf": "g", "hotel": "h", "india": "i", "juliet": "j", "juliett": "j",
    "kilo": "k", "lima": "l", "mike": "m", "november": "n", "oscar": "o", "papa": "p",
    "quebec": "q", "romeo": "r", "sierra": "s", "tango": "t", "uniform": "u", "victor": "v",
    "whiskey": "w", "xray": "x", "yankee": "y", "zulu": "z",
}
_DIGITS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_SYMBOLS = {
    "dash": "-", "hyphen": "-", "dot": ".", "period": ".", "underscore": "_",
    "space": " ", "at": "@", "hash": "#", "slash": "/", "plus": "+", "star": "*",
    "colon": ":", "comma": ",", "semicolon": ";", "equals": "=",
}
_UPPER = {"capital", "cap", "upper", "uppercase"}
_LOWER = {"lowercase", "lower", "small"}
_REPEAT = {"double": 2, "triple": 3}


def spell_parse(text: str) -> str:
    """Parse a spoken spelling into an exact character string. Pure.

    "capital alpha bravo double lima" → "Abll"; understands digits and symbol words.
    """
    tokens = (text or "").lower().replace("-", " ").split()
    out: list = []
    upper = False
    repeat = 1
    for w in tokens:
        if w in _UPPER:
            upper = True
            continue
        if w in _LOWER:
            upper = False
            continue
        if w in _REPEAT:
            repeat = _REPEAT[w]
            continue
        ch = _NATO.get(w) or _DIGITS.get(w) or _SYMBOLS.get(w)
        if ch is None:
            continue
        if upper and ch.isalpha():
            ch = ch.upper()
        out.append(ch * repeat)
        upper = False
        repeat = 1
    return "".join(out)
