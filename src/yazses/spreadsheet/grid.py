"""Spreadsheet grid movement + cell-reference parsing (pure) — ADR-v2-059.

Map spoken grid movements to key sequences and parse spoken cell addresses. Pure and
deterministic; dispatch/injection happens elsewhere.
"""
from __future__ import annotations

import re

# Spoken movement phrase → key sequence (key names as the injector understands them).
_MOVES = {
    "next row": ["Return"],
    "new row": ["Return"],
    "next cell": ["Tab"],
    "next column": ["Tab"],
    "previous cell": ["shift+Tab"],
    "previous column": ["shift+Tab"],
    "cell up": ["Up"],
    "cell down": ["Down"],
    "cell left": ["Left"],
    "cell right": ["Right"],
    "move up": ["Up"],
    "move down": ["Down"],
    "move left": ["Left"],
    "move right": ["Right"],
    "start of row": ["Home"],
    "end of row": ["End"],
    "top of column": ["ctrl+Up"],
    "bottom of column": ["ctrl+Down"],
}

_CELL_WORDS = re.compile(r"\bcolumn\s+([a-z]{1,3})\s+row\s+(\d{1,7})\b", re.IGNORECASE)
_CELL_A1 = re.compile(r"\b(?:go to|goto|cell|select)\s+([a-z]{1,3})\s*(\d{1,7})\b", re.IGNORECASE)


def parse_grid_move(text: str):
    """Return the key sequence for a spoken grid movement, or ``None``. Pure."""
    key = (text or "").strip().lower()
    seq = _MOVES.get(key)
    return list(seq) if seq else None


def parse_cell_reference(text: str):
    """Parse a spoken cell address into a normalized reference like ``"B7"``, or ``None``. Pure.

    Accepts "column B row 7" and an anchored "go to/cell/select B7" (the anchor keeps ordinary
    word+number tokens like "mp3" from being read as cells).
    """
    m = _CELL_WORDS.search(text or "")
    if m:
        return f"{m.group(1).upper()}{int(m.group(2))}"
    m = _CELL_A1.search(text or "")
    if m:
        return f"{m.group(1).upper()}{int(m.group(2))}"
    return None
