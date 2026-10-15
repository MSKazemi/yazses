"""The face-switch detector at its edges (EYE-FACE-001) -- the orderings a clean trace never has.

``test_facegesture_switch.py`` drives the happy paths. These are the cases a fake hides:
a score sitting *exactly* on a threshold, a reading that goes missing or non-finite in the
middle of a hold, a face that leaves and comes back, a debounce longer than the gesture, a clock
that runs backwards, and the claim in the module docstring that the detector is *pure*.

Every trace here is synthetic. They are regression tools for the state machine, not evidence
for any threshold (``design/eye-control/ROADMAP.md`` P5.4): nothing below tunes a default.
"""
from __future__ import annotations

import json
import math
import random
import subprocess
import sys

import pytest

from yazses.facegesture.calibration import Reading, calibrate
from yazses.facegesture.detector import GestureSwitch


def _events(switch: GestureSwitch, scores, *, t0: float = 0.0, dt: float = 0.1) -> list[str]:
    """Feed ``scores`` one frame each (with a monotone clock) and return the events, in order."""
    out: list[str] = []
    for i, score in enumerate(scores):
        event = switch.update(score, 1.0, now_s=t0 + i * dt)
        if event is not None:
            out.append(event)
    return out


# --------------------------------------------------------------------------- exact thresholds


def test_a_score_exactly_on_the_hold_threshold_counts_as_above_it():
    assert _events(GestureSwitch(0.5, 0.35, min_hold_frames=3), [0.5] * 3) == ["start"]


def test_a_score_one_ulp_below_the_hold_threshold_never_fires_however_long_it_lasts():
    just_below = math.nextafter(0.5, 0.0)
    assert just_below < 0.5
    assert _events(GestureSwitch(0.5, 0.35, min_hold_frames=3), [just_below] * 5000) == []


def test_a_score_sitting_exactly_on_the_release_threshold_holds_forever_without_chattering():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=1, min_release_frames=1)
    assert _events(sw, [0.9]) == ["start"]
    # `release` means strictly below: exactly on it is not a release, and not a second start.
    assert _events(sw, [0.35] * 5000, t0=1.0) == []
    assert sw.held


def test_one_ulp_below_the_release_threshold_releases_exactly_once():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=1, min_release_frames=2)
    _events(sw, [0.9])
    below = math.nextafter(0.35, 0.0)
    assert _events(sw, [below] * 50, t0=1.0) == ["end"]
    assert not sw.held


def test_a_score_dithering_between_the_thresholds_is_one_hold_not_many():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=1, min_release_frames=1)
    trace = [0.9] + [0.36, 0.49, 0.36, 0.499, 0.351] * 400 + [0.1]
    assert _events(sw, trace) == ["start", "end"]


# --------------------------------------------------------------- a reading goes bad mid-hold


_BAD = [
    pytest.param(float("nan"), id="nan"),
    pytest.param(float("inf"), id="inf"),
    pytest.param(float("-inf"), id="neg-inf"),
    pytest.param(None, id="none"),
    pytest.param("not-a-number", id="text"),
]


@pytest.mark.parametrize("bad", _BAD)
def test_a_hold_never_stays_latched_on_missing_data(bad):
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=2, min_release_frames=2)
    assert _events(sw, [0.9, 0.9]) == ["start"]
    # NaN used to compare false on both sides and freeze the hold (an open microphone).
    assert _events(sw, [bad] * 50, t0=1.0) == ["end"]
    assert not sw.held
    assert sw.last_frame == "no_reading"
    assert sw.last_end_reason == "release"


@pytest.mark.parametrize("bad", _BAD)
def test_the_same_holds_with_a_baseline_in_force(bad):
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=2, min_release_frames=2, baseline=0.1)
    assert _events(sw, [0.95, 0.95]) == ["start"]
    assert _events(sw, [bad] * 50, t0=1.0) == ["end"]


@pytest.mark.parametrize("bad", _BAD)
def test_bad_readings_never_start_a_hold_even_after_a_good_run_of_frames(bad):
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=3)
    assert _events(sw, [0.9, 0.9, bad, 0.9, 0.9, bad, 0.9]) == []  # the bad frame resets the run


@pytest.mark.parametrize(
    "confidence",
    [pytest.param(None, id="none"), pytest.param(float("nan"), id="nan"), pytest.param(float("inf"), id="inf")],
)
def test_an_unreadable_confidence_mid_hold_releases_when_a_floor_is_set(confidence):
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=2, min_release_frames=2, confidence_floor=0.5)
    assert [sw.update(0.9, 0.9, now_s=0.0), sw.update(0.9, 0.9, now_s=0.1)] == [None, "start"]
    events = [sw.update(0.9, confidence, now_s=0.2 + i * 0.1) for i in range(20)]
    assert [e for e in events if e] == ["end"]


# ----------------------------------------------------------------- the face leaves and comes back


def test_a_face_lost_mid_hold_releases_and_a_returning_gesture_is_a_new_deliberate_one():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=3, min_release_frames=2)
    trace = [0.9] * 5 + [None] * 5 + [0.9] * 5
    assert _events(sw, trace) == ["start", "end", "start"]
    assert sw.held
    assert _events(sw, [0.0, 0.0], t0=5.0) == ["end"]


def test_a_dropout_shorter_than_the_release_debounce_does_not_split_the_hold():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=3, min_release_frames=3)
    assert _events(sw, [0.9] * 4 + [None, None] + [0.9] * 4 + [0.0] * 3) == ["start", "end"]


def test_a_face_that_never_returns_cannot_hold_the_switch_forever():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=1, min_release_frames=2)
    assert _events(sw, [0.9] + [None] * 100_000) == ["start", "end"]


# --------------------------------------------------------------- the debounce is longer than the gesture


def test_a_debounce_longer_than_the_gesture_emits_nothing_and_exactly_the_debounce_emits_one():
    assert _events(GestureSwitch(0.5, 0.35, min_hold_frames=10), [0.9] * 9 + [0.0] * 5) == []
    assert _events(GestureSwitch(0.5, 0.35, min_hold_frames=10), [0.9] * 10) == ["start"]


def test_the_refractory_window_swallows_a_gesture_that_begins_inside_it_and_only_that():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=2, min_release_frames=1, refractory_frames=6)
    #          start     end       inside the window (6 frames) -> ignored      after it
    trace = [0.9, 0.9, 0.0, 0.9, 0.9, 0.9, 0.9, 0.9, 0.0, 0.0, 0.9, 0.9]
    assert _events(sw, trace) == ["start", "end", "start"]


# ------------------------------------------------------------- timestamps: repeated, and backwards


def test_the_detector_counts_frames_so_the_caller_must_not_feed_one_observation_twice():
    # Documented contract, not a defect: this class reads no clock and keeps no timestamp
    # ledger. The backend counts each observation once (see test_facegesture_shared_camera:
    # test_one_observation_polled_many_times_counts_as_one_frame). If this ever changes, that
    # test is the one to keep.
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=3)
    assert [sw.update(0.9, 1.0, now_s=7.0) for _ in range(3)] == [None, None, "start"]


def test_a_clock_that_jumps_backwards_during_a_stuck_hold_still_ends_it():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=1, max_hold_s=2.0)
    assert sw.update(0.9, 1.0, now_s=1000.0) == "start"
    assert sw.update(0.9, 1.0, now_s=1000.5) is None
    # The clock steps back an hour. Before this was handled, elapsed time went negative and the
    # limit stayed disarmed until the clock caught up -- an hour of open microphone.
    events = [sw.update(0.9, 1.0, now_s=100.0 + i * 0.5) for i in range(10)]
    assert [e for e in events if e] == ["end"]
    assert sw.last_end_reason == "max_hold"
    assert sw.latched


def test_a_clock_that_keeps_stepping_backwards_never_trips_a_healthy_short_hold():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=1, max_hold_s=2.0)
    assert sw.update(0.9, 1.0, now_s=50.0) == "start"
    for t in (40.0, 30.0, 20.0, 10.0):  # each step back restarts the count
        assert sw.update(0.9, 1.0, now_s=t) is None
    assert sw.held


# ------------------------------------------------------------------ calibration from too little


@pytest.mark.parametrize("count", [0, 1, 14])
def test_a_baseline_from_too_few_samples_is_refused_not_guessed(count):
    result = calibrate("jaw_open", [Reading(0.05, 0.9)] * count)
    assert result.baseline is None and result.reason == "too_few_samples"


def test_a_baseline_from_enough_samples_survives_a_blink_outlier_in_the_capture():
    readings = [Reading(0.05, 0.9)] * 20 + [Reading(0.95, 0.9)]
    result = calibrate("jaw_open", readings)
    assert result.baseline is not None and result.baseline.level == pytest.approx(0.05)


def test_a_saved_baseline_does_not_follow_a_face_that_has_drifted_it_normalises_and_says_nothing():
    # Characterisation, reported rather than fixed: a baseline is a stored number. A face that
    # now rests above the release level fires, and can only be ended by the opt-in max_hold_s
    # guard (see test_facegesture_stuck_open) or by `doctor` noticing the saved level.
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=3, baseline=0.0)
    assert _events(sw, [0.45] * 1000) == []          # drifted to 0.45 is still below hold: quiet
    assert _events(sw, [0.5] * 1000, t0=200.0) == ["start"]  # and at 0.5 it is held for good
    assert sw.held


# --------------------------------------------------- ordinary speech: how often does each guard fire


def _speech_like(seed: int, frames: int) -> list[float]:
    """A jaw-score trace shaped like talking: syllable bursts ~4/s at 15 fps over a low floor.

    SYNTHETIC. The envelope (floor near 0.02, bursts clipped at 0.26) mirrors the one-person
    measurement quoted in the task; it is a fixture for the regression below, not data.
    """
    rng = random.Random(seed)
    out: list[float] = []
    while len(out) < frames:
        out += [min(0.26, abs(rng.gauss(0.02, 0.01)))] * rng.randint(1, 3)  # between syllables
        peak = min(0.26, rng.lognormvariate(-2.6, 0.5))
        out += [peak * 0.5, peak, peak * 0.6]  # one syllable, 3 frames
    return out[:frames]


@pytest.mark.parametrize("seed", [pytest.param(s, id=f"seed-{s}") for s in range(5)])
def test_synthetic_ordinary_speech_fires_no_guard_at_the_shipped_defaults(seed):
    trace = _speech_like(seed, frames=15 * 60 * 10)  # ten minutes at 15 fps
    assert max(trace) <= 0.26
    sw = GestureSwitch()  # the shipped defaults: 0.5 / 0.35, 3 frames
    assert _events(sw, trace, dt=1 / 15) == []
    assert sw.last_frame == "reading"


def test_the_frame_debounce_is_what_separates_a_loud_syllable_from_a_deliberate_hold():
    # Even a speech burst that DOES cross the hold threshold is rejected by the debounce alone
    # when it is short; a burst held as long as the debounce is, by definition, a hold.
    # Characterisation of the mechanism on synthetic input; it says nothing about real mouths.
    loud_syllable = [0.0] * 4 + [0.7, 0.8, 0.7] + [0.0] * 4
    assert _events(GestureSwitch(0.5, 0.35, min_hold_frames=4), loud_syllable) == []
    assert _events(GestureSwitch(0.5, 0.35, min_hold_frames=3), loud_syllable) == ["start", "end"]


# ------------------------------------------------------------------------- the claim: it is pure

_PURITY_SCRIPT = r"""
import importlib, json, sys

BLOCK_ROOTS = ("numpy", "cv2", "mediapipe", "PySide6", "torch", "onnxruntime", "sounddevice",
               "faster_whisper", "ctranslate2", "pynput", "PIL")
BLOCK_PROJECT = ("yazses.core", "yazses.headpointer", "yazses.platform", "yazses.inject",
                 "yazses.perception", "yazses.gaze", "yazses.ipc", "yazses.cli", "yazses.handsfree",
                 "yazses.gesture", "yazses.activation", "yazses.cmdsafety")


class Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in BLOCK_ROOTS or any(
            fullname == p or fullname.startswith(p + ".") for p in BLOCK_PROJECT
        ):
            raise ModuleNotFoundError("blocked: " + fullname, name=fullname)
        return None


sys.meta_path.insert(0, Block())
for name in list(sys.modules):
    if name.split(".")[0] in BLOCK_ROOTS:
        del sys.modules[name]

PURE = ("detector", "calibration", "switches", "actions", "levels", "restcheck")
for m in PURE:
    importlib.import_module("yazses.facegesture." + m)

# Exercise them, not just import them: a lazy import inside a function is the usual leak.
from yazses.facegesture.calibration import Reading, calibrate
from yazses.facegesture.detector import GestureSwitch
from yazses.facegesture.restcheck import assess_release
from yazses.facegesture.switches import SwitchAction, SwitchMapper, SwitchIntent, parse_bindings

result = calibrate("jaw_open", [Reading(0.05, 0.9)] * 20)
assert result.baseline is not None
sw = GestureSwitch(baseline=result.baseline.level)
events = [sw.update(0.95, 0.9, now_s=i * 0.1) for i in range(5)] + [sw.update(None, None, now_s=1.0 + i) for i in range(3)]
assert "start" in events and "end" in events, events
assess_release("jaw_open", 0.5, 0.35, rest=result.baseline)
bindings, _ = parse_bindings([{"gesture": "smile", "intent": "select"}], "jaw_open")
hits = []
mapper = SwitchMapper(bindings, {"select": SwitchAction(press=lambda: hits.append(1))})
mapper.handle(SwitchIntent("smile", "press", 0.0))
assert hits == [1]

loaded = sorted(n for n in sys.modules if n.startswith("yazses"))
print(json.dumps(loaded))
"""


def test_the_detector_calibration_mapping_and_action_modules_run_with_no_camera_daemon_or_desktop():
    proc = subprocess.run(
        [sys.executable, "-c", _PURITY_SCRIPT],
        capture_output=True, text=True, timeout=120, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    loaded = json.loads(proc.stdout.strip().splitlines()[-1])
    stray = [m for m in loaded if m != "yazses" and not m.startswith("yazses.facegesture")]
    assert stray == [], f"the pure face-switch modules pulled in {stray}"
    assert "yazses.facegesture.detector" in loaded  # the probe really imported what it claims
