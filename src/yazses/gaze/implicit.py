"""Refine the gaze calibration from ordinary mouse clicks (#101).

A click is ground truth: the user was looking at what they clicked, ~100 ms
before the button went down. Explicit wizard calibration drifts within a session
— studies re-run it three times — and every current desktop gaze tool, commercial
or open source, still asks the user to sit through a 9-point wizard whenever it
does. Implicit adaptation reaches 2.9° with **no** explicit calibration in the
literature (Sugano et al.); this is the same idea applied to the affine map
`gaze/calibrate.py` already fits.

The estimator is **recursive least squares** — mathematically the same fit as
`fit_calibration`, updated one sample at a time instead of re-solving over a
growing list. That matters for a background refinement: cost per click is
constant and no history has to be retained, so nothing accumulates on disk and
there is nothing to leak.

## The guardrails are the design

Adapting to bad samples is worse than not adapting, because the user cannot see
the map moving and has no way to attribute the drift:

* **Low-confidence samples are refused.** Eye agreement below the configured
  floor means the two eyes disagree about direction, and a click at that moment
  says nothing about where the person looked.
* **A forgetting factor** (< 1) weights recent clicks above old ones, which is
  what lets the map follow a laptop lid being adjusted instead of averaging
  across both positions forever.
* **A residual gate.** A click a long way from the current prediction is more
  likely a mis-click, a moved window, or a face-tracking glitch than a genuine
  calibration error, so it is dropped rather than absorbed.
* **Never worse than the wizard.** `refined_if_better` compares the candidate
  against the baseline on **held-out** samples and returns the baseline unless
  the candidate genuinely wins — the same held-out rule ADR-014 uses for tuning.
  This is what makes "apply refined calibration" safe to offer.

Nothing here opens a camera or listens for clicks; it is pure estimation, so it
tests without a desktop. Sample capture is the caller's job and is opt-in per
ADR-011/012.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from yazses.gaze.calibrate import CalibrationMap

# Defaults; all overridable.
DEFAULT_FORGETTING = 0.995      # ~200-click memory: follows a lid angle, ignores noise
DEFAULT_MAX_RESIDUAL_PX = 400.0  # beyond this a click is not a calibration error
DEFAULT_MIN_CONFIDENCE = 0.5


@dataclass
class ImplicitCalibrator:
    """Recursive-least-squares refinement of an affine gaze→screen map.

    Seeded from an existing map so refinement *starts* at the wizard's answer and
    moves away from it only as evidence arrives — a cold start would make the
    first few clicks catastrophic.
    """

    baseline: CalibrationMap
    forgetting: float = DEFAULT_FORGETTING
    max_residual_px: float = DEFAULT_MAX_RESIDUAL_PX
    min_confidence: float = DEFAULT_MIN_CONFIDENCE

    _A: np.ndarray = field(init=False)
    # Inverse correlation matrix, per RLS. Large diagonal = "we are not confident
    # in the seed", so early samples move the map more than late ones.
    _P: np.ndarray = field(init=False)
    accepted: int = field(default=0, init=False)
    rejected: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self._A = np.array(self.baseline.A, dtype="float64", copy=True)
        self._P = np.eye(3, dtype="float64") * 1000.0

    # ---- estimation ------------------------------------------------------

    def observe(
        self,
        gaze: tuple[float, float],
        click: tuple[float, float],
        *,
        confidence: float = 1.0,
    ) -> bool:
        """Fold one (gaze, click) pair in. True when it was accepted.

        Returning a bool rather than raising keeps the caller a one-liner: a
        rejected sample is the normal case, not an error.
        """
        if confidence < self.min_confidence:
            self.rejected += 1
            return False

        phi = np.array([gaze[0], gaze[1], 1.0], dtype="float64")
        predicted = self._A @ phi
        error = np.array(click, dtype="float64") - predicted
        if float(np.hypot(*error)) > self.max_residual_px:
            # More likely a mis-click or a moved window than a calibration error.
            self.rejected += 1
            return False

        # Standard RLS update, shared across both output axes because they see
        # the same regressor.
        p_phi = self._P @ phi
        denom = self.forgetting + float(phi @ p_phi)
        gain = p_phi / denom
        self._A = self._A + np.outer(error, gain)
        self._P = (self._P - np.outer(gain, p_phi)) / self.forgetting
        self.accepted += 1
        return True

    @property
    def candidate(self) -> CalibrationMap:
        """The refined map as it currently stands."""
        return CalibrationMap(A=np.array(self._A, copy=True))


# ---- evaluation ---------------------------------------------------------


def mean_error_px(cal: CalibrationMap, samples) -> float:
    """Mean euclidean error of *cal* over ``[((yaw, pitch), (x, y)), ...]``."""
    if not samples:
        return float("inf")
    total = 0.0
    for (yaw, pitch), (x, y) in samples:
        px, py = cal.predict(yaw, pitch)
        total += float(np.hypot(px - x, py - y))
    return total / len(samples)


def refined_if_better(
    baseline: CalibrationMap,
    candidate: CalibrationMap,
    holdout,
    *,
    min_improvement_px: float = 1.0,
) -> tuple[CalibrationMap, float, float]:
    """Return whichever map is better on *holdout*, plus both errors.

    The gate is held-out data and a margin, not "the candidate saw more samples".
    A refinement that is merely different is a regression waiting to be blamed on
    something else, and the user cannot see the map — so the burden of proof sits
    with the new map, exactly as ADR-014 requires for tuning proposals.
    """
    base_error = mean_error_px(baseline, holdout)
    new_error = mean_error_px(candidate, holdout)
    if not holdout or new_error > base_error - min_improvement_px:
        return baseline, base_error, new_error
    return candidate, base_error, new_error
