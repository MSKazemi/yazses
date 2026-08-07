"""Per-sample gaze confidence from left/right eye agreement (pure).

The MediaPipe backend estimates the gaze signal independently from each eye's
normalised iris offset. When the landmarks are good the two eyes agree closely;
blur, extreme head pose, or partial occlusion make them diverge. That divergence
is a real, per-frame quality signal — unlike the previous hard-coded 1.0, which
made ``[gaze] confidence_min`` a no-op for the default backend.

``eye_agreement_confidence`` maps the eye disagreement distance to [0, 1]:
identical offsets → 1.0, disagreement ≥ ``scale`` → 0.0, linear in between.
``scale`` defaults to 0.4 because the normalised iris offset itself lives in
roughly [-0.5, 0.5]; a disagreement approaching the signal's own range means the
landmarks carry no usable gaze information.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GazeSample:
    """One gaze estimate with its per-frame confidence."""

    x: float
    y: float
    confidence: float

    @property
    def point(self) -> tuple[float, float]:
        return (self.x, self.y)


def eye_agreement_confidence(
    left: tuple[float, float], right: tuple[float, float], scale: float = 0.4
) -> float:
    """Confidence in [0, 1] from how closely the two eyes' offsets agree. Pure."""
    if scale <= 0:
        return 1.0
    dist = math.hypot(left[0] - right[0], left[1] - right[1])
    return max(0.0, min(1.0, 1.0 - dist / scale))
