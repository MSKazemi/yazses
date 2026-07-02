"""Extractive condensation (pure) — ADR-v2-062.

Tighten a spoken paragraph by keeping the highest-information sentences (normalized content-word
frequency), in original order. Pure and deterministic; the abstractive LLM tier is deferred.
"""
from __future__ import annotations

import re
from collections import Counter

# Very common words carry little topical signal — excluded from scoring.
_STOP = frozenset("""
a an the and or but if then so of to in on at by for with from as is are was were be been being
this that these those it its i you he she we they them his her our your my me him us do does did
have has had will would can could should may might must not no yes just very really about into
""".split())

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[a-z0-9']+")


def _sentences(text: str) -> list:
    return [s.strip() for s in _SENT_SPLIT.split(text or "") if s.strip()]


def condense(text: str, max_sentences: int = 2) -> str:
    """Return the ``max_sentences`` most informative sentences, in original order. Pure.

    Text with at most ``max_sentences`` sentences is returned unchanged.
    """
    sentences = _sentences(text)
    if len(sentences) <= max_sentences:
        return (text or "").strip()

    freq: Counter = Counter()
    for s in sentences:
        for w in _WORD.findall(s.lower()):
            if w not in _STOP:
                freq[w] += 1

    def score(s: str) -> float:
        words = [w for w in _WORD.findall(s.lower()) if w not in _STOP]
        return sum(freq[w] for w in words) / len(words) if words else 0.0

    # Rank by score (stable), take the top N, then restore original order.
    ranked = sorted(range(len(sentences)), key=lambda i: score(sentences[i]), reverse=True)
    keep = sorted(ranked[:max_sentences])
    return " ".join(sentences[i] for i in keep)
