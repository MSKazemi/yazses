"""Semantic line-break insertion (pure) — ADR-v2-111.

Break prose after sentence and major-clause boundaries so the source diffs cleanly. Pure regex/string
transformation; no model.
"""
from __future__ import annotations

import re

_CLAUSE_WORDS = (
    "and", "but", "or", "so", "yet", "nor", "for", "because", "which", "while",
    "although", "though", "since", "whereas", "however", "therefore",
)
_COORD = re.compile(rf",\s+(?=(?:{'|'.join(_CLAUSE_WORDS)})\b)", re.IGNORECASE)


def _soft_wrap(line: str, max_len: int):
    out = []
    while len(line) > max_len:
        cut = line.rfind(" ", 0, max_len)
        if cut <= 0:
            break
        out.append(line[:cut])
        line = line[cut + 1:]
    out.append(line)
    return out


def semantic_breaks(text: str, max_len=None) -> str:
    """Insert newlines after sentence/clause boundaries; optionally soft-wrap long lines. Pure."""
    s = re.sub(r"\s+", " ", (text or "").strip())
    if not s:
        return ""
    s = re.sub(r"([.!?])\s+", r"\1\n", s)      # after sentence terminators
    s = re.sub(r"([;:])\s+", r"\1\n", s)        # after semicolons/colons
    s = _COORD.sub(",\n", s)                    # before a comma-led clause word
    if max_len:
        lines = []
        for line in s.split("\n"):
            lines.extend(_soft_wrap(line, max_len))
        s = "\n".join(lines)
    return s
