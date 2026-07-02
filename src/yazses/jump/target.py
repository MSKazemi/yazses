"""Spoken navigation target → editor motion (pure) — ADR-v2-081.

Parse a spoken jump target, fuzzy-pick a symbol from a provided list, and plan the motion. Pure
and deterministic (stdlib ``difflib``); the live LSP symbol feed lives elsewhere.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


@dataclass(frozen=True)
class Target:
    """A parsed navigation target: ``kind`` is line/symbol/search, ``value`` its int/str payload."""
    kind: str
    value: object


@dataclass(frozen=True)
class Motion:
    """A planned editor motion: ``kind`` (goto_line/goto_symbol/search) + ``payload``."""
    kind: str
    payload: object


def resolve_target(text: str):
    """Parse a spoken jump command into a :class:`Target`, or ``None``. Pure."""
    t = (text or "").strip().lower()

    m = re.search(r"\b(?:go to |goto |jump to )?line\s+(\d+)\b", t)
    if m:
        return Target("line", int(m.group(1)))
    m = re.search(r"\bline\s+([a-z]+)\b", t)
    if m and m.group(1) in _WORDNUM:
        return Target("line", _WORDNUM[m.group(1)])

    m = re.search(r"\b(?:jump to|go to|goto)\s+(?:the\s+)?"
                  r"(?:function|func|def|method|class|symbol)\s+([a-z_][\w]*)", t)
    if m:
        return Target("symbol", m.group(1))

    m = re.search(r"\b(?:find|search for|search)\s+(.+)$", t)
    if m:
        return Target("search", m.group(1).strip())
    return None


def fuzzy_pick(name: str, symbols, cutoff: float = 0.6):
    """Return the closest symbol to ``name`` from ``symbols``, or ``None``. Pure."""
    if not symbols:
        return None
    lowered = {s.lower(): s for s in symbols}
    matches = difflib.get_close_matches((name or "").lower(), list(lowered), n=1, cutoff=cutoff)
    return lowered[matches[0]] if matches else None


def plan_motion(target: Target, symbols=None):
    """Plan a :class:`Motion` for a target, using ``symbols`` for symbol jumps. Pure."""
    if target is None:
        return None
    if target.kind == "line":
        return Motion("goto_line", target.value)
    if target.kind == "search":
        return Motion("search", target.value)
    # symbol: fuzzy-pick from the list, else fall back to a text search
    picked = fuzzy_pick(str(target.value), symbols or [])
    if picked:
        return Motion("goto_symbol", picked)
    return Motion("search", target.value)
