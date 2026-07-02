"""CriticMarkup emission + word-level diff (pure) — ADR-v2-113.

Render tracked-change edits as CriticMarkup and diff two texts into it. Pure; uses only stdlib
``difflib``.
"""
from __future__ import annotations

import difflib


def to_criticmarkup(kind: str, text: str = "", old: str = "", new: str = "") -> str:
    """Render an edit as CriticMarkup: insert/delete/substitute/comment. Pure."""
    if kind == "insert":
        return "{++" + text + "++}"
    if kind == "delete":
        return "{--" + text + "--}"
    if kind == "substitute":
        return "{~~" + old + "~>" + new + "~~}"
    if kind == "comment":
        return "{>>" + text + "<<}"
    return text


def diff_to_critic(before: str, after: str) -> str:
    """Word-level CriticMarkup diff of ``before`` → ``after``. Pure."""
    a = (before or "").split()
    b = (after or "").split()
    sm = difflib.SequenceMatcher(None, a, b)
    parts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            parts.append(" ".join(a[i1:i2]))
        elif tag == "delete":
            parts.append("{--" + " ".join(a[i1:i2]) + "--}")
        elif tag == "insert":
            parts.append("{++" + " ".join(b[j1:j2]) + "++}")
        elif tag == "replace":
            parts.append("{~~" + " ".join(a[i1:i2]) + "~>" + " ".join(b[j1:j2]) + "~~}")
    return " ".join(p for p in parts if p)
