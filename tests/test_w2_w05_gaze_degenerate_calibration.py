"""`fit_calibration` refuses degenerate or non-finite samples instead of saving a broken map.

Before the fix, ``np.linalg.lstsq`` silently returned the minimum-norm solution for a
rank-deficient design matrix. Gaze angles that never moved (a frozen or constant
estimator) produced a map that sends every future gaze to one screen point; collinear
angles produced one that collapses the plane onto a line. ``yazses gaze calibrate``
saved either as a valid calibration. A NaN or infinite sample produced a NaN map or an
unexplained LAPACK error. All are pure-function checks; no camera, model or mocks.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from yazses.gaze.calibrate import fit_calibration

_TARGETS = [(100.0, 100.0), (1800.0, 100.0), (960.0, 540.0), (100.0, 980.0), (1800.0, 980.0)]


def test_identical_gaze_angles_are_refused() -> None:
    samples = [((0.1, -0.05), xy) for xy in _TARGETS]
    with pytest.raises(ValueError, match="degenerate"):
        fit_calibration(samples)


def test_collinear_gaze_angles_are_refused() -> None:
    # pitch == 2 * yaw for every sample: the angles lie on one line.
    angles = [(-0.2, -0.4), (-0.1, -0.2), (0.0, 0.0), (0.1, 0.2), (0.2, 0.4)]
    samples = list(zip(angles, _TARGETS))
    with pytest.raises(ValueError, match="degenerate"):
        fit_calibration(samples)


def test_three_points_with_two_identical_angles_are_refused() -> None:
    samples = [((0.0, 0.0), (100.0, 100.0)), ((0.0, 0.0), (900.0, 500.0)), ((0.3, 0.1), (1800.0, 900.0))]
    with pytest.raises(ValueError, match="degenerate"):
        fit_calibration(samples)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_gaze_angle_is_refused(bad: float) -> None:
    angles = [(-0.2, -0.1), (0.2, -0.1), (bad, 0.0), (-0.2, 0.1), (0.2, 0.1)]
    samples = list(zip(angles, _TARGETS))
    with pytest.raises(ValueError, match="finite"):
        fit_calibration(samples)


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_non_finite_screen_target_is_refused(bad: float) -> None:
    angles = [(-0.2, -0.1), (0.2, -0.1), (0.0, 0.0), (-0.2, 0.1), (0.2, 0.1)]
    targets = list(_TARGETS)
    targets[1] = (bad, 100.0)
    with pytest.raises(ValueError, match="finite"):
        fit_calibration(list(zip(angles, targets)))


def test_noisy_but_well_spread_angles_still_fit() -> None:
    """The guard fires on exact degeneracy only, never on ordinary sensor noise."""
    rng = np.random.default_rng(7)

    def truth(yaw: float, pitch: float) -> tuple[float, float]:
        return (4000.0 * yaw + 960.0, 4000.0 * pitch + 540.0)

    samples = []
    for yaw in (-0.2, 0.0, 0.2):
        for pitch in (-0.1, 0.0, 0.1):
            noisy = (yaw + float(rng.normal(0, 1e-3)), pitch + float(rng.normal(0, 1e-3)))
            samples.append((noisy, truth(yaw, pitch)))
    cal = fit_calibration(samples)
    x, y = cal.predict(0.1, 0.05)
    assert abs(x - 1360.0) < 50.0 and abs(y - 740.0) < 50.0


def test_small_angular_range_is_not_mistaken_for_degeneracy() -> None:
    """A tight but genuine 2-D spread (tiny radians) must still calibrate."""
    angles = [(-1e-3, -5e-4), (1e-3, -5e-4), (0.0, 0.0), (-1e-3, 5e-4), (1e-3, 5e-4)]
    cal = fit_calibration(list(zip(angles, _TARGETS)))
    assert all(math.isfinite(v) for v in cal.predict(0.0, 0.0))
