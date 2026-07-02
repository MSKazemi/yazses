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
