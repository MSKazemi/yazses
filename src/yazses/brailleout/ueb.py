"""Table-driven UEB Braille translation (pure) — ADR-v2-117.

Map text to Unicode Braille cells: Grade 1 is letter/digit/punctuation transcription; Grade 2 adds
the UEB strong wordsigns and groupsigns. Pure and deterministic; full liblouis tables are an
optional heavy backend.
"""
from __future__ import annotations

import re

_LETTERS = {
    "a": "⠁", "b": "⠃", "c": "⠉", "d": "⠙", "e": "⠑", "f": "⠋", "g": "⠛", "h": "⠓",
    "i": "⠊", "j": "⠚", "k": "⠅", "l": "⠇", "m": "⠍", "n": "⠝", "o": "⠕", "p": "⠏",
    "q": "⠟", "r": "⠗", "s": "⠎", "t": "⠞", "u": "⠥", "v": "⠧", "w": "⠺", "x": "⠭",
    "y": "⠽", "z": "⠵",
}
_PUNCT = {
    ".": "⠲", ",": "⠂", ";": "⠆", ":": "⠒", "?": "⠦", "!": "⠖", "'": "⠄", "-": "⠤",
}
_DIGITS = {d: _LETTERS[l] for d, l in zip("1234567890", "abcdefghij")}
_CAPITAL = "⠠"
#: UEB's *capitals word indicator*: dot-6 twice, marking the whole word as capitalised.
#: A single ``⠠`` capitalises only the letter after it, so an all-caps word emitted with
#: one indicator reads back as Title Case -- "ABC" and "Abc" produced the SAME cells, and
#: a reader on a refreshable display or an embossed page has no way to tell. Acronyms are
#: common in dictation, and this is output nobody sighted proofreads.
_CAPITAL_WORD = _CAPITAL * 2
_NUMBER = "⠼"

# UEB strong/alphabetic wordsigns — standalone whole words only.
_WORDSIGNS = {
    "and": "⠯", "for": "⠿", "of": "⠷", "the": "⠮", "with": "⠾", "but": "⠃", "can": "⠉",
    "do": "⠙", "every": "⠑", "from": "⠋", "go": "⠛", "have": "⠓", "just": "⠚",
    "knowledge": "⠅", "like": "⠇", "more": "⠍", "not": "⠝", "people": "⠏", "quite": "⠟",
    "rather": "⠗", "so": "⠎", "that": "⠞", "us": "⠥", "very": "⠧", "will": "⠺",
    "it": "⠭", "you": "⠽", "as": "⠵",
}
# UEB groupsigns usable within a word — matched longest-first.
_GROUPSIGNS = {
    "ing": "⠬", "and": "⠯", "for": "⠿", "the": "⠮", "with": "⠾", "of": "⠷",
    "ch": "⠡", "sh": "⠩", "th": "⠹", "wh": "⠱", "ou": "⠳", "ow": "⠪", "st": "⠌",
    "ar": "⠜", "er": "⠻", "ed": "⠫", "gh": "⠣", "en": "⠢", "in": "⠔",
}
_MAX_GROUP = max(len(k) for k in _GROUPSIGNS)


def _encode_word(word: str, grade: int) -> str:
    lower = word.lower()
    # A single capital letter takes one indicator; a word in capitals takes the capitals
    # WORD indicator. `word.isupper()` is False for a one-letter word only if that letter
    # is not a capital, so "I" and "A" correctly fall through to the single form.
    if word.isupper() and len(word) > 1:
        prefix = _CAPITAL_WORD
    elif word[:1].isupper():
        prefix = _CAPITAL
    else:
        prefix = ""
    if grade >= 2 and lower in _WORDSIGNS:
        return prefix + _WORDSIGNS[lower]
    out = [prefix]
    i = 0
    while i < len(lower):
        matched = False
        if grade >= 2:
            for length in range(min(_MAX_GROUP, len(lower) - i), 1, -1):
                seg = lower[i:i + length]
                if seg in _GROUPSIGNS:
                    out.append(_GROUPSIGNS[seg])
                    i += length
                    matched = True
                    break
        if not matched:
            out.append(_LETTERS.get(lower[i], lower[i]))
            i += 1
    return "".join(out)


def to_braille(text: str, grade: int = 2) -> str:
    """Translate ``text`` to Unicode Braille cells (Grade 1 or 2 UEB subset). Pure.

    Words are contracted per UEB wordsigns/groupsigns when ``grade >= 2``; digit runs get one
    number sign; a leading capital gets the capital indicator; unknown characters pass through.
    """
    out = []
    for tok in re.findall(r"[A-Za-z]+|[0-9]+|\s+|.", text or ""):
        if tok[0].isalpha() and tok.isascii():
            out.append(_encode_word(tok, grade))
        elif tok[0].isdigit():
            out.append(_NUMBER + "".join(_DIGITS[d] for d in tok))
        elif tok.isspace():
            out.append(tok)
        else:
            out.append(_PUNCT.get(tok, tok))
    return "".join(out)
