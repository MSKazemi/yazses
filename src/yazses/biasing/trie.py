"""Hotword trie + N-best rescorer (pure) — ADR-v2-069.

A char-level prefix trie of the user's hotwords and a post-hoc N-best rescorer that boosts
hypotheses containing them. Pure and deterministic; the in-decoder logit-biasing hook is deferred.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[A-Za-z0-9']+")
_END = "\x00"   # terminal marker in a trie node


class HotwordTrie:
    """A char-level prefix trie of hotwords, for term membership and prefix tests."""

    __slots__ = ("_root",)

    def __init__(self) -> None:
        self._root: dict = {}

    def insert(self, term: str) -> None:
        """Add a hotword (case-insensitive)."""
        node: dict = self._root
        for ch in term.lower():
            node = node.setdefault(ch, {})
        node[_END] = True

    def is_term(self, word: str) -> bool:
        """True if ``word`` is a complete enrolled hotword. Pure."""
        node: dict = self._root
        for ch in word.lower():
            child = node.get(ch)
            if child is None:
                return False
            node = child
        return _END in node

    def has_prefix(self, prefix: str) -> bool:
        """True if any hotword starts with ``prefix``. Pure."""
        node: dict = self._root
        for ch in prefix.lower():
            child = node.get(ch)
            if child is None:
                return False
            node = child
        return True

    def __bool__(self) -> bool:
        return bool(self._root)


def build_hotword_trie(terms) -> HotwordTrie:
    """Build a :class:`HotwordTrie` from an iterable of terms (blanks ignored). Pure."""
    trie = HotwordTrie()
    for term in terms or ():
        t = (term or "").strip()
        if t:
            trie.insert(t)
    return trie


def rescore_nbest(hypotheses, trie: HotwordTrie, boost: float = 2.0):
    """Re-rank ``(text, score)`` hypotheses, adding ``boost`` per hotword hit. Pure.

    Returns a new list sorted by adjusted score, highest first. Ties keep input order (stable).
    """
    scored = []
    for text, score in hypotheses:
        hits = sum(1 for w in _WORD.findall(text) if trie.is_term(w))
        scored.append((text, score + boost * hits))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored
