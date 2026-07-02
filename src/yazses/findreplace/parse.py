"""Spoken find-and-replace command parsing + apply (pure) — ADR-v2-068.

Parse "replace every X with Y" style commands into a :class:`ReplaceOp` and apply it to text for
previews/tests. Deterministic and dependency-free; the live-editor backend lives elsewhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CMD = re.compile(
    r"^(?:replace|change|substitute|swap)\s+"
    r"(?:(every|all|each|the\s+first|first|the\s+next|next|one)\s+)?"
    r"(.+?)\s+(?:with|to|for|by)\s+(.+?)\s*$",
    re.IGNORECASE,
)
_SINGULAR = {"first", "the first", "next", "the next", "one"}


@dataclass(frozen=True)
class ReplaceOp:
    """A find/replace: replace ``find`` with ``replace`` (all or first, case-sensitive or not)."""
    find: str
    replace: str
    all: bool = True
    case_sensitive: bool = False


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    return s


def parse_replace_command(text: str):
    """Parse a spoken find-and-replace command into a :class:`ReplaceOp`, or ``None``. Pure."""
    t = (text or "").strip()
    case_sensitive = False
    m = re.search(r"\s+case[- ]sensitive(?:ly)?\s*$", t, re.IGNORECASE)
    if m:
        case_sensitive = True
        t = t[:m.start()].strip()

    match = _CMD.match(t)
    if not match:
        return None
    scope, find, replace = match.group(1), match.group(2), match.group(3)
    find = _strip_quotes(find)
    replace = _strip_quotes(replace)
    if not find:
        return None
    all_ = not (scope and scope.lower() in _SINGULAR)
    return ReplaceOp(find=find, replace=replace, all=all_, case_sensitive=case_sensitive)


def apply_replace(op: ReplaceOp, text: str) -> str:
    """Apply a :class:`ReplaceOp` to ``text`` (literal find). Pure — used for previews/tests."""
    flags = 0 if op.case_sensitive else re.IGNORECASE
    count = 0 if op.all else 1
    return re.sub(re.escape(op.find), op.replace.replace("\\", "\\\\"), text,
                  count=count, flags=flags)
