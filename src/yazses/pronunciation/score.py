"""Pronunciation scoring/feedback (pure) — ADR-v2-041.

Turn per-phoneme goodness-of-pronunciation (GOP) values into learner feedback: band
classification, an overall score, and a practice list. Pure and deterministic; the GOP model
that produces the values lives behind the ``pronunciation`` extra.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhonemeScore:
    """A phoneme and its goodness-of-pronunciation value in ``[0, 1]``."""
    phoneme: str
    gop: float


def classify(gop: float, good_threshold: float = 0.7, poor_threshold: float = 0.4) -> str:
    """Classify a GOP value into ``good`` / ``fair`` / ``poor``. Pure."""
    if gop >= good_threshold:
        return "good"
    if gop >= poor_threshold:
        return "fair"
    return "poor"


def overall_score(scores) -> float:
    """Mean GOP across phonemes in ``[0, 1]``; 0.0 for empty input. Pure."""
    vals = [s.gop for s in scores]
    return sum(vals) / len(vals) if vals else 0.0


def problem_phonemes(scores, config) -> list:
    """Return phonemes scoring below the poor threshold (need practice). Pure."""
    poor = float(getattr(config, "poor_threshold", 0.4))
    return [s.phoneme for s in scores if s.gop < poor]
