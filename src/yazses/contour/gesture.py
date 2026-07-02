"""Pitch-contour classification + command mapping (pure) — ADR-v2-103.

Z-normalize a voiced F0 contour, classify its shape, and map it to a command. Pure and
deterministic; the F0 tracker is the lazy extra.
"""
from __future__ import annotations

import math

_DEFAULT_MAP = {
    "rise": "confirm",
    "fall": "cancel",
    "rise_fall": "undo",
    "flat": "repeat",
}


def normalize_contour(f0_series):
    """Voiced F0 as semitone deviations from the mean; ``[]`` if too few voiced. Pure.

    Semitones (``12·log2(f/mean)``) preserve absolute flatness — a near-constant pitch stays near
    zero — unlike z-scores, which amplify tiny variation to unit variance.
    """
    voiced = [f for f in (f0_series or ()) if f and f > 0]
    if len(voiced) < 2:
        return []
    mean = sum(voiced) / len(voiced)
    return [12.0 * math.log2(f / mean) for f in voiced]


def classify_contour(f0_norm, slope_threshold: float = 1.5) -> str:
    """Classify a normalized contour → ``rise`` | ``fall`` | ``rise_fall`` | ``flat``. Pure."""
    n = len(f0_norm)
    if n < 2:
        return "flat"
    third = max(1, n // 3)
    start = sum(f0_norm[:third]) / third
    end = sum(f0_norm[-third:]) / third
    peak = max(f0_norm)
    peak_idx = f0_norm.index(peak)
    if 0 < peak_idx < n - 1 and peak - start > slope_threshold and peak - end > slope_threshold:
        return "rise_fall"
    if end - start > slope_threshold:
        return "rise"
    if start - end > slope_threshold:
        return "fall"
    return "flat"


def gesture_to_command(gesture: str, profile=None):
    """Map a gesture name to a command via ``profile`` (or the default map), or ``None``. Pure."""
    mapping = profile if profile is not None else _DEFAULT_MAP
    return mapping.get(gesture)
