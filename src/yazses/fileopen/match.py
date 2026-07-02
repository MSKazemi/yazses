"""Fuzzy file ranking (pure) — ADR-v2-080.

Rank filenames against a spoken query by a blend of sequence similarity and content-token overlap.
Pure and deterministic (stdlib ``difflib``); the semantic-embedding tier lives elsewhere.
"""
from __future__ import annotations

import difflib
import re

_TOKEN = re.compile(r"[a-z0-9]+")
# words that carry no file-targeting signal.
_STOP = frozenset("""
open the a an my me file files document documents please find show load about of for to with
that this and or on in it is
""".split())


def _content_tokens(s: str):
    return {w for w in _TOKEN.findall((s or "").lower()) if w not in _STOP}


def _score(query: str, name: str) -> float:
    ratio = difflib.SequenceMatcher(None, (query or "").lower(), (name or "").lower()).ratio()
    qt = _content_tokens(query)
    nt = _content_tokens(name)
    overlap = len(qt & nt) / len(qt) if qt else 0.0
    return 0.5 * ratio + 0.5 * overlap


def fuzzy_rank(query: str, filenames):
    """Return ``(name, score)`` pairs sorted best-first. Pure (stable on ties)."""
    scored = [(name, _score(query, name)) for name in filenames or ()]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def resolve_open(query: str, filenames, threshold: float = 0.4):
    """Return the best-matching filename above ``threshold``, or ``None``. Pure."""
    ranked = fuzzy_rank(query, filenames)
    if ranked and ranked[0][1] >= threshold:
        return ranked[0][0]
    return None
