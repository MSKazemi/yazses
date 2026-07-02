"""Voice-snippet match/expand (pure) — ADR-v2-026.

Map a spoken trigger phrase to a stored template. An optional leading verb
("insert/expand/snippet") is stripped; matching is on the normalized phrase, longest
trigger first. Pure and deterministic.
"""
from __future__ import annotations

import re

_LEADING_VERBS = ("insert", "expand", "snippet", "paste snippet")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())).strip()


def _strip_verb(norm: str) -> str:
    for v in _LEADING_VERBS:
        if norm == v:
            return norm
        if norm.startswith(v + " "):
            return norm[len(v) + 1:]
    return norm


def expand_snippet(phrase, entries) -> str | None:
    """Return the template for a spoken trigger, or ``None`` if none matches.

    The phrase is normalized and an optional leading verb removed, then matched exactly
    against each entry's normalized trigger; the longest trigger wins on ties. Empty
    phrase or empty store returns ``None``. Pure.
    """
    if not entries:
        return None
    norm = _strip_verb(_norm(phrase))
    if not norm:
        return None
    best_template: str | None = None
    best_len = -1
    for trigger, template in entries.items():
        tnorm = _norm(trigger)
        if tnorm and tnorm == norm and len(tnorm) > best_len:
            best_template = template
            best_len = len(tnorm)
    return best_template
