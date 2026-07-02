"""Word→audio index + selection (pure) — ADR-v2-037.

Resolve spoken/positional word selections to audio start/end bounds over a list of
timestamped words. Pure and deterministic; the timestamps come from faster-whisper and
playback happens elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimedWord:
    """A transcribed word with its audio span (seconds)."""
    text: str
    start: float
    end: float


def _norm(word: str) -> str:
    return (word or "").lower().strip(".,!?;:\"'")


def find_word(words, query):
    """Return the index of the LAST word matching ``query`` (case/punct-insensitive), or None.

    Last-match so "fix the word 'report'" targets the most recent occurrence. Pure.
    """
    q = _norm(query)
    if not q:
        return None
    for i in range(len(words) - 1, -1, -1):
        if _norm(words[i].text) == q:
            return i
    return None


def slice_bounds(words, i):
    """Return ``(start, end)`` audio bounds for word ``i``. Raises IndexError if out of range."""
    w = words[i]
    return (w.start, w.end)


def range_bounds(words, start_i, end_i):
    """Return ``(start, end)`` audio bounds spanning words ``start_i..end_i`` inclusive.

    Order-insensitive (swaps if start_i > end_i). Raises IndexError if out of range. Pure.
    """
    if start_i > end_i:
        start_i, end_i = end_i, start_i
    return (words[start_i].start, words[end_i].end)
