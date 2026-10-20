"""Timed minimum hold and refractory for the face-switch detector (EYE-FACE-001, #406).

``min_hold_frames`` and ``refractory_frames`` count samples, so their *duration* is whatever the
camera makes it: the eyes-closed floor the hands-free panel writes (12 frames, "0.8 s at
15 fps") is 0.4 s on a shared camera running at 30 fps -- inside a long blink. ``min_hold_s`` and
``refractory_s`` state the same rules in seconds of sample time, on top of the frame rules.

Every trace here is SYNTHETIC and built deterministically from (duration, score) segments at a
stated sample rate. They are regression fixtures for the state machine at several frame rates,
not evidence for any threshold or duration: the numbers are chosen to make each case
unambiguous, and nothing here may be read as a recommended default
(``design/eye-control/ROADMAP.md`` P5.4; spec-eye-face-switch, "Measurement").
"""
from __future__ import annotations

import math
import random

import pytest

from yazses.facegesture.detector import (
    DEFAULT_MAX_SAMPLE_GAP_S,
    GestureSwitch,
    gesture_reading,
)
from yazses.perception.signals import FaceSignal

RATES = (15, 30, 60)


def _trace(segments, fps, *, t0=0.0, confidence=1.0):
    """``[(duration_s, score), ...]`` sampled at ``fps`` as ``(t, score, confidence)`` triples.

    Sample ``i`` sits at ``t0 + i / fps`` (an index, not an accumulated sum, so no drift), and a
    segment owns the samples whose time falls inside it.
    """
    out = []
    total = sum(d for d, _ in segments)
    n = int(round(total * fps))
    bounds, acc = [], 0.0
    for duration, score in segments:
        acc += duration
        bounds.append((acc, score))
    for i in range(n):
        rel = i / fps
        score = next(s for end, s in bounds if rel < end - 1e-12)
        out.append((t0 + rel, score, confidence))
    return out


def _run(switch, samples):
    """Feed ``(t, score, confidence)`` samples; return ``[(event, t), ...]``."""
    events = []
    for t, score, conf in samples:
        event = switch.update(score, conf, now_s=t)
        if event is not None:
            events.append((event, t))
    return events


def _kinds(events):
    return [e for e, _ in events]


# --------------------------------------------------------------- the problem the timed rule solves


def test_a_frame_count_lasts_whatever_the_camera_makes_it():
    # Characterisation, on purpose: three frames is a different *duration* at each rate, so a
    # 0.12 s burst passes a three-frame debounce at 30 and 60 fps but not at 15.
    burst = [(0.5, 0.0), (0.12, 0.9), (0.5, 0.0)]
    fired = {fps: _kinds(_run(GestureSwitch(min_hold_frames=3), _trace(burst, fps))) for fps in RATES}
    assert fired == {15: [], 30: ["start", "end"], 60: ["start", "end"]}


def test_a_timed_hold_rejects_the_same_burst_at_every_frame_rate():
    burst = [(0.5, 0.0), (0.12, 0.9), (0.5, 0.0)]
    for fps in RATES:
        sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.3)
        assert _run(sw, _trace(burst, fps)) == [], fps


# ------------------------------------------------------------------- deliberate action, any rate


@pytest.mark.parametrize("fps", RATES)
def test_a_deliberate_hold_fires_exactly_once_after_the_same_wait_at_any_rate(fps):
    onset = 1.0
    trace = _trace([(onset, 0.05), (1.5, 0.9), (1.0, 0.05)], fps)
    events = _run(GestureSwitch(min_hold_frames=1, min_hold_s=0.4), trace)
    assert _kinds(events) == ["start", "end"]
    latency = events[0][1] - onset
    # The press lands on the first sample at least 0.4 s after the run began: never earlier,
    # and never more than one sample period later.
    assert 0.4 - 1e-9 <= latency < 0.4 + 1.0 / fps + 1e-9


def test_the_timed_hold_adds_to_the_frame_count_and_never_replaces_it():
    # 0.1 s is under one frame period at 15 fps; five frames still have to be seen.
    trace = _trace([(0.2, 0.0), (1.0, 0.9)], 15)
    events = _run(GestureSwitch(min_hold_frames=5, min_hold_s=0.1), trace)
    assert _kinds(events) == ["start"]
    first_high = next(t for t, s, _ in trace if s == 0.9)
    assert math.isclose(events[0][1] - first_high, 4 / 15)


# --------------------------------------------------------------------------- ordinary blink


def _blink_frames(fps, closure_s, *, every_s, total_s, t0=0.0):
    """FaceSignals for a face that blinks for ``closure_s`` every ``every_s`` (synthetic)."""
    frames = []
    for i in range(int(round(total_s * fps))):
        t = i / fps
        closed = (t % every_s) < closure_s
        b = 0.95 if closed else 0.04
        frames.append(FaceSignal(
            timestamp_s=t0 + t, confidence=0.9,
            blendshapes={"eyeBlinkLeft": b, "eyeBlinkRight": b, "jawOpen": 0.03},
        ))
    return frames


def _drive_gesture(switch, frames, gesture):
    events = []
    for f in frames:
        r = gesture_reading(f, gesture, now_s=f.timestamp_s, max_age_s=0.5)
        e = switch.update(r.score, r.confidence, now_s=f.timestamp_s)
        if e is not None:
            events.append(e)
    return events


def test_the_panels_frame_floor_for_eyes_closed_fires_on_a_long_blink_at_30_fps():
    # The hazard, characterised: 12 frames (the 0.8 s floor computed for 15 fps) on a 30 fps
    # source is 0.4 s, and a 0.4 s closure every 4 s fires the opt-in blink switch.
    frames = _blink_frames(30, 0.4, every_s=4.0, total_s=60.0)
    assert _drive_gesture(GestureSwitch(min_hold_frames=12), frames, "eyes_closed") != []


@pytest.mark.parametrize("fps", RATES)
def test_ordinary_blinking_never_fires_a_timed_eyes_closed_switch(fps):
    # A minute of blinking every 4 s with closures up to 0.4 s, at each rate.
    for closure in (0.1, 0.25, 0.4):
        frames = _blink_frames(fps, closure, every_s=4.0, total_s=60.0)
        sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.8)
        assert _drive_gesture(sw, frames, "eyes_closed") == [], (fps, closure)


@pytest.mark.parametrize("fps", RATES)
def test_a_deliberate_eyes_closed_squeeze_fires_exactly_once(fps):
    frames = _blink_frames(fps, 1.5, every_s=10.0, total_s=10.0)
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.8)
    assert _drive_gesture(sw, frames, "eyes_closed") == ["start", "end"]


@pytest.mark.parametrize("fps", RATES)
def test_ordinary_blinking_never_fires_a_non_blink_gesture_with_a_timed_hold(fps):
    frames = _blink_frames(fps, 0.4, every_s=2.0, total_s=30.0)
    for gesture in ("jaw_open", "brow_raise", "mouth_pucker", "smile"):
        sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.3)
        assert _drive_gesture(sw, frames, gesture) == [], (fps, gesture)


# --------------------------------------------------------------- talking-like mouth movement


def _speech(fps, seed, *, seconds=60.0):
    """Syllables 0.08-0.2 s long with the jaw ABOVE the hold threshold, ~4 per second.

    SYNTHETIC and deliberately harsher than real speech scores (the one-person webcam summary
    peaked well below 0.5): every syllable crosses the threshold, so only the hold duration
    separates them from a deliberate gesture. A regression fixture, not a safety claim.
    """
    rng = random.Random(seed)
    segments, total = [], 0.0
    while total < seconds:
        gap, syl = rng.uniform(0.08, 0.2), rng.uniform(0.08, 0.2)
        segments += [(gap, 0.05), (syl, rng.uniform(0.55, 0.8))]
        total += gap + syl
    return _trace(segments, fps)


@pytest.mark.parametrize("seed", range(3))
def test_threshold_crossing_syllables_pass_the_default_frame_debounce_at_30_fps(seed):
    # Characterisation: the shipped three-frame debounce is 0.1 s at 30 fps, under a syllable.
    assert _run(GestureSwitch(), _speech(30, seed)) != []


@pytest.mark.parametrize("fps", RATES)
@pytest.mark.parametrize("seed", range(3))
def test_threshold_crossing_syllables_never_fire_a_timed_hold(fps, seed):
    assert _run(GestureSwitch(min_hold_s=0.3), _speech(fps, seed)) == []


@pytest.mark.parametrize("fps", RATES)
def test_a_deliberate_mouth_open_after_speech_still_fires_once(fps):
    speech = _speech(fps, 0, seconds=10.0)
    tail_t0 = speech[-1][0] + 1.0 / fps
    hold = _trace([(0.3, 0.05), (1.0, 0.85), (0.5, 0.05)], fps, t0=tail_t0)
    assert _kinds(_run(GestureSwitch(min_hold_s=0.3), speech + hold)) == ["start", "end"]


# ------------------------------------------------------------------------------- low confidence


@pytest.mark.parametrize("fps", RATES)
def test_a_held_gesture_at_low_confidence_emits_nothing_however_long_it_lasts(fps):
    trace = _trace([(0.5, 0.05), (3.0, 0.9), (0.5, 0.05)], fps, confidence=0.2)
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.4, confidence_floor=0.6)
    assert _run(sw, trace) == []
    assert sw.last_frame == "low_confidence"


def test_one_low_confidence_sample_restarts_the_timed_run():
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.4, confidence_floor=0.6)
    t = [i / 30 for i in range(40)]
    samples = [(ti, 0.9, 0.9) for ti in t]
    samples[9] = (t[9], 0.9, 0.1)  # one unsure frame 0.3 s into the hold
    events = _run(sw, samples)
    assert _kinds(events) == ["start"]
    # The run restarted at sample 10, so the press is 0.4 s after t[10], not after t[0].
    assert math.isclose(events[0][1], t[10] + 0.4, abs_tol=1e-9)


# ---------------------------------------------------------------------- what the clock may do


def test_the_same_observation_fed_twice_adds_no_time():
    # The frame-count contract lets a repeated sample count again; a timed hold cannot.
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.2)
    assert [sw.update(0.9, 1.0, now_s=7.0) for _ in range(50)] == [None] * 50
    assert sw.update(0.9, 1.0, now_s=7.2) == "start"


def test_untimed_samples_can_never_press_a_timed_switch():
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.2)
    assert sw.needs_clock is True
    assert [sw.update(0.9, 1.0) for _ in range(100)] == [None] * 100
    assert sw.held is False


def test_an_untimed_sample_breaks_a_timed_run():
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.3)
    assert sw.update(0.9, 1.0, now_s=0.0) is None
    assert sw.update(0.9, 1.0, now_s=0.2) is None
    assert sw.update(0.9, 1.0, now_s=None) is None
    assert sw.update(0.9, 1.0, now_s=0.35) is None   # would have fired without the break
    assert sw.update(0.9, 1.0, now_s=0.5) is None
    assert sw.update(0.9, 1.0, now_s=0.65) == "start"  # 0.3 s since the restart at 0.35


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_time_is_an_untimed_sample(bad):
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.1)
    assert sw.update(0.9, 1.0, now_s=0.0) is None
    assert sw.update(0.9, 1.0, now_s=bad) is None
    assert sw.update(0.9, 1.0, now_s=0.15) is None   # restarted at 0.15
    assert sw.update(0.9, 1.0, now_s=0.25) == "start"


def test_a_gap_longer_than_max_gap_restarts_the_run_and_a_shorter_one_is_credited():
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.5, max_gap_s=0.25)
    assert sw.update(0.9, 1.0, now_s=0.0) is None
    assert sw.update(0.9, 1.0, now_s=0.6) is None     # 0.6 s unseen: not held time
    assert sw.update(0.9, 1.0, now_s=0.85) is None    # 0.25 s gap: credited, 0.25 held
    assert sw.update(0.9, 1.0, now_s=1.1) == "start"  # 0.5 s since the restart


def test_a_clock_stepping_backwards_restarts_the_run():
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.3)
    assert sw.update(0.9, 1.0, now_s=100.0) is None
    assert sw.update(0.9, 1.0, now_s=100.2) is None
    assert sw.update(0.9, 1.0, now_s=5.0) is None     # an hour back: from here, not credited
    assert sw.update(0.9, 1.0, now_s=5.2) is None
    assert sw.update(0.9, 1.0, now_s=5.3) == "start"


def test_discard_pending_restarts_a_timed_run():
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.3)
    for t in (0.0, 0.1, 0.2):
        assert sw.update(0.9, 1.0, now_s=t) is None
    sw.discard_pending()
    assert sw.update(0.9, 1.0, now_s=0.3) is None
    assert sw.update(0.9, 1.0, now_s=0.5) is None
    assert sw.update(0.9, 1.0, now_s=0.6) == "start"


# ------------------------------------------------------------------------------- refractory_s


@pytest.mark.parametrize("fps", RATES)
def test_a_timed_refractory_swallows_a_bounce_the_same_way_at_every_rate(fps):
    # Hold, release, then the face springs back within 0.3 s: a bounce, not a new gesture.
    bounce = [(0.3, 0.9), (0.1, 0.05), (0.4, 0.9), (0.5, 0.05)]
    sw = GestureSwitch(min_hold_frames=1, min_release_frames=1, refractory_s=0.6)
    assert _kinds(_run(sw, _trace(bounce, fps))) == ["start", "end"]


@pytest.mark.parametrize("fps", RATES)
def test_a_gesture_after_the_timed_refractory_fires_again(fps):
    trace = [(0.3, 0.9), (0.8, 0.05), (0.3, 0.9), (0.3, 0.05)]
    sw = GestureSwitch(min_hold_frames=1, min_release_frames=1, refractory_s=0.6)
    assert _kinds(_run(sw, _trace(trace, fps))) == ["start", "end", "start", "end"]


def test_an_untimed_end_starts_the_refractory_at_the_next_timed_sample():
    sw = GestureSwitch(min_hold_frames=1, min_release_frames=1, refractory_s=0.5)
    assert sw.update(0.9, 1.0) == "start"
    assert sw.update(0.0, 1.0) == "end"               # no time: the window cannot be dated
    assert sw.update(0.9, 1.0) is None                # untimed: still refractory
    assert sw.update(0.9, 1.0, now_s=10.0) is None    # the window starts here
    assert sw.update(0.9, 1.0, now_s=10.4) is None
    assert sw.update(0.9, 1.0, now_s=10.5) == "start"


def test_a_clock_stepping_backwards_restarts_the_refractory_window():
    sw = GestureSwitch(min_hold_frames=1, min_release_frames=1, refractory_s=0.5)
    assert sw.update(0.9, 1.0, now_s=50.0) == "start"
    assert sw.update(0.0, 1.0, now_s=50.1) == "end"
    assert sw.update(0.9, 1.0, now_s=1.0) is None     # back in time: still refractory
    assert sw.update(0.9, 1.0, now_s=1.4) is None
    assert sw.update(0.9, 1.0, now_s=1.5) == "start"


def test_frame_and_timed_refractory_both_have_to_elapse():
    sw = GestureSwitch(min_hold_frames=1, min_release_frames=1, refractory_frames=5,
                       refractory_s=0.1)
    assert sw.update(0.9, 1.0, now_s=0.0) == "start"
    assert sw.update(0.0, 1.0, now_s=0.01) == "end"
    # 0.1 s passes within two samples, but five frames must still be swallowed.
    assert [sw.update(0.9, 1.0, now_s=0.2 + i * 0.1) for i in range(5)] == [None] * 5
    assert sw.update(0.9, 1.0, now_s=0.8) == "start"


def test_reset_clears_a_timed_refractory_window():
    sw = GestureSwitch(min_hold_frames=1, min_release_frames=1, refractory_s=10.0)
    assert sw.update(0.9, 1.0, now_s=0.0) == "start"
    assert sw.update(0.0, 1.0, now_s=0.1) == "end"
    sw.reset()
    assert sw.update(0.9, 1.0, now_s=0.2) == "start"


def test_a_max_hold_release_opens_the_timed_refractory_too():
    sw = GestureSwitch(min_hold_frames=1, min_release_frames=1, max_hold_s=1.0,
                       refractory_s=0.5)
    assert sw.update(0.9, 1.0, now_s=0.0) == "start"
    assert sw.update(0.9, 1.0, now_s=1.0) == "end"
    assert sw.last_end_reason == "max_hold"
    assert sw.update(0.1, 1.0, now_s=1.1) is None     # clears the latch, inside the window
    assert sw.update(0.9, 1.0, now_s=1.2) is None
    assert sw.update(0.9, 1.0, now_s=1.5) == "start"


# ------------------------------------------------------------------- off by default, unchanged


def test_the_timed_rules_are_off_by_default_and_need_no_clock():
    sw = GestureSwitch()
    assert (sw.min_hold_s, sw.refractory_s, sw.needs_clock) == (0.0, 0.0, False)
    assert [sw.update(0.9, 1.0) for _ in range(3)] == [None, None, "start"]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1.0, "x", None, True])
def test_an_unreadable_duration_turns_the_timed_rule_off(bad):
    # +inf included: "never press" is not a duration anyone can mean, and a typo must not
    # silently cost someone their only input method.
    sw = GestureSwitch(min_hold_s=bad, refractory_s=bad)  # type: ignore[arg-type]
    assert (sw.min_hold_s, sw.refractory_s, sw.needs_clock) == (0.0, 0.0, False)


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, "x"])
def test_an_unreadable_max_gap_falls_back_to_the_default(bad):
    sw = GestureSwitch(min_hold_frames=1, min_hold_s=0.3, max_gap_s=bad)  # type: ignore[arg-type]
    assert sw.update(0.9, 1.0, now_s=0.0) is None
    assert sw.update(0.9, 1.0, now_s=DEFAULT_MAX_SAMPLE_GAP_S) is None   # credited
    assert sw.update(0.9, 1.0, now_s=0.3) == "start"


@pytest.mark.parametrize("fps", RATES)
@pytest.mark.parametrize("seed", range(4))
def test_on_a_steady_cadence_a_timed_hold_equal_to_the_frame_span_changes_nothing(fps, seed):
    # Three frames span two sample periods; at a steady rate the timed rule is then the frame
    # rule restated, so on any trace the two switches must agree event for event.
    rng = random.Random(seed)
    trace = [(i / fps, rng.choice([0.0, 0.2, 0.4, 0.6, 0.9]), 1.0) for i in range(fps * 30)]
    frames = _run(GestureSwitch(min_hold_frames=3), trace)
    timed = _run(GestureSwitch(min_hold_frames=3, min_hold_s=2 / fps), trace)
    assert timed == frames
    assert frames  # the trace really exercised the switch
