"""Playback-timeline construction + barge-in alignment (pure) — ADR-v2-108.

Build a per-word playback timeline and map a barge-in timestamp to the word being spoken. Pure
arithmetic; TTS/barge-in capture is the existing infra.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """A word's playback interval: ``[start_ms, end_ms)``."""
    index: int
    start_ms: float
    end_ms: float


def build_schedule(words, per_word_ms):
    """Build a cumulative per-word playback timeline. ``per_word_ms`` is a scalar or per-word list. Pure."""
    spans = []
    t = 0.0
    for i, _w in enumerate(words or ()):
        dur = per_word_ms[i] if isinstance(per_word_ms, (list, tuple)) else per_word_ms
        spans.append(Span(i, t, t + dur))
        t += dur
    return spans


def word_at(schedule, t_ms: float) -> int:
    """Return the word index playing at ``t_ms`` (clamped to the ends), or ``-1`` if empty. Pure."""
    if not schedule:
        return -1
    if t_ms < schedule[0].start_ms:
        return schedule[0].index
    for sp in schedule:
        if sp.start_ms <= t_ms < sp.end_ms:
            return sp.index
    return schedule[-1].index


def resolve_target(index: int, intent: str = "replace") -> dict:
    """Return the edit target for a barge-in at ``index``. Pure."""
    return {"word_index": index, "intent": intent}
