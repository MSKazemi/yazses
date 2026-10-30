"""``yazses.xr.geometry`` — vector helpers over the full finite float range."""
from __future__ import annotations

import math
import sys

import pytest

from yazses.xr.geometry import angle_between, norm, normalize
from yazses.xr.types import Vec3

BIG = 1e200
TINY = 1e-200
MAX = sys.float_info.max


def test_normalize_huge_vector_is_not_the_zero_vector() -> None:
    # Reproducer: used to return Vec3(0, 0, 0) because x*x overflowed to inf.
    assert normalize(Vec3(BIG, 0, 0)) == Vec3(1.0, 0.0, 0.0)


def test_normalize_tiny_nonzero_vector_does_not_claim_zero_length() -> None:
    # Reproducer: used to raise "zero-length" because x*x underflowed to 0.
    assert normalize(Vec3(TINY, 0, 0)) == Vec3(1.0, 0.0, 0.0)


@pytest.mark.parametrize("mag", [5e-324, 1e-310, 1e-200, 1e-3, 1.0, 1e3, 1e200, MAX])
def test_normalize_is_unit_length_at_every_magnitude(mag: float) -> None:
    u = normalize(Vec3(mag, -mag, mag))
    assert math.hypot(u.x, u.y, u.z) == pytest.approx(1.0, abs=1e-12)
    assert u.x == pytest.approx(1 / math.sqrt(3), abs=1e-12)


def test_normalize_zero_vector_still_raises() -> None:
    with pytest.raises(ValueError, match="zero-length"):
        normalize(Vec3(0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="zero-length"):
        normalize(Vec3(-0.0, 0.0, -0.0))


def test_angle_between_opposite_huge_vectors_is_pi() -> None:
    # Reproducer: used to raise / return garbage because dot and norm overflowed.
    assert angle_between(Vec3(BIG, 0, 0), Vec3(-BIG, 0, 0)) == pytest.approx(math.pi)


def test_angle_between_mixed_magnitudes() -> None:
    assert angle_between(Vec3(BIG, 0, 0), Vec3(0, TINY, 0)) == pytest.approx(math.pi / 2)
    assert angle_between(Vec3(TINY, 0, 0), Vec3(TINY, 0, 0)) == pytest.approx(0.0, abs=1e-7)


def test_angle_between_zero_vector_raises() -> None:
    with pytest.raises(ValueError, match="zero-length"):
        angle_between(Vec3(0, 0, 0), Vec3(1, 0, 0))
    with pytest.raises(ValueError, match="zero-length"):
        angle_between(Vec3(1, 0, 0), Vec3(0, 0, 0))


def test_norm_survives_overflow_and_underflow() -> None:
    assert norm(Vec3(BIG, 0, 0)) == BIG
    assert norm(Vec3(TINY, 0, 0)) == TINY
    assert norm(Vec3(3.0, 4.0, 0.0)) == 5.0
    assert norm(Vec3(0.0, 0.0, 0.0)) == 0.0
