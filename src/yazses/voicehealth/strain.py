"""Vocal-strain scoring + break decision (pure) — ADR-v2-034.

Fold per-utterance voice biomarkers (jitter, shimmer, HNR) into a normalized strain estimate,
and decide from a session trend whether to advise a break. Pure and deterministic; the
biomarkers are measured elsewhere (parselmouth). Advisory only, never diagnostic.
"""
from __future__ import annotations


def strain_level(jitter: float, shimmer: float, hnr: float) -> float:
    """Normalized 0–1 vocal-strain estimate (higher = more strain). Pure.

    High jitter and shimmer indicate strain; low harmonics-to-noise ratio (HNR) indicates a
    degraded/breathy voice. Rough clinical anchors: jitter >~2%, shimmer >~10%, HNR <~20 dB
    trend toward strain. The three normalized components are averaged.
    """
    j = min(1.0, max(0.0, jitter / 0.02))
    s = min(1.0, max(0.0, shimmer / 0.10))
    h = min(1.0, max(0.0, (20.0 - hnr) / 20.0))
    return (j + s + h) / 3.0


def should_suggest_break(samples, config) -> bool:
    """Return True when the recent mean strain warrants a break suggestion.

    ``samples`` is a session's strain-level history (most recent last). Fires only when there
    are at least ``min_samples`` and the mean of the most-recent ``min_samples`` is at least
    ``threshold``. Disabled config never fires. Pure.
    """
    if not getattr(config, "enabled", False):
        return False
    min_samples = int(getattr(config, "min_samples", 20))
    threshold = float(getattr(config, "threshold", 0.6))
    if len(samples) < min_samples or min_samples <= 0:
        return False
    window = samples[-min_samples:]
    return (sum(window) / len(window)) >= threshold
