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

# Scoring is mean content-word frequency, and dividing by the sentence's own length made a
# one-word interjection the winner: "Ship it." scores the full frequency of "ship" over a
# single word, beating the long sentence that actually said something. Ramble is full of
# these -- "Right.", "Okay.", "Sure." -- and they are the least informative sentences there
# are, so a summariser that reliably picks them is inverted, not merely noisy.
#
# The divisor therefore has a floor: one content word is not a measurement.
#
# The floor is 2 and deliberately no higher. Sweeping it showed there is no value that is
# simply "better": at 3 the summariser starts discarding legitimate short sentences ("Fix
# the wheel."), and it takes 4-5 to out-rank a two- or three-word echo. The floor trades one
# error for the other and the crossover sits in the middle of the useful range, so 2 is the
# largest value that removes a failure with no legitimate counterpart -- a sentence carrying
# one content word has no summary value by construction. See
# tests/test_condense_ignores_interjections.py, which pins both ends.
_MIN_CONTENT_WORDS = 2


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
        if not words:
            return 0.0
        return sum(freq[w] for w in words) / max(len(words), _MIN_CONTENT_WORDS)

    # Rank by score (stable), take the top N, then restore original order.
    ranked = sorted(range(len(sentences)), key=lambda i: score(sentences[i]), reverse=True)
    keep = sorted(ranked[:max_sentences])
    return " ".join(sentences[i] for i in keep)
