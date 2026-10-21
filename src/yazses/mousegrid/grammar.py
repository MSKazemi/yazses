"""The voice mouse grid's spoken grammar (pure) — ADR-v2-030.

Every rule is anchored at both ends (``^...$``) against the *whole* utterance, after the
same outer-punctuation strip the command grammar uses (:func:`strip_outer_punct`), so a
sentence that merely contains "click" or "three" is never a grid command.

Two vocabularies, and which one applies depends on whether a grid is open:

* **Closed** — only :data:`OPEN_PHRASES` ("mouse grid") is claimed. Nothing else is ever
  read, so with the grid closed dictation is untouched.
* **Open** — cell numbers ("three", "3", "three seven", "37"), ``click`` /
  ``right click`` / ``double click``, ``back`` (zoom out one level) and ``cancel``.

It deliberately does **not** live in ``commands/grammars/en.py``: that table is always on,
is shared with the Android parity contract, and would claim "click" for every user. This
grammar is reachable only from :mod:`yazses.mousegrid.runtime`, which the daemon builds only
when ``[mousegrid] enabled`` is true.

Homophones ("to" for "two", "for" for "four", "tree" for "three") are refused on purpose
(AGENTS.md rule 9): accepting them would let ordinary words move the pointer while a grid is
open, and a misheard number is recovered by saying it again, or ``back``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from yazses.commands.grammars.en import strip_outer_punct

__all__ = ["OPEN_PHRASES", "GridCommand", "is_open_phrase", "parse_open_command"]

#: The whole-utterance phrases that open a grid while none is open.
OPEN_PHRASES: frozenset[str] = frozenset({"mouse grid", "show mouse grid"})

_NUMBER_WORDS: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16,
}

_CLICKS: dict[str, tuple[str, int]] = {
    "click": ("left", 1),
    "left click": ("left", 1),
    "right click": ("right", 1),
    "double click": ("left", 2),
}

_CANCEL = frozenset({"cancel", "close grid", "cancel grid", "hide grid"})
_BACK = frozenset({"back", "go back"})

# Tokens of a cell sequence: words or digit runs, separated by spaces, commas, full stops
# or hyphens ("Three. Seven." is how Whisper sometimes writes two spoken numbers).
_SPLIT_RE = re.compile(r"[\s,.\-]+")
_DIGITS_RE = re.compile(r"^\d+$")


@dataclass(frozen=True)
class GridCommand:
    """One parsed grid utterance.

    ``kind`` is ``"cells"`` (``cells`` holds 1-based cell numbers, in spoken order),
    ``"click"`` (``button`` and ``count``), ``"back"`` or ``"cancel"``.
    """

    kind: str
    cells: tuple[int, ...] = ()
    button: str = "left"
    count: int = 1


def _normalise(text: str) -> str:
    """Lower-case, outer punctuation stripped, inner whitespace collapsed. Pure."""
    return " ".join(strip_outer_punct(text or "").lower().split())


def is_open_phrase(text: str) -> bool:
    """True when the whole utterance is a grid-opening phrase ("mouse grid"). Pure."""
    return _normalise(text) in OPEN_PHRASES


def _parse_cells(phrase: str, cell_count: int) -> tuple[int, ...] | None:
    """Cell numbers spoken as words or digits, or None if any token is not one. Pure.

    With at most nine cells a digit run is a *sequence* ("37" is three then seven), which is
    how Whisper often writes "three seven". With more than nine a digit run is one cell
    number ("12"). Every number must be inside ``1..cell_count``, or nothing is accepted:
    half a path is a different place, not a shorter route to the same one.
    """
    tokens = [t for t in _SPLIT_RE.split(phrase) if t]
    if not tokens:
        return None
    cells: list[int] = []
    for token in tokens:
        if token in _NUMBER_WORDS:
            cells.append(_NUMBER_WORDS[token])
        elif _DIGITS_RE.match(token):
            if cell_count <= 9:
                cells.extend(int(ch) for ch in token)
            else:
                cells.append(int(token))
        else:
            return None
    if not all(1 <= c <= cell_count for c in cells):
        return None
    return tuple(cells)


def parse_open_command(text: str, cell_count: int) -> GridCommand | None:
    """Parse one utterance spoken while a grid is open, or None if it is not a grid command.

    ``cell_count`` is ``cols * rows``. Pure.
    """
    phrase = _normalise(text)
    if not phrase:
        return None
    if phrase in _CANCEL:
        return GridCommand("cancel")
    if phrase in _BACK:
        return GridCommand("back")
    click = _CLICKS.get(phrase)
    if click is not None:
        return GridCommand("click", button=click[0], count=click[1])
    cells = _parse_cells(phrase, cell_count)
    if cells is not None:
        return GridCommand("cells", cells=cells)
    return None
