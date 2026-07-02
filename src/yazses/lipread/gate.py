"""Mouth open/active gate (pure) — ADR-v2-053.

Compute a mouth aspect ratio from face landmarks and decide when the mouth is open/moving, so
the heavy VSR model only runs when the user is actually mouthing. Pure math.
"""
from __future__ import annotations


def mouth_aspect_ratio(top, bottom, left, right) -> float:
    """Vertical/horizontal lip opening ratio from four ``(x, y)`` landmarks. Pure.

    Returns 0.0 when the mouth width is degenerate (avoids divide-by-zero).
    """
    vert = abs(top[1] - bottom[1])
    horiz = abs(left[0] - right[0])
    return vert / horiz if horiz else 0.0


def mouth_active(ratio: float, threshold: float = 0.35) -> bool:
    """Whether the mouth is open enough to be mouthing speech. Pure."""
    return ratio >= threshold
