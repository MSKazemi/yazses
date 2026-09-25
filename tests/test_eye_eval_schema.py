"""The eye-control evaluation result schema says the same thing on every platform.

Pure data in, list of problems out -- no camera, no network, no clock. Every test below
starts from one of the shipped fixtures and breaks exactly one thing, because a validator
is only useful if it fires on the specific defect and stays quiet otherwise (AGENTS.md
rule 9: a guard that fires on a house number teaches people to dismiss it).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from yazses.eyeeval import (
    FORBIDDEN_FIELD_TOKENS,
    MISSING_REASONS,
    REQUIRED_SECTIONS,
    REQUIRED_TOP_LEVEL,
    SCHEMA_VERSION,
    EyeEvalSchemaError,
    check_result,
    validate_result,
)

FIXTURES = Path(__file__).parent / "fixtures" / "eye_eval"
FIXTURE_NAMES = (
    "gaze_community_qa.json",
    "head_pointer_community_qa.json",
    "face_switch_synthetic.json",
)


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def gaze() -> dict:
    return load("gaze_community_qa.json")


def test_the_three_shipped_fixtures_validate():
    """One example per metric family, so a downstream reader has something real to parse."""
    for name in FIXTURE_NAMES:
        assert validate_result(load(name)) == [], f"{name} should be valid"


def test_every_fixture_in_the_directory_is_covered():
    """A fixture added without a test would be shipped unvalidated."""
    on_disk = sorted(p.name for p in FIXTURES.glob("*.json"))
    assert on_disk == sorted(FIXTURE_NAMES)


@pytest.mark.parametrize("field", REQUIRED_TOP_LEVEL)
def test_a_missing_top_level_field_is_named_in_the_error(gaze, field):
    gaze.pop(field)
    problems = validate_result(gaze)
    assert any(p.startswith(f"{field}:") for p in problems), problems


@pytest.mark.parametrize(
    ("section", "key"),
    [(s, k) for s, keys in REQUIRED_SECTIONS.items() for k in keys],
)
def test_a_missing_section_field_is_named_in_the_error(gaze, section, key):
    gaze[section].pop(key)
    problems = validate_result(gaze)
    assert f"{section}.{key}: missing required field." in problems, problems


def test_the_error_says_what_to_do_about_it(gaze):
    """'Invalid' is not actionable; the path plus the fix is."""
    del gaze["machine"]["cpu_model"]
    del gaze["protocol"]["task_version"]
    with pytest.raises(EyeEvalSchemaError) as exc:
        check_result(gaze)
    text = str(exc.value)
    assert "machine.cpu_model" in text
    assert "protocol.task_version" in text
    assert "2 eye-control evaluation schema problem(s)" in text


def test_a_valid_document_raises_nothing(gaze):
    assert check_result(gaze) is None


# --- compatibility rule -------------------------------------------------------------


def test_an_unknown_field_is_not_an_error(gaze):
    """Same major version: a reader must ignore fields a later minor version added."""
    gaze["metrics"]["some_metric_from_1_7"] = 3
    gaze["camera"]["exposure_mode_added_later"] = "auto"
    gaze["a_whole_new_section"] = {"anything": [1, 2, 3]}
    assert validate_result(gaze) == []


def test_a_newer_major_version_is_refused_rather_than_misread(gaze):
    gaze["schema_version"] = "2.0"
    problems = validate_result(gaze)
    assert len(problems) == 1
    assert "major version 2" in problems[0]
    assert f"{SCHEMA_VERSION.split('.')[0]}.x" in problems[0]


def test_an_older_major_version_is_refused_too(gaze):
    gaze["schema_version"] = "0.9"
    assert any("major version 0" in p for p in validate_result(gaze))


@pytest.mark.parametrize("bad", ["1", "one.two", "", None, 1.0, "v1.0"])
def test_a_malformed_schema_version_stops_validation_immediately(gaze, bad):
    """Without a version, no other check can be trusted -- so it is the only complaint."""
    gaze["schema_version"] = bad
    problems = validate_result(gaze)
    assert len(problems) == 1
    assert problems[0].startswith("schema_version:")


# --- a missing metric is never zero -------------------------------------------------


def test_a_bare_null_metric_is_refused(gaze):
    gaze["metrics"]["wrong_target"] = None
    problems = validate_result(gaze)
    assert any("bare null is not a metric value" in p for p in problems), problems


def test_a_missing_metric_needs_a_reason_from_the_dictionary(gaze):
    gaze["metrics"]["wrong_target"] = {"value": None, "reason": "couldn't be bothered"}
    problems = validate_result(gaze)
    assert any("a missing metric needs a reason" in p for p in problems), problems


@pytest.mark.parametrize("reason", MISSING_REASONS)
def test_every_documented_missing_reason_is_accepted(gaze, reason):
    gaze["metrics"]["wrong_target"] = {"value": None, "reason": reason}
    assert validate_result(gaze) == []


def test_a_missing_metric_nested_in_a_group_is_checked_too(gaze):
    gaze["metrics"]["calibration"]["held_out_rmse_px"] = None
    problems = validate_result(gaze)
    assert any(p.startswith("metrics.calibration.held_out_rmse_px:") for p in problems), problems


def test_zero_is_still_a_legitimate_measurement(gaze):
    """The rule bans silent zeros, not measured ones."""
    gaze["metrics"]["wrong_target"] = 0
    assert validate_result(gaze) == []


def test_metrics_must_not_be_empty(gaze):
    gaze["metrics"] = {}
    assert any(p.startswith("metrics:") for p in validate_result(gaze))


# --- privacy ------------------------------------------------------------------------


@pytest.mark.parametrize("token", FORBIDDEN_FIELD_TOKENS)
def test_a_forbidden_field_name_fails_wherever_it_appears(gaze, token):
    gaze["machine"][f"tester_{token}"] = "redacted-in-this-test"
    problems = validate_result(gaze)
    assert any(token in p and "forbidden field" in p for p in problems), problems


def test_a_forbidden_field_is_found_deep_inside_a_list(gaze):
    gaze["display"]["displays"][0]["monitor_serial"] = "XYZ123"
    problems = validate_result(gaze)
    assert any("display.displays.0.monitor_serial" in p for p in problems), problems


def test_the_ordinary_fixtures_trip_no_forbidden_token():
    """`mac_address` must not fire on `machine`, which is why the tokens are spelled out."""
    for name in FIXTURE_NAMES:
        assert not [p for p in validate_result(load(name)) if "forbidden field" in p]


def test_retained_raw_media_is_refused(gaze):
    gaze["privacy"]["raw_media_retained"] = True
    assert any(p.startswith("privacy.raw_media_retained:") for p in validate_result(gaze))


def test_declared_personal_identifiers_are_refused(gaze):
    gaze["privacy"]["contains_personal_identifiers"] = True
    assert any(
        p.startswith("privacy.contains_personal_identifiers:") for p in validate_result(gaze)
    )


# --- study mode and evidence class (ADR-v2-150) --------------------------------------


def test_an_unknown_study_mode_is_refused(gaze):
    gaze["study_mode"] = "user_testing"
    assert any(p.startswith("study_mode:") for p in validate_result(gaze))


def test_community_qa_cannot_declare_itself_research_grade(gaze):
    """Rule 6: the data class is a fact about collection, not a later relabelling."""
    gaze["privacy"]["data_class"] = "C"
    problems = validate_result(gaze)
    assert any("privacy.data_class" in p for p in problems), problems


def test_research_mode_requires_a_protocol_identifier(gaze):
    """Rule 2: changing the enum after collection is not a consent mechanism."""
    gaze["study_mode"] = "research"
    gaze["privacy"]["data_class"] = "C"
    problems = validate_result(gaze)
    assert any(p.startswith("protocol.protocol_id:") for p in problems), problems

    gaze["protocol"]["protocol_id"] = "yazses-eye-2026-a/1.0"
    assert validate_result(gaze) == []


def test_community_qa_does_not_need_a_protocol_identifier(gaze):
    assert gaze["protocol"]["protocol_id"] is None
    assert validate_result(gaze) == []


# --- enums and shape ----------------------------------------------------------------


def test_an_unknown_feature_name_is_refused(gaze):
    gaze["feature"]["name"] = "gase"
    assert any(p.startswith("feature.name:") for p in validate_result(gaze))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("camera", "camera_class"), "builtin"),
        (("camera", "capture_mode"), "recorded"),
        (("os_session", "session_type"), "wayland"),
    ],
)
def test_an_unknown_enum_value_is_refused(gaze, path, value):
    gaze[path[0]][path[1]] = value
    problems = validate_result(gaze)
    assert any(p.startswith(f"{path[0]}.{path[1]}:") for p in problems), problems


def test_a_section_that_is_not_an_object_is_reported_once(gaze):
    gaze["machine"] = "Ubuntu 24.04"
    problems = validate_result(gaze)
    assert "machine: expected an object, got str." in problems
    assert not any(p.startswith("machine.") for p in problems)


@pytest.mark.parametrize("doc", [[], "result", 7, None])
def test_a_non_object_document_is_refused(doc):
    problems = validate_result(doc)
    assert len(problems) == 1
    assert problems[0].startswith("<root>:")


def test_validation_does_not_mutate_the_document(gaze):
    before = copy.deepcopy(gaze)
    validate_result(gaze)
    assert gaze == before
