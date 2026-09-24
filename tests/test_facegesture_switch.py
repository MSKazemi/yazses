"""Face-gesture switch access — the pure activation policy (#102).

The whole point of splitting `facegesture/detector.py` out of the capture loop is
that the decision "is the user holding the gesture" is testable with no camera, no
model and no mediapipe. These drive the state machine frame by frame.
"""
from __future__ import annotations

import pytest

from yazses.facegesture.detector import (
    GESTURES,
    GestureSwitch,
    blendshape_scores,
    gesture_names,
    gesture_score,
)


class _Cat:
    """Stand-in for a MediaPipe blendshape category."""

    def __init__(self, name, score):
        self.category_name = name
        self.score = score


def _drive(switch, scores):
    """Feed a whole score sequence and return the events it produced."""
    return [e for e in (switch.update(s) for s in scores) if e is not None]


def test_blendshape_scores_flattens_mediapipe_categories():
    got = blendshape_scores([_Cat("jawOpen", 0.7), _Cat("browInnerUp", 0.1)])
    assert got == {"jawOpen": 0.7, "browInnerUp": 0.1}


def test_blendshape_scores_survives_a_malformed_category():
    assert blendshape_scores([_Cat("jawOpen", 0.4), object()]) == {"jawOpen": 0.4}


def test_gesture_score_is_the_max_over_the_gestures_categories():
    # An asymmetric brow raise (one brow leads) must score as the strong side; a
    # mean would halve a movement the user really made.
    scores = {"browInnerUp": 0.2, "browOuterUpLeft": 0.8, "browOuterUpRight": 0.1}
    assert gesture_score(scores, "brow_raise") == pytest.approx(0.8)


def test_gesture_score_is_none_for_an_unknown_gesture_or_a_missing_reading():
    assert gesture_score({"jawOpen": 0.9}, "wink") is None
    assert gesture_score({"browInnerUp": 0.9}, "jaw_open") is None


def test_every_gesture_name_maps_to_at_least_one_blendshape():
    assert set(gesture_names()) == set(GESTURES)
    assert all(GESTURES[g] for g in gesture_names())


def test_a_held_gesture_opens_then_closes_exactly_once():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=3, min_release_frames=2)
    events = _drive(sw, [0.8] * 5 + [0.0] * 4)
    assert events == ["start", "end"]
    assert sw.held is False


def test_the_mic_opens_only_after_min_hold_frames():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=3, min_release_frames=2)
    assert sw.update(0.9) is None
    assert sw.update(0.9) is None
    assert sw.update(0.9) == "start"


def test_a_transient_spike_does_not_fire_the_switch():
    # Two frames of jawOpen is a laugh or a yawn, not a hold. This is the
    # Midas-touch defence: without it the mic opens all day.
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=3)
    assert _drive(sw, [0.9, 0.95, 0.1, 0.0, 0.9, 0.2]) == []


def test_hysteresis_keeps_one_hold_when_the_score_dithers_at_the_threshold():
    # Scores sitting on the hold threshold cross it repeatedly. With a single
    # threshold this is a burst of one-word recordings; with two it is one hold.
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=2, min_release_frames=2)
    events = _drive(sw, [0.6, 0.6] + [0.49, 0.52, 0.48, 0.51] * 3)
    assert events == ["start"]
    assert sw.held is True


def test_a_lost_face_releases_the_hold_rather_than_leaving_the_mic_open():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=2, min_release_frames=2)
    assert _drive(sw, [0.9, 0.9]) == ["start"]
    assert _drive(sw, [None, None]) == ["end"]


def test_one_dropped_frame_does_not_cut_a_held_gesture_in_half():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=2, min_release_frames=2)
    _drive(sw, [0.9, 0.9])
    assert _drive(sw, [None, 0.9, 0.9, 0.9]) == []
    assert sw.held is True


def test_a_release_threshold_at_or_above_the_hold_threshold_is_repaired():
    # Not rejected: a bad number must not cost someone their only input method.
    sw = GestureSwitch(0.5, 0.9)
    assert sw.repaired_release is True
    hold, release = sw.thresholds
    assert release < hold


def test_thresholds_outside_zero_to_one_are_clamped():
    sw = GestureSwitch(5.0, -2.0)
    hold, release = sw.thresholds
    assert (hold, release) == (1.0, 0.0)


def test_frame_counts_below_one_are_treated_as_one():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=0, min_release_frames=0)
    assert sw.update(0.9) == "start"
    assert sw.update(0.0) == "end"


def test_reset_releases_an_open_hold_and_is_idempotent():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=1)
    sw.update(0.9)
    assert sw.reset() == "end"
    assert sw.reset() is None
