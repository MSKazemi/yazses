"""Natural-language → regex (pure) — ADR-v2-066.

A bounded compositional grammar: counts, character-class units, literal words, quantifiers, and a
``starting with`` anchor. Deterministic and dependency-free; free-form English is deferred.
"""
from __future__ import annotations

import re

_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
# Character-class units (1- or 2-word). Longer keys are matched first.
_UNIT = {
    "capital letter": "[A-Z]", "capital letters": "[A-Z]",
    "lowercase letter": "[a-z]", "lowercase letters": "[a-z]",
    "word character": "\\w", "word characters": "\\w",
    "digit": "\\d", "digits": "\\d",
    "letter": "[A-Za-z]", "letters": "[A-Za-z]",
    "number": "\\d", "numbers": "\\d",
    "whitespace": "\\s", "space": "\\s", "spaces": "\\s",
    "character": ".", "characters": ".",
}
# Literal words → escaped literals.
_LITERAL = {
    "dash": "-", "hyphen": "-", "dot": "\\.", "period": "\\.", "point": "\\.",
    "slash": "/", "underscore": "_", "at sign": "@", "colon": ":", "comma": ",",
    "semicolon": ";", "plus sign": "\\+", "hash": "#", "percent": "%",
}
_FILLER = {"a", "an", "any", "and", "then", "followed", "by", "the", "of", "single"}


def nl_to_regex(text: str):
    """Compile a spoken description into a regex string, or ``None`` if nothing parses. Pure."""
    t = (text or "").lower().strip()

    prefix = ""
    m = re.match(r"(?:lines?\s+)?(?:that\s+)?start(?:s|ing)?\s+with\s+(.*)$", t)
    if m:
        prefix = "^"
        t = m.group(1).strip()

    tokens = t.split()
    out: list = []
    pending = ""   # a quantifier (+, *, ?) to apply to the next emitted atom
    i = 0

    def emit(frag: str) -> None:
        nonlocal pending
        out.append(frag + pending)
        pending = ""

    while i < len(tokens):
        three = " ".join(tokens[i:i + 3])
        two = " ".join(tokens[i:i + 2])
        w = tokens[i]

        if three == "one or more":
            pending = "+"; i += 3; continue
        if three == "zero or more":
            pending = "*"; i += 3; continue
        if w == "optional":
            pending = "?"; i += 1; continue

        if w in _NUM:
            n = _NUM[w]
            unit2 = " ".join(tokens[i + 1:i + 3])
            unit1 = tokens[i + 1] if i + 1 < len(tokens) else ""
            if unit2 in _UNIT:
                emit(f"{_UNIT[unit2]}{{{n}}}"); i += 3; continue
            if unit1 in _UNIT:
                emit(f"{_UNIT[unit1]}{{{n}}}"); i += 2; continue

        if two in _UNIT:
            emit(_UNIT[two]); i += 2; continue
        if two in _LITERAL:
            emit(_LITERAL[two]); i += 2; continue
        if w in _UNIT:
            emit(_UNIT[w]); i += 1; continue
        if w in _LITERAL:
            emit(_LITERAL[w]); i += 1; continue
        if w in _FILLER:
            i += 1; continue
        i += 1   # unknown token → skip

    if not out:
        return None
    return prefix + "".join(out)
