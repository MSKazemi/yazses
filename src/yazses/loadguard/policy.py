"""Cognitive-load estimation + guard policy (pure) — ADR-v2-121.

Fuse speech-derived load signals into a 0..1 estimate and map it to a guardrail policy. Pure and
deterministic over metrics the pipeline already computes (pause ratio, filler rate, speech rate,
self-corrections).
"""
from __future__ import annotations

_TYPICAL_WPM = 160.0


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def estimate_load(metrics: dict | None) -> float:
    """Estimate cognitive load 0..1 from available speech signals (missing keys skipped). Pure.

    Signals (each normalized to 0..1, then averaged): ``pause_ratio`` (silence share),
    ``filler_rate`` (fillers per word, saturates at 0.15), ``speech_rate_wpm`` (slowdown below a
    typical 160 wpm), ``self_corrections`` (per utterance, saturates at 3).
    """
    if not metrics:
        return 0.0
    signals = []
    if "pause_ratio" in metrics:
        signals.append(_clamp(float(metrics["pause_ratio"])))
    if "filler_rate" in metrics:
        signals.append(_clamp(float(metrics["filler_rate"]) / 0.15))
    if "speech_rate_wpm" in metrics:
        signals.append(_clamp((_TYPICAL_WPM - float(metrics["speech_rate_wpm"])) / 80.0))
    if "self_corrections" in metrics:
        signals.append(_clamp(float(metrics["self_corrections"]) / 3.0))
    return round(sum(signals) / len(signals), 3) if signals else 0.0


def guard_policy(load: float, threshold: float = 0.7) -> dict:
    """Map a load estimate to guardrails. Pure.

    ``high`` (load ≥ threshold): widen confirmations AND defer risky/destructive actions.
    ``elevated`` (load ≥ 0.7·threshold): widen confirmations only. ``normal``: no change.
    """
    if load >= threshold:
        return {"level": "high", "widen_confirmations": True, "defer_risky": True}
    if load >= threshold * 0.7:
        return {"level": "elevated", "widen_confirmations": True, "defer_risky": False}
    return {"level": "normal", "widen_confirmations": False, "defer_risky": False}
