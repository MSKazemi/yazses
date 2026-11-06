"""Spoken punctuation & formatting → symbols (opt-in).

When ``[commands] voice_punctuation`` is enabled, dictating the *name* of a
punctuation mark inserts the mark: "hello comma world period" → "hello, world.".
Off by default because the words also occur in ordinary speech ("a period of
time"), so it is only safe for users who opt in and adapt their phrasing.

Whisper punctuates on its own, and it punctuates the spoken mark *as a word*:
saying "hello comma world period" commonly comes back as
``"Hello, comma, world period."`` or ``"I went home. Period."``. A literal
word-for-symbol swap then types ``"Hello,,, world."`` and ``"I went home..."``.
The spoken mark is the user's explicit instruction, so it wins over the
decoder's guess at a pause: the ASR mark glued to the phrase's end is dropped,
and an ASR pause mark (``,`` ``;`` ``:``, or the very symbol being inserted)
directly before the phrase is replaced. A different sentence mark before the
phrase (``"Mr. comma"``, ``"Really? comma"``) is kept — it may be meaningful.

All attach-left phrases are replaced in **one** pass, so a symbol this module
has just inserted is never mistaken for decoder punctuation and absorbed by the
next phrase ("a comma period" → "a,.").
"""
from __future__ import annotations

import re

# Formatting phrases → literal (surrounding whitespace is absorbed).
# Longest-first so "new paragraph" is tried before shorter phrases.
_FORMATTING: list[tuple[str, str]] = [
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
    ("newline", "\n"),
    ("tab key", "\t"),
]

# Punctuation that attaches to the preceding word: no space before, keep after.
# ("hello comma" → "hello,"). Alternatives share one symbol.
_ATTACH_LEFT: list[tuple[str, str]] = [
    ("full stop", "."),
    ("period", "."),
    ("question mark", "?"),
    ("exclamation mark", "!"),
    ("exclamation point", "!"),
    ("semicolon", ";"),
    ("semi colon", ";"),
    ("colon", ":"),
    ("comma", ","),
]

# Punctuation an ASR decoder inserts around a spoken mark it heard as a word.
_ASR_MARKS = ",.;:!?"
# Of those, the pause marks a spoken mark may replace when they precede it.
_PAUSE_MARKS = frozenset(",;:")

_SYMBOL_FOR = {phrase.lower(): sym for phrase, sym in _ATTACH_LEFT}

_ATTACH_RE = re.compile(
    rf"(?P<pre>[{re.escape(_ASR_MARKS)}])?\s*"
    rf"\b(?P<phrase>{'|'.join(re.escape(p) for p, _ in _ATTACH_LEFT)})\b"
    rf"[{re.escape(_ASR_MARKS)}]*",
    flags=re.IGNORECASE,
)

_FORMATTING_RES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            rf"\s*\b{re.escape(phrase)}\b[{re.escape(_ASR_MARKS)}]*\s*",
            flags=re.IGNORECASE,
        ),
        repl,
    )
    for phrase, repl in _FORMATTING
]


def _attach(match: re.Match[str]) -> str:
    sym = _SYMBOL_FOR[" ".join(match.group("phrase").lower().split())]
    pre = match.group("pre") or ""
    if pre in _PAUSE_MARKS or pre == sym:
        pre = ""
    return pre + sym


def apply_voice_punctuation(text: str) -> str:
    """Replace spoken punctuation/formatting words with their symbols."""
    if not text:
        return text
    s = text
    for pattern, repl in _FORMATTING_RES:
        # A lambda, so a replacement is never parsed for backslash escapes.
        s = pattern.sub(lambda _m, r=repl: r, s)
    # Absorb whitespace before the phrase so the symbol hugs the prior word;
    # whatever follows (usually a space) is preserved.
    s = _ATTACH_RE.sub(_attach, s)
    # Collapse doubled *spaces* the substitutions produced. Tabs are left alone:
    # "tab key tab key" is two deliberate tabs, not a run to squash to a space.
    s = re.sub(r" {2,}", " ", s)
    return s
