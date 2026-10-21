"""Spoken Edit Mode — text operations + command parsing (v2.0.0 Wave A, ADR-v2-003).

Pure functions that apply open-ended edits to the last-injected dictation span, plus
a small parser mapping a spoken phrase to an operation. Kept independent of the
grammar/dispatch + injection layers so they are unit-testable and reusable: the
daemon decides *when* to apply these (command-key gated) and how to realise the change
(re-type / backspace); this module only computes the new text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_LAST_WORD = re.compile(r"(\w+)(\W*)$")

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


@dataclass(frozen=True)
class EditResult:
    text: str
    changed: bool


def _n(token: str, default: int = 1) -> int:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token, default)


# ── operations ─────────────────────────────────────────────────────────────

def replace_words(text: str, old: str, new: str) -> EditResult:
    """Case-insensitive, word-boundary replace of every occurrence of ``old``."""
    if not old:
        return EditResult(text, False)
    pattern = re.compile(rf"\b{re.escape(old)}\b", re.IGNORECASE)
    new_text, count = pattern.subn(new, text)
    return EditResult(new_text, count > 0)


def delete_last_sentence(text: str) -> EditResult:
    stripped = text.rstrip()
    if not stripped:
        return EditResult(text, False)
    parts = _SENTENCE_SPLIT.split(stripped)
    if len(parts) <= 1:
        return EditResult("", True)  # only one sentence → clear it
    return EditResult(" ".join(parts[:-1]), True)


def delete_last_words(text: str, n: int = 1) -> EditResult:
    if n <= 0:
        return EditResult(text, False)
    words = text.split()
    if not words:
        return EditResult(text, False)
    kept = words[:-n] if n < len(words) else []
    return EditResult(" ".join(kept), True)


def _recase_last_word(text: str, fn) -> EditResult:
    m = _LAST_WORD.search(text)
    if not m:
        return EditResult(text, False)
    word = m.group(1)
    replaced = fn(word)
    if replaced == word:
        return EditResult(text, False)
    start = m.start(1)
    return EditResult(text[:start] + replaced + text[m.end(1):], True)


def capitalize_last_word(text: str) -> EditResult:
    return _recase_last_word(text, lambda w: w[:1].upper() + w[1:])


def uppercase_last_word(text: str) -> EditResult:
    return _recase_last_word(text, str.upper)


def lowercase_last_word(text: str) -> EditResult:
    return _recase_last_word(text, str.lower)


# ── parsing ────────────────────────────────────────────────────────────────

_RE_REPLACE = re.compile(
    r"^(?:change|replace)\s+(.+?)\s+(?:to|with)\s+(.+)$", re.IGNORECASE
)
_RE_DEL_SENTENCE = re.compile(
    r"^delete\s+(?:the\s+)?last\s+sentence$", re.IGNORECASE
)
# The count must be a word of its own. With `(\w+)?\s*words?` the regex backtracked into
# a longer word and matched its tail: "delete the last passwords" parsed as a count of
# "pass" (unknown, so 1) plus "words" -- a destructive edit from a word that merely ends
# in "words". tests/test_spoken_edit_does_not_match_a_word_ending_in_words.py holds it.
_RE_DEL_WORDS = re.compile(
    r"^delete\s+(?:the\s+)?last\s+(?:(\w+)\s+)?words?$", re.IGNORECASE
)
_RE_CAP = re.compile(
    r"^capital(?:ize|ise)\s+(?:that|the\s+last\s+word)$", re.IGNORECASE
)
_RE_UPPER = re.compile(
    r"^(?:uppercase|upper case)\s+(?:that|the\s+last\s+word)$", re.IGNORECASE
)
_RE_LOWER = re.compile(
    r"^(?:lowercase|lower case)\s+(?:that|the\s+last\s+word)$", re.IGNORECASE
)


def parse_edit(phrase: str) -> tuple[str, dict] | None:
    """Map a spoken edit phrase to ``(op, args)`` or ``None`` if unrecognised.

    Outer punctuation/whitespace is stripped first (Whisper adds trailing periods).
    """
    p = phrase.strip().strip(".!?,").strip()
    if not p:
        return None
    if m := _RE_REPLACE.match(p):
        return ("replace", {"old": m.group(1).strip(), "new": m.group(2).strip()})
    if _RE_DEL_SENTENCE.match(p):
        return ("delete_sentence", {})
    if m := _RE_DEL_WORDS.match(p):
        return ("delete_words", {"n": _n(m.group(1) or "one")})
    if _RE_CAP.match(p):
        return ("capitalize", {})
    if _RE_UPPER.match(p):
        return ("uppercase", {})
    if _RE_LOWER.match(p):
        return ("lowercase", {})
    return None


_DISPATCH = {
    "replace": lambda text, a: replace_words(text, a["old"], a["new"]),
    "delete_sentence": lambda text, a: delete_last_sentence(text),
    "delete_words": lambda text, a: delete_last_words(text, a.get("n", 1)),
    "capitalize": lambda text, a: capitalize_last_word(text),
    "uppercase": lambda text, a: uppercase_last_word(text),
    "lowercase": lambda text, a: lowercase_last_word(text),
}

# Operations that remove text over a multi-word span → require confirmation
# (human-in-the-loop invariant, ADR-v2-000).
DESTRUCTIVE = frozenset({"delete_sentence", "delete_words"})


def apply_edit(text: str, phrase: str) -> EditResult:
    """Parse ``phrase`` and apply it to ``text``; unchanged if unrecognised."""
    parsed = parse_edit(phrase)
    if parsed is None:
        return EditResult(text, False)
    op, args = parsed
    return _DISPATCH[op](text, args)
