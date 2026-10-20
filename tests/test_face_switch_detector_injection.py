"""EYE-BENCH-001 (#409): nuisance traces, and any detector replayed over the same traces.

Two additions to the face-switch false-activation harness (``eyeeval/switch_replay.py``):

* **Realistic nuisance traces** -- natural blinks, lively talking, yawns and glances down at a
  keyboard -- each labelled with the context that produced it, so a report says *which*
  involuntary movement fired the switch. The fixtures are invented; the tests below pin what
  each one is, so an edit cannot quietly turn a "blink" trace into something easier.
* **An injected detector.** The harness takes a :class:`Detector` (a name plus a factory) and
  defaults to the shipped ``GestureSwitch``. A candidate policy -- a timed minimum hold, say --
  is replayed over exactly the same traces and scored by exactly the same rules, and the
  harness refuses a detector whose events it could not count rather than reading silence as a
  perfect run.

No number here is a recommendation: the traces are synthetic (``NO_THRESHOLD_NOTICE``).
"""

from __future__ import annotations

import ast
import inspect
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from yazses.eyeeval import switch_replay
from yazses.eyeeval.switch_replay import (
    CURRENT_DETECTOR,
    FRAME_STATUSES,
    Detector,
    SwitchConfig,
    SwitchReplayError,
    aggregate,
    replay_trace,
    replay_traces,
)
from yazses.eyeeval.switch_trace import SwitchTrace, check_trace
from yazses.facegesture import detector as detector_module
from yazses.facegesture.detector import GestureSwitch

ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = ROOT / "tests" / "fixtures" / "face_switch_traces"
REPORT_PATH = ROOT / "tests" / "fixtures" / "face_switch_replay_report.json"
BACKEND = ROOT / "src" / "yazses" / "facegesture" / "backend.py"
HARNESS = ROOT / "src" / "yazses" / "eyeeval" / "switch_replay.py"

NUISANCE_IDS = ("animated-talking", "blinks-on-jaw-open", "look-down-glances", "natural-blinks", "yawns")


def _trace(trace_id: str) -> SwitchTrace:
    return check_trace(json.loads((TRACE_DIR / f"{trace_id}.json").read_text(encoding="utf-8")))


def _segments(trace: SwitchTrace, context: str) -> list[list[float]]:
    """The scores of every segment labelled ``context``, one list per segment."""
    out: list[list[float]] = []
    cursor = 0
    for segment in trace.segments:
        if segment.context == context:
            out.append([v for v in trace.scores[cursor : cursor + segment.samples] if v is not None])
        cursor += segment.samples
    return out


def _longest_run_at_or_above(values: list[float], level: float) -> int:
    best = run = 0
    for value in values:
        run = run + 1 if value >= level else 0
        best = max(best, run)
    return best


def _block(trace_id: str, detector: Detector = CURRENT_DETECTOR, **config: Any) -> dict[str, Any]:
    return aggregate([replay_trace(_trace(trace_id), SwitchConfig(**config), detector=detector)])


# --------------------------------------------------------------------------- an independent candidate policy


@dataclass
class _TimedHold:
    """A deliberately independent policy (it shares no code with ``GestureSwitch``): press once
    the score has stayed at or above ``hold`` for ``min_hold_s`` of *sample* time, release after
    ``min_release`` samples below ``release`` or without a reading. Stands in for any candidate,
    including the timed minimum hold #406 proposes."""

    hold: float
    release: float
    min_hold_s: float
    min_release: int
    repaired_release: bool = False
    _held: bool = False
    _since: float | None = None
    _below: int = 0
    _frame: str = "no_reading"

    @property
    def held(self) -> bool:
        return self._held

    @property
    def last_frame(self) -> str:
        return self._frame

    @property
    def thresholds(self) -> tuple[float, float]:
        return self.hold, self.release

    def update(self, score: float | None, confidence: float | None = None, now_s: float | None = None) -> str | None:
        self._frame = "no_reading" if score is None else "reading"
        value = -1.0 if score is None else score
        if self._held:
            if value < self.release:
                self._below += 1
                if self._below >= self.min_release:
                    self._held, self._below = False, 0
                    return "end"
            else:
                self._below = 0
            return None
        if value >= self.hold and now_s is not None:
            self._since = now_s if self._since is None else self._since
            if now_s - self._since >= self.min_hold_s - 1e-9:
                self._held, self._since = True, None
                return "start"
        else:
            self._since = None
        return None

    def reset(self) -> str | None:
        if self._held:
            self._held = False
            return "end"
        return None


def _timed_for_eyes_closed(config: SwitchConfig, gesture: str, baseline: float | None) -> Any:
    if gesture != "eyes_closed":
        return CURRENT_DETECTOR.build(config, gesture, baseline)
    return _TimedHold(config.hold_threshold, config.release_threshold, 0.8, config.min_release_frames)


TIMED = Detector(name="test.TimedHold(eyes_closed 0.8 s)", build=_timed_for_eyes_closed)


# --------------------------------------------------------------------------- 1. the nuisance fixtures are what they claim


def test_natural_blinks_are_spontaneous_blinks_at_an_ordinary_rate_and_length() -> None:
    trace = _trace("natural-blinks")
    assert trace.gesture == "eyes_closed" and trace.sample_rate_hz == 15
    blinks = _segments(trace, "blink")
    minutes = trace.duration_s / 60
    assert len(blinks) == 34
    assert 15 <= len(blinks) / minutes <= 20, "a resting adult blinks roughly 15-20 times a minute"
    for blink in blinks:
        assert 2 <= len(blink) <= 6, "about 130-400 ms at 15 Hz"
        assert 0.60 <= max(blink) <= 0.92, "the range the description states"
    # The long ones are the hard case: three or more samples at a 0.5 hold threshold.
    assert sum(_longest_run_at_or_above(b, 0.5) >= 3 for b in blinks) == 6
    closures = _segments(trace, "deliberate")
    assert [len(c) for c in closures] == [18, 18, 18], "three deliberate 1.2 s closures"


def test_look_down_glances_hold_the_lids_partly_closed_for_seconds() -> None:
    trace = _trace("look-down-glances")
    assert trace.gesture == "eyes_closed"
    glances = _segments(trace, "look_down")
    assert len(glances) == 6
    assert all(1.5 <= len(g) / trace.sample_rate_hz <= 4.0 for g in glances)
    assert all(max(g) < 0.7 for g in glances), "partly closed, never a full closure"
    deep = [g for g in glances if min(g[2:-2]) >= 0.5]
    shallow = [g for g in glances if max(g) < 0.52]
    assert len(deep) == 4 and len(shallow) == 2
    # One shallow glance brushes the default hold for exactly the default debounce: the edge case.
    assert sorted(_longest_run_at_or_above(g, 0.5) for g in shallow) == [0, 3]
    assert len(_segments(trace, "blink")) == 12 and len(_segments(trace, "deliberate")) == 2


def test_animated_talking_has_emphatic_vowels_but_none_held_for_three_samples() -> None:
    trace = _trace("animated-talking")
    (speech,) = _segments(trace, "speech")
    assert len(speech) / trace.sample_rate_hz == 70.0
    assert 0.5 <= max(speech) <= 0.58, "emphatic open vowels cross the default hold threshold"
    assert _longest_run_at_or_above(speech, 0.5) <= 2, "... but never for the default 3-sample debounce"
    assert not _segments(trace, "deliberate")


def test_yawns_are_longer_and_wider_than_the_deliberate_gesture() -> None:
    trace = _trace("yawns")
    yawns, holds = _segments(trace, "yawn"), _segments(trace, "deliberate")
    assert [len(y) / trace.sample_rate_hz for y in yawns] == [6.0, 6.0, 6.0]
    assert len(holds) == 2 and all(len(h) / trace.sample_rate_hz < 1.5 for h in holds)
    assert min(max(y) for y in yawns) > max(max(h) for h in holds)


def test_blinks_watched_by_a_jaw_switch_barely_move_the_jaw_score() -> None:
    trace = _trace("blinks-on-jaw-open")
    assert trace.gesture == "jaw_open"
    assert len(_segments(trace, "blink")) == 17
    assert max(v for v in trace.scores if v is not None) < 0.1


# --------------------------------------------------------------------------- 2. what the shipped detector does on them


def test_the_shipped_detector_fires_on_long_natural_blinks() -> None:
    block = _block("natural-blinks")
    assert block["false_activations"] == 6
    assert block["by_context"]["blink"]["false_activations"] == 6
    assert block["by_context"]["rest"]["false_activations"] == 0
    assert block["intended_activations"] == 3 and block["misses"] == 0 and block["recall"] == 1.0
    assert block["per_hour_extrapolated"] is True
    hours = block["non_deliberate_s"] / 3600
    assert block["false_activations_per_hour"] == pytest.approx(6 / hours, abs=1e-3)
    assert block["false_activations_per_hour_lower_95"] < block["false_activations_per_hour"]
    assert block["false_activations_per_hour_upper_95"] > block["false_activations_per_hour"]


def test_the_shipped_detector_fires_on_deep_glances_down_and_not_on_short_blinks() -> None:
    block = _block("look-down-glances")
    assert block["by_context"]["look_down"]["false_activations"] == 5
    assert block["by_context"]["blink"]["false_activations"] == 0
    assert block["recall"] == 1.0


def test_lively_talking_does_not_fire_the_default_but_a_lower_threshold_does() -> None:
    default = _block("animated-talking")
    assert default["false_activations"] == 0
    assert default["intended_activations"] == 0 and default["misses"] == 0
    assert default["recall"] == {"value": None, "reason": "not_measured"}
    assert default["activation_latency_ms"] == {"value": None, "reason": "not_measured"}
    lowered = _block("animated-talking", hold_threshold=0.35)
    assert lowered["by_context"]["speech"]["false_activations"] == 2


def test_every_yawn_is_a_phantom_whatever_the_threshold() -> None:
    for hold in (0.35, 0.5, 0.6):
        block = _block("yawns", hold_threshold=hold)
        assert block["by_context"]["yawn"]["false_activations"] == 3, hold
        assert block["detections"] == 2
    # A longer debounce cannot help either: a yawn is longer than the gesture it imitates.
    assert _block("yawns", min_hold_frames=15)["by_context"]["yawn"]["false_activations"] == 3


def test_ordinary_blinks_do_not_fire_a_non_blink_gesture() -> None:
    """design/specs/eye-face-switch.md: "Ordinary blink trace does not fire a non-blink gesture"."""
    block = _block("blinks-on-jaw-open")
    assert block["false_activations"] == 0
    assert block["by_context"]["blink"]["false_activations"] == 0


def test_the_committed_report_carries_the_same_nuisance_numbers() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert report["detector"] == CURRENT_DETECTOR.name
    by_id = {t["trace_id"]: t for t in report["traces"]}
    assert set(NUISANCE_IDS) <= set(by_id)
    for trace_id in NUISANCE_IDS:
        block = _block(trace_id)
        for key in ("false_activations", "false_activations_per_hour", "misses", "by_context"):
            assert by_id[trace_id][key] == block[key], (trace_id, key)
    assert "eyes_closed" in report["pooled_by_gesture"]


# --------------------------------------------------------------------------- 3. another detector, the same traces


def test_a_timed_hold_removes_blink_phantoms_and_keeps_every_deliberate_closure() -> None:
    shipped, timed = _block("natural-blinks"), _block("natural-blinks", TIMED)
    assert shipped["by_context"]["blink"]["false_activations"] == 6
    assert timed["by_context"]["blink"]["false_activations"] == 0
    assert timed["recall"] == 1.0 and timed["misses"] == 0
    # Same traces, same scoring: the exposure is identical, only the policy changed.
    assert timed["non_deliberate_s"] == shipped["non_deliberate_s"]
    assert timed["activation_latency_ms"]["median"] > shipped["activation_latency_ms"]["median"]


def test_a_timed_hold_does_not_fix_looking_down() -> None:
    assert _block("look-down-glances", TIMED)["by_context"]["look_down"]["false_activations"] > 0


def test_the_report_names_the_detector_and_the_sweep_replays_the_same_one() -> None:
    traces = [_trace("natural-blinks")]
    shipped = replay_traces(traces, sweep=[0.5])
    timed = replay_traces(traces, sweep=[0.5], detector=TIMED)
    assert shipped["detector"] == "yazses.facegesture.detector.GestureSwitch"
    assert timed["detector"] == TIMED.name
    assert timed["sweep"][0]["by_gesture"]["eyes_closed"]["false_activations"] == 0
    assert shipped["sweep"][0]["by_gesture"]["eyes_closed"]["false_activations"] == 6
    assert shipped["config"] == timed["config"], "the configuration is the input, the detector the variable"


def test_the_factory_builds_a_fresh_detector_per_trace_from_gesture_and_baseline_only() -> None:
    calls: list[tuple[Any, ...]] = []

    def build(config: SwitchConfig, gesture: str, baseline: float | None) -> Any:
        calls.append((config, gesture, baseline))
        return CURRENT_DETECTOR.build(config, gesture, baseline)

    traces = [_trace("natural-blinks"), _trace("baseline-shifted-rest")]
    config = SwitchConfig(use_trace_baseline=True)
    replay_traces(traces, config, detector=Detector("recording", build))
    assert [(g, b) for _, g, b in calls] == [("jaw_open", 0.40), ("eyes_closed", None)]
    assert all(c is config for c, _, _ in calls)
    assert list(inspect.signature(build).parameters) == ["config", "gesture", "baseline"]


def test_the_default_detector_is_the_shipped_switch_and_changes_nothing() -> None:
    trace = _trace("natural-blinks")
    assert isinstance(CURRENT_DETECTOR.build(SwitchConfig(), "eyes_closed", None), GestureSwitch)
    assert replay_trace(trace) == replay_trace(trace, detector=CURRENT_DETECTOR)


# --------------------------------------------------------------------------- 4. a detector the harness cannot count is refused


@dataclass
class _Scripted:
    """Returns the scripted events in order, then None; ``frame`` is its frame status."""

    events: list[Any]
    final: Any = None
    frame: str = "reading"
    repaired_release: bool = False
    _i: int = field(default=0)

    @property
    def held(self) -> bool:
        return False

    @property
    def last_frame(self) -> str:
        return self.frame

    @property
    def thresholds(self) -> tuple[float, float]:
        return 0.5, 0.35

    def update(self, score: float | None, confidence: float | None = None, now_s: float | None = None) -> Any:
        event = self.events[self._i] if self._i < len(self.events) else None
        self._i += 1
        return event

    def reset(self) -> Any:
        return self.final


def _scripted(**kw: Any) -> Detector:
    return Detector("scripted", lambda config, gesture, baseline: _Scripted(**kw))


@pytest.mark.parametrize(
    ("kw", "fragment"),
    [
        ({"events": ["press"]}, "only None, 'start' and 'end'"),
        ({"events": [True]}, "only None, 'start' and 'end'"),
        ({"events": ["end"]}, "with no hold open"),
        ({"events": ["start", None, "start"]}, "still open"),
        ({"events": [], "final": "end"}, "with no hold open"),
        ({"events": ["start"], "final": "bogus"}, "only None, 'start' and 'end'"),
        ({"events": [], "frame": "blurry"}, "frame status"),
    ],
)
def test_an_event_or_status_the_harness_cannot_count_is_refused(kw: dict[str, Any], fragment: str) -> None:
    with pytest.raises(SwitchReplayError, match="scripted") as raised:
        replay_trace(_trace("blinks-on-jaw-open"), detector=_scripted(**kw))
    assert fragment in str(raised.value)


def test_a_well_behaved_scripted_detector_is_counted() -> None:
    """The refusals above are not a harness that refuses everything."""
    block = aggregate([replay_trace(_trace("blinks-on-jaw-open"), detector=_scripted(events=["start", None, "end"]))])
    assert block["false_activations"] == 1
    assert set(FRAME_STATUSES) == set(block["sample_status"])


# --------------------------------------------------------------------------- 5. short and empty-of-events traces


def _short(scores: list[float], contexts: list[tuple[str, int]], gesture: str = "eyes_closed") -> SwitchTrace:
    return check_trace(
        {
            "schema_version": "1.1",
            "trace_id": "short",
            "study_mode": "synthetic",
            "gesture": gesture,
            "sample_rate_hz": 15,
            "segments": [{"context": c, "samples": n} for c, n in contexts],
            "scores": scores,
        }
    )


def test_a_one_second_trace_with_one_blink_reports_zero_with_a_wide_limit_not_a_clean_bill() -> None:
    trace = _short([0.1] * 6 + [0.6, 0.55] + [0.1] * 7, [("rest", 6), ("blink", 2), ("rest", 7)])
    block = aggregate([replay_trace(trace)])
    assert block["duration_s"] == 1.0
    assert block["false_activations"] == 0 and block["false_activations_per_hour"] == 0.0
    assert block["per_hour_extrapolated"] is True
    assert block["false_activations_per_hour_upper_95"] == pytest.approx(2.9957 * 3600, rel=1e-3)
    assert block["intended_activations"] == 0 and block["misses"] == 0
    assert block["recall"] == {"value": None, "reason": "not_measured"}


def test_a_trace_that_is_all_deliberate_has_no_phantom_rate_at_all() -> None:
    trace = _short([0.9] * 15, [("deliberate", 15)])
    block = aggregate([replay_trace(trace)])
    assert block["detections"] == 1 and block["misses"] == 0
    assert block["false_activations"] == 0
    assert block["false_activations_per_hour"] == {"value": None, "reason": "not_measured"}


def test_a_1_0_trace_still_reads_and_the_new_contexts_are_1_1() -> None:
    doc = json.loads((TRACE_DIR / "quiet-rest.json").read_text(encoding="utf-8"))
    assert doc["schema_version"] == "1.0"
    check_trace(doc)
    for trace_id in NUISANCE_IDS:
        assert json.loads((TRACE_DIR / f"{trace_id}.json").read_text(encoding="utf-8"))["schema_version"] == "1.1"


# --------------------------------------------------------------------------- 6. the default follows the backend


def _gesture_switch_calls(tree: ast.AST) -> list[ast.Call]:
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            if name == "GestureSwitch":
                calls.append(node)
    return calls


def test_the_default_detector_passes_every_argument_the_backend_passes() -> None:
    """When the backend starts building its switch with a new argument (#406's timed hold), the
    harness must build it the same way, or the committed report measures a detector that no
    longer ships. Fix by passing the same argument in ``_build_gesture_switch``."""
    backend_calls = _gesture_switch_calls(ast.parse(BACKEND.read_text(encoding="utf-8")))
    assert backend_calls, "found no GestureSwitch(...) in the backend: this guard would pass on nothing"
    harness_tree = ast.parse(HARNESS.read_text(encoding="utf-8"))
    builder = next(
        n for n in ast.walk(harness_tree) if isinstance(n, ast.FunctionDef) and n.name == "_build_gesture_switch"
    )
    (harness_call,) = _gesture_switch_calls(builder)
    assert not harness_call.args, "keywords only, so the comparison below is by name"
    harness_kw = {k.arg for k in harness_call.keywords}
    for call in backend_calls:
        assert not call.args, "the backend passes keywords; a positional one would escape this guard"
        missing = {k.arg for k in call.keywords} - harness_kw
        assert not missing, f"the backend builds GestureSwitch with {sorted(missing)}; _build_gesture_switch does not"


def test_the_backend_guard_would_notice_a_new_argument() -> None:
    """Green on a backend that adds nothing proves little; show it fires."""
    mutated = _gesture_switch_calls(ast.parse("GestureSwitch(hold_threshold=1, min_hold_s=0.8)"))
    harness_kw = {
        k.arg for k in _gesture_switch_calls(ast.parse(inspect.getsource(switch_replay._build_gesture_switch)))[0].keywords
    }
    assert {k.arg for k in mutated[0].keywords} - harness_kw == {"min_hold_s"}


@pytest.mark.skipif(
    "min_hold_s" not in inspect.signature(GestureSwitch).parameters
    or not hasattr(detector_module, "min_hold_s_for"),
    reason="GestureSwitch has no timed minimum hold in this tree (#406 not merged)",
)
def test_the_real_timed_hold_once_it_exists_removes_blink_phantoms() -> None:
    """Runs only once #406's timed minimum hold is in ``GestureSwitch``: the same replay, the real policy."""
    min_hold_s_for = detector_module.min_hold_s_for

    def build(config: SwitchConfig, gesture: str, baseline: float | None) -> Any:
        return GestureSwitch(
            hold_threshold=config.hold_threshold,
            release_threshold=config.release_threshold,
            min_hold_frames=config.min_hold_frames,
            min_release_frames=config.min_release_frames,
            baseline=baseline,
            confidence_floor=config.confidence_floor,
            refractory_frames=config.refractory_frames,
            max_hold_s=config.max_hold_s,
            min_hold_s=min_hold_s_for(gesture),
        )

    block = _block("natural-blinks", Detector("GestureSwitch+min_hold_s_for", build))
    assert block["by_context"]["blink"]["false_activations"] == 0
    assert block["recall"] == 1.0
