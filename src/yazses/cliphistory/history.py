"""Clipboard ring buffer + spoken-reference resolver (pure) — ADR-v2-060.

A bounded, newest-first clipboard history and a resolver that maps a spoken recall to one entry.
Pure and deterministic; the OS clipboard I/O and injection happen elsewhere.
"""
from __future__ import annotations

import re

_URL = re.compile(r"https?://\S+")
_EMAIL = re.compile(r"\S+@\S+\.\S+")
# ordinal word → index in the newest-first list.
_ORDINALS = (
    ("most recent", 0), ("last", 0), ("latest", 0),
    ("second", 1), ("third", 2), ("fourth", 3), ("fifth", 4),
)


class ClipboardRing:
    """A bounded, consecutive-dedup clipboard history (newest first)."""

    def __init__(self, capacity: int = 20) -> None:
        self._cap = max(1, capacity)
        self._items: list = []

    def add(self, text: str) -> None:
        """Record a copy. Ignores empties and consecutive duplicates; caps at capacity."""
        if not text:
            return
        if self._items and self._items[0] == text:
            return
        self._items.insert(0, text)
        del self._items[self._cap:]

    def items(self) -> list:
        """The history, newest first."""
        return list(self._items)


def resolve_reference(query: str, items):
    """Resolve a spoken clipboard recall to one entry (newest-first ``items``), or ``None``. Pure.

    Understands keyword filters (url/link, email), ordinals (last/second/…), "first/oldest",
    and "number N"; defaults to the most recent entry.
    """
    if not items:
        return None
    q = (query or "").lower()

    if "url" in q or "link" in q:
        return next((it for it in items if _URL.search(it)), None)
    if "email" in q:
        return next((it for it in items if _EMAIL.search(it)), None)

    for word, idx in _ORDINALS:
        if word in q:
            return items[idx] if idx < len(items) else None
    if "first" in q or "oldest" in q:
        return items[-1]

    m = re.search(r"\b(\d+)\b", q)
    if m:
        n = int(m.group(1)) - 1
        return items[n] if 0 <= n < len(items) else None

    return items[0]
