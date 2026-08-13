"""Implicit gaze calibration from mouse clicks (#101).

Pure estimation: no camera, no desktop, no click listener. The interesting
assertions are the guardrails, because adapting to bad samples is worse than not
adapting — the user cannot see the map moving and has no way to attribute the
drift to it.
"""

from __future__ import annotations

import numpy as np
import pytest

from yazses.gaze.calibrate import CalibrationMap, fit_calibration
from yazses.gaze.implicit import ImplicitCalibrator, mean_error_px, refined_if_better

# The "true" map a simulated user's eyes obey.
TRUE = CalibrationMap(A=np.array([[900.0, 40.0, 960.0], [30.0, 700.0, 540.0]]))


def _drifted(offset_x=140.0, offset_y=-90.0) -> CalibrationMap:
    """A wizard fit that was right once and has since drifted."""
    A = np.array(TRUE.A, copy=True)
    A[0, 2] += offset_x
    A[1, 2] += offset_y
    return CalibrationMap(A=A)


def _samples(n=60, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        yaw, pitch = rng.uniform(-0.4, 0.4), rng.uniform(-0.3, 0.3)
        out.append(((yaw, pitch), TRUE.predict(yaw, pitch)))
    return out


# ---- it actually converges -------------------------------------------------


def test_clicks_pull_a_drifted_map_back_toward_truth():
    """The point of the feature: no wizard, just ordinary clicking."""
    drifted = _drifted()
    train = _samples(80)
    before = mean_error_px(drifted, train)

    cal = ImplicitCalibrator(drifted)
    for gaze, click in train:
        cal.observe(gaze, click, confidence=0.9)

    after = mean_error_px(cal.candidate, train)
    assert after < before / 5, f"expected convergence: {before:.1f}px -> {after:.1f}px"


def test_a_perfect_map_is_not_disturbed_by_good_clicks():
    """Refinement must be a no-op when there is nothing to fix."""
    cal = ImplicitCalibrator(TRUE)
    for gaze, click in _samples(40):
        cal.observe(gaze, click, confidence=1.0)
    assert mean_error_px(cal.candidate, _samples(40, seed=7)) < 1.0


def test_it_starts_from_the_baseline_not_from_nothing():
    """A cold start would make the first handful of clicks catastrophic."""
    cal = ImplicitCalibrator(_drifted())
    assert np.allclose(cal.candidate.A, _drifted().A)


# ---- the guardrails --------------------------------------------------------


def test_low_confidence_samples_are_refused():
    """Disagreeing eyes say nothing about where the person looked."""
    cal = ImplicitCalibrator(TRUE, min_confidence=0.5)
    accepted = cal.observe((0.1, 0.1), (0.0, 0.0), confidence=0.2)
    assert accepted is False
    assert (cal.accepted, cal.rejected) == (0, 1)
    assert np.allclose(cal.candidate.A, TRUE.A), "a refused sample must change nothing"


def test_a_wild_click_is_dropped_rather_than_absorbed():
    """A mis-click or a moved window is not a calibration error."""
    cal = ImplicitCalibrator(TRUE, max_residual_px=300.0)
    gaze = (0.2, 0.1)
    far = tuple(v + 5000 for v in TRUE.predict(*gaze))
    assert cal.observe(gaze, far, confidence=1.0) is False
    assert np.allclose(cal.candidate.A, TRUE.A)


def test_one_outlier_among_good_samples_does_not_wreck_the_map():
    cal = ImplicitCalibrator(_drifted())
    train = _samples(60)
    for i, (gaze, click) in enumerate(train):
        if i == 30:
            cal.observe(gaze, (click[0] + 4000, click[1] - 3000), confidence=1.0)
        cal.observe(gaze, click, confidence=0.9)
    assert mean_error_px(cal.candidate, train) < 30.0


def test_forgetting_lets_the_map_follow_a_real_change():
    """A laptop lid moves; averaging both positions forever would be wrong."""
    cal = ImplicitCalibrator(TRUE, forgetting=0.9)
    moved = _drifted(offset_x=200.0, offset_y=120.0)
    new_world = [((y, p), moved.predict(y, p)) for (y, p), _ in _samples(80, seed=3)]
    for gaze, click in new_world:
        cal.observe(gaze, click, confidence=1.0)
    assert mean_error_px(cal.candidate, new_world) < mean_error_px(TRUE, new_world) / 5


# ---- never worse than the wizard ------------------------------------------


def test_a_worse_candidate_is_rejected_on_holdout():
    """The burden of proof is on the new map; the user cannot see it move."""
    holdout = _samples(30, seed=11)
    worse = _drifted(offset_x=500.0)
    chosen, base_err, new_err = refined_if_better(TRUE, worse, holdout)
    assert chosen is TRUE
    assert new_err > base_err


def test_a_genuinely_better_candidate_is_accepted():
    holdout = _samples(30, seed=12)
    chosen, base_err, new_err = refined_if_better(_drifted(), TRUE, holdout)
    assert chosen is TRUE
    assert new_err < base_err


def test_a_marginal_improvement_does_not_count():
    """Different is not better; a tiny win is noise."""
    holdout = _samples(30, seed=13)
    barely = CalibrationMap(A=TRUE.A + np.array([[0, 0, 0.2], [0, 0, 0.0]]))
    chosen, _, _ = refined_if_better(TRUE, barely, holdout, min_improvement_px=1.0)
    assert chosen is TRUE


def test_an_empty_holdout_keeps_the_baseline():
    """No evidence must mean no change, not a free pass."""
    chosen, _, _ = refined_if_better(TRUE, _drifted(), [])
    assert chosen is TRUE


# ---- it is the same estimator as the wizard's ------------------------------


def test_rls_agrees_with_the_batch_least_squares_fit():
    """Same estimator, updated incrementally — so results cannot diverge."""
    train = _samples(120, seed=5)
    batch = fit_calibration(train)

    cal = ImplicitCalibrator(_drifted(), forgetting=1.0)  # 1.0 == plain least squares
    for gaze, click in train:
        cal.observe(gaze, click, confidence=1.0)

    assert mean_error_px(cal.candidate, train) == pytest.approx(
        mean_error_px(batch, train), abs=1.0
    )
