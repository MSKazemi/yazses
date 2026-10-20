"""The false-activation harness reports what the switch actually did, and refuses to report on nothing.

`src/yazses/eyeeval/switch_trace.py` and `src/yazses/eyeeval/switch_replay.py` are EYE-BENCH-001
(#409), ROADMAP P5.4: replay *numeric* traces through the real `GestureSwitch` / `SwitchMapper`
and report phantom actions per hour of non-deliberate time, recall on deliberate gestures,
latency and chatter. The properties below are the ones an evaluation harness gets wrong in ways
that read as success, and this repository has shipped each shape at least once (see the
neighbouring `tests/test_grounding_replay.py`, whose pattern this follows):

1. **A guard that iterates is green on an empty collection.** `0.0` phantoms per hour over zero
   samples is character-identical to a switch that never misfires, so an empty trace, an empty
   trace set and an empty sweep are all refused, each proved on an *empty* input.
2. **A zero denominator is a marker, never a zero.** No non-deliberate time, no deliberate
   gesture and no usable reading each yield `{"value": null, "reason": ...}`.
3. **A short trace with no events is not zero per hour.** The rate travels with its exact
   Poisson upper bound.
4. **A check that cannot parse its input must fail loudly.** Unreadable input exits `2`; input
   that parses but breaks a rule exits `1`.
5. **Recall is matching, not counting.** A start only counts for an interval if it falls inside
   that interval's window; the matching tests below are the ones a mutation of the matcher has
   to turn red.
6. **An "is it in sync?" test on a generated artifact cannot notice an omission**, so the
   committed report is also checked for completeness by count and by trace id.

Nothing here measures a product threshold, and nothing may: every fixture is invented, the
`webcam-summary-reproduction` one included -- it is shaped to three numbers from a one-line
summary of one session and contains no recorded data. The real curve is a volunteer study
(ROADMAP P5.4, ADR-v2-150).
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import math
import statistics
from pathlib import Path
from typing import Any

import pytest

from yazses.eyeeval.schema import FORBIDDEN_FIELD_TOKENS, MISSING_REASONS, forbidden_field_problems
from yazses.eyeeval.switch_replay import (
    NO_THRESHOLD_NOTICE,
    ZERO_DENOMINATOR_RULE,
    SwitchConfig,
    SwitchReplayError,
    aggregate,
    poisson_upper_95,
    replay_trace,
    replay_traces,
    sweep_thresholds,
)
from yazses.eyeeval.switch_trace import (
    CONTEXTS,
    EXTRA_FORBIDDEN_TOKENS,
    SwitchTraceError,
    check_trace,
    validate_trace,
)
from yazses.facegesture.detector import GestureSwitch

ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = ROOT / "tests" / "fixtures" / "face_switch_traces"
REPORT_PATH = ROOT / "tests" / "fixtures" / "face_switch_replay_report.json"
SCRIPT = ROOT / "scripts" / "replay_face_switch_trace.py"
MODULES = [
    ROOT / "src" / "yazses" / "eyeeval" / "switch_trace.py",
    ROOT / "src" / "yazses" / "eyeeval" / "switch_replay.py",
]

#: Written out rather than derived from the directory, so deleting a fixture changes the
#: report and *not* this list -- which is the whole point of a completeness check.
EXPECTED_TRACE_IDS = frozenset(
    {
        "animated-talking",
        "baseline-shifted-rest",
        "blinks-on-jaw-open",
        "chatter-around-threshold",
        "deliberate-hold",
        "look-down-glances",
        "low-confidence-frames",
        "missing-readings",
        "natural-blinks",
        "quiet-rest",
        "speech-and-everyday",
        "webcam-summary-reproduction",
        "yawns",
    }
)


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("replay_face_switch_trace", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()


def _document(trace_id: str) -> dict[str, Any]:
    loaded = json.loads((TRACE_DIR / f"{trace_id}.json").read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _trace(trace_id: str) -> Any:
    return check_trace(_document(trace_id))


def _fixture_files() -> list[Path]:
    files = sorted(TRACE_DIR.glob("*.json"))
    assert len(files) == len(EXPECTED_TRACE_IDS), (
        f"expected {len(EXPECTED_TRACE_IDS)} trace fixtures in {TRACE_DIR}, found "
        f"{[p.name for p in files]} -- a guard that globs an empty directory is green for the wrong reason"
    )
    return files


def _build(
    segments: list[tuple[str, list[float | None]]],
    *,
    trace_id: str = "built",
    rate: float = 10,
    confidences: list[float | None] | None = None,
    baseline: float | None = None,
    gesture: str = "jaw_open",
    mode: str = "synthetic",
) -> Any:
    """An in-memory trace from (context, scores) runs, through the real validator."""
    doc: dict[str, Any] = {
        "schema_version": "1.0",
        "trace_id": trace_id,
        "study_mode": mode,
        "gesture": gesture,
        "sample_rate_hz": rate,
        "segments": [{"context": c, "samples": len(s)} for c, s in segments],
        "scores": [v for _, s in segments for v in s],
    }
    if confidences is not None:
        doc["confidences"] = confidences
    if baseline is not None:
        doc["baseline"] = {"level": baseline}
    return check_trace(doc)


def _rest(n: int, level: float = 0.04) -> list[float | None]:
    return [level] * n


STRONG_HOLD: list[float | None] = [0.3, 0.7, 0.8, 0.85, 0.85, 0.85, 0.8, 0.5, 0.2, 0.05]


def _is_missing(value: Any, reason: str) -> bool:
    return value == {"value": None, "reason": reason}


# --------------------------------------------------------------------------- 0. fixtures are what they claim


def test_the_fixture_directory_holds_exactly_the_expected_traces() -> None:
    assert {p.stem for p in _fixture_files()} == EXPECTED_TRACE_IDS


def test_every_fixture_is_valid_and_synthetic_and_names_its_own_id() -> None:
    for path in _fixture_files():
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert validate_trace(doc) == [], path.name
        assert doc["trace_id"] == path.stem
        assert doc["study_mode"] in ("synthetic", "ci"), "a checked-in trace can never be community data"
        assert forbidden_field_problems(doc) == []


def test_the_webcam_reproduction_really_has_the_three_numbers_it_claims() -> None:
    """Speech peaked 0.26; a held deliberate jaw-open peaked 0.46 with median 0.29. If a fixture
    edit drifts from the summary it reproduces, the `0.5 never fires / 0.35 fires` test below
    would still pass for the wrong reason."""
    doc = _document("webcam-summary-reproduction")
    assert doc["description"].startswith("SYNTHETIC REPRODUCTION")
    trace = check_trace(doc)
    cursor, speech, hold = 0, [], []
    for seg in trace.segments:
        values = [v for v in trace.scores[cursor : cursor + seg.samples] if v is not None]
        if seg.context == "speech":
            speech += values
        if seg.context == "deliberate":
            hold.append(values)
        cursor += seg.samples
    assert max(speech) == 0.26
    assert len(hold) == 3
    for one in hold:
        assert max(one) == 0.46
        assert statistics.median(one) == pytest.approx(0.29)


def test_each_fixture_really_is_the_case_it_is_named_for() -> None:
    rest = _trace("quiet-rest")
    assert [s.context for s in rest.segments] == ["rest"] and max(v for v in rest.scores if v is not None) < 0.1
    assert any(s.context == "speech" for s in _trace("speech-and-everyday").segments)
    assert {s.context for s in _trace("speech-and-everyday").segments} >= {"head_movement", "smile"}
    assert sum(v is None for v in _trace("missing-readings").scores) >= 20
    low = _trace("low-confidence-frames")
    assert any(c is not None and c < 0.3 for c in low.confidences)
    assert _trace("baseline-shifted-rest").baseline_level == 0.40
    rest_levels = [v for v in _trace("baseline-shifted-rest").scores[:50] if v is not None]
    assert min(rest_levels) > 0.35, "a shifted rest must sit above the release threshold"


# --------------------------------------------------------------------------- 1. the headline reproduction


def test_default_threshold_never_fires_on_the_webcam_summary_but_035_does() -> None:
    trace = _trace("webcam-summary-reproduction")
    default = aggregate([replay_trace(trace, SwitchConfig())])
    assert default["intended_activations"] == 3
    assert default["detections"] == 0 and default["misses"] == 3
    assert default["recall"] == 0.0
    assert default["false_activations"] == 0

    at_035 = aggregate([replay_trace(trace, SwitchConfig(hold_threshold=0.35))])
    assert at_035["detections"] == 3 and at_035["misses"] == 0
    assert at_035["recall"] == 1.0
    assert at_035["false_activations"] == 0
    assert at_035["effective_thresholds"]["release_repaired"] is True


def test_the_sweep_shows_the_trade_off_and_not_a_recommendation() -> None:
    report = replay_traces(
        [_trace("webcam-summary-reproduction")], sweep=[0.5, 0.35, 0.25, 0.2]
    )
    rows = {row["hold_threshold"]: row["by_gesture"]["jaw_open"] for row in report["sweep"]}
    assert [row["hold_threshold"] for row in report["sweep"]] == [0.2, 0.25, 0.35, 0.5], "sorted, input order irrelevant"
    assert rows[0.5]["detections"] == 0
    assert rows[0.35]["detections"] == 3 and rows[0.35]["false_activations"] == 0
    # Lowering far enough lets ordinary speech through: the other end of the trade-off.
    assert rows[0.2]["false_activations"] > 0
    assert rows[0.2]["by_context"]["speech"]["false_activations"] == rows[0.2]["false_activations"]
    assert rows[0.2]["recall"] == 1.0
    assert report["no_threshold_notice"] == NO_THRESHOLD_NOTICE
    assert "recommended" in NO_THRESHOLD_NOTICE and "synthetic" in NO_THRESHOLD_NOTICE.lower()


# --------------------------------------------------------------------------- 2. the individual shapes


def test_quiet_rest_has_no_phantoms_but_the_rate_carries_its_upper_bound() -> None:
    result = aggregate([replay_trace(_trace("quiet-rest"))])
    assert result["false_activations"] == 0
    assert result["false_activations_per_hour"] == 0.0
    # 60 s with nothing is "no more than ~180 an hour", not "never".
    assert result["false_activations_per_hour_upper_95"] == pytest.approx(2.9957 / (60 / 3600), rel=1e-3)
    assert _is_missing(result["recall"], "not_measured")
    assert _is_missing(result["activation_latency_ms"], "not_measured")


def test_speech_and_everyday_movement_do_not_fire_the_default() -> None:
    result = aggregate([replay_trace(_trace("speech-and-everyday"))])
    assert result["false_activations"] == 0
    assert set(result["by_context"]) == {"rest", "speech", "head_movement", "smile"}
    assert result["by_context"]["speech"]["duration_s"] == 20.0
    assert result["by_context"]["speech"]["false_activations_per_hour"] == 0.0


def test_a_clean_deliberate_hold_is_detected_with_the_debounce_as_its_latency() -> None:
    result = aggregate([replay_trace(_trace("deliberate-hold"))])
    assert (result["intended_activations"], result["detections"], result["misses"]) == (3, 3, 0)
    assert result["false_activations"] == 0
    # First sample >= 0.5 is index 1 of the hold; the third consecutive one starts it: 3 samples at 10 Hz.
    assert result["activation_latency_ms"] == {"count": 3, "median": 300.0, "max": 300.0}
    assert result["chatter"]["chattering_gestures"] == 0
    assert result["chatter"]["starts_per_detected_gesture"] == 1.0


def test_chatter_around_the_threshold_is_counted_and_the_release_debounce_removes_it() -> None:
    trace = _trace("chatter-around-threshold")
    chatty = aggregate([replay_trace(trace)])
    assert chatty["detections"] == 2 and chatty["false_activations"] == 0
    assert chatty["chatter"]["chattering_gestures"] == 1
    assert chatty["chatter"]["max_starts_per_gesture"] == 6
    assert chatty["chatter"]["extra_starts"] == 5
    assert chatty["chatter"]["starts_per_detected_gesture"] == 3.5

    # Three low samples to let go, and the two-sample dips no longer release: one start.
    calm = aggregate([replay_trace(trace, SwitchConfig(min_release_frames=3))])
    assert calm["chatter"]["chattering_gestures"] == 0
    assert calm["chatter"]["max_starts_per_gesture"] == 1


def test_chatter_is_not_a_false_activation() -> None:
    """The extra starts happen while the person is gesturing; they belong to chatter, not to the phantom rate."""
    result = aggregate([replay_trace(_trace("chatter-around-threshold"))])
    assert result["false_activations"] == 0 and result["chatter"]["extra_starts"] > 0


def test_missing_readings_never_hold_a_gesture_open_and_a_dropout_can_split_one() -> None:
    result = aggregate([replay_trace(_trace("missing-readings"))])
    assert result["detections"] == 2
    # The two-sample 0.9 spike next to dropouts is below min_hold_frames; the dropout does not hold a key.
    assert result["false_activations"] == 0
    # One dropped sample inside a hold is survived; a four-sample dropout splits it in two.
    assert result["chatter"]["chattering_gestures"] == 1 and result["chatter"]["max_starts_per_gesture"] == 2
    status = result["sample_status"]
    assert status["no_reading"] >= 20 and status["reading"] > 0
    assert sum(status.values()) == result["samples"]
    assert result["non_deliberate_usable_fraction"] < 1.0


def test_nan_is_a_missing_reading_not_a_number() -> None:
    nan = float("nan")
    trace = _build([("rest", _rest(20)), ("deliberate", [0.8, 0.8, nan, nan, nan, nan, 0.8, 0.8, 0.8, 0.1, 0.1]), ("rest", _rest(20))])
    assert trace.scores[20 + 2] is None
    result = aggregate([replay_trace(trace)])
    assert result["sample_status"]["no_reading"] == 4
    assert result["detections"] == 1


def test_low_confidence_spikes_are_phantoms_without_a_floor_and_not_with_one() -> None:
    trace = _trace("low-confidence-frames")
    open_gate = aggregate([replay_trace(trace, SwitchConfig())])
    assert open_gate["false_activations"] == 3
    assert open_gate["by_context"]["rest"]["false_activations"] == 3

    gated = aggregate([replay_trace(trace, SwitchConfig(confidence_floor=0.5))])
    assert gated["false_activations"] == 0
    assert gated["recall"] == 1.0
    assert gated["sample_status"]["low_confidence"] == 15


def test_a_confidence_floor_with_a_source_that_reports_none_blocks_everything_and_says_so() -> None:
    """The landmarker reports no per-frame confidence (ROADMAP P5.4), so a floor on a trace without
    any must read as 'tracking unavailable', not as a perfectly quiet switch."""
    trace = _build([("rest", _rest(100)), ("deliberate", STRONG_HOLD), ("rest", _rest(50))])
    result = aggregate([replay_trace(trace, SwitchConfig(confidence_floor=0.5))])
    assert result["detections"] == 0 and result["recall"] == 0.0
    assert result["sample_status"]["low_confidence"] == result["samples"]
    assert _is_missing(result["false_activations_per_hour"], "tracking_unavailable")
    assert _is_missing(result["false_activations_per_hour_upper_95"], "tracking_unavailable")
    assert result["non_deliberate_usable_fraction"] == 0.0


def test_baseline_shifted_rest_is_a_stuck_phantom_in_absolute_terms_and_quiet_with_the_baseline() -> None:
    trace = _trace("baseline-shifted-rest")
    absolute = aggregate([replay_trace(trace, SwitchConfig())])
    assert absolute["false_activations"] == 1
    # The phantom never releases (rest stays above 0.35), so every later gesture finds the key already held.
    assert absolute["detections"] == 0 and absolute["misses"] == 3
    assert absolute["intervals_held_at_start"] == 3

    calibrated_config = SwitchConfig(use_trace_baseline=True)
    calibrated = replay_trace(trace, calibrated_config)
    assert calibrated.baseline_applied == 0.40
    doc = aggregate([calibrated])
    assert doc["false_activations"] == 0 and doc["detections"] == 3 and doc["recall"] == 1.0


def test_a_baseline_with_no_headroom_makes_every_sample_unusable_and_the_rate_missing() -> None:
    trace = _build([("rest", _rest(100)), ("deliberate", STRONG_HOLD)], baseline=0.9)
    result = aggregate([replay_trace(trace, SwitchConfig(use_trace_baseline=True))])
    assert result["sample_status"]["unusable_baseline"] == result["samples"]
    assert _is_missing(result["false_activations_per_hour"], "tracking_unavailable")
    assert result["detections"] == 0


# --------------------------------------------------------------------------- 3. empty and zero-denominator


def test_replaying_zero_traces_raises_rather_than_reporting_a_perfect_run() -> None:
    with pytest.raises(SwitchReplayError, match="zero traces"):
        replay_traces([])
    with pytest.raises(SwitchReplayError):
        aggregate([])


@pytest.mark.parametrize("sweep", [[], (), iter(())])
def test_an_empty_sweep_is_refused_not_reported_as_no_trade_off(sweep: Any) -> None:
    with pytest.raises(SwitchReplayError, match="empty threshold sweep"):
        sweep_thresholds(sweep)
    with pytest.raises(SwitchReplayError):
        replay_traces([_trace("quiet-rest")], sweep=sweep)


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.5, float("nan"), float("inf"), True, "0.3"])
def test_a_sweep_threshold_outside_the_open_unit_interval_is_refused(bad: Any) -> None:
    with pytest.raises(SwitchReplayError):
        sweep_thresholds([0.4, bad])


def test_duplicate_sweep_thresholds_and_duplicate_trace_ids_are_refused() -> None:
    with pytest.raises(SwitchReplayError, match="duplicate"):
        sweep_thresholds([0.3, 0.3])
    twin = _build([("rest", _rest(10))], trace_id="same")
    with pytest.raises(SwitchReplayError, match="unique"):
        replay_traces([twin, twin])


def test_a_trace_with_no_non_deliberate_time_reports_the_rate_as_missing_not_zero() -> None:
    trace = _build([("deliberate", STRONG_HOLD)])
    result = aggregate([replay_trace(trace)])
    assert result["non_deliberate_s"] == 0.0
    assert _is_missing(result["false_activations_per_hour"], "not_measured")
    assert _is_missing(result["false_activations_per_hour_upper_95"], "not_measured")
    assert result["false_activations"] == 0, "the count is real; only the rate is undefined"
    assert result["recall"] == 1.0
    assert result["by_context"] == {}


def test_a_trace_with_no_deliberate_gesture_reports_recall_latency_and_chatter_as_missing() -> None:
    result = aggregate([replay_trace(_build([("rest", _rest(50))]))])
    assert result["intended_activations"] == 0
    for field in ("recall", "activation_latency_ms"):
        assert _is_missing(result[field], "not_measured")
    for value in result["chatter"].values():
        assert _is_missing(value, "not_measured")


def test_every_missing_marker_in_a_full_report_uses_a_schema_reason() -> None:
    report = replay_traces(
        [_trace(t) for t in sorted(EXPECTED_TRACE_IDS)],
        SwitchConfig(confidence_floor=0.5),
        sweep=[0.3, 0.5],
    )
    found: list[Any] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "reason" in node and "value" in node:
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(report)
    assert found, "this configuration must produce missing markers or the test proves nothing"
    assert all(m["value"] is None and m["reason"] in MISSING_REASONS for m in found)
    assert ZERO_DENOMINATOR_RULE in report["zero_denominator_rule"]


def test_the_missing_marker_is_distinguishable_from_a_real_zero() -> None:
    quiet = aggregate([replay_trace(_trace("quiet-rest"))])
    deliberate_only = aggregate([replay_trace(_build([("deliberate", STRONG_HOLD)]))])
    assert quiet["false_activations_per_hour"] == 0.0
    assert isinstance(deliberate_only["false_activations_per_hour"], dict)


@pytest.mark.parametrize(
    ("events", "expected"), [(0, 2.9957), (1, 4.7439), (2, 6.2958), (10, 16.9622)]
)
# upper = chi2.ppf(0.95, 2 (n + 1)) / 2: 9.488 / 2 for n=1, 12.592 / 2 for n=2, 33.924 / 2 for n=10.
def test_the_poisson_upper_bound_matches_the_chi_square_table(events: int, expected: float) -> None:
    assert poisson_upper_95(events) == pytest.approx(expected, abs=1e-3)


def test_the_upper_bound_never_falls_below_the_observed_rate() -> None:
    for events in range(0, 40):
        assert poisson_upper_95(events) > events


# --------------------------------------------------------------------------- 4. matching (mutation targets)


def test_a_start_before_the_labelled_interval_is_a_phantom_not_a_detection() -> None:
    """The gesture label starts at sample 30. A strong burst at 10-14 is during rest: it must not
    be credited as recall for an interval that has not started."""
    early = [0.8] * 5
    trace = _build(
        [("rest", _rest(10)), ("rest", early + _rest(15)), ("deliberate", [0.1] * 12), ("rest", _rest(20))]
    )
    result = aggregate([replay_trace(trace)])
    assert result["false_activations"] == 1
    assert result["detections"] == 0 and result["misses"] == 1 and result["recall"] == 0.0


def test_a_start_inside_the_interval_is_a_detection_and_not_a_phantom() -> None:
    trace = _build([("rest", _rest(20)), ("deliberate", STRONG_HOLD), ("rest", _rest(20))])
    result = aggregate([replay_trace(trace)])
    assert (result["detections"], result["false_activations"]) == (1, 0)


def test_latency_is_measured_from_the_interval_start_in_milliseconds() -> None:
    trace = _build([("rest", _rest(20)), ("deliberate", STRONG_HOLD), ("rest", _rest(20))], rate=20)
    result = replay_trace(trace)
    (interval,) = result.intervals
    assert interval.start == 20 and interval.starts == (23,)  # 0.7 at +1, 0.8 at +2, start on the 3rd >=0.5 ... +3
    assert aggregate([result])["activation_latency_ms"]["median"] == pytest.approx(3 * 1000 / 20)


def test_a_start_just_after_the_interval_needs_the_grace_window_and_the_grace_is_not_exposure() -> None:
    late = [0.1, 0.1, 0.1, 0.1]
    # The gesture label ends before the debounce completes: the switch starts 2 samples after it.
    trace = _build(
        [("rest", _rest(20)), ("deliberate", [0.2, 0.8]), ("rest", [0.8, 0.8] + late + _rest(30))]
    )
    strict = aggregate([replay_trace(trace)])
    assert (strict["detections"], strict["false_activations"]) == (0, 1)

    graced = aggregate([replay_trace(trace, SwitchConfig(match_grace_samples=3))])
    assert (graced["detections"], graced["false_activations"]) == (1, 0)
    # The three graced samples left the exposure, or they would flatter the rate.
    assert graced["non_deliberate_s"] == pytest.approx(strict["non_deliberate_s"] - 0.3)


def test_the_grace_window_stops_at_the_next_deliberate_interval() -> None:
    trace = _build(
        [("deliberate", [0.1] * 4), ("rest", [0.1] * 2), ("deliberate", STRONG_HOLD)]
    )
    result = replay_trace(trace, SwitchConfig(match_grace_samples=500))
    assert result.deliberate_samples == 4 + 2 + len(STRONG_HOLD), "grace covers the gap and no further"
    assert result.intervals[1].detected and not result.intervals[0].detected


def test_a_second_start_in_one_window_is_chatter_not_a_second_detection() -> None:
    twice = [0.8] * 3 + [0.1] * 3 + [0.8] * 3 + [0.1] * 3
    result = aggregate([replay_trace(_build([("rest", _rest(10)), ("deliberate", twice), ("rest", _rest(10))]))])
    assert result["intended_activations"] == 1 and result["detections"] == 1 and result["misses"] == 0
    assert result["chatter"]["extra_starts"] == 1 and result["false_activations"] == 0


def test_a_phantom_is_attributed_to_the_context_it_began_in() -> None:
    burst = [0.8] * 4 + [0.1] * 4
    trace = _build([("rest", _rest(10)), ("speech", burst), ("smile", burst), ("rest", _rest(10))])
    result = aggregate([replay_trace(trace)])
    assert result["false_activations"] == 2
    assert result["by_context"]["speech"]["false_activations"] == 1
    assert result["by_context"]["smile"]["false_activations"] == 1
    assert result["by_context"]["rest"]["false_activations"] == 0


def test_a_phantom_is_one_action_however_long_it_is_held() -> None:
    result = aggregate([replay_trace(_build([("rest", _rest(5)), ("speech", [0.9] * 100), ("rest", _rest(10))]))])
    assert result["false_activations"] == 1


def test_a_hold_still_open_when_the_trace_ends_counts_once() -> None:
    result = aggregate([replay_trace(_build([("rest", _rest(5)), ("deliberate", [0.9] * 20)]))])
    assert (result["detections"], result["false_activations"]) == (1, 0)


def test_the_rate_is_the_count_over_non_deliberate_hours() -> None:
    burst = [0.8] * 4 + [0.1] * 4
    trace = _build([("rest", _rest(100)), ("speech", burst + _rest(92)), ("deliberate", STRONG_HOLD)], rate=10)
    result = aggregate([replay_trace(trace)])
    assert result["non_deliberate_s"] == 20.0
    assert result["false_activations"] == 1
    assert result["false_activations_per_hour"] == pytest.approx(1 / (20 / 3600), abs=1e-3)


def test_pooling_adds_counts_and_seconds_and_never_averages_rates() -> None:
    burst = [0.8] * 4 + [0.1] * 4
    a = _build([("rest", _rest(36000 // 10 * 1)), ("speech", burst)], trace_id="a")  # 1 hour minus a bit
    b = _build([("rest", _rest(10)), ("speech", burst)], trace_id="b")
    pooled = aggregate([replay_trace(a), replay_trace(b)])
    assert pooled["false_activations"] == 2
    expected_seconds = (len(a.scores) + len(b.scores)) / 10
    assert pooled["non_deliberate_s"] == pytest.approx(expected_seconds)
    assert pooled["false_activations_per_hour"] == pytest.approx(2 / (expected_seconds / 3600), abs=1e-2)
    mean_of_rates = (
        aggregate([replay_trace(a)])["false_activations_per_hour"]
        + aggregate([replay_trace(b)])["false_activations_per_hour"]
    ) / 2
    assert abs(pooled["false_activations_per_hour"] - mean_of_rates) > 1.0


# --------------------------------------------------------------------------- 5. the real switch decides


def test_the_default_config_is_the_switchs_own_default() -> None:
    parameters = inspect.signature(GestureSwitch.__init__).parameters
    config = SwitchConfig()
    for name in ("hold_threshold", "release_threshold", "min_hold_frames", "min_release_frames",
                 "confidence_floor", "refractory_frames"):
        assert getattr(config, name) == parameters[name].default, name


def test_every_start_equals_what_the_bare_switch_does_on_the_same_numbers() -> None:
    """An independent drive of `GestureSwitch` with no mapper and no attribution: detections +
    extra starts + phantoms must equal its start count, on every fixture and several configs."""
    for config in (SwitchConfig(), SwitchConfig(hold_threshold=0.3), SwitchConfig(min_hold_frames=1),
                   SwitchConfig(refractory_frames=4), SwitchConfig(confidence_floor=0.5)):
        for trace_id in sorted(EXPECTED_TRACE_IDS):
            trace = _trace(trace_id)
            switch = GestureSwitch(
                config.hold_threshold, config.release_threshold, config.min_hold_frames,
                config.min_release_frames, confidence_floor=config.confidence_floor,
                refractory_frames=config.refractory_frames,
            )
            starts = sum(
                switch.update(s, c) == "start" for s, c in zip(trace.scores, trace.confidences, strict=True)
            )
            result = replay_trace(trace, config)
            attributed = sum(len(i.starts) for i in result.intervals)
            assert attributed + len(result.phantom_samples) == starts, (trace_id, config)


def test_an_unrelated_action_binding_still_counts_its_press() -> None:
    trace = _build([("rest", _rest(10)), ("deliberate", STRONG_HOLD), ("rest", _rest(10))])
    assert aggregate([replay_trace(trace, SwitchConfig(action="select"))])["detections"] == 1
    with pytest.raises(SwitchReplayError, match="action"):
        replay_trace(trace, SwitchConfig(action="launch_missiles"))


@pytest.mark.parametrize(
    "field", ["hold_threshold", "release_threshold", "confidence_floor"]
)
@pytest.mark.parametrize("bad", [-0.1, 1.1, float("nan"), "0.5", True])
def test_a_configuration_outside_its_range_is_refused_not_clamped(field: str, bad: Any) -> None:
    with pytest.raises(SwitchReplayError):
        replay_trace(_build([("rest", _rest(5))]), SwitchConfig(**{field: bad}))


@pytest.mark.parametrize("field", ["min_hold_frames", "min_release_frames", "refractory_frames", "match_grace_samples"])
def test_a_frame_count_that_is_not_a_count_is_refused(field: str) -> None:
    for bad in (-1, 1.5, True, "3"):
        with pytest.raises(SwitchReplayError):
            replay_trace(_build([("rest", _rest(5))]), SwitchConfig(**{field: bad}))


def test_a_release_threshold_the_switch_repairs_is_reported_as_repaired() -> None:
    result = aggregate([replay_trace(_build([("rest", _rest(5))]), SwitchConfig(hold_threshold=0.3))])
    assert result["effective_thresholds"] == {"hold": 0.3, "release": 0.21, "release_repaired": True}
    kept = aggregate([replay_trace(_build([("rest", _rest(5))]), SwitchConfig(hold_threshold=0.6))])
    assert kept["effective_thresholds"] == {"hold": 0.6, "release": 0.35, "release_repaired": False}


# --------------------------------------------------------------------------- 6. determinism


def test_the_report_is_byte_identical_across_runs_and_trace_order() -> None:
    traces = [_trace(t) for t in sorted(EXPECTED_TRACE_IDS)]
    first = script.render(replay_traces(traces, sweep=[0.3, 0.4]))
    second = script.render(replay_traces(list(reversed(traces)), sweep=[0.4, 0.3]))
    assert first == second


# --------------------------------------------------------------------------- 7. the validator


def _valid() -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "trace_id": "ok",
        "study_mode": "synthetic",
        "gesture": "jaw_open",
        "sample_rate_hz": 10,
        "segments": [{"context": "rest", "samples": 3}],
        "scores": [0.1, 0.2, 0.3],
    }


def test_a_valid_minimal_trace_is_accepted() -> None:
    assert validate_trace(_valid()) == []
    trace = check_trace(_valid())
    assert trace.confidences == (None, None, None) and trace.duration_s == pytest.approx(0.3)


def test_an_empty_trace_is_a_rule_violation_from_every_direction() -> None:
    for patch in ({"scores": []}, {"segments": []}, {"scores": [], "segments": []}):
        doc = {**_valid(), **patch}
        problems = validate_trace(doc)
        assert problems, patch
        with pytest.raises(SwitchTraceError):
            check_trace(doc)
    assert validate_trace({}) and validate_trace([]) and validate_trace(None)


@pytest.mark.parametrize(
    ("patch", "fragment"),
    [
        ({"scores": [0.1, 1.5, 0.3]}, "scores"),
        ({"scores": [0.1, -0.1, 0.3]}, "scores"),
        ({"scores": [0.1, float("inf"), 0.3]}, "scores"),
        ({"scores": [0.1, True, 0.3]}, "scores"),
        ({"scores": [0.1, "0.2", 0.3]}, "scores"),
        ({"scores": "abc"}, "scores"),
        ({"confidences": [0.5, 0.5]}, "confidences"),
        ({"confidences": [0.5, 2.0, 0.5]}, "confidences"),
        ({"segments": [{"context": "rest", "samples": 2}]}, "labels cover 2"),
        ({"segments": [{"context": "sleeping", "samples": 3}]}, "context"),
        ({"segments": [{"context": "rest", "samples": 0}, {"context": "rest", "samples": 3}]}, "samples"),
        ({"segments": [{"context": "rest", "samples": True}]}, "samples"),
        ({"gesture": "eyebrow_wiggle"}, "gesture"),
        ({"sample_rate_hz": 0}, "sample_rate_hz"),
        ({"sample_rate_hz": -5}, "sample_rate_hz"),
        ({"sample_rate_hz": float("nan")}, "sample_rate_hz"),
        ({"sample_rate_hz": True}, "sample_rate_hz"),
        ({"trace_id": "Has Spaces"}, "trace_id"),
        ({"trace_id": ""}, "trace_id"),
        ({"study_mode": "research"}, "study_mode"),
        ({"study_mode": "live"}, "study_mode"),
        ({"baseline": {"level": 1.5}}, "baseline"),
        ({"baseline": {"level": 0.2, "gesture": "smile"}}, "baseline.gesture"),
        ({"baseline": 0.4}, "baseline"),
        ({"description": "x" * 1000}, "description"),
        ({"schema_version": "2.0"}, "major version"),
        ({"schema_version": "banana"}, "schema_version"),
    ],
)
def test_a_malformed_trace_becomes_a_problem_and_never_a_traceback(patch: dict[str, Any], fragment: str) -> None:
    problems = validate_trace({**_valid(), **patch})
    assert problems and any(fragment in p for p in problems), problems


def test_two_adjacent_deliberate_segments_are_refused() -> None:
    doc = {**_valid(), "segments": [{"context": "deliberate", "samples": 1}, {"context": "deliberate", "samples": 2}]}
    assert any("adjacent" in p for p in validate_trace(doc))


def test_a_missing_required_field_is_named() -> None:
    for name in ("trace_id", "study_mode", "gesture", "sample_rate_hz", "segments", "scores"):
        doc = _valid()
        del doc[name]
        assert any(p.startswith(f"{name}:") for p in validate_trace(doc)), name


def test_community_qa_is_accepted_and_research_is_not() -> None:
    assert validate_trace({**_valid(), "study_mode": "community_qa"}) == []
    assert any("ADR-v2-150" in p for p in validate_trace({**_valid(), "study_mode": "research"}))


def test_nan_in_a_document_is_read_as_a_missing_reading() -> None:
    trace = check_trace({**_valid(), "scores": [0.1, float("nan"), 0.3], "confidences": [0.5, 0.5, float("nan")]})
    assert trace.scores[1] is None and trace.confidences[2] is None


@pytest.mark.parametrize(
    "key",
    ["frames", "frame_bytes", "landmarks", "face_mesh", "image", "pixels", "video_path", "audio", "transcript",
     "participant_id", "identity", "subject", "username", "email", "hostname", "blendshapes",
     "face_embedding", "voiceprint", "screenshot", "window_title"],
)
def test_a_trace_that_invents_a_place_for_a_frame_or_a_person_is_refused(key: str) -> None:
    assert validate_trace({**_valid(), key: "x"}), key
    # ... at any depth, inside a segment, inside the baseline, inside a list.
    assert validate_trace({**_valid(), "segments": [{"context": "rest", "samples": 3, key: 1}]})
    assert validate_trace({**_valid(), "baseline": {"level": 0.2, key: 1}})
    assert validate_trace({**_valid(), "extra": [{"deep": {key: 1}}]})


def test_the_forbidden_lists_are_the_shared_one_plus_the_trace_specific_one() -> None:
    assert "landmark" in FORBIDDEN_FIELD_TOKENS, "the shared list is the one in use"
    assert {"frame", "image", "mesh", "participant", "identity"} <= set(EXTRA_FORBIDDEN_TOKENS)


def test_the_trace_vocabulary_itself_uses_no_forbidden_word() -> None:
    for name in ("schema_version", "trace_id", "study_mode", "gesture", "sample_rate_hz", "segments",
                 "scores", "confidences", "baseline", "description", "context", "samples", "level"):
        assert not any(tok in name for tok in (*FORBIDDEN_FIELD_TOKENS, *EXTRA_FORBIDDEN_TOKENS)), name


def test_an_unknown_benign_field_is_ignored_and_never_reaches_the_report() -> None:
    doc = {**_valid(), "future_extension": "secret-marker-7731"}
    trace = check_trace(doc)
    report = json.dumps(replay_traces([trace], sweep=[0.3]))
    assert "secret-marker-7731" not in report and "future_extension" not in report


def test_the_description_is_never_copied_into_a_report() -> None:
    doc = {**_valid(), "description": "describing-words-unique-4412"}
    report = json.dumps(replay_traces([check_trace(doc)]))
    assert "describing-words-unique-4412" not in report


def test_the_whole_report_passes_the_forbidden_field_scan() -> None:
    report = replay_traces([_trace(t) for t in sorted(EXPECTED_TRACE_IDS)], sweep=[0.3, 0.5])
    assert forbidden_field_problems(report) == []
    text = json.dumps(report).lower()
    for token in EXTRA_FORBIDDEN_TOKENS:
        assert f'"{token}' not in text, token


def test_the_report_has_no_per_sample_data() -> None:
    """Counts, rates and thresholds only: no list longer than the sweep or trace table appears."""
    report = replay_traces([_trace("deliberate-hold")], sweep=[0.3, 0.5])
    scalars = {"scores", "samples_list", "readings"}
    assert not scalars & set(report) and "scores" not in json.dumps(report)


def test_every_context_is_a_member_of_the_closed_list() -> None:
    assert set(CONTEXTS) == {
        "rest", "speech", "head_movement", "smile", "blink", "yawn", "look_down", "deliberate", "other",
    }


# --------------------------------------------------------------------------- 8. the committed report and CLI


def _golden() -> Any:
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def _generated() -> Any:
    traces, problems = script.collect_traces(_fixture_files())
    assert problems == []
    return replay_traces(traces, script.SwitchConfig(), sweep=list(script.DEFAULT_SWEEP))


def test_the_committed_report_matches_its_generator() -> None:
    assert REPORT_PATH.read_text(encoding="utf-8") == script.render(_generated())


def test_the_committed_report_accounts_for_every_fixture_trace() -> None:
    golden = _golden()
    assert {t["trace_id"] for t in golden["traces"]} == EXPECTED_TRACE_IDS
    assert golden["total_traces"] == len(EXPECTED_TRACE_IDS)
    assert len(golden["sweep"]) == len(script.DEFAULT_SWEEP)
    assert golden["no_threshold_notice"] == NO_THRESHOLD_NOTICE
    assert golden["evidence_class"] == "synthetic"


def test_dropping_a_fixture_is_caught_by_count_and_by_id(tmp_path: Path) -> None:
    for path in _fixture_files():
        if path.stem != "quiet-rest":
            (tmp_path / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    traces, problems = script.collect_traces(sorted(tmp_path.glob("*.json")))
    assert problems == []
    smaller = script.render(replay_traces(traces, script.SwitchConfig(), sweep=list(script.DEFAULT_SWEEP)))
    # The sync check does catch it (the committed report still has the dropped trace) ...
    assert smaller != REPORT_PATH.read_text(encoding="utf-8")
    # ... and the completeness check, which does not read the generator at all, catches it by id and count.
    assert {t.trace_id for t in traces} != EXPECTED_TRACE_IDS
    assert len(traces) != len(EXPECTED_TRACE_IDS)


def test_the_cli_check_passes_on_the_committed_report() -> None:
    assert script.main(["--check"]) == 0


def test_the_cli_check_fails_when_the_report_drifted(tmp_path: Path) -> None:
    stale = tmp_path / "stale.json"
    stale.write_text(REPORT_PATH.read_text(encoding="utf-8").replace('"recall": 1.0', '"recall": 0.5', 1), encoding="utf-8")
    assert script.main(["--check", str(stale)]) == 1


def test_the_cli_check_exits_two_when_the_report_is_absent(tmp_path: Path) -> None:
    assert script.main(["--check", str(tmp_path / "nope.json")]) == 2


def test_the_cli_prints_json_and_write_round_trips(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert script.main([]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed) == _golden()
    out = tmp_path / "r.json"
    assert script.main(["--write", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == printed


def _write(tmp_path: Path, name: str, doc: Any) -> Path:
    path = tmp_path / name
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return path


def test_the_cli_exits_one_when_it_finds_no_trace_files_at_all(tmp_path: Path) -> None:
    assert script.main(["--trace-dir", str(tmp_path)]) == 1


@pytest.mark.parametrize("payload", ["", "{not json", "[1, 2"])
def test_the_cli_exits_two_on_input_it_cannot_parse(tmp_path: Path, payload: str) -> None:
    assert script.main(["--trace", str(_write(tmp_path, "t.json", payload))]) == 2


def test_the_cli_exits_two_when_the_trace_file_is_absent(tmp_path: Path) -> None:
    assert script.main(["--trace", str(tmp_path / "gone.json")]) == 2


def test_the_cli_exits_one_on_an_empty_trace_and_on_a_rule_violation(tmp_path: Path) -> None:
    empty = {**_valid(), "scores": [], "segments": []}
    assert script.main(["--trace", str(_write(tmp_path, "empty.json", empty))]) == 1
    leaky = {**_valid(), "landmarks": [[0.1, 0.2]]}
    assert script.main(["--trace", str(_write(tmp_path, "leaky.json", leaky))]) == 1


def test_the_cli_exits_zero_on_a_valid_trace(tmp_path: Path) -> None:
    assert script.main(["--trace", str(_write(tmp_path, "ok.json", _valid())), "--no-sweep"]) == 0


@pytest.mark.parametrize("sweep", ["", ",", "0.3,,0.4", "abc", "0.3,0.3", "0,0.4", "1.5"])
def test_the_cli_refuses_an_empty_or_malformed_sweep(tmp_path: Path, sweep: str) -> None:
    ok = _write(tmp_path, "ok.json", _valid())
    assert script.main(["--trace", str(ok), "--sweep", sweep]) == 1


@pytest.mark.parametrize("flag", [["--hold-threshold", "2"], ["--confidence-floor", "-1"], ["--min-hold-frames", "0"]])
def test_the_cli_refuses_an_out_of_range_configuration(tmp_path: Path, flag: list[str]) -> None:
    ok = _write(tmp_path, "ok.json", _valid())
    assert script.main(["--trace", str(ok), "--no-sweep", *flag]) == 1


def test_the_cli_applies_the_trace_baseline_only_on_request(capsys: pytest.CaptureFixture[str]) -> None:
    path = str(TRACE_DIR / "baseline-shifted-rest.json")
    assert script.main(["--trace", path, "--no-sweep"]) == 0
    plain = json.loads(capsys.readouterr().out)["pooled_by_gesture"]["jaw_open"]
    assert script.main(["--trace", path, "--no-sweep", "--use-trace-baseline"]) == 0
    calibrated = json.loads(capsys.readouterr().out)["pooled_by_gesture"]["jaw_open"]
    assert plain["detections"] == 0 and calibrated["detections"] == 3


# --------------------------------------------------------------------------- 9. purity and layering

FORBIDDEN_NAMES = {
    "time", "monotonic", "perf_counter", "random", "urlopen", "requests", "socket", "subprocess", "open",
    "datetime", "environ", "getenv",
}


def test_the_purity_scan_reads_both_modules() -> None:
    for path in MODULES:
        assert path.exists() and path.read_text(encoding="utf-8").strip()
    assert len(MODULES) == 2


def _names(tree: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }


def test_neither_module_names_a_clock_a_file_or_a_network_call() -> None:
    for path in MODULES:
        names = _names(ast.parse(path.read_text(encoding="utf-8")))
        assert not (names & FORBIDDEN_NAMES), (path.name, sorted(names & FORBIDDEN_NAMES))


def test_the_purity_scan_would_notice_a_clock() -> None:
    """Green on any module that does not call one, including a module that does nothing. Prove it fires."""
    names = _names(ast.parse("import time\ndef f():\n    return time.monotonic()\n"))
    assert names & FORBIDDEN_NAMES == {"time", "monotonic"}


def test_the_harness_imports_only_stdlib_and_this_package() -> None:
    allowed = {"bisect", "collections", "dataclasses", "math", "re", "statistics", "typing", "yazses", "__future__"}
    for path in MODULES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
        assert roots <= allowed, (path.name, sorted(roots - allowed))


def test_the_daemon_facing_packages_do_not_import_the_harness() -> None:
    """`facegesture` is on the runtime path; the harness reaches into it, never the reverse."""
    for package in ("facegesture", "core", "platform"):
        sources = sorted((ROOT / "src" / "yazses" / package).rglob("*.py"))
        assert sources, f"no sources found for {package}: this guard would pass on an empty set"
        for path in sources:
            text = path.read_text(encoding="utf-8")
            assert "switch_replay" not in text and "switch_trace" not in text, path


def test_the_harness_never_compares_a_score_to_a_threshold_itself() -> None:
    """`GestureSwitch` is the only thing that decides whether a gesture is held."""
    tree = ast.parse(MODULES[1].read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            seen = {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}
            assert not seen & {"hold_threshold", "release_threshold", "scores"}, ast.dump(node)
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert {"update", "handle", "reset"} <= called


def test_poisson_helper_is_total_over_a_large_count() -> None:
    value = poisson_upper_95(5000)
    assert math.isfinite(value) and 5000 < value < 5000 + 4 * math.sqrt(5000)
