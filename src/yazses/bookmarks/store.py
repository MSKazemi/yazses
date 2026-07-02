"""Session bookmark store + command grammar (pure) — ADR-v2-090.

Hold named session positions and parse spoken bookmark commands. Pure and deterministic; positions
come from the injection timeline.
"""
from __future__ import annotations

import re


class BookmarkStore:
    """Named session positions, insertion-ordered. Pure state."""

    def __init__(self) -> None:
        self._marks: dict = {}
        self._order: list = []

    def add(self, name: str, position) -> None:
        """Record or update a bookmark ``name`` → ``position``."""
        if name not in self._marks:
            self._order.append(name)
        self._marks[name] = position

    def goto(self, name: str):
        """Return the position for ``name``, or ``None``."""
        return self._marks.get(name)

    def names(self) -> list:
        """Bookmark names in insertion order."""
        return list(self._order)

    def last(self):
        """The most recently added bookmark's position, or ``None``."""
        return self._marks[self._order[-1]] if self._order else None


def parse_bookmark_command(text: str):
    """Parse a spoken bookmark command → ``("add", name|None)`` / ``("goto", name|None)``, or None.

    On a goto, a ``None`` name means the most recent bookmark. Pure.
    """
    t = (text or "").lower().strip()

    m = re.search(r"\b(?:jump|go|goto)\s+(?:to\s+)?(?:my\s+)?(?:(last)\s+)?bookmark(?:\s+(.+))?$", t)
    if m:
        if m.group(2) and not m.group(1):
            return ("goto", m.group(2).strip())
        return ("goto", None)   # "last bookmark" or bare "bookmark"

    m = re.search(r"\bbookmark\s*(?:here|this)?\s*(?:as\s+(.+)|called\s+(.+))?$", t)
    if m:
        name = (m.group(1) or m.group(2))
        return ("add", name.strip() if name else None)
    return None
