"""A face switch that cannot let go holds the microphone open -- the stuck-open hazard.

An absolute-threshold `GestureSwitch` releases only when the score falls *below*
`release_threshold`. A face whose resting score is at or above it fires once and never lets go;
for hold-to-talk that is a microphone open indefinitely, with nothing in the configuration
looking wrong. The replay fixture `baseline-shifted-rest` demonstrates it.

Three layers, each pinned here:

* the *checkable refusal* (`facegesture/restcheck.py`): a saved resting level at or above the
  effective release threshold, or an unreachable release threshold -- said with the numbers, at
  `calibrate`, at backend start, in `doctor` and in the hands-free panel, and said NOTHING when
  nothing is known (a guard that fires on a heuristic teaches people to dismiss it, ADR-021);
* the *runtime safeguard* (`[facegesture] max_hold_s`, default OFF): a hold that has lasted the
  limit is released once and the switch re-arms only after a real reading below release;
* the *harness name* (`stuck_open` in the replay report).

Every score below is a hand-written numeric fixture; none of it is evidence about a real face.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from yazses.config import Config, FacegestureConfig
from yazses.eyeeval.switch_replay import (
    STUCK_OPEN,
    SwitchConfig,
    SwitchReplayError,
    aggregate,
    replay_trace,
)
from yazses.eyeeval.switch_trace import check_trace
from yazses.facegesture.backend import FaceGestureBackend
from yazses.facegesture.calibration import Baseline
from yazses.facegesture.detector import GestureSwitch
from yazses.facegesture.levels import GestureLevels, LevelCapture
from yazses.facegesture.restcheck import (
    RELEASE_UNREACHABLE,
    REST_AT_OR_ABOVE_HOLD,
    REST_AT_OR_ABOVE_RELEASE,
    assess_release,
    format_findings,
)
from yazses.perception import FaceSignal

ROOT = Path(__file__).resolve().parent.parent
TRACES = ROOT / "tests" / "fixtures" / "face_switch_traces"

DT = 0.1  # seconds per frame in the pure-switch tests


def _drive(switch, scores, *, dt=DT, start=0.0, confidence=None):
    """(frame, event) for every non-None event; time is ``start + i * dt``."""
    out = []
    for i, score in enumerate(scores):
        event = switch.update(score, confidence, now_s=start + i * dt)
        if event is not None:
            out.append((i, event))
    return out


def _events(switch, scores, **kw):
    return [e for _, e in _drive(switch, scores, **kw)]


# ============================================================================ the detector


def test_a_face_that_rests_above_release_never_lets_go_without_the_limit():
    """The defect itself, on the shipped defaults: this is what the limit exists to bound."""
    sw = GestureSwitch(0.5, 0.35)
    # 0.9 to fire, then a resting face that sits at 0.40 for ten minutes of frames.
    assert _events(sw, [0.9] * 4 + [0.40] * 6000) == ["start"]
    assert sw.held, "still open: the microphone would be open indefinitely"


def test_the_limit_is_off_by_default_and_changes_nothing_when_unset():
    sw = GestureSwitch()
    assert sw.max_hold_s == 0.0
    assert _events(sw, [0.9] * 3 + [0.9] * 5000) == ["start"]
    assert sw.last_end_reason == ""


def test_a_hold_that_reaches_the_limit_is_released_once_with_a_normal_end():
    sw = GestureSwitch(0.5, 0.35, max_hold_s=2.0)
    got = _drive(sw, [0.9] * 3 + [0.40] * 100)
    assert [e for _, e in got] == ["start", "end"]
    start_frame, end_frame = got[0][0], got[1][0]
    assert (end_frame - start_frame) * DT == pytest.approx(2.0, abs=DT)
    assert sw.last_end_reason == "max_hold"
    assert not sw.held and sw.latched


def test_a_stuck_switch_cannot_immediately_refire_after_the_limit():
    """Latched: a score that never falls below release re-fires nothing, however long it stays."""
    sw = GestureSwitch(0.5, 0.35, max_hold_s=1.0)
    events = _events(sw, [0.9] * 3 + [0.95] * 2000)  # above HOLD the whole time, never relaxes
    assert events == ["start", "end"], "no second start while the score has not been seen below release"


def test_it_rearms_only_after_a_real_reading_below_release():
    sw = GestureSwitch(0.5, 0.35, max_hold_s=1.0)
    scores = [0.9] * 3 + [0.9] * 15 + [0.9] * 5 + [0.2] + [0.9] * 5
    got = _events(sw, scores)
    assert got == ["start", "end", "start"]
    assert not sw.latched


def test_a_frame_with_no_reading_does_not_clear_the_latch():
    """A camera dropout is not evidence that the face relaxed."""
    sw = GestureSwitch(0.5, 0.35, max_hold_s=1.0)
    _drive(sw, [0.9] * 20)
    assert sw.latched
    assert _events(sw, [None] * 10 + [float("nan")] * 10 + [0.9] * 10, start=100.0) == []
    assert sw.latched


def test_low_confidence_and_an_unusable_baseline_do_not_clear_the_latch_either():
    sw = GestureSwitch(0.5, 0.35, max_hold_s=1.0, confidence_floor=0.5)
    _drive(sw, [0.9] * 20, confidence=0.9)
    assert sw.latched
    # a below-release score on a frame the floor refuses is not a reading
    assert _events(sw, [0.0] * 10 + [0.9] * 10, confidence=0.1, start=50.0) == []
    assert sw.latched


def test_a_hold_that_releases_normally_before_the_limit_is_not_latched():
    sw = GestureSwitch(0.5, 0.35, max_hold_s=5.0)
    assert _events(sw, [0.9] * 10 + [0.0] * 5 + [0.9] * 10) == ["start", "end", "start"]
    sw2 = GestureSwitch(0.5, 0.35, max_hold_s=5.0)
    _drive(sw2, [0.9] * 10 + [0.0] * 5)
    assert sw2.last_end_reason == "release" and not sw2.latched


def test_the_limit_never_gates_a_release_that_is_due():
    """A release on the frame the limit also trips is reported as a plain release."""
    sw = GestureSwitch(0.5, 0.35, min_release_frames=1, max_hold_s=1.0)
    sw.update(0.9, now_s=0.0)
    sw.update(0.9, now_s=0.1)
    sw.update(0.9, now_s=0.2)
    assert sw.held
    assert sw.update(0.0, now_s=5.0) == "end"  # far past the limit AND below release
    assert sw.last_end_reason == "release"
    assert not sw.latched


def test_without_a_time_the_limit_is_not_enforced_and_release_is_unaffected():
    sw = GestureSwitch(0.5, 0.35, max_hold_s=1.0)
    events = [sw.update(0.9) for _ in range(500)] + [sw.update(0.0), sw.update(0.0)]
    assert events.count("start") == 1 and events[-1] == "end"
    assert sw.last_end_reason == "release"


@pytest.mark.parametrize("bad_time", [float("nan"), float("inf"), float("-inf"), None, "x"])
def test_a_non_finite_clock_reading_never_trips_and_never_blocks_a_release(bad_time):
    sw = GestureSwitch(0.5, 0.35, max_hold_s=0.5)
    sw.update(0.9, now_s=0.0)
    sw.update(0.9, now_s=0.0)
    sw.update(0.9, now_s=0.0)
    assert sw.held
    for _ in range(50):
        assert sw.update(0.9, now_s=bad_time) is None
    assert sw.held
    sw.update(0.0, now_s=bad_time)
    assert sw.update(0.0, now_s=bad_time) == "end"


def test_a_clock_that_jumps_backwards_never_trips_the_limit():
    sw = GestureSwitch(0.5, 0.35, max_hold_s=1.0)
    for t in (100.0, 100.1, 100.2):
        sw.update(0.9, now_s=t)
    assert sw.held
    for t in (50.0, 40.0, 30.0):
        assert sw.update(0.9, now_s=t) is None
    assert sw.held


def test_a_hold_that_began_on_an_untimed_frame_starts_counting_at_the_first_timed_one():
    sw = GestureSwitch(0.5, 0.35, min_hold_frames=1, max_hold_s=1.0)
    assert sw.update(0.9) == "start"  # no time given
    assert sw.update(0.9, now_s=10.0) is None  # counting starts here
    assert sw.update(0.9, now_s=10.5) is None
    assert sw.update(0.9, now_s=11.0) == "end"
    assert sw.last_end_reason == "max_hold"


@pytest.mark.parametrize("bad", [0, 0.0, -1.0, -0.001, float("nan"), float("inf"), "abc", None, True, [], {}])
def test_an_unreadable_negative_or_zero_limit_is_off(bad):
    sw = GestureSwitch(0.5, 0.35, max_hold_s=bad)
    assert sw.max_hold_s == 0.0, bad
    assert _events(sw, [0.9] * 5000) == ["start"]


def test_reset_closes_an_open_hold_clears_the_latch_and_names_the_reason():
    sw = GestureSwitch(0.5, 0.35, max_hold_s=1.0)
    _drive(sw, [0.9] * 20)
    assert sw.latched and not sw.held
    assert sw.reset() is None and not sw.latched
    sw2 = GestureSwitch(0.5, 0.35)
    _drive(sw2, [0.9] * 5)
    assert sw2.reset() == "end" and sw2.last_end_reason == "reset"


def test_an_empty_stream_and_a_stream_of_nothing_do_nothing():
    sw = GestureSwitch(max_hold_s=1.0)
    assert _drive(sw, []) == []
    assert _drive(sw, [None] * 100) == []
    assert _drive(sw, [float("nan")] * 100) == []
    assert not sw.held and not sw.latched


def test_the_limit_works_on_a_normalised_switch_too():
    """With a baseline at 0.4 the stuck state is a resting score that normalises to >= release."""
    sw = GestureSwitch(0.5, 0.35, baseline=0.4, max_hold_s=1.0)
    # 0.95 normalises to 0.917 (>= hold) and keeps it there
    assert _events(sw, [0.95] * 200) == ["start", "end"]


def test_the_refractory_still_applies_after_the_limit():
    sw = GestureSwitch(0.5, 0.35, refractory_frames=3, max_hold_s=1.0)
    events = _events(sw, [0.9] * 20 + [0.0] * 2 + [0.9] * 10)
    assert events[:2] == ["start", "end"]
    assert events.count("start") == 2


def test_a_nan_release_threshold_is_repaired_and_cannot_pin_the_hold_open():
    """`release_threshold = nan` is valid TOML; NaN compares false, so it could never be crossed."""
    sw = GestureSwitch(0.5, float("nan"))
    assert sw.thresholds[1] < sw.thresholds[0]
    assert _events(sw, [0.9] * 4 + [0.0] * 4) == ["start", "end"]
    nan_hold = GestureSwitch(float("nan"), 0.35)
    assert nan_hold.thresholds == (0.5, 0.35)


# ============================================================================ the refusal


def _rest(level, spread=0.01, gesture="jaw_open"):
    return Baseline(gesture, level, spread, 30)


def test_nothing_known_about_the_face_means_nothing_said():
    assert assess_release("jaw_open", 0.5, 0.35) == ()
    assert assess_release("jaw_open", 0.5, 0.35, rest=None, use_baseline=True) == ()


def test_a_resting_level_below_release_is_silent():
    assert assess_release("jaw_open", 0.5, 0.35, rest=_rest(0.10)) == ()
    assert assess_release("jaw_open", 0.5, 0.35, rest=_rest(0.3499)) == ()


def test_a_resting_level_at_or_above_release_is_named_with_the_numbers():
    (f,) = assess_release("jaw_open", 0.5, 0.35, rest=_rest(0.40))
    assert f.code == REST_AT_OR_ABOVE_RELEASE
    assert "0.40" in f.message and "0.35" in f.message and "jaw_open" in f.message
    assert "microphone" in f.message
    assert "use_baseline" in f.remedy
    (edge,) = assess_release("jaw_open", 0.5, 0.35, rest=_rest(0.35))
    assert edge.code == REST_AT_OR_ABOVE_RELEASE, "equal is stuck: the switch releases only strictly below"


def test_a_resting_level_at_or_above_hold_is_the_stronger_finding():
    (f,) = assess_release("jaw_open", 0.5, 0.35, rest=_rest(0.55))
    assert f.code == REST_AT_OR_ABOVE_HOLD
    assert "0.55" in f.message and "0.50" in f.message and "0.35" in f.message


def test_with_the_baseline_applied_the_resting_face_reads_zero_and_is_silent():
    assert assess_release("jaw_open", 0.5, 0.35, rest=_rest(0.40), use_baseline=True) == ()


def test_a_baseline_with_no_headroom_is_silent_because_that_switch_is_inert():
    """use_baseline on and a baseline too high to normalise: the switch cannot fire at all."""
    assert assess_release("jaw_open", 0.5, 0.35, rest=_rest(0.9), use_baseline=True) == ()


def test_the_remedy_changes_when_use_baseline_is_already_on():
    (raw,) = assess_release("jaw_open", 0.5, 0.35, rest=_rest(0.40))
    (derived,) = assess_release(
        "jaw_open", 0.5, 0.35, rest=_rest(0.40), use_baseline=True, use_active_levels=True,
        levels=GestureLevels(active=LevelCapture("jaw_open", "active", 0.9, 0.95, 30)),
    ) or (None,)
    assert "use_baseline = true" in raw.remedy
    assert derived is None  # derived thresholds sit above rest by construction


@pytest.mark.parametrize("release", [0.0, -0.5])
def test_an_unreachable_release_threshold_is_named_without_any_calibration(release):
    (f,) = assess_release("jaw_open", 0.5, release)
    assert f.code == RELEASE_UNREACHABLE
    assert "release_threshold" in f.remedy and "0.00" in f.message


def test_a_release_at_or_above_hold_is_repaired_by_the_switch_not_flagged():
    assert assess_release("jaw_open", 0.5, 0.6) == ()  # the switch repairs it to 0.35
    (f,) = assess_release("jaw_open", 0.5, 0.6, rest=_rest(0.40))
    assert f.code == REST_AT_OR_ABOVE_RELEASE and "0.35" in f.message, "judged on the REPAIRED release"


def test_derived_thresholds_are_judged_not_the_configured_pair():
    levels = GestureLevels(active=LevelCapture("jaw_open", "active", 0.9, 0.95, 30))
    got = assess_release(
        "jaw_open", 0.5, 0.35, rest=_rest(0.40, spread=0.01), levels=levels, use_active_levels=True
    )
    assert got == (), "the derivation keeps release above rest, so a derivable setup is safe"


def test_a_derivation_that_is_refused_falls_back_to_the_configured_pair():
    # active barely above rest -> span_too_small -> the configured raw pair stands
    levels = GestureLevels(active=LevelCapture("jaw_open", "active", 0.42, 0.45, 30))
    (f,) = assess_release(
        "jaw_open", 0.5, 0.35, rest=_rest(0.40), levels=levels, use_active_levels=True
    )
    assert f.code == REST_AT_OR_ABOVE_RELEASE


@pytest.mark.parametrize(
    "hold,release,level",
    [
        (float("nan"), float("nan"), 0.4),
        (None, None, 0.4),
        ("a", "b", 0.4),
        (float("inf"), float("-inf"), 0.4),
        (0.5, 0.35, float("nan")),
    ],
)
def test_garbage_numbers_never_raise(hold, release, level):
    rest = Baseline("jaw_open", level, 0.0, 1)
    assess_release("jaw_open", hold, release, rest=rest)
    assess_release("jaw_open", hold, release, rest=rest, use_baseline=True)


def test_format_findings_is_one_line_per_finding_and_empty_for_none():
    assert format_findings(()) == []
    (line,) = format_findings(assess_release("jaw_open", 0.5, 0.35, rest=_rest(0.40)))
    assert "\n" not in line and line.endswith(".")


# ============================================================================ the backend


def _bk(config, *, baselines=None, levels=None, clock=None):
    events: list[str] = []
    kw = {}
    if clock is not None:
        kw["clock"] = clock
    backend = FaceGestureBackend(
        config,
        lambda n: events.append("start"),
        lambda: events.append("end"),
        baselines=baselines,
        levels=levels,
        **kw,
    )
    return backend, events


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_start_up_warns_once_with_the_numbers_when_a_known_resting_level_cannot_release(caplog):
    caplog.set_level(logging.WARNING)
    cfg = replace(FacegestureConfig(enabled=True), use_active_levels=True)
    # use_active_levels is on but nothing can be derived (no active level): the configured raw
    # pair stands, and the saved resting level sits above its release threshold.
    _bk(cfg, baselines={"jaw_open": _rest(0.40)}, levels={})
    text = " | ".join(_warnings(caplog))
    assert "release threshold 0.35" in text and "0.40" in text and "microphone" in text
    assert text.count("cannot let go") == 1


def test_start_up_is_silent_for_the_shipped_config_and_reads_nothing(caplog):
    caplog.set_level(logging.WARNING)
    _bk(FacegestureConfig(enabled=True))
    assert [m for m in _warnings(caplog) if "let go" in m or "microphone" in m] == []


def test_start_up_warns_about_an_unreachable_release_threshold_without_any_calibration(caplog):
    caplog.set_level(logging.WARNING)
    _bk(replace(FacegestureConfig(enabled=True), release_threshold=0.0))
    assert any("release threshold for jaw_open is 0.00" in m for m in _warnings(caplog))


def test_a_gesture_that_holds_nothing_open_is_not_judged(caplog):
    # `cancel` neither opens a microphone nor freezes the pointer, so a resting level above
    # its release threshold leaves nothing stuck and there is nothing to warn about.
    caplog.set_level(logging.WARNING)
    cfg = replace(
        FacegestureConfig(enabled=True),
        use_active_levels=True,
        switches=[{"gesture": "jaw_open", "intent": "none"}, {"gesture": "brow_raise", "intent": "cancel"}],
    )
    _bk(cfg, baselines={"brow_raise": _rest(0.40, gesture="brow_raise")}, levels={})
    assert [m for m in _warnings(caplog) if "let go" in m] == []


def test_a_commit_gesture_that_cannot_let_go_is_judged_by_what_it_leaves_frozen(caplog):
    # `select` freezes the Head-Pointer for as long as the gesture lasts (ADR-v2-147), so a
    # face that rests above the release threshold leaves the POINTER stuck -- not a microphone.
    caplog.set_level(logging.WARNING)
    cfg = replace(
        FacegestureConfig(enabled=True),
        use_active_levels=True,
        switches=[{"gesture": "jaw_open", "intent": "none"}, {"gesture": "brow_raise", "intent": "select"}],
    )
    _bk(cfg, baselines={"brow_raise": _rest(0.40, gesture="brow_raise")}, levels={})
    stuck = [m for m in _warnings(caplog) if "let go" in m]
    assert len(stuck) == 1
    assert "pointer stays frozen" in stuck[0] and "microphone" not in stuck[0]


@pytest.mark.parametrize("bad", ["abc", -1, float("nan"), True])
def test_an_unreadable_max_hold_s_is_off_and_said_once(caplog, bad):
    caplog.set_level(logging.WARNING)
    backend, _ = _bk(replace(FacegestureConfig(enabled=True), max_hold_s=bad))
    assert backend._switch.max_hold_s == 0.0
    assert sum("max_hold_s" in m for m in _warnings(caplog)) == 1


def test_the_shipped_default_is_off():
    assert FacegestureConfig().max_hold_s == 0.0
    backend, _ = _bk(FacegestureConfig(enabled=True))
    assert backend._switch.max_hold_s == 0.0


def _face(t, jaw):
    return FaceSignal(t, 0.9, {"jawOpen": jaw})


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_the_shared_camera_path_releases_a_stuck_mic_logs_it_and_does_not_refire(caplog):
    caplog.set_level(logging.WARNING)
    clock = _Clock()
    backend, events = _bk(
        replace(FacegestureConfig(enabled=True), max_hold_s=2.0, fps=10), clock=clock
    )
    for _ in range(100):  # 10 s of a resting face that scores 0.9 and never falls
        clock.now += 0.1
        backend._feed_face(_face(clock.now, 0.9), clock.now)
    assert events == ["start", "end"], "released once, not re-fired"
    msgs = [m for m in _warnings(caplog) if "max_hold_s" in m]
    assert len(msgs) == 1 and "2 s" in msgs[0] and "0.35" in msgs[0]
    # the face finally relaxes, then holds on purpose: it works again
    for jaw in [0.0] * 3 + [0.9] * 5:
        clock.now += 0.1
        backend._feed_face(_face(clock.now, jaw), clock.now)
    assert events == ["start", "end", "start"]


def test_the_shared_camera_path_without_the_limit_stays_open(caplog):
    clock = _Clock()
    backend, events = _bk(replace(FacegestureConfig(enabled=True), fps=10), clock=clock)
    for _ in range(1000):
        clock.now += 0.1
        backend._feed_face(_face(clock.now, 0.9), clock.now)
    assert events == ["start"], "the shipped default is unchanged: this is the hazard the limit bounds"


class _Cat:
    def __init__(self, name, score):
        self.category_name, self.score = name, score


def test_the_own_capture_path_passes_its_clock_so_the_limit_works_there_too(monkeypatch):
    clock = _Clock()
    backend, events = _bk(
        replace(FacegestureConfig(enabled=True), max_hold_s=2.0, fps=10), clock=clock
    )

    class _Landmarker:
        def detect(self, image):
            return SimpleNamespace(face_blendshapes=[[_Cat("jawOpen", 0.9)]])

    cv2 = SimpleNamespace(COLOR_BGR2RGB=0, cvtColor=lambda f, c: f)
    mp = SimpleNamespace(ImageFormat=SimpleNamespace(SRGB=0), Image=lambda image_format, data: data)

    class _Cap:
        def read(self):
            return True, object()

    for _ in range(100):
        clock.now += 0.1
        backend._step(_Landmarker(), _Cap(), cv2, mp)
    assert events == ["start", "end"]


def test_a_paused_gate_releases_an_open_hold_and_a_release_is_never_gated():
    """The hands-free gate and the limit compose: pause closes the mic at once; nothing blocks it."""
    from yazses.handsfree.safety import HandsFreeSafety

    class _T:
        now = 0.0

        def __call__(self):
            return self.now

    t = _T()
    gate = HandsFreeSafety(("facegesture",), clock=t)
    gate.sample("facegesture")
    assert gate.resume().ok
    events: list[str] = []
    backend = FaceGestureBackend(
        replace(FacegestureConfig(enabled=True), fps=10),
        lambda n: events.append("start"),
        lambda: events.append("end"),
        safety=gate,
        clock=_Clock(),
    )
    clock = backend._clock
    for _ in range(5):
        backend._feed_face(_face(clock(), 0.9), clock())
    assert events == ["start"]
    gate.pause("test")
    backend._feed_face(_face(clock(), 0.9), clock())
    assert events == ["start", "end"], "pause releases the open hold on the very next frame"
    # faulted: same path
    gate2 = HandsFreeSafety(("facegesture",), clock=t)
    gate2.sample("facegesture")
    assert gate2.resume().ok
    events2: list[str] = []
    b2 = FaceGestureBackend(
        replace(FacegestureConfig(enabled=True), fps=10),
        lambda n: events2.append("start"),
        lambda: events2.append("end"),
        safety=gate2,
        clock=_Clock(),
    )
    for _ in range(5):
        b2._feed_face(_face(1000.0, 0.9), 1000.0)
    gate2.fault("facegesture", "model closed")
    b2._feed_face(_face(1000.0, 0.9), 1000.0)
    assert events2 == ["start", "end"]


# ============================================================================ the harness


def _trace(name):
    return check_trace(json.loads((TRACES / f"{name}.json").read_text(encoding="utf-8")))


def test_the_baseline_shifted_fixture_is_a_named_stuck_open_failure():
    result = replay_trace(_trace("baseline-shifted-rest"), SwitchConfig())
    assert result.stuck_open_holds == 1
    report = aggregate([result])
    assert report["failures"] == [STUCK_OPEN]
    assert report["stuck_open_holds"] == 1
    assert report["longest_hold_s"] > 20.0, "one hold, from the first phantom to the end of the trace"
    assert report["intervals_held_at_start"] == 3, "the older counter still reads"


@pytest.mark.parametrize(
    "name",
    [
        "chatter-around-threshold", "deliberate-hold", "low-confidence-frames", "missing-readings",
        "quiet-rest", "speech-and-everyday", "webcam-summary-reproduction",
    ],
)
def test_the_other_fixtures_are_not_stuck_open(name):
    report = aggregate([replay_trace(_trace(name), SwitchConfig())])
    assert report["stuck_open_holds"] == 0 and report["failures"] == []


def test_the_baseline_applied_makes_the_shifted_rest_not_stuck():
    report = aggregate([replay_trace(_trace("baseline-shifted-rest"), SwitchConfig(use_trace_baseline=True))])
    assert report["failures"] == []


def test_the_limit_bounds_the_stuck_fixture_in_the_harness_and_names_no_failure():
    cfg = SwitchConfig(max_hold_s=5.0)
    result = replay_trace(_trace("baseline-shifted-rest"), cfg)
    report = aggregate([result])
    assert report["stuck_open_holds"] == 0 and report["failures"] == []
    assert report["longest_hold_s"] == pytest.approx(5.0, abs=0.2)
    assert report["false_activations"] == 1, "the single phantom start is still counted, just no longer stuck"
    assert report["intervals_held_at_start"] == 0


def test_the_report_config_records_the_limit_and_validates_it():
    assert SwitchConfig().to_document()["max_hold_s"] == 0.0
    for bad in (-1.0, float("nan"), float("inf"), "x", True):
        assert SwitchConfig(max_hold_s=bad).problems(), bad
        with pytest.raises(SwitchReplayError):
            SwitchConfig(max_hold_s=bad).check()


def test_a_hold_spanning_a_whole_quiet_segment_is_stuck_even_with_no_deliberate_interval():
    from tests.test_face_switch_replay import _build, _rest  # noqa: PLC0415

    trace = _build([("rest", [0.9] * 5 + [0.4] * 100)])
    report = aggregate([replay_trace(trace, SwitchConfig())])
    assert report["stuck_open_holds"] == 1 and report["failures"] == [STUCK_OPEN]
    assert _rest  # imported for symmetry with the fixture builders


def test_a_hold_still_open_at_a_deliberate_interval_is_stuck_by_that_alone():
    """Started inside a rest segment, so it spans no whole quiet segment; released inside the
    deliberate interval, so it does not run to the end of the trace. Only the held-at-start
    criterion can name it."""
    from tests.test_face_switch_replay import _build  # noqa: PLC0415

    trace = _build([
        ("rest", [0.0] * 10 + [0.9] * 5 + [0.4] * 5),
        ("deliberate", [0.4] * 3 + [0.0] * 5),
    ])
    result = replay_trace(trace, SwitchConfig())
    assert result.intervals[0].held_at_start
    assert result.stuck_open_holds == 1
    assert aggregate([result])["failures"] == [STUCK_OPEN]


def test_a_short_phantom_that_releases_is_not_stuck():
    from tests.test_face_switch_replay import _build  # noqa: PLC0415

    trace = _build([("rest", [0.0] * 20 + [0.9] * 5 + [0.0] * 40)])
    report = aggregate([replay_trace(trace, SwitchConfig())])
    assert report["false_activations"] == 1 and report["stuck_open_holds"] == 0


def test_the_committed_report_carries_the_named_failure():
    report = json.loads((ROOT / "tests" / "fixtures" / "face_switch_replay_report.json").read_text(encoding="utf-8"))
    by_id = {t["trace_id"]: t for t in report["traces"]}
    assert by_id["baseline-shifted-rest"]["failures"] == [STUCK_OPEN]
    assert all(t["failures"] == [] for k, t in by_id.items() if k != "baseline-shifted-rest")
    assert report["pooled_by_gesture"]["jaw_open"]["failures"] == [STUCK_OPEN]
    assert report["config"]["max_hold_s"] == 0.0


# ============================================================================ calibrate, doctor, panel


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    from yazses import cli

    paths = SimpleNamespace(data_dir=tmp_path / "data", config_file=tmp_path / "config.toml")
    monkeypatch.setattr(cli, "get_platform", lambda: SimpleNamespace(paths=paths))
    return paths


def _fake_capture(monkeypatch, readings):
    class _Cap:
        def release(self):
            pass

    class _Lm:
        def close(self):
            pass

    monkeypatch.setattr(FaceGestureBackend, "_build_landmarker", lambda self: _Lm())
    monkeypatch.setattr(FaceGestureBackend, "_open_camera", lambda self: (_Cap(), object()))
    monkeypatch.setattr(FaceGestureBackend, "collect_readings", lambda self, *a, **k: list(readings))


def _calibrate(sandbox, monkeypatch, scores):
    from typer.testing import CliRunner

    from yazses import cli
    from yazses.facegesture.calibration import Reading

    _fake_capture(monkeypatch, [Reading(s, 0.9) for s in scores])
    return CliRunner().invoke(cli.app, ["facegesture", "calibrate", "--yes"])


def test_calibrate_warns_with_the_numbers_when_the_relaxed_face_is_above_release(sandbox, monkeypatch):
    r = _calibrate(sandbox, monkeypatch, [0.4, 0.42, 0.41, 0.4, 0.39] * 4)
    assert r.exit_code == 0, r.output
    out = r.output
    assert "Warning" in out and "release threshold 0.35" in out and "microphone" in out
    assert "use_baseline" in out


def test_calibrate_is_quiet_for_a_relaxed_face_below_release(sandbox, monkeypatch):
    r = _calibrate(sandbox, monkeypatch, [0.05, 0.06, 0.04, 0.05, 0.05] * 4)
    assert r.exit_code == 0, r.output
    assert "cannot let go" not in r.output and "microphone stays open" not in r.output


def test_calibrate_still_stores_the_baseline_when_it_warns(sandbox, monkeypatch):
    from yazses.facegesture.calibration import baseline_path, load_baselines

    _calibrate(sandbox, monkeypatch, [0.4, 0.42, 0.41, 0.4, 0.39] * 4)
    assert load_baselines(baseline_path(sandbox.data_dir))["jaw_open"].level == pytest.approx(0.4, abs=0.01)


class _DoctorPlatform:
    name = "linux"

    def __init__(self, data_dir):
        self.paths = SimpleNamespace(data_dir=data_dir)


def _stored(tmp_path, level):
    from yazses.facegesture.calibration import baseline_path, save_baseline

    save_baseline(baseline_path(tmp_path), _rest(level))


def test_doctor_gets_one_warn_row_under_the_face_switch_row_when_the_stored_rest_cannot_release(tmp_path):
    from yazses.system.doctor import _handsfree_checks

    _stored(tmp_path, 0.40)
    cfg = Config()
    cfg.facegesture.enabled = True
    rows = _handsfree_checks(cfg, _DoctorPlatform(tmp_path), ("Camera", "OK", "ready"), unwired=frozenset())
    labels = [r[0] for r in rows]
    assert labels.count("Face switch release") == 1
    assert labels.index("Face switch release") == labels.index("Face switch") + 1
    (row,) = [r for r in rows if r[0] == "Face switch release"]
    assert row[1] == "WARN" and "0.40" in row[2] and "0.35" in row[2]


def test_doctor_is_silent_with_no_baseline_a_low_baseline_or_the_baseline_applied(tmp_path):
    from yazses.system.doctor import _handsfree_checks

    cfg = Config()
    cfg.facegesture.enabled = True
    def labels():
        rows = _handsfree_checks(cfg, _DoctorPlatform(tmp_path), ("Camera", "OK", "ready"), unwired=frozenset())
        return [r[0] for r in rows]

    assert "Face switch release" not in labels()          # nothing stored
    _stored(tmp_path, 0.05)
    assert "Face switch release" not in labels()          # below release
    _stored(tmp_path, 0.40)
    cfg.facegesture.use_baseline = True
    assert "Face switch release" not in labels()          # normalised away


def test_doctor_does_not_judge_a_gesture_that_only_cancels(tmp_path):
    from yazses.system.doctor import _handsfree_checks

    _stored(tmp_path, 0.40)
    cfg = Config()
    cfg.facegesture.enabled = True
    cfg.facegesture.switches = [{"gesture": "jaw_open", "intent": "cancel"}]
    rows = _handsfree_checks(cfg, _DoctorPlatform(tmp_path), ("Camera", "OK", "ready"), unwired=frozenset())
    assert "Face switch release" not in [r[0] for r in rows]


def test_doctor_judges_a_select_gesture_by_the_frozen_pointer_it_would_leave(tmp_path):
    from yazses.system.doctor import _handsfree_checks

    _stored(tmp_path, 0.40)
    cfg = Config()
    cfg.facegesture.enabled = True
    cfg.facegesture.switches = [{"gesture": "jaw_open", "intent": "select"}]
    rows = _handsfree_checks(cfg, _DoctorPlatform(tmp_path), ("Camera", "OK", "ready"), unwired=frozenset())
    release = [r for r in rows if r[0] == "Face switch release"]
    assert len(release) == 1 and release[0][1] == "WARN"
    assert "pointer stays frozen" in release[0][2] and "microphone" not in release[0][2]


def test_the_panel_shows_the_same_finding_as_a_problem_row(tmp_path):
    from yazses.handsfree.panel import build_panel
    from yazses.handsfree.panel_io import gather_panel_inputs

    _stored(tmp_path, 0.40)
    cfg = Config()
    cfg.facegesture.enabled = True
    inputs = gather_panel_inputs(
        cfg, _DoctorPlatform(tmp_path), None,
        deps_probe=lambda mods: [], blocked_probe=lambda pk: None,
        camera_gate=SimpleNamespace(allowed=True, blocker=None, reason="", remedy=""),
        unwired=frozenset(),
    )
    assert inputs.release_issues and "0.40" in inputs.release_issues[0][0]
    panel = build_panel(inputs)
    rows = [r for r in panel.health if r.label == "Face switch release"]
    assert len(rows) == 1 and rows[0].status == "problem"


def test_the_pure_check_reads_no_file_and_no_clock():
    import ast

    src = (ROOT / "src" / "yazses" / "facegesture" / "restcheck.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "math", "collections", "dataclasses", "yazses"}, imported
    assert "open(" not in src and "read_text" not in src
