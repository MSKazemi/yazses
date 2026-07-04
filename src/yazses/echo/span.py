"""Span-index construction + playback-target resolution (pure) — ADR-v2-119.

Build a char-range → audio-time-range index from word timings, and resolve a spoken playback
request ("play that back", "play the last word", "repeat 'foo'") to an audio (start, end) window.
Pure and deterministic; audio capture/playback is handled elsewhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    text: str
    char_start: int
    char_end: int
    t_start: float
    t_end: float


def build_span_index(words) -> list[Span]:
    """Build char/time spans from ``[(text, t_start, t_end), ...]`` word timings. Pure.

    Char offsets accumulate with a single separating space between words (matching injected text).
    """
    spans: list[Span] = []
    cursor = 0
    for i, (text, t0, t1) in enumerate(words or ()):
        start = cursor if i == 0 else cursor + 1        # leading space between words
        end = start + len(text)
        spans.append(Span(text, start, end, float(t0), float(t1)))
        cursor = end
    return spans


def _merge(spans: list[Span]) -> tuple[float, float]:
    """Merge a non-empty span list into one (t_start, t_end) window. Callers guard non-empty."""
    return (min(s.t_start for s in spans), max(s.t_end for s in spans))


def resolve_playback_target(utterance: str, spans: list[Span]):
    """Resolve a spoken playback request to an audio ``(t_start, t_end)`` window, or ``None``. Pure.

    Supports "play that back"/"play all" (whole clip), "last word"/"that word" (final word),
    "first word", and "play 'word'"/quoted-or-bare token match (all matching words merged).
    """
    if not spans:
        return None
    u = (utterance or "").lower()
    if not u:
        return None
    if "last" in u or ("that" in u and "word" in u):
        return _merge([spans[-1]])
    if "first" in u:
        return _merge([spans[0]])
    quoted = re.findall(r"['\"]([^'\"]+)['\"]", u)
    targets = quoted or [w for w in re.findall(r"[a-z']+", u)
                         if w not in {"play", "back", "that", "the", "word", "repeat", "again"}]
    if targets:
        wanted = {t.strip().lower() for t in targets}
        hit = [s for s in spans if s.text.lower().strip(".,!?;:") in wanted]
        if hit:
            return _merge(hit)
    return _merge(spans)                                 # default: replay everything
