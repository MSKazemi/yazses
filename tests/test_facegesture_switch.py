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


# ---------------------------------------------------------------------------
# EYE-FACE-001 (#406): per-user baseline, a distinct confidence floor, refractory.
#
# Every trace below is a hand-written numeric list. They are regression fixtures for the
# *decision rule*, not evidence that any threshold is right for real faces: nothing here was
# measured on a person, and design/eye-control/ROADMAP.md (P5.4) forbids recommending a
# default from synthetic data. The thresholds in these tests are chosen to make a case
# unambiguous, and say nothing about what a user should set.
# ---------------------------------------------------------------------------

from yazses.facegesture.calibration import Reading, normalise  # noqa: E402
from yazses.facegesture.detector import gesture_reading  # noqa: E402
from yazses.perception.signals import FaceSignal  # noqa: E402


def _drive_frames(switch, frames):
    """Feed ``(score, confidence)`` pairs (or Reading tuples) and return the events."""
    return [e for e in (switch.update(s, c) for s, c in frames) if e is not None]


# -- confidence floor ------------------------------------------------------


def test_a_deliberate_gesture_at_good_confidence_fires_exactly_once():
    sw = GestureSwitch(confidence_floor=0.6)
    trace = [(0.1, 0.9)] * 3 + [(0.9, 0.9)] * 6 + [(0.1, 0.9)] * 4
    assert _drive_frames(sw, trace) == ["start", "end"]


def test_the_same_gesture_at_low_confidence_emits_nothing():
    sw = GestureSwitch(confidence_floor=0.6)
    trace = [(0.9, 0.2)] * 12
    assert _drive_frames(sw, trace) == []
    # Reported as low confidence, not as a relaxed face: the two are different facts.
    assert sw.last_frame == "low_confidence"
    assert sw.held is False


def test_low_confidence_is_a_distinct_input_not_a_low_score():
    """A high score under a low confidence and a low score under a high one are not the
    same frame, and the switch must be able to say which it saw."""
    sw = GestureSwitch(confidence_floor=0.6)
    sw.update(0.9, 0.1)
    assert sw.last_frame == "low_confidence"
    sw.update(0.05, 0.99)
    assert sw.last_frame == "reading"


def test_a_missing_confidence_is_not_trusted_once_a_floor_is_set():
    sw = GestureSwitch(confidence_floor=0.6)
    assert _drive_frames(sw, [(0.9, None)] * 8) == []
    assert sw.last_frame == "low_confidence"


def test_with_no_floor_the_confidence_is_ignored_entirely():
    """Floor 0 is the shipped behaviour: even a 0.0 or NaN confidence changes nothing."""
    sw = GestureSwitch()
    assert _drive_frames(sw, [(0.9, 0.0), (0.9, float("nan")), (0.9, None)]) == ["start"]


def test_one_low_confidence_frame_restarts_the_hold_debounce():
    """It counts as no reading, so it breaks the run of frames above threshold."""
    sw = GestureSwitch(confidence_floor=0.6)
    trace = [(0.9, 0.9), (0.9, 0.9), (0.9, 0.1), (0.9, 0.9), (0.9, 0.9)]
    assert _drive_frames(sw, trace) == []
    assert _drive_frames(sw, [(0.9, 0.9)]) == ["start"]


def test_one_blurred_frame_does_not_cut_a_held_gesture():
    sw = GestureSwitch(confidence_floor=0.6)
    _drive_frames(sw, [(0.9, 0.9)] * 3)
    assert sw.held is True
    assert _drive_frames(sw, [(0.9, 0.1), (0.9, 0.9), (0.9, 0.9)]) == []
    assert sw.held is True


def test_sustained_low_confidence_releases_a_held_gesture():
    """Fail safe: a landmarker that has lost the face must not leave the mic open.

    This is the one event a low-confidence frame can produce, and it is an end, never a start.
    """
    sw = GestureSwitch(confidence_floor=0.6)
    _drive_frames(sw, [(0.9, 0.9)] * 3)
    assert _drive_frames(sw, [(0.9, 0.1)] * 2) == ["end"]


@pytest.mark.parametrize("bad", ["x", -1.0, float("nan"), None])
def test_an_unreadable_floor_turns_the_gate_off_rather_than_locking_the_user_out(bad):
    sw = GestureSwitch(confidence_floor=bad)  # type: ignore[arg-type]
    assert _drive_frames(sw, [(0.9, 0.8)] * 4) == ["start"]


def test_an_out_of_range_floor_clamps_to_a_real_strict_gate():
    sw = GestureSwitch(confidence_floor=5.0)
    assert _drive_frames(sw, [(0.9, 0.99)] * 4) == []
    assert _drive_frames(sw, [(0.9, 1.0)] * 4) == ["start"]


# -- baseline normalisation ------------------------------------------------


# A user whose resting jaw-open score hovers around 0.45, with small wobble.
_RESTING_JITTER = [0.45, 0.50, 0.52, 0.51, 0.47, 0.52, 0.53, 0.49, 0.46, 0.45]
# The same user making a deliberate jaw-open, then relaxing back to rest.
_DELIBERATE = [0.95, 0.96, 0.95, 0.94, 0.95]
_RELAX = [0.46, 0.45, 0.46]


def test_baseline_changes_the_decision_for_a_user_with_a_non_zero_resting_score():
    """Same numbers, two verdicts: the absolute switch phantom-fires on a resting face."""
    absolute = GestureSwitch()
    assert _drive(absolute, _RESTING_JITTER) == ["start"], (
        "premise: without a baseline this resting face reaches the hold threshold"
    )

    calibrated = GestureSwitch(baseline=0.45)
    assert _drive(calibrated, _RESTING_JITTER) == []
    assert calibrated.held is False


def test_a_calibrated_user_still_fires_once_on_the_deliberate_gesture():
    sw = GestureSwitch(baseline=0.45)
    assert _drive(sw, _RESTING_JITTER + _DELIBERATE + _RELAX) == ["start", "end"]


def test_baseline_also_rejects_a_gesture_too_small_for_this_users_range():
    # 0.62 clears the absolute 0.5, but is only ~31% of the way up this user's headroom.
    mild = [0.62] * 6
    assert _drive(GestureSwitch(), mild) == ["start"]
    assert _drive(GestureSwitch(baseline=0.45), mild) == []


def test_a_zero_baseline_is_exactly_the_absolute_switch():
    trace = [0.0, 0.3, 0.6, 0.9, 0.9, 0.9, 0.4, 0.2, 0.2, 0.9, 0.9, 0.9, 0.0, 0.0]
    assert _drive(GestureSwitch(baseline=0.0), trace) == _drive(GestureSwitch(), trace)


def test_no_baseline_leaves_scores_untouched():
    assert normalise(0.73, None) == 0.73


@pytest.mark.parametrize("level", [0.9, 0.76, 1.0, 1.5, -0.1, float("nan"), float("inf")])
def test_a_baseline_with_no_headroom_makes_the_switch_inert_not_wild(level):
    """Zero-denominator and near-zero-denominator cases are defined: no division, no event."""
    sw = GestureSwitch(baseline=level)
    assert sw.baseline_usable is False
    assert _drive(sw, [1.0] * 10) == []
    assert sw.last_frame == "unusable_baseline"
    assert normalise(1.0, level) is None


def test_normalise_maps_rest_to_zero_and_full_to_one_and_clamps():
    assert normalise(0.45, 0.45) == 0.0
    assert normalise(1.0, 0.45) == 1.0
    assert normalise(0.2, 0.45) == 0.0  # below the resting level is not a negative score
    assert normalise(0.725, 0.45) == pytest.approx(0.5)


@pytest.mark.parametrize("score", [None, float("nan"), float("inf"), "x"])
def test_normalise_gives_none_for_a_non_reading(score):
    assert normalise(score, 0.2) is None  # type: ignore[arg-type]
    assert normalise(score, None) is None  # type: ignore[arg-type]


def test_a_non_finite_score_is_a_release_candidate_not_a_frozen_hold():
    """NaN compares false against every threshold: it used to count toward neither side."""
    sw = GestureSwitch()
    _drive(sw, [0.9] * 3)
    assert sw.held is True
    assert _drive(sw, [float("nan")] * 2) == ["end"]
    assert _drive(GestureSwitch(), [float("nan")] * 10) == []


# -- jitter, missing readings, refractory -----------------------------------


def test_threshold_jitter_without_a_sustained_hold_emits_nothing():
    jitter = [0.52, 0.48, 0.53, 0.47, 0.51, 0.49, 0.52, 0.48, 0.52, 0.47]
    assert _drive(GestureSwitch(), jitter) == []


def test_a_missing_reading_never_starts_a_hold_and_breaks_the_run():
    assert _drive(GestureSwitch(), [None] * 10) == []
    assert _drive(GestureSwitch(), [0.9, 0.9, None, 0.9, 0.9, None]) == []


def test_talking_like_mouth_movement_with_short_syllables_does_not_fire():
    """A regression fixture, NOT a safety claim.

    Each syllable opens the jaw for two frames (about 130 ms at 15 fps), which is under
    ``min_hold_frames``. A speaker who holds a vowel open for three or more frames above the
    threshold WOULD fire this switch, which is why jaw-open stays experimental until
    false activations per hour are measured on real speech (spec-eye-face-switch).
    """
    syllable = [0.62, 0.66, 0.12, 0.09]
    assert _drive(GestureSwitch(), syllable * 8) == []


def test_an_ordinary_blink_does_not_fire_a_non_blink_gesture():
    blink = [0.0, 0.2, 0.9, 1.0, 0.8, 0.1, 0.0]
    frames = [
        FaceSignal(timestamp_s=i / 15, confidence=0.9,
                   blendshapes={"eyeBlinkLeft": b, "eyeBlinkRight": b, "jawOpen": 0.03})
        for i, b in enumerate(blink)
    ]
    for gesture in ("jaw_open", "brow_raise", "mouth_pucker", "smile"):
        sw = GestureSwitch(confidence_floor=0.5)
        reads = [gesture_reading(f, gesture) for f in frames]
        assert _drive_frames(sw, reads) == [], gesture


def test_refractory_stops_a_release_bounce_from_re_firing():
    bounce = [0.9] * 3 + [0.1] * 2 + [0.9] * 3
    assert _drive(GestureSwitch(refractory_frames=0), bounce) == ["start", "end", "start"]
    assert _drive(GestureSwitch(refractory_frames=4), bounce) == ["start", "end"]


def test_a_deliberate_gesture_after_the_refractory_window_fires_again():
    sw = GestureSwitch(refractory_frames=2)
    assert _drive(sw, [0.9] * 3 + [0.1] * 2 + [0.1] * 2 + [0.9] * 3) == ["start", "end", "start"]


def test_reset_clears_the_refractory_window():
    sw = GestureSwitch(refractory_frames=10)
    _drive(sw, [0.9] * 3 + [0.1] * 2)
    sw.reset()
    assert _drive(sw, [0.9] * 3) == ["start"]


# -- the shared-perception seam: a missing channel costs only this channel ----


def _face(ts, conf=0.9, **shapes):
    return FaceSignal(timestamp_s=ts, confidence=conf, blendshapes=shapes)


def test_a_missing_blendshape_channel_is_no_reading_for_the_switch():
    assert gesture_reading(None, "jaw_open") == Reading(None, None)


def test_a_signal_without_this_gestures_categories_is_no_reading_but_others_still_work():
    face = _face(1.0, browInnerUp=0.8)
    assert gesture_reading(face, "jaw_open") == Reading(None, None)
    assert gesture_reading(face, "brow_raise") == Reading(0.8, 0.9)


def test_an_unknown_gesture_is_no_reading():
    assert gesture_reading(_face(1.0, jawOpen=0.9), "wink") == Reading(None, None)


def test_a_reading_carries_the_signals_confidence_separately_from_the_score():
    assert gesture_reading(_face(1.0, conf=0.31, jawOpen=0.8), "jaw_open") == Reading(0.8, 0.31)


def test_a_stale_signal_is_no_reading_and_cannot_hold_a_gesture():
    face = _face(10.0, jawOpen=0.9)
    assert gesture_reading(face, "jaw_open", now_s=10.2, max_age_s=0.5) == Reading(0.9, 0.9)
    assert gesture_reading(face, "jaw_open", now_s=10.6, max_age_s=0.5) == Reading(None, None)
    # Future-stamped is a clock fault, not freshness.
    assert gesture_reading(face, "jaw_open", now_s=9.0, max_age_s=0.5) == Reading(None, None)

    sw = GestureSwitch()
    _drive_frames(sw, [(0.9, None)] * 3)
    assert sw.held is True
    stale = gesture_reading(face, "jaw_open", now_s=99.0, max_age_s=0.5)
    assert _drive_frames(sw, [stale, stale]) == ["end"]
