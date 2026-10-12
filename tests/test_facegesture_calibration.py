"""Neutral-baseline capture for the face-gesture switch (pure) — #406.

`calibrate()` turns a few seconds of a *relaxed* face into a per-gesture resting level. These
drive it with hand-written numeric traces: no camera, no model, no clock. The traces are
regression fixtures for the arithmetic and the empty/degenerate cases; none of them is evidence
about real faces, and none of the numbers is a recommended operating point.
"""
from __future__ import annotations

import json

import pytest

from yazses.facegesture.calibration import (
    DEFAULT_MIN_SAMPLES,
    MIN_HEADROOM,
    Baseline,
    Reading,
    baseline_path,
    calibrate,
    load_baselines,
    reset_baseline,
    save_baseline,
)
from yazses.facegesture.detector import GestureSwitch

_REST = [0.40, 0.42, 0.41, 0.40, 0.39, 0.41, 0.40, 0.42, 0.40, 0.41, 0.40, 0.39, 0.41, 0.40, 0.42]


def _readings(scores, conf=0.9):
    return [Reading(s, conf) for s in scores]


def test_the_baseline_is_the_median_of_a_relaxed_trace():
    result = calibrate("jaw_open", _readings(_REST))
    assert result.ok and result.reason == ""
    assert result.baseline is not None
    assert result.baseline.level == pytest.approx(0.40)
    assert result.baseline.samples == len(_REST)
    assert result.baseline.spread < 0.02


def test_one_outlier_does_not_move_the_baseline():
    """A swallow or a yawn during the capture is an outlier, not the resting level."""
    noisy = _REST[:7] + [0.98] + _REST[7:]
    mean = sum(noisy) / len(noisy)
    result = calibrate("jaw_open", _readings(noisy))
    assert result.baseline is not None
    assert result.baseline.level == pytest.approx(0.40, abs=0.01)
    assert mean > result.baseline.level + 0.03, "premise: a mean would have been dragged up"


def test_no_frames_at_all_is_a_defined_failure_not_a_zero_baseline():
    result = calibrate("jaw_open", [])
    assert result.baseline is None and not result.ok
    assert result.reason == "too_few_samples"
    assert result.kept == 0


def test_frames_with_no_reading_are_dropped_and_counted():
    result = calibrate("jaw_open", [Reading(None, None)] * 40)
    assert result.baseline is None
    assert result.reason == "too_few_samples"
    assert result.dropped_no_reading == 40


def test_a_non_finite_score_is_dropped_not_averaged():
    frames = _readings(_REST) + [Reading(float("nan"), 0.9), Reading(float("inf"), 0.9)]
    result = calibrate("jaw_open", frames)
    assert result.baseline is not None
    assert result.dropped_no_reading == 2
    assert result.kept == len(_REST)


def test_too_few_confident_frames_refuses_to_guess():
    result = calibrate("jaw_open", _readings(_REST[: DEFAULT_MIN_SAMPLES - 1]))
    assert result.baseline is None and result.reason == "too_few_samples"


def test_low_confidence_frames_are_excluded_exactly_as_the_switch_would_refuse_them():
    low = _readings([0.95] * 30, conf=0.1)  # a bad capture: confidently wrong would be worse
    frames = _readings(_REST) + low
    result = calibrate("jaw_open", frames, confidence_floor=0.6)
    assert result.baseline is not None
    assert result.baseline.level == pytest.approx(0.40)
    assert result.dropped_low_confidence == 30


def test_with_a_floor_a_frame_that_reports_no_confidence_is_not_trusted():
    result = calibrate("jaw_open", _readings(_REST, conf=None), confidence_floor=0.5)
    assert result.baseline is None
    assert result.dropped_low_confidence == len(_REST)
    # ...and without a floor it is kept.
    assert calibrate("jaw_open", _readings(_REST, conf=None)).ok


def test_a_face_that_rests_near_the_top_of_the_range_has_no_headroom():
    """Normalising would divide by ~0: refused at capture, with a stable reason."""
    result = calibrate("jaw_open", _readings([0.85] * 30))
    assert result.baseline is None and result.reason == "no_headroom"
    assert 1 - 0.85 < MIN_HEADROOM


def test_a_face_pinned_at_exactly_one_is_the_zero_denominator_case():
    result = calibrate("jaw_open", _readings([1.0] * 30))
    assert result.baseline is None and result.reason == "no_headroom"


def test_out_of_range_scores_are_clamped_rather_than_trusted():
    result = calibrate("jaw_open", _readings([-0.5] * 20))
    assert result.baseline is not None and result.baseline.level == 0.0


def test_a_noisy_neutral_is_flagged_as_not_separable_from_the_hold_threshold():
    steady = calibrate("jaw_open", _readings(_REST)).baseline
    assert steady is not None and steady.separable_from(0.5)
    # A neutral face whose own wobble spans most of the range cannot be separated from
    # a gesture by a 0.5 threshold, and the baseline says so instead of firing on it.
    wobble = [0.1, 0.7, 0.2, 0.8, 0.15, 0.75, 0.1, 0.7, 0.2, 0.8, 0.1, 0.7, 0.2, 0.8, 0.1]
    noisy = calibrate("jaw_open", _readings(wobble)).baseline
    assert noisy is not None and not noisy.separable_from(0.5)


def test_an_unusable_baseline_is_never_separable():
    assert not Baseline("jaw_open", 0.95, 0.0, 20).separable_from(0.5)
    assert not Baseline("jaw_open", 0.2, 0.01, 20).separable_from(float("nan"))


def test_a_captured_baseline_feeds_the_switch_and_stops_the_phantom_hold():
    """End to end over numbers: capture the resting face, then run the switch on it."""
    rest = [0.50, 0.52, 0.51, 0.50, 0.53, 0.51, 0.50, 0.52, 0.50, 0.51, 0.52, 0.50, 0.51, 0.50, 0.52]
    base = calibrate("jaw_open", _readings(rest)).baseline
    assert base is not None
    absolute, calibrated = GestureSwitch(), GestureSwitch(baseline=base.level)
    a = [e for s in rest if (e := absolute.update(s))]
    c = [e for s in rest if (e := calibrated.update(s))]
    assert a == ["start"] and c == []
    assert [e for s in [0.97] * 4 if (e := calibrated.update(s))] == ["start"]


# -- persistence: derived numbers only -------------------------------------


def test_a_baseline_round_trips_and_stores_only_derived_numbers(tmp_path):
    path = baseline_path(tmp_path)
    save_baseline(path, Baseline("jaw_open", 0.4, 0.01, 30))
    assert load_baselines(path)["jaw_open"] == Baseline("jaw_open", 0.4, 0.01, 30)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert set(stored["baselines"][0]) == {"gesture", "level", "spread", "samples"}


def test_saving_a_second_gesture_keeps_the_first_and_replaces_the_same_one(tmp_path):
    path = baseline_path(tmp_path)
    save_baseline(path, Baseline("jaw_open", 0.4, 0.01, 30))
    save_baseline(path, Baseline("brow_raise", 0.1, 0.02, 30))
    save_baseline(path, Baseline("jaw_open", 0.3, 0.01, 30))
    got = load_baselines(path)
    assert got["jaw_open"].level == 0.3 and got["brow_raise"].level == 0.1


def test_reset_forgets_one_gesture_or_all(tmp_path):
    path = baseline_path(tmp_path)
    save_baseline(path, Baseline("jaw_open", 0.4, 0.01, 30))
    save_baseline(path, Baseline("brow_raise", 0.1, 0.02, 30))
    assert reset_baseline(path, "jaw_open") is True
    assert set(load_baselines(path)) == {"brow_raise"}
    assert reset_baseline(path, "jaw_open") is False
    assert reset_baseline(path) is True
    assert load_baselines(path) == {}
    assert reset_baseline(path) is False


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json",
        "[]",
        "{}",
        '{"baselines": "nope"}',
        '{"baselines": [1, null, "x"]}',
        '{"baselines": [{"gesture": "jaw_open", "level": "high", "spread": 0, "samples": 3}]}',
        '{"baselines": [{"gesture": "jaw_open", "level": 1.5, "spread": 0, "samples": 3}]}',
        '{"baselines": [{"gesture": "jaw_open", "level": 0.2, "spread": -1, "samples": 3}]}',
        '{"baselines": [{"gesture": "jaw_open", "level": 0.2, "spread": 0, "samples": 0}]}',
        '{"baselines": [{"gesture": "jaw_open", "level": true, "spread": 0, "samples": 3}]}',
        '{"baselines": [{"gesture": "", "level": 0.2, "spread": 0, "samples": 3}]}',
    ],
)
def test_an_unreadable_baseline_file_is_no_baseline_never_an_exception(tmp_path, content):
    path = baseline_path(tmp_path)
    path.write_text(content, encoding="utf-8")
    assert load_baselines(path) == {}


def test_a_missing_file_is_no_baseline(tmp_path):
    assert load_baselines(tmp_path / "nope.json") == {}


def test_one_malformed_entry_does_not_discard_its_neighbours(tmp_path):
    path = baseline_path(tmp_path)
    path.write_text(
        json.dumps({"baselines": [
            {"gesture": "jaw_open", "level": "bad", "spread": 0, "samples": 3},
            {"gesture": "smile", "level": 0.2, "spread": 0.01, "samples": 12},
        ]}),
        encoding="utf-8",
    )
    assert set(load_baselines(path)) == {"smile"}
