"""The sub-pixel accumulator, tested directly — it is pure, so nothing needs mocking.

The rule it encodes is small and the consequence of getting it wrong is not: a pointer
driven by head pose produces fractions of a pixel per frame, and a backend that rounded
each call on its own would move for a fast turn and sit perfectly still for a slow,
deliberate one. Every assertion below is about that: nothing is dropped, nothing is
invented, and the residual cannot run away.
"""

from __future__ import annotations

import math

import pytest

from yazses.pointer.subpixel import SubPixelAccumulator


def test_whole_steps_pass_straight_through() -> None:
    acc = SubPixelAccumulator()
    assert acc.take(3.0, -4.0) == (3, -4)
    assert acc.residual == (0.0, 0.0)


def test_a_sub_step_delta_emits_nothing_yet_and_is_not_lost() -> None:
    acc = SubPixelAccumulator()
    assert acc.take(0.4, 0.0) == (0, 0)
    assert acc.take(0.4, 0.0) == (1, 0)  # 0.8 rounds to 1
    assert acc.residual[0] == pytest.approx(-0.2)


def test_ten_tenths_of_a_pixel_move_exactly_one_pixel() -> None:
    """The property that matters: total motion is preserved, not approximated away."""
    acc = SubPixelAccumulator()
    total = sum(acc.take(0.1, -0.1)[0] for _ in range(10))
    assert total == 1
    assert acc.residual[0] == pytest.approx(0.0, abs=1e-9)


def test_a_long_slow_drift_accumulates_the_right_total() -> None:
    acc = SubPixelAccumulator()
    moved_x = 0
    moved_y = 0
    for _ in range(300):  # ten seconds at 30 fps, a gentle head lean
        step_x, step_y = acc.take(0.37, -0.21)
        moved_x += step_x
        moved_y += step_y
    assert moved_x == pytest.approx(0.37 * 300, abs=1)
    assert moved_y == pytest.approx(-0.21 * 300, abs=1)


def test_the_residual_never_exceeds_half_a_step() -> None:
    """A residual that could grow would become a delayed lurch across the screen."""
    acc = SubPixelAccumulator()
    for delta in (0.3, 0.3, 0.3, 9.9, -0.45, -20.2, 0.5, 0.5, 0.5):
        acc.take(delta, -delta)
        assert abs(acc.residual[0]) <= 0.5 + 1e-9
        assert abs(acc.residual[1]) <= 0.5 + 1e-9


def test_the_two_axes_do_not_borrow_from_each_other() -> None:
    acc = SubPixelAccumulator()
    assert acc.take(0.9, 0.0) == (1, 0)
    assert acc.take(0.0, 0.9) == (0, 1)


def test_a_non_finite_delta_is_refused_rather_than_poisoning_the_residual() -> None:
    """A NaN added to the residual would stop the pointer for the rest of the session."""
    acc = SubPixelAccumulator()
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            acc.take(bad, 0.0)
        with pytest.raises(ValueError):
            acc.take(0.0, bad)
    assert acc.residual == (0.0, 0.0)
    assert acc.take(1.0, 1.0) == (1, 1), "a refused delta must leave the accumulator usable"


def test_reset_forgets_the_remainder() -> None:
    acc = SubPixelAccumulator()
    acc.take(0.4, 0.4)
    acc.reset()
    assert acc.residual == (0.0, 0.0)
    assert acc.take(0.4, 0.4) == (0, 0)
