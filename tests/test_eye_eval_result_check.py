"""The result schema, applied to a FILE -- and to every document a producer can emit.

Issue #421 (EYE-EVAL-001). `tests/test_eye_eval_schema.py` proves the validator on parsed
dicts. This file covers what a dict-level test cannot see, each one a shape this repository
has shipped before:

* **A check that cannot parse its input reports compliance.** A result file that is
  missing, a directory, empty, not UTF-8, not JSON, repeats a key, or carries `NaN` must be
  a reported problem and a non-zero exit, never an empty document that passes.
* **A guard that iterates is green on an empty collection.** `scripts/check_eye_eval_result.py`
  with no file named is a usage error (exit 2), not a clean pass.
* **A hand-written set is the defect.** The list of producers is derived from `src/` by
  scanning for the envelope constructor, and the committed example fixtures are found by
  walking `tests/fixtures`, so a new producer or a new fixture cannot be forgotten.
* **A missing metric is never zero** extends to non-finite numbers, a value that also
  carries a reason, an empty metric group and a `null` inside a list.
* **Accept-with-note** for a later minor of the supported major: valid, but not silent.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
from pathlib import Path
from typing import Any

import pytest

from yazses.eyeeval import (
    MISSING_REASONS,
    SCHEMA_VERSION,
    STUDY_MODES,
    TASK_IDS,
    Provenance,
    build_result,
    compatibility_note,
    dump_result,
    generate_task,
    synthetic_records,
    validate_result,
    validate_result_file,
    validate_result_text,
)
from yazses.eyeeval.gaze_field import (
    CalibrationFacts,
    MeasurementSession,
    build_report,
    report_problems,
)

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "check_eye_eval_result.py"
FIXTURES = ROOT / "tests" / "fixtures"
GOOD = FIXTURES / "eye_eval" / "gaze_community_qa.json"

_PROV = Provenance(
    yazses_version="9.9.9", git_commit="0123456789ab", python_version="3.13.0",
    os_name="ExampleOS", os_version="1.2", kernel="0.0.0-test", arch="x86_64",
    cpu_model="Example CPU 1000", logical_cpus=8, ram_gb=16.0, session_type="headless",
    displays=({"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
               "scale": 1.0, "primary": True},),
    packages={"yazses": "9.9.9"},
)
_NOW = "2026-10-15T00:00:00+00:00"


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("check_eye_eval_result", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def doc() -> dict[str, Any]:
    return json.loads(GOOD.read_text(encoding="utf-8"))


# --- a file that cannot be read is a problem, never a pass ------------------------------


def test_a_missing_file_is_a_problem(tmp_path: Path) -> None:
    problems = validate_result_file(tmp_path / "nope.json")
    assert len(problems) == 1 and "cannot be read" in problems[0]


def test_a_directory_is_a_problem(tmp_path: Path) -> None:
    assert validate_result_file(tmp_path)


@pytest.mark.parametrize("text", ["", "   \n\t", "﻿"])
def test_an_empty_file_is_a_problem(tmp_path: Path, text: str) -> None:
    path = tmp_path / "r.json"
    path.write_text(text, encoding="utf-8")
    problems = validate_result_file(path)
    assert problems and "empty" in problems[0], "an empty file must be named as empty"


def test_a_file_that_is_not_utf8_is_a_problem(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_bytes(b"\xff\xfe{\x00}\x00")
    assert validate_result_file(path) == ["<file>: not UTF-8 text."]


@pytest.mark.parametrize(
    "text",
    ['{"schema_version": "1.0"', "not json", "[]", "null", "42", '"1.0"', "{}", "{'a': 1}"],
)
def test_garbled_or_wrongly_shaped_text_is_a_problem(text: str) -> None:
    assert validate_result_text(text), text


def test_nesting_too_deep_for_the_parser_is_a_problem_not_a_crash() -> None:
    assert validate_result_text("[" * 200000)
    assert validate_result_text('{"a":' * 200000)


def test_an_integer_past_the_interpreters_limit_is_a_problem_not_a_crash() -> None:
    assert validate_result_text('{"schema_version": ' + "9" * 6000 + "}")


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_a_non_json_constant_is_refused_at_the_parser(doc: dict[str, Any], constant: str) -> None:
    text = json.dumps(doc).replace('"trials": 40', f'"trials": {constant}')
    assert constant in text
    problems = validate_result_text(text)
    assert problems and constant in problems[0]


def test_a_repeated_key_is_refused_because_the_last_copy_would_win(doc: dict[str, Any]) -> None:
    text = json.dumps(doc)[:-1] + ', "metrics": {"trials": 1}}'
    assert json.loads(text)["metrics"] == {"trials": 1}, "this is what a plain loader would see"
    problems = validate_result_text(text)
    assert len(problems) == 1 and "'metrics' appears twice" in problems[0]


def test_a_byte_order_mark_is_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "r.json"
    path.write_bytes(b"\xef\xbb\xbf" + GOOD.read_bytes())
    assert validate_result_file(path) == []


def test_the_shipped_example_is_valid_as_text_and_as_a_file() -> None:
    assert validate_result_text(GOOD.read_text(encoding="utf-8")) == []
    assert validate_result_file(GOOD) == []


# --- missing is never zero, now for the shapes a dict-level test did not try ------------


def _with_metric(doc: dict[str, Any], value: Any) -> dict[str, Any]:
    doc["metrics"]["zz"] = value
    return doc


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_metric_is_refused(doc: dict[str, Any], bad: float) -> None:
    problems = validate_result(_with_metric(doc, bad))
    assert problems and "not a measurement" in problems[0]


def test_a_non_finite_number_inside_a_list_or_group_is_refused(doc: dict[str, Any]) -> None:
    assert validate_result(_with_metric(doc, [1.0, math.nan]))
    assert validate_result(_with_metric(doc, {"a": {"b": math.inf}}))


def test_a_null_inside_a_list_is_a_bare_null(doc: dict[str, Any]) -> None:
    assert validate_result(_with_metric(doc, [1, None, 3]))


def test_an_empty_metric_group_is_refused(doc: dict[str, Any]) -> None:
    problems = validate_result(_with_metric(doc, {}))
    assert problems and "empty metric group" in problems[0]
    assert validate_result(_with_metric(doc, {"inner": {}}))


def test_a_value_that_also_claims_to_be_missing_is_refused(doc: dict[str, Any]) -> None:
    assert validate_result(_with_metric(doc, {"value": 3, "reason": "not_measured"}))


def test_a_measured_value_is_still_checked_inside_its_wrapper(doc: dict[str, Any]) -> None:
    assert validate_result(_with_metric(doc, {"value": 3})) == []
    assert validate_result(_with_metric(doc, {"value": math.nan}))


def test_zero_and_false_and_empty_list_remain_legitimate_measurements(doc: dict[str, Any]) -> None:
    for fine in (0, 0.0, False, "", [], [0, 0.0]):
        assert validate_result(_with_metric(doc, fine)) == [], fine


@pytest.mark.parametrize("stamp", [None, 5, "", "yesterday", "2026-13-45T00:00:00", []])
def test_a_timestamp_that_is_not_a_time_is_refused(doc: dict[str, Any], stamp: Any) -> None:
    doc["timestamp"] = stamp
    problems = validate_result(doc)
    assert problems and problems[0].startswith("timestamp:")


def test_a_display_count_that_disagrees_with_the_list_is_refused(doc: dict[str, Any]) -> None:
    doc["display"]["display_count"] = 2
    problems = validate_result(doc)
    assert len(problems) == 1 and problems[0].startswith("display.display_count:")
    doc["display"]["display_count"] = True
    assert validate_result(doc), "True == 1 must not count as one display"
    doc["display"]["displays"] = "one"
    assert validate_result(doc)


# --- accept-with-note for a later minor -------------------------------------------------


def test_a_later_minor_is_valid_and_noted(doc: dict[str, Any]) -> None:
    doc["schema_version"] = "1.7"
    doc["added_in_1_7"] = {"anything": 1}
    assert validate_result(doc) == []
    note = compatibility_note(doc)
    assert note is not None and "'1.7'" in note and "not checked" in note


def test_no_note_for_the_current_or_an_older_minor_or_a_refused_version(doc: dict[str, Any]) -> None:
    assert compatibility_note(doc) is None
    for version in (SCHEMA_VERSION, "1.0", "2.0", "1.x", None, 1):
        doc["schema_version"] = version
        assert compatibility_note(doc) is None, version
    assert compatibility_note([]) is None


# --- the script: exit codes -------------------------------------------------------------


def test_the_script_exits_zero_on_a_valid_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert _script().main([str(GOOD)]) == 0
    assert "OK" in capsys.readouterr().out


def test_the_script_exits_nonzero_for_each_kind_of_bad_input(
    tmp_path: Path, doc: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    main = _script().main
    empty = tmp_path / "empty.json"
    empty.write_text("", encoding="utf-8")
    garbled = tmp_path / "garbled.json"
    garbled.write_text("{not json", encoding="utf-8")
    del doc["privacy"]
    missing_field = tmp_path / "missing.json"
    missing_field.write_text(json.dumps(doc), encoding="utf-8")
    for bad in (tmp_path / "absent.json", tmp_path, empty, garbled, missing_field):
        assert main([str(bad)]) == 1, bad
    assert "privacy: missing required field" in capsys.readouterr().err


def test_one_bad_file_fails_the_run_even_beside_good_ones(tmp_path: Path) -> None:
    assert _script().main([str(GOOD), str(tmp_path / "absent.json"), str(GOOD)]) == 1


def test_naming_no_file_is_a_usage_error_not_a_pass() -> None:
    assert _script().main([]) == 2


def test_the_script_sweeps_values_for_a_home_directory(
    tmp_path: Path, doc: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    doc["software"]["perception_backend"] = {"name": "/home/someone/model.task"}
    path = tmp_path / "leak.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert _script().main([str(path)]) == 1
    assert "POSIX home directory" in capsys.readouterr().err


def test_the_script_prints_the_note_for_a_later_minor_and_still_exits_zero(
    tmp_path: Path, doc: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    doc["schema_version"] = "1.42"
    path = tmp_path / "later.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert _script().main([str(path)]) == 0
    assert "note:" in capsys.readouterr().out


def test_an_unknown_major_is_refused_by_the_script(tmp_path: Path, doc: dict[str, Any]) -> None:
    doc["schema_version"] = "2.0"
    path = tmp_path / "v2.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert _script().main([str(path)]) == 1


# --- every producer's output validates (producers derived, not listed) -------------------


def _producer_modules() -> set[str]:
    """Source files that build the result envelope: they stamp `"schema_version": SCHEMA_VERSION`."""
    pattern = re.compile(r'"schema_version":\s*SCHEMA_VERSION')
    return {
        p.relative_to(ROOT / "src" / "yazses").as_posix()
        for p in (ROOT / "src" / "yazses").rglob("*.py")
        if pattern.search(p.read_text(encoding="utf-8"))
    }


def test_the_producers_found_in_src_are_exactly_the_two_this_file_exercises() -> None:
    """A third producer must be added below, or this fails and says so."""
    assert _producer_modules() == {"eyeeval/runner.py", "eyeeval/gaze_field.py"}


def _runner_docs() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for task_id in TASK_IDS:
        task = generate_task(task_id)
        for mode in STUDY_MODES:
            common = {
                "task": task, "provenance": _PROV, "study_mode": mode, "timestamp": _NOW,
                "camera_class": "none", "capture_mode": "synthetic_replay",
                "protocol_id": "example-protocol/1" if mode == "research" else None,
            }
            out.append((f"{task_id}/{mode}/synthetic", build_result(
                records=synthetic_records(task), records_source="synthetic", **common)))
            for reason in MISSING_REASONS:
                out.append((f"{task_id}/{mode}/blocked:{reason}", build_result(
                    records=[], records_source="blocked", blocked_reason=reason, **common)))
    return out


def test_every_runner_document_validates_and_round_trips() -> None:
    docs = _runner_docs()
    assert len(docs) == len(TASK_IDS) * len(STUDY_MODES) * (1 + len(MISSING_REASONS))
    for label, produced in docs:
        assert validate_result(produced) == [], label
        text = dump_result(produced)
        assert validate_result_text(text) == [], label
        assert json.loads(text) == produced, f"{label}: write then read changed the document"


def test_the_gaze_field_report_validates_in_its_empty_and_populated_forms() -> None:
    session = MeasurementSession(confidence_min=0.5)
    for confidence in (0.9, 0.4, 0.0):
        session.record_confidence(confidence)
    session.set_duration(60.0)
    for label, built in {
        "empty": build_report(
            provenance=_PROV, timestamp=_NOW, session=MeasurementSession(),
            calibration=CalibrationFacts(),
        ),
        "populated": build_report(
            provenance=_PROV, timestamp=_NOW, session=session,
            calibration=CalibrationFacts(source="explicit", age_s=10.0, topology_validity="valid"),
        ),
    }.items():
        assert report_problems(built) == [], label
        assert validate_result_text(json.dumps(built)) == [], label


def _envelope_fixtures() -> list[Path]:
    found = []
    for path in sorted(FIXTURES.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and {"schema_version", "metrics", "privacy"} <= data.keys():
            found.append(path)
    return found


def test_every_committed_envelope_fixture_validates() -> None:
    found = _envelope_fixtures()
    assert len(found) >= 5, f"the walk found {len(found)} fixtures; it is looking in the wrong place"
    for path in found:
        assert validate_result_file(path) == [], path.relative_to(ROOT)


def test_the_fixture_walk_is_not_vacuous() -> None:
    """Break a copy of each found fixture; the same check must now object."""
    for path in _envelope_fixtures():
        broken = json.loads(path.read_text(encoding="utf-8"))
        del broken["metrics"]
        assert validate_result(broken), path.relative_to(ROOT)
