"""Confusable scanning + ASCII skeleton normalization (pure) — ADR-v2-123.

Detect the common Unicode homoglyph hazards (UTS-39 subset): Cyrillic/Greek look-alikes of Latin
letters, fullwidth forms, and invisible/zero-width characters, plus mixed-script words. Pure and
deterministic; the full UTS-39 confusables table stays an optional data extra.
"""
from __future__ import annotations

import re

# Common Cyrillic/Greek homoglyphs of Latin letters (UTS-39 core subset).
_HOMOGLYPHS = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i",
    "ѕ": "s", "ј": "j", "ԁ": "d", "ɡ": "g", "ο": "o", "α": "a", "ν": "v", "ρ": "p",
    "τ": "t", "υ": "u", "ε": "e", "ι": "i", "κ": "k", "Α": "A", "Β": "B", "Ε": "E",
    "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P",
    "Τ": "T", "Χ": "X", "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
}
_INVISIBLE = {"​", "‌", "‍", "⁠", "﻿", "­"}
# ZWNJ and ZWJ are orthography in Persian, Arabic, Urdu and Indic scripts (the half-space in
# می‌خواهم is part of the spelling), so between two non-ASCII letters they are not a hidden character.
# Anywhere else (between ASCII letters, at an edge, next to a digit) they are still flagged.
_JOINER_CONTROLS = {"‌", "‍"}


def _is_orthographic_joiner(text: str, i: int) -> bool:
    """A ZWNJ/ZWJ at ``text[i]`` that sits between two non-ASCII letters. Pure."""
    if text[i] not in _JOINER_CONTROLS or i == 0 or i + 1 >= len(text):
        return False
    before, after = text[i - 1], text[i + 1]
    return (before.isalpha() and not before.isascii()
            and after.isalpha() and not after.isascii())


def _skeleton_char(ch: str) -> str:
    if ch in _INVISIBLE:
        return ""
    if ch in _HOMOGLYPHS:
        return _HOMOGLYPHS[ch]
    if 0xFF01 <= ord(ch) <= 0xFF5E:              # fullwidth ASCII forms
        return chr(ord(ch) - 0xFEE0)
    return ch


def _scripts(word: str) -> set[str]:
    scripts = set()
    for ch in word:
        if "a" <= ch.lower() <= "z":
            scripts.add("latin")
        elif "Ѐ" <= ch <= "ӿ":
            scripts.add("cyrillic")
        elif "Ͱ" <= ch <= "Ͽ":
            scripts.add("greek")
    return scripts


def scan_confusables(text: str) -> list[dict]:
    """Scan ``text`` for glyph hazards → findings ``{index, char/word, kind, suggestion}``. Pure.

    Kinds: ``confusable`` (homoglyph/fullwidth), ``invisible`` (zero-width class), and
    ``mixed-script`` (one word blending Latin with Cyrillic/Greek).
    """
    findings = []
    for i, ch in enumerate(text or ""):
        if ch in _INVISIBLE:
            if _is_orthographic_joiner(text, i):
                continue
            findings.append({"index": i, "char": ch, "kind": "invisible", "suggestion": ""})
        elif ch in _HOMOGLYPHS or 0xFF01 <= ord(ch) <= 0xFF5E:
            findings.append({"index": i, "char": ch, "kind": "confusable",
                             "suggestion": _skeleton_char(ch)})
    for m in re.finditer(r"\S+", text or ""):
        scripts = _scripts(m.group())
        if "latin" in scripts and len(scripts) > 1:
            findings.append({"index": m.start(), "word": m.group(), "kind": "mixed-script",
                             "suggestion": normalize_ascii(m.group())})
    return findings


def normalize_ascii(text: str) -> str:
    """Map homoglyphs/fullwidth forms to their ASCII skeleton and drop invisibles. Pure."""
    return "".join(_skeleton_char(ch) for ch in (text or ""))
