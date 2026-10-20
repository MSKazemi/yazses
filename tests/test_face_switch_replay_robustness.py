"""What the face-switch false-activation harness must still say when the input or the world is awkward.

``tests/test_face_switch_replay.py`` pins the counting rules. This file pins the five ways such a
harness reads as success while being wrong (EYE-BENCH-001, #409):

1. **A trace in a format it does not understand is read anyway.** An unknown major version, a
   version string that crashes the parser, an id with a trailing newline, a timestamp column that is
   silently ignored (so a gap or time running backwards is replayed as even sampling), a sample rate
   that makes the duration zero and the per-hour rate infinite.
2. **A rate travels alone.** "0.0 an hour" from twenty seconds of speech is not a measurement. Every
   per-hour figure -- the per-context ones included -- must carry both exact limits and say when it
   was scaled up from under an hour.
3. **The gate is blind to the thing it guards.** A detector made over-sensitive on purpose (a
   mutant) must turn the replay red and the committed-report check red.
4. **The report differs by machine.** Same trace, same bytes: under any hash seed, with LF endings
   and no byte-order mark, written by the script's own writer.
5. **Breakdowns that quietly merge.** Per gesture and per threshold are separate rows.

Every trace here is invented. Nothing below says what a threshold should be.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from yazses.eyeeval import switch_replay
from yazses.eyeeval.switch_replay import (
    SwitchConfig,
    aggregate,
    poisson_lower_95,
    poisson_upper_95,
    replay_trace,
    replay_traces,
)
from yazses.eyeeval.switch_trace import (
    MAX_SAMPLE_RATE_HZ,
    MIN_SAMPLE_RATE_HZ,
    check_trace,
    validate_trace,
)
from yazses.facegesture.detector import GestureSwitch

ROOT = Path(__file__).resolve().parent.parent
TRACE_DIR = ROOT / "tests" / "fixtures" / "face_switch_traces"
REPORT_PATH = ROOT / "tests" / "fixtures" / "face_switch_replay_report.json"
SCRIPT = ROOT / "scripts" / "replay_face_switch_trace.py"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("replay_face_switch_trace_robust", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()

HOLD = [0.3, 0.7, 0.8, 0.85, 0.85, 0.85, 0.8, 0.5, 0.2, 0.05]


def _doc(**patch: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "schema_version": "1.0",
        "trace_id": "ok",
        "study_mode": "synthetic",
        "gesture": "jaw_open",
        "sample_rate_hz": 10,
        "segments": [{"context": "rest", "samples": 5}],
        "scores": [0.0] * 5,
    }
    doc.update(patch)
    return doc


def _build(
    segments: list[tuple[str, list[float | None]]],
    *,
    trace_id: str = "built",
    rate: float = 10,
    gesture: str = "jaw_open",
) -> Any:
    return check_trace(
        {
            "schema_version": "1.0",
            "trace_id": trace_id,
            "study_mode": "synthetic",
            "gesture": gesture,
            "sample_rate_hz": rate,
            "segments": [{"context": c, "samples": len(s)} for c, s in segments],
            "scores": [v for _, s in segments for v in s],
        }
    )


def _walk(node: Any):
    """Every dict in a document, depth first."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


# --------------------------------------------------------------------------- 1. format versioning


@pytest.mark.parametrize("version", ["2.0", "0.9", "10.1", "99.0", "3.7"])
def test_an_unknown_major_version_is_refused_not_half_read(version: str) -> None:
    problems = validate_trace(_doc(schema_version=version))
    assert len(problems) == 1 and "major version" in problems[0]


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.7", "1.10", "1.999"])
def test_a_later_minor_of_the_same_major_is_accepted_and_its_new_fields_are_ignored(version: str) -> None:
    doc = _doc(schema_version=version, a_field_added_in_a_later_minor={"x": 1})
    assert validate_trace(doc) == []
    report = json.dumps(replay_traces([check_trace(doc)]))
    assert "a_field_added_in_a_later_minor" not in report


@pytest.mark.parametrize(
    "version",
    [
        pytest.param("1", id="no-minor"),
        pytest.param("1.0.0", id="three-parts"),
        pytest.param("1.", id="empty-minor"),
        pytest.param(".1", id="empty-major"),
        pytest.param("v1.0", id="v-prefix"),
        pytest.param("1.²", id="superscript-two"),
        pytest.param("1.٣", id="arabic-indic-digit"),
        pytest.param("１.０", id="fullwidth-digits"),
        pytest.param("1.0\n", id="trailing-newline"),
        pytest.param("1." + "9" * 5000, id="five-thousand-digits"),
        pytest.param(1.0, id="a-float"),
        pytest.param(None, id="null"),
        pytest.param(["1", "0"], id="a-list"),
    ],
)
def test_a_malformed_version_is_a_problem_never_a_traceback(version: Any) -> None:
    """``"1.\\u00b2".isdigit()`` is true and ``int("\\u00b2")`` raises: the old reader crashed on it."""
    problems = validate_trace(_doc(schema_version=version))
    assert len(problems) == 1 and "schema_version" in problems[0]


def test_the_reader_and_the_fixtures_agree_on_the_version() -> None:
    from yazses.eyeeval.switch_trace import SUPPORTED_MAJOR, TRACE_SCHEMA_VERSION

    assert TRACE_SCHEMA_VERSION.split(".")[0] == str(SUPPORTED_MAJOR)
    for path in sorted(TRACE_DIR.glob("*.json")):
        assert json.loads(path.read_text(encoding="utf-8"))["schema_version"] == TRACE_SCHEMA_VERSION


@pytest.mark.parametrize("trace_id", ["a\n", "a\n\n", "A", "-a", "a b", "", "a" * 81])
def test_a_trace_id_that_is_not_a_slug_is_refused_including_a_trailing_newline(trace_id: str) -> None:
    """``re.match(r"...$")`` lets "a\\n" through, and the id is copied into the report."""
    problems = validate_trace(_doc(trace_id=trace_id))
    assert any(p.startswith("trace_id") for p in problems), problems


# --------------------------------------------------------------------------- 1b. time


@pytest.mark.parametrize(
    "key",
    [
        pytest.param("timestamps", id="timestamps"),
        pytest.param("timestamps_ms", id="timestamps-ms"),
        pytest.param("Timestamp", id="capitalised"),
        pytest.param("t", id="single-letter"),
        pytest.param("time_s", id="time-s"),
        pytest.param("dt", id="dt"),
    ],
)
def test_a_trace_that_brings_its_own_clock_is_refused_because_time_is_the_sample_index(key: str) -> None:
    """Silently ignoring a backwards or gapped clock would replay it as evenly sampled."""
    backwards = [4.0, 3.0, 2.0, 1.0, 0.0]
    problems = validate_trace(_doc(**{key: backwards}))
    assert len(problems) == 1 and key in problems[0] and "uniform" in problems[0], problems


def test_a_dropped_frame_is_a_null_reading_that_still_counts_as_time() -> None:
    """The supported way to say "no frames here": the gap keeps its seconds and loses its trust."""
    steady = _build([("rest", [0.04] * 20)])
    gapped = _build([("rest", [0.04] * 5 + [None] * 10 + [0.04] * 5)])
    a, b = aggregate([replay_trace(steady)]), aggregate([replay_trace(gapped)])
    assert a["duration_s"] == b["duration_s"] == 2.0
    assert a["non_deliberate_usable_fraction"] == 1.0
    assert b["non_deliberate_usable_fraction"] == pytest.approx(0.5)
    assert b["sample_status"]["no_reading"] == 10


def test_a_nan_is_a_gap_and_infinity_is_not_a_number() -> None:
    assert validate_trace(_doc(scores=[0.0, float("nan"), 0.0, 0.0, 0.0])) == []
    problems = validate_trace(_doc(scores=[0.0, float("inf"), 0.0, 0.0, 0.0]))
    assert len(problems) == 1 and "scores" in problems[0]
    assert validate_trace(_doc(scores=[0.0, -0.01, 0.0, 0.0, 0.0]))
    assert validate_trace(_doc(scores=[0.0, 1.01, 0.0, 0.0, 0.0]))


@pytest.mark.parametrize("rate", [1e308, 1e-300, 1e6, 0.05, -1.0, 0.0, float("inf")])
def test_a_sample_rate_that_makes_the_duration_meaningless_is_refused(rate: float) -> None:
    problems = validate_trace(_doc(sample_rate_hz=rate))
    assert len(problems) == 1 and "sample_rate_hz" in problems[0]


@pytest.mark.parametrize("rate", [MIN_SAMPLE_RATE_HZ, 1, 15, 30, 120, MAX_SAMPLE_RATE_HZ])
def test_the_extremes_of_the_allowed_rate_still_give_a_finite_json_report(rate: float) -> None:
    phantom = [0.9] * 10 + [0.0] * 10
    trace = _build([("rest", phantom)], rate=rate)
    report = replay_traces([trace])
    text = json.dumps(report, allow_nan=False)  # raises on NaN / Infinity
    assert "Infinity" not in text and "NaN" not in text


# --------------------------------------------------------------------------- 2. rates carry their denominator


def _rates(document: Any) -> list[dict[str, Any]]:
    # The report's own `metric_definitions` block names the key too; a rate is a number or a marker.
    return [
        d for d in _walk(document)
        if isinstance(d.get("false_activations_per_hour"), (int, float, dict))
    ]


def test_every_per_hour_figure_in_the_committed_report_carries_both_limits_and_the_extrapolation_flag() -> None:
    document = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    rates = _rates(document)
    # Not vacuous: 8 traces, each with per-context rows, a pooled row per gesture and 8 sweep rows.
    assert len(rates) > 40, len(rates)
    for block in rates:
        if not isinstance(block["false_activations_per_hour"], dict):  # a missing marker is its own answer
            assert block["false_activations_per_hour_lower_95"] <= block["false_activations_per_hour"]
            assert block["false_activations_per_hour"] <= block["false_activations_per_hour_upper_95"]
            assert isinstance(block["per_hour_extrapolated"], bool)
        else:
            for name in ("false_activations_per_hour_lower_95", "false_activations_per_hour_upper_95",
                         "per_hour_extrapolated"):
                assert block[name] == block["false_activations_per_hour"], (name, block)


def test_a_per_context_rate_from_twenty_seconds_is_not_a_bare_zero() -> None:
    result = aggregate([replay_trace(_build([("speech", [0.05] * 200)]))])
    speech = result["by_context"]["speech"]
    assert speech["duration_s"] == 20.0 and speech["false_activations"] == 0
    assert speech["false_activations_per_hour"] == 0.0
    assert speech["false_activations_per_hour_lower_95"] == 0.0
    assert speech["false_activations_per_hour_upper_95"] == pytest.approx(2.9957 / (20 / 3600), rel=1e-3)
    assert speech["per_hour_extrapolated"] is True


def test_an_hour_or_more_of_exposure_is_not_flagged_as_extrapolated() -> None:
    long_rest = _build([("rest", [0.04] * 36_000)])  # exactly one hour at 10 Hz
    short_rest = _build([("rest", [0.04] * 35_999)])
    assert aggregate([replay_trace(long_rest)])["per_hour_extrapolated"] is False
    assert aggregate([replay_trace(short_rest)])["per_hour_extrapolated"] is True


def test_the_rate_is_missing_not_zero_when_no_exposure_was_trusted() -> None:
    result = aggregate([replay_trace(_build([("rest", [None] * 30)]))])
    for name in ("false_activations_per_hour", "false_activations_per_hour_lower_95",
                 "false_activations_per_hour_upper_95", "per_hour_extrapolated"):
        assert result[name] == {"value": None, "reason": "tracking_unavailable"}, name


@pytest.mark.parametrize(
    ("events", "expected"),
    # lower = chi2.ppf(0.05, 2 n) / 2: 0.1026 / 2, 0.7107 / 2, 3.9403 / 2, 10.851 / 2.
    [(0, 0.0), (1, 0.05129), (2, 0.35536), (5, 1.97015), (10, 5.42541)],
)
def test_the_poisson_lower_limit_matches_the_chi_square_table(events: int, expected: float) -> None:
    assert poisson_lower_95(events) == pytest.approx(expected, abs=1e-4)


def test_the_two_limits_always_bracket_the_count_and_never_cross() -> None:
    for events in range(0, 80):
        lower, upper = poisson_lower_95(events), poisson_upper_95(events)
        assert 0.0 <= lower <= events <= upper, events
        assert lower < upper


def test_a_negative_count_is_refused_by_both_limits() -> None:
    for fn in (poisson_lower_95, poisson_upper_95):
        with pytest.raises(ValueError):
            fn(-1)


def test_the_limit_narrows_as_the_exposure_grows_and_does_not_before() -> None:
    """The point of publishing a limit: one phantom in a minute and one in a day are not the same claim."""
    minute = aggregate([replay_trace(_build([("rest", [0.9] * 5 + [0.0] * 595)]))])
    assert minute["false_activations"] == 1
    day = aggregate([replay_trace(_build([("rest", [0.9] * 5 + [0.0] * 595)], rate=0.1))])
    assert day["false_activations"] == 1
    width_minute = minute["false_activations_per_hour_upper_95"] - minute["false_activations_per_hour_lower_95"]
    width_long = day["false_activations_per_hour_upper_95"] - day["false_activations_per_hour_lower_95"]
    assert width_long < width_minute / 100


# --------------------------------------------------------------------------- 3. an over-sensitive detector is caught


def _speech_trace() -> Any:
    return check_trace(json.loads((TRACE_DIR / "speech-and-everyday.json").read_text(encoding="utf-8")))


class _OverSensitive(GestureSwitch):
    """The shipped switch with its hold threshold collapsed and its debounce removed."""

    def __init__(self, hold: float, release: float, min_hold: int, min_release: int, **kw: Any) -> None:
        super().__init__(0.12, 0.05, 1, min_release, **kw)


def test_a_deliberately_over_sensitive_detector_produces_phantoms_the_real_one_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace = _speech_trace()
    honest = aggregate([replay_trace(trace)])
    assert honest["false_activations"] == 0
    monkeypatch.setattr(switch_replay, "GestureSwitch", _OverSensitive)
    mutant = aggregate([replay_trace(trace)])
    assert mutant["false_activations"] > 0
    assert mutant["false_activations_per_hour"] > 0
    assert mutant["false_activations_per_hour_lower_95"] > 0, "enough phantoms that even the lower limit leaves zero"
    assert mutant["by_context"]["speech"]["false_activations"] > 0


def test_the_committed_report_check_goes_red_under_the_over_sensitive_detector(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert script.main(["--check"]) == 0
    monkeypatch.setattr(switch_replay, "GestureSwitch", _OverSensitive)
    assert script.main(["--check"]) == 1
    assert "out of date" in capsys.readouterr().err


# --------------------------------------------------------------------------- 4. breakdowns stay separate


def test_per_gesture_rows_are_separate_and_each_has_its_own_denominator() -> None:
    jaw = _build([("rest", [0.9] * 5 + [0.0] * 95)], trace_id="jaw", gesture="jaw_open")
    smile = _build([("rest", [0.04] * 300)], trace_id="smile", gesture="smile")
    report = replay_traces([jaw, smile])
    assert list(report["pooled_by_gesture"]) == ["jaw_open", "smile"]
    assert report["pooled_by_gesture"]["jaw_open"]["false_activations"] == 1
    assert report["pooled_by_gesture"]["smile"]["false_activations"] == 0
    assert report["pooled_by_gesture"]["jaw_open"]["non_deliberate_s"] == 10.0
    assert report["pooled_by_gesture"]["smile"]["non_deliberate_s"] == 30.0


def test_each_threshold_row_of_a_sweep_recounts_the_same_trace_and_keeps_its_limits() -> None:
    # Three bursts of rising strength inside one rest stretch: 0.25, 0.40 and 0.55.
    def burst(level: float) -> list[float | None]:
        return [level] * 6 + [0.0] * 6

    trace = _build([("rest", burst(0.25) + burst(0.40) + burst(0.55))])
    report = replay_traces([trace], sweep=[0.2, 0.35, 0.5, 0.6])
    counts = {row["hold_threshold"]: row["by_gesture"]["jaw_open"]["false_activations"] for row in report["sweep"]}
    assert counts == {0.2: 3, 0.35: 2, 0.5: 1, 0.6: 0}
    for row in report["sweep"]:
        block = row["by_gesture"]["jaw_open"]
        assert block["false_activations_per_hour_upper_95"] > block["false_activations_per_hour"] or block[
            "false_activations"
        ] == 0
        assert block["per_hour_extrapolated"] is True
        assert block["duration_s"] == pytest.approx(3.6)


# --------------------------------------------------------------------------- 5. the bytes


def _run_script(seed: str, *extra: str) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *extra], cwd=ROOT, env=env, capture_output=True, check=False, timeout=120,
    )


@pytest.mark.parametrize("seed", ["0", "1", "424242"])
def test_a_fresh_process_prints_the_committed_report_byte_for_byte_under_any_hash_seed(seed: str) -> None:
    done = _run_script(seed)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")[-500:]
    assert done.stdout == REPORT_PATH.read_bytes()
    assert b"\r" not in done.stdout


def test_the_script_writes_lf_utf8_without_a_byte_order_mark(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    assert script.main(["--write", str(out)]) == 0
    raw = out.read_bytes()
    assert raw == REPORT_PATH.read_bytes()
    assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"}\n")


def test_a_report_that_was_checked_out_with_crlf_is_a_drift_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    crlf = tmp_path / "crlf.json"
    crlf.write_bytes(REPORT_PATH.read_bytes().replace(b"\n", b"\r\n"))
    assert script.main(["--check", str(crlf)]) == 1
    assert "line endings" in capsys.readouterr().err


def test_the_trace_fixtures_and_the_report_are_lf_ascii_and_end_in_one_newline() -> None:
    files = sorted(TRACE_DIR.glob("*.json")) + [REPORT_PATH]
    assert len(files) == 9
    for path in files:
        raw = path.read_bytes()
        assert b"\r" not in raw, path.name
        raw.decode("ascii")
        assert raw.endswith(b"}\n") and not raw.endswith(b"\n\n"), path.name


def test_the_gitattributes_pin_covers_every_file_the_determinism_checks_hash() -> None:
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    pinned = {line.split()[0] for line in lines if "eol=lf" in line}
    assert "tests/fixtures/face_switch_traces/**" in pinned
    assert "tests/fixtures/face_switch_replay_report.json" in pinned


def test_no_number_in_the_report_is_not_finite() -> None:
    document = json.loads(REPORT_PATH.read_text(encoding="utf-8"), parse_constant=lambda name: pytest.fail(name))
    for block in _walk(document):
        for value in block.values():
            if isinstance(value, float):
                assert math.isfinite(value)


def test_the_default_config_replays_the_shipped_behaviour_the_report_describes() -> None:
    assert SwitchConfig().to_document()["hold_threshold"] == 0.5
    assert json.loads(REPORT_PATH.read_text(encoding="utf-8"))["config"] == SwitchConfig().to_document()
