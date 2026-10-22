"""Head gestures from head pose: nod, shake, tilt (pure) -- EYE-GESTURE-001.

Every pose here is a number a test fabricated; there is no camera and no model. What is pinned:

* a deliberate nod or shake is recognised from a *window* of poses, once, and the same motion
  is never two tokens;
* the things that look like a nod and are not -- a glance (one down-and-back), a diagonal
  look-around, a small tremor, a slow drift -- produce nothing;
* **doubt is silence**: a missing, stale, low-confidence, non-finite or non-advancing sample
  yields no token, empties the window (so two halves of a nod are never stitched across a
  dropout) and releases a held tilt.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from yazses.gesture.headmotion import (
    HEAD_TOKENS,
    PRESS,
    PULSE,
    RELEASE,
    HeadGestureDetector,
    HeadMotionSettings,
    count_swings,
)
from yazses.perception.signals import HeadPoseSignal

FPS = 15.0
DT = 1.0 / FPS
AMP = math.radians(10.0)  # the default leg threshold


def pose(t, yaw=0.0, pitch=0.0, roll=0.0, conf=1.0):
    return HeadPoseSignal(t, yaw, pitch, roll, conf)


def run(det, samples, *, start=100.0):
    """Feed ``(yaw, pitch, roll)`` triples one frame apart; return every event emitted."""
    events = []
    t = start
    for yaw, pitch, roll in samples:
        t += DT
        events.extend(det.update(pose(t, yaw, pitch, roll), t))
    return events, t


def oscillate(axis, amplitude, cycles, *, seconds=None):
    """A sine on one axis starting at zero: ``cycles`` full cycles over ``seconds``."""
    seconds = seconds if seconds is not None else cycles * 0.5  # 2 Hz by default
    n = max(2, int(seconds * FPS))
    out = []
    for i in range(n + 1):
        value = amplitude * math.sin(2 * math.pi * cycles * i / n)
        out.append((value, 0.0, 0.0) if axis == "yaw" else (0.0, value, 0.0))
    return out


# --------------------------------------------------------------------------- #
# count_swings
# --------------------------------------------------------------------------- #
def test_swings_count_legs_not_samples():
    assert count_swings([0, 0.2, 0], 0.15) == 2          # out and back
    assert count_swings([0, 0.2, 0, 0.2], 0.15) == 3
    assert count_swings([0, 0.05, 0, 0.05, 0, 0.05], 0.15) == 0  # a tremor adds nothing


def test_swings_ignore_non_finite_values_and_a_useless_threshold():
    assert count_swings([0, float("nan"), 0.2, 0], 0.15) == 2
    assert count_swings([0, 0.2, 0], 0.0) == 0
    assert count_swings([0, 0.2, 0], float("nan")) == 0
    assert count_swings([0.1], 0.05) == 0
    assert count_swings([], 0.05) == 0


# --------------------------------------------------------------------------- #
# nod / shake
# --------------------------------------------------------------------------- #
def test_a_double_nod_is_one_nod_pulse():
    events, _ = run(HeadGestureDetector(), oscillate("pitch", 0.2, 2))
    assert events == [("nod", PULSE)]


def test_a_double_shake_is_one_shake_pulse():
    events, _ = run(HeadGestureDetector(), oscillate("yaw", 0.2, 2))
    assert events == [("shake", PULSE)]


def test_one_down_and_back_is_a_glance_not_a_nod_by_default():
    events, _ = run(HeadGestureDetector(), oscillate("pitch", 0.2, 1))
    assert events == []


def test_the_leg_count_is_configurable_so_a_single_nod_can_be_asked_for():
    det = HeadGestureDetector(HeadMotionSettings(swings=2))
    events, _ = run(det, oscillate("pitch", 0.2, 1))
    assert events == [("nod", PULSE)]


def test_a_diagonal_look_around_is_neither():
    samples = [(p, p, 0.0) for _, p, _ in oscillate("pitch", 0.2, 2)]
    events, _ = run(HeadGestureDetector(), samples)
    assert events == []


def test_a_motion_smaller_than_the_amplitude_is_nothing():
    events, _ = run(HeadGestureDetector(), oscillate("pitch", 0.05, 6))
    assert events == []


def test_a_slow_drift_inside_the_window_is_nothing():
    # 0.5 rad out and back over 20 s: far larger than the amplitude, far slower than a gesture.
    events, _ = run(HeadGestureDetector(), oscillate("pitch", 0.5, 2, seconds=40.0))
    assert events == []


def test_one_motion_is_one_pulse_and_the_refractory_holds_the_next_off():
    det = HeadGestureDetector(HeadMotionSettings(refractory_s=1.0))
    events, t = run(det, oscillate("pitch", 0.2, 6, seconds=3.0))
    # three seconds of continuous nodding: pulses are at least a refractory apart
    assert events and all(e == ("nod", PULSE) for e in events)
    assert len(events) <= 3


def test_after_a_pulse_the_same_samples_cannot_fire_it_again():
    det = HeadGestureDetector()
    first, t = run(det, oscillate("pitch", 0.2, 2))
    again = det.update(pose(t), t)  # the same timestamp, polled again
    assert first == [("nod", PULSE)] and again == []


@pytest.mark.parametrize("axis,token", [("pitch", "nod"), ("yaw", "shake")])
def test_a_dropout_in_the_middle_does_not_stitch_two_halves_together(axis, token):
    det = HeadGestureDetector()
    wave = oscillate(axis, 0.2, 2)
    half = len(wave) // 2
    first, t = run(det, wave[:half])
    assert det.update(None, t + DT) == []              # the camera lost the face
    second, _ = run(det, wave[half:], start=t + DT)
    assert first == [] and second == []                # neither half is a gesture alone


def test_the_window_is_emptied_by_a_stale_sample_too():
    det = HeadGestureDetector(HeadMotionSettings(freshness_s=0.5))
    wave = oscillate("pitch", 0.2, 2)
    run(det, wave[: len(wave) // 2])
    stale = pose(50.0)
    assert det.update(stale, 99.0) == []               # 49 s old: no signal
    events, _ = run(det, wave[len(wave) // 2:], start=150.0)
    assert events == []


def test_a_low_confidence_sample_is_no_signal():
    det = HeadGestureDetector(HeadMotionSettings(min_confidence=0.5))
    t = 100.0
    events = []
    for _, pitch, _ in oscillate("pitch", 0.2, 2):
        t += DT
        events.extend(det.update(pose(t, pitch=pitch, conf=0.2), t))
    assert events == []


def test_a_future_timestamp_is_a_clock_fault_not_a_pose():
    det = HeadGestureDetector()
    assert det.update(pose(200.0), 100.0) == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_a_non_finite_angle_is_no_token_and_no_crash(bad):
    # HeadPoseSignal refuses these at construction; a duck-typed sample must be refused here.
    det = HeadGestureDetector()
    sample = SimpleNamespace(timestamp_s=100.0, yaw=bad, pitch=0.0, roll=0.0, confidence=1.0)
    assert det.update(sample, 100.0) == []  # type: ignore[arg-type]
    other = SimpleNamespace(timestamp_s=100.0, yaw=0.0, pitch=0.0, roll=bad, confidence=1.0)
    assert det.update(other, 100.0) == []  # type: ignore[arg-type]


def test_a_non_finite_clock_is_no_token():
    det = HeadGestureDetector()
    assert det.update(pose(100.0), float("nan")) == []


def test_a_nan_in_the_middle_of_a_nod_breaks_it():
    det = HeadGestureDetector()
    wave = oscillate("pitch", 0.2, 2)
    _, t = run(det, wave[: len(wave) // 2])
    t += DT                                   # the very next frame is garbage
    broken = SimpleNamespace(timestamp_s=t, yaw=0.0, pitch=float("nan"), roll=0.0, confidence=1.0)
    assert det.update(broken, t) == []  # type: ignore[arg-type]
    events, _ = run(det, wave[len(wave) // 2:], start=t)
    assert events == []                       # the two halves were not stitched across the NaN


def test_the_same_nod_without_the_nan_does_complete():
    """The control for the test above: it is the NaN, not the split, that stops the nod."""
    det = HeadGestureDetector()
    wave = oscillate("pitch", 0.2, 2)
    _, t = run(det, wave[: len(wave) // 2])
    events, _ = run(det, wave[len(wave) // 2:], start=t)
    assert events == [("nod", PULSE)]


# --------------------------------------------------------------------------- #
# tilt (held)
# --------------------------------------------------------------------------- #
def tilt_run(det, roll, seconds, *, start=100.0):
    events = []
    t = start
    for _ in range(int(seconds * FPS)):
        t += DT
        events.extend(det.update(pose(t, roll=roll), t))
    return events, t


@pytest.mark.parametrize("roll", [0.5, -0.5])
def test_a_held_tilt_presses_once_either_way_and_releases_when_the_head_is_back(roll):
    det = HeadGestureDetector()
    pressed, t = tilt_run(det, roll, 1.0)
    assert pressed == [("tilt", PRESS)] and det.tilt_held
    released, _ = tilt_run(det, 0.0, 0.5, start=t)
    assert released == [("tilt", RELEASE)] and not det.tilt_held


def test_a_brief_tilt_is_not_a_press():
    det = HeadGestureDetector(HeadMotionSettings(tilt_hold_s=0.4))
    events, _ = tilt_run(det, 0.5, 0.2)
    assert events == []


def test_a_tilt_between_press_and_release_thresholds_stays_held():
    det = HeadGestureDetector()
    pressed, t = tilt_run(det, 0.5, 1.0)
    inside = det._tilt * 0.85  # noqa: SLF001 - below the press threshold, above the release one
    events, _ = tilt_run(det, inside, 0.5, start=t)
    assert pressed == [("tilt", PRESS)] and events == []


def test_losing_the_signal_releases_a_held_tilt_at_once():
    det = HeadGestureDetector()
    _, t = tilt_run(det, 0.5, 1.0)
    assert det.update(None, t + DT) == [("tilt", RELEASE)]
    assert det.update(None, t + 2 * DT) == []         # and only once


def test_reset_releases_a_held_tilt_and_is_idempotent():
    det = HeadGestureDetector()
    tilt_run(det, 0.5, 1.0)
    assert det.reset() == [("tilt", RELEASE)]
    assert det.reset() == []


def test_the_token_vocabulary_is_exactly_what_the_detector_can_emit():
    assert set(HEAD_TOKENS) == {"nod", "shake", "tilt"}


# --------------------------------------------------------------------------- #
# discard_pending: the head side of #417 (a stop or a re-arm cuts a half-made gesture)
# --------------------------------------------------------------------------- #
def test_discard_pending_forgets_half_a_nod():
    det = HeadGestureDetector()
    nod = oscillate("pitch", 0.2, 2)
    half = len(nod) // 2
    first, t = run(det, nod[:half])
    det.discard_pending()
    second, _ = run(det, nod[half:], start=t)
    assert first == [] and second == []   # neither half is a nod on its own


def test_without_discard_pending_the_same_two_halves_are_one_nod():
    det = HeadGestureDetector()
    nod = oscillate("pitch", 0.2, 2)
    half = len(nod) // 2
    _, t = run(det, nod[:half])
    second, _ = run(det, nod[half:], start=t)
    assert second == [("nod", PULSE)]     # the control: the fixture *is* a nod


def test_discard_pending_restarts_a_tilt_that_was_still_building():
    det = HeadGestureDetector(HeadMotionSettings(tilt_hold_s=0.4))
    before, t = tilt_run(det, 0.5, 0.3)   # under tilt_hold_s
    det.discard_pending()
    after, t = tilt_run(det, 0.5, 0.3, start=t)
    assert before == [] and after == []   # 0.6 s tilted in all, but never 0.4 s since the cut
    rest, _ = tilt_run(det, 0.5, 0.3, start=t)
    assert rest == [("tilt", PRESS)]


def test_discard_pending_leaves_a_held_tilt_held_and_emits_nothing():
    det = HeadGestureDetector()
    pressed, t = tilt_run(det, 0.5, 1.0)
    assert pressed == [("tilt", PRESS)]
    det.discard_pending()
    assert det.tilt_held
    still, t = tilt_run(det, 0.5, 1.0, start=t)
    assert still == []                    # no second press for the same tilt
    back, _ = tilt_run(det, 0.0, 0.5, start=t)
    assert back == [("tilt", RELEASE)]    # and its release still arrives
