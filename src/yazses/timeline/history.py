"""Injection undo/redo timeline (pure) — ADR-v2-089.

Record YazSes injections and compute the backspace/retype delta to undo/redo them across bursts.
Pure and deterministic; the injector applies the delta.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UndoOp:
    """The edit to apply: press ``backspaces`` then type ``insert``."""
    backspaces: int
    insert: str


class InjectionTimeline:
    """A ring of injection events supporting word/sentence/burst undo and redo. Pure state."""

    def __init__(self) -> None:
        self._events: list = []   # live injected strings, oldest first
        self._redo: list = []     # removed fragments, for redo

    def record(self, text: str) -> None:
        """Record an injected string (clears the redo stack)."""
        if text:
            self._events.append(text)
            self._redo.clear()

    def text(self) -> str:
        """The concatenation of live events (for inspection/tests)."""
        return "".join(self._events)

    def _trailing_count(self, last: str, scope: str) -> int:
        if scope in ("last", "burst", "all"):
            return len(last)
        if scope == "word":
            m = re.search(r"\s*\S+\s*$", last)
            return len(m.group()) if m else len(last)
        if scope == "sentence":
            idx = max(last.rfind("."), last.rfind("!"), last.rfind("?"))
            return len(last) - idx - 1 if 0 <= idx < len(last) - 1 else len(last)
        return len(last)

    def undo(self, scope: str = "last"):
        """Undo the last word/sentence/burst; returns an :class:`UndoOp`, or ``None``. Pure state."""
        if not self._events:
            return None
        last = self._events[-1]
        n = self._trailing_count(last, scope)
        fragment = last[len(last) - n:]
        remaining = last[:len(last) - n]
        if remaining:
            self._events[-1] = remaining
        else:
            self._events.pop()
        self._redo.append(fragment)
        return UndoOp(backspaces=len(fragment), insert="")

    def redo(self):
        """Re-insert the last undone fragment; returns an :class:`UndoOp`, or ``None``. Pure state."""
        if not self._redo:
            return None
        fragment = self._redo.pop()
        self._events.append(fragment)
        return UndoOp(backspaces=0, insert=fragment)

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

# Spoken scope -> the `scope` argument :meth:`InjectionTimeline.undo` already takes.
_SCOPE_WORDS = {
    "word": "word", "words": "word",
    "sentence": "sentence", "sentences": "sentence",
    "burst": "burst", "bursts": "burst",
    "everything": "all", "all": "all",
}

# Whole-utterance undo/redo commands, normalized (lower, stripped, trailing sentence
# punctuation removed). Anchored at both ends for the same reason `_SCRATCH_RE` in
# commands/revise.py is: "undo" is an ordinary English word, and "click undo", "I need
# to undo that" or "press control z to undo" are things a person dictates and expects
# to see typed. A pattern that merely has to *end* the utterance obeys all of them.
_TIMELINE_RE = re.compile(
    r"^(?P<action>undo|redo)"
    r"(?:\s+(?:that|this))?"
    r"(?:\s+(?:the\s+)?last)?"
    r"(?:\s+(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten))?"
    r"(?:\s+(?P<scope>words?|sentences?|bursts?|everything|all))?"
    r"$"
)

MAX_REPEAT = 10


def parse_timeline_command(text: str):
    """Parse a whole-utterance timeline command.

    Returns ``(action, count, scope)`` — e.g. ``("undo", 2, "word")`` for "undo two
    words" — or ``None`` when the utterance is ordinary dictation. ``scope`` is one of
    the values :meth:`InjectionTimeline.undo` accepts. Pure.
    """
    if not text:
        return None
    norm = text.strip().lower().rstrip(".?!,").strip()
    m = _TIMELINE_RE.match(norm)
    if not m:
        return None

    raw_count = m.group("count")
    if raw_count is None:
        count = 1
    elif raw_count.isdigit():
        count = int(raw_count)
    else:
        count = _NUMBER_WORDS[raw_count]
    # A misheard number must not turn into a thousand backspaces at the injector.
    count = max(1, min(count, MAX_REPEAT))

    scope = _SCOPE_WORDS.get(m.group("scope") or "", "last")
    return (m.group("action"), count, scope)
