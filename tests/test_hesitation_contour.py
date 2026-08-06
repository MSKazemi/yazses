"""Hesitation-Hold Endpointing (ADR-v2-101) + Pitch-Contour Gestures (ADR-v2-103) — pure cores."""
from __future__ import annotations

from yazses.contour.gesture import classify_contour, gesture_to_command, normalize_contour
from yazses.hesitation.endpoint import endpoint_decision, is_filled_pause

# ---- hesitation-hold endpointing -------------------------------------------

def test_is_filled_pause():
    assert is_filled_pause([120, 122, 119, 121], spectral_stability=0.9) is True   # flat + stable
    assert is_filled_pause([120, 200, 90], spectral_stability=0.9) is False          # wide F0 swing
    assert is_filled_pause([120, 121], spectral_stability=0.3) is False              # unstable spectrum
    assert is_filled_pause([0, 0, 0], spectral_stability=0.9) is False               # no voiced frames
    assert is_filled_pause([], spectral_stability=1.0) is False


def test_endpoint_decision_extends_after_filled_pause():
    # 900 ms silence commits normally, but holds right after a filled pause
    assert endpoint_decision(900, last_was_filled_pause=False) == "commit"
    assert endpoint_decision(900, last_was_filled_pause=True) == "hold"
    assert endpoint_decision(2100, last_was_filled_pause=True) == "commit"
    assert endpoint_decision(500, last_was_filled_pause=False) == "hold"


# ---- pitch-contour gestures ------------------------------------------------

def test_normalize_contour():
    out = normalize_contour([100, 0, 200, 300])   # drops the unvoiced 0
    assert len(out) == 3
    flat = normalize_contour([200, 200, 200, 200])
    assert all(abs(x) < 1e-9 for x in flat)         # constant pitch → ~zero semitone deviation
    assert normalize_contour([100]) == []           # too few voiced


def test_classify_contour():
    assert classify_contour(normalize_contour([100, 150, 220, 300])) == "rise"
    assert classify_contour(normalize_contour([300, 220, 150, 100])) == "fall"
    assert classify_contour(normalize_contour([100, 260, 300, 250, 110])) == "rise_fall"
    assert classify_contour(normalize_contour([200, 201, 199, 200])) == "flat"
    assert classify_contour([]) == "flat"


def test_gesture_to_command():
    assert gesture_to_command("rise") == "confirm"
    assert gesture_to_command("fall") == "cancel"
    assert gesture_to_command("rise_fall") == "undo"
    assert gesture_to_command("rise", profile={"rise": "accept"}) == "accept"
    assert gesture_to_command("unknown") is None


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "hesitation" in slugs and "contour" in slugs
    assert Config().hesitation.enabled is False and Config().contour.enabled is False
