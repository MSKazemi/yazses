"""Small vector helpers over :class:`yazses.xr.types.Vec3` (pure, stdlib only)."""
from __future__ import annotations

import math

from yazses.xr.types import Vec3


def add(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(a.x + b.x, a.y + b.y, a.z + b.z)


def sub(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(a.x - b.x, a.y - b.y, a.z - b.z)


def scale(a: Vec3, k: float) -> Vec3:
    return Vec3(a.x * k, a.y * k, a.z * k)


def dot(a: Vec3, b: Vec3) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def cross(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)


def norm(a: Vec3) -> float:
    """Euclidean length, correct over the whole finite float range.

    ``math.hypot`` scales internally, so ``(1e200, 0, 0)`` does not overflow to ``inf``
    and ``(1e-200, 0, 0)`` does not underflow to ``0``. It returns ``inf`` only when the
    true length exceeds the largest float.
    """
    return math.hypot(a.x, a.y, a.z)


def _unit(a: Vec3, what: str) -> Vec3:
    """``a`` scaled to unit length without ever squaring an unscaled component."""
    m = max(abs(a.x), abs(a.y), abs(a.z))
    if m == 0.0:
        raise ValueError(what)
    # Components are now in [-1, 1] with at least one of magnitude 1, so the length of
    # the scaled vector is in [1, sqrt(3)]: no overflow, no underflow.
    sx, sy, sz = a.x / m, a.y / m, a.z / m
    n = math.sqrt(sx * sx + sy * sy + sz * sz)
    return Vec3(sx / n, sy / n, sz / n)


def normalize(a: Vec3) -> Vec3:
    """Unit vector along ``a``; a zero-length vector is a caller bug and raises.

    Correct for every non-zero finite vector, including magnitudes near 1e308 and
    subnormals near 5e-324 (a naive sum of squares returns zero or overflows there).
    """
    return _unit(a, "cannot normalize a zero-length vector")


def angle_between(a: Vec3, b: Vec3) -> float:
    """Unsigned angle in radians between two non-zero vectors, in [0, pi].

    Both vectors are normalised first, so the result is correct for any finite
    magnitude (``(1e200,0,0)`` against ``(-1e200,0,0)`` is exactly pi).
    """
    ua = _unit(a, "angle is undefined for a zero-length vector")
    ub = _unit(b, "angle is undefined for a zero-length vector")
    # atan2(|a x b|, a . b) is accurate at both ends of [0, pi]; acos of a dot product
    # loses half its digits near 0 and pi (identical unit vectors read ~1e-8, not 0).
    c = cross(ua, ub)
    return math.atan2(math.hypot(c.x, c.y, c.z), dot(ua, ub))
