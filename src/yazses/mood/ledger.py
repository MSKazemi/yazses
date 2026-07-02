"""Mood aggregation + trend (pure) — ADR-v2-040.

Aggregate emotion labels over a dictation history and compare windows to surface a mood
trend. Pure and deterministic; the SER model that produces labels lives behind the
``sentiment`` extra.
"""
from __future__ import annotations

# Rough valence for a handful of common emotion labels (higher = more positive).
_VALENCE = {
    "happy": 1.0, "excited": 1.0, "joy": 1.0, "content": 0.7, "calm": 0.5,
    "neutral": 0.0,
    "tired": -0.4, "bored": -0.4, "sad": -1.0, "angry": -1.0, "stressed": -1.0,
    "anxious": -0.8, "frustrated": -0.8,
}


def aggregate(labels) -> dict:
    """Count emotion labels into a ``{label: count}`` distribution (case-insensitive). Pure."""
    counts: dict = {}
    for label in labels:
        k = (label or "").lower().strip()
        if k:
            counts[k] = counts.get(k, 0) + 1
    return counts


def dominant_mood(labels):
    """Return the most frequent label (first-seen wins ties), or ``None`` if empty. Pure."""
    counts = aggregate(labels)
    if not counts:
        return None
    best, best_n = None, -1
    for label in (l.lower().strip() for l in labels if (l or "").strip()):
        n = counts[label]
        if n > best_n:
            best, best_n = label, n
    return best


def mood_shift(earlier, later) -> str:
    """Compare the dominant mood of two windows by valence. Pure.

    Returns ``"improved"`` / ``"declined"`` / ``"stable"`` / ``"unknown"`` (the last when
    either window is empty).
    """
    de, dl = dominant_mood(earlier), dominant_mood(later)
    if de is None or dl is None:
        return "unknown"
    ve, vl = _VALENCE.get(de, 0.0), _VALENCE.get(dl, 0.0)
    if vl > ve:
        return "improved"
    if vl < ve:
        return "declined"
    return "stable"
