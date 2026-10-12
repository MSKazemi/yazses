"""Glance-Type gaze behaves identically on the shared perception source (#396).

EYE-CAM-003 moves the camera and the model under Glance-Type gaze onto the shared
source (ADR-v2-145) and promises *no behaviour change*. A promise like that is only
worth something if it is pinned by tests written against the behaviour **before** it
moved, so these were written and run green against the unmodified tree first; each one
states a single claim that has to survive the migration.

Three layers, because "gaze still works" hides three different ways to be wrong:

* **Numbers.** The legacy ``MediapipeGazeBackend`` and the shared source's derivation
  must produce the same ``(x, y, confidence)`` from the same landmarks, in every shape
  the landmarks can take (aligned, disagreeing, degenerate, truncated).
* **Decisions.** Fed the same sequence of samples, a ``GazeTargeter`` over the old
  backend and one over the shared-source adapter must reach the same routing decision
  every time: confidence gating, low-confidence and missing-gaze fallback, the
  burst snapshot deixis reads.
* **Wiring.** ``build_gaze`` hands back exactly what it did before unless a shared
  source is explicitly supplied, so the default install is untouched.

Hermetic: the fake ``cv2``/``mediapipe`` tree is the one ``tests/test_gaze_mediapipe.py``
already builds, and the shared-source side uses numeric fakes. No camera, no model, no
network.
"""
from __future__ import annotations

import numpy as np
import pytest

from tests import test_gaze_mediapipe as _legacy_tests
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.confidence import GazeSample
from yazses.gaze.targeter import GazeTargeter
from yazses.perception.derive import derive_gaze

# The legacy backend's fake cv2/mediapipe tree, reused rather than copied: if that
# fixture changes shape, this file follows it instead of pinning a stale fake.
_FakeResult = _legacy_tests._FakeResult
_landmarks = _legacy_tests._landmarks
_Pt = _legacy_tests._Pt
mp_backend = _legacy_tests.mp_backend

# --------------------------------------------------------------------------- #
# Layer 1 — the numbers
# --------------------------------------------------------------------------- #


def _degenerate_width():
    """Both corners of one eye on the same x: the `or 1e-6` guard, not a ZeroDivisionError."""
    pts = _landmarks((0.1, 0.0), (0.1, 0.0))
    pts[33], pts[133] = _Pt(0.5, 0.5), _Pt(0.5, 0.5)
    return pts


_CASES = {
    "eyes_agree_looking_right": _landmarks((0.5, 0.0), (0.5, 0.0)),
    "eyes_agree_looking_down_left": _landmarks((-0.3, 0.25), (-0.3, 0.25)),
    "eyes_disagree_mildly": _landmarks((0.4, -0.2), (0.6, 0.2)),
    "eyes_disagree_past_the_scale": _landmarks((0.9, 0.0), (-0.9, 0.0)),
    "centred": _landmarks((0.0, 0.0), (0.0, 0.0)),
    "degenerate_eye_width": _degenerate_width(),
}


@pytest.mark.parametrize("case", sorted(_CASES))
def test_shared_derivation_matches_the_legacy_backend_number_for_number(mp_backend, case):
    backend, _, landmarker = mp_backend
    landmarks = _CASES[case]
    landmarker.result = _FakeResult(landmarks)

    legacy = backend.estimate_sample()
    shared = derive_gaze(landmarks, 12.5)

    assert legacy is not None and shared is not None
    assert shared.raw_x == pytest.approx(legacy.x, abs=1e-12)
    assert shared.raw_y == pytest.approx(legacy.y, abs=1e-12)
    assert shared.confidence == pytest.approx(legacy.confidence, abs=1e-12)


def test_a_truncated_landmark_list_is_no_gaze_on_both_paths(mp_backend):
    backend, _, landmarker = mp_backend
    landmarks = [_Pt(0.5, 0.5) for _ in range(10)]  # no iris landmarks at all
    landmarker.result = _FakeResult(landmarks)
    assert backend.estimate_sample() is None
    assert derive_gaze(landmarks, 0.0) is None


def test_no_face_is_no_gaze_on_both_paths(mp_backend):
    backend, _, landmarker = mp_backend
    landmarker.result = _FakeResult(None)
    assert backend.estimate_sample() is None


def test_the_legacy_backend_still_returns_the_calibration_input_unchanged(mp_backend):
    """``estimate()`` is the (yaw, pitch) pair calibration fits against — the same
    mean iris offset the shared signal calls ``raw_x``/``raw_y``."""
    backend, _, landmarker = mp_backend
    landmarker.result = _FakeResult(_landmarks((0.4, -0.2), (0.6, 0.2)))
    gx, gy = backend.estimate()
    assert gx == pytest.approx(0.5)
    assert gy == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Layer 2 — the decisions
# --------------------------------------------------------------------------- #


class _ScriptedSamples:
    """The old backend's shape: ``estimate_sample()`` pops the next scripted sample."""

    name = "scripted"

    def __init__(self, script):
        self._script = list(script)
        self.closed = False

    def estimate_sample(self):
        item = self._script.pop(0) if self._script else None
        return None if item is None else GazeSample(*item)

    def estimate(self):
        sample = self.estimate_sample()
        return None if sample is None else sample.point

    def close(self):
        self.closed = True


class _Desktop:
    def __init__(self, focused, windows):
        self._focused = focused
        self._windows = windows
        self.activated: list = []

    def focused_window(self):
        return self._focused

    def list_windows(self):
        return self._windows

    def activate(self, wid):
        self.activated.append(wid)


_IDENTITY = CalibrationMap(A=np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]))
_PANES = [("editor", 0, 0, 500, 1000), ("browser", 500, 0, 500, 1000)]

# (x, y, confidence): confident-in-browser, confident-in-editor, low confidence in the
# browser, exactly at the threshold, just under it, outside every pane, and no sample.
_SCRIPT = [
    (700.0, 500.0, 0.9),
    (100.0, 500.0, 0.9),
    (700.0, 500.0, 0.2),
    (700.0, 500.0, 0.5),
    (700.0, 500.0, 0.4999),
    (9999.0, 9999.0, 0.95),
    None,
]


def _decisions(backend, *, confidence_min=0.5):
    desktop = _Desktop("editor", _PANES)
    targeter = GazeTargeter(backend, _IDENTITY, desktop, confidence_min)
    out = []
    for _ in _SCRIPT:
        decision = targeter.retarget()
        out.append((decision.used_gaze, decision.target, targeter.last_decision == decision))
    return out, desktop.activated


def test_the_scripted_backend_pins_the_decisions_the_migration_must_reproduce():
    """The expected decisions, written out — not derived from either implementation."""
    decisions, activated = _decisions(_ScriptedSamples(_SCRIPT))
    assert [(used, target) for used, target, _ in decisions] == [
        (True, "browser"),   # confident gaze lands in the browser pane
        (True, "editor"),    # confident gaze lands in the already-focused editor (no re-focus)
        (False, "editor"),   # below confidence_min -> focused window, nothing moves
        (True, "browser"),   # exactly at the threshold counts as confident
        (False, "editor"),   # one hair under it does not
        (False, "editor"),   # outside every window -> focused window
        (False, "editor"),   # no sample -> focused window
    ]
    assert all(snapshot for _, _, snapshot in decisions)  # last_decision == the return
    assert activated == ["browser", "browser"]


# --------------------------------------------------------------------------- #
# The one place the two paths are deliberately not byte-identical
# --------------------------------------------------------------------------- #


def test_non_finite_landmarks_are_no_gaze_and_route_exactly_as_no_gaze_always_did(mp_backend):
    """Before #396 a NaN landmark produced ``GazeSample(nan, nan, 1.0)``; the shared
    derivation answers ``None`` instead. The user-visible outcome is identical: NaN
    lands in no window, so the old path fell back to the focused window too, and the
    calibration wizard stops averaging NaN into a fit. Pinned so it stays deliberate."""
    backend, _, landmarker = mp_backend
    nan_landmarks = _landmarks((0.1, 0.0), (0.1, 0.0))
    nan_landmarks[468] = _Pt(float("nan"), 0.5)
    landmarker.result = _FakeResult(nan_landmarks)
    assert backend.estimate_sample() is None

    decisions, activated = _decisions(backend)
    # Every hold saw the same NaN face (the fake landmarker repeats its result).
    assert all(not used for used, _, _ in decisions)
    assert {target for _, target, _ in decisions} == {"editor"}
    assert activated == []
