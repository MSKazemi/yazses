"""The eye-control evaluation runner: what it counts, what it refuses to count, and when.

Every test here builds its result from a **fake machine** (`_FAKE_PROVENANCE`) and a
generated task, so nothing depends on the host that ran the suite and the golden document
is byte-stable on Windows, macOS and Linux. The one test that does read this machine reads
it to prove a negative -- see `test_eye_eval_privacy.py`.

Three things are asserted here that the code cannot assert about itself:

* a metric that was not measured is a marker, not a zero -- checked on the path where the
  zero is most tempting (`--blocked`, where every number is absent at once);
* the verdict is derived from completeness and never from a rate, so it cannot turn into
  an accidental promotion gate;
* the golden document is the whole envelope, so a field appearing or vanishing shows up in
  a diff rather than in a report somebody publishes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yazses.eyeeval import (
    FACE_SWITCH_TASK,
    GAZE_TASK,
    HEAD_POINTER_TASK,
    MISSING_REASONS,
    SCHEMA_VERSION,
    TASK_IDS,
    TASK_RECORDS,
    VERDICTS,
    EyeEvalRunError,
    Provenance,
    build_result,
    check_records,
    completeness_verdict,
    dump_result,
    generate_task,
    safe_settings,
    summarize,
    synthetic_records,
    tally,
    validate_result,
    write_result,
)
from yazses.eyeeval.runner import GENERATOR, UNUSABLE_OUTCOMES

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "eye_eval_runner" / "gaze_synthetic.json"

#: A machine that does not exist, so no assertion below can pass or fail because of the
#: one that ran it. Every field is the shape the real collector produces.
_FAKE_PROVENANCE = Provenance(
    yazses_version="9.9.9",
    git_commit="0123456789ab",
    python_version="3.13.0",
    os_name="ExampleOS",
    os_version="1.2",
    kernel="0.0.0-test",
    arch="x86_64",
    cpu_model="Example CPU 1000",
    logical_cpus=8,
    ram_gb=16.0,
    session_type="headless",
    displays=({"index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080,
               "scale": 1.0, "primary": True},),
    packages={"yazses": "9.9.9"},
)
_FIXED_TIME = "2026-09-25T00:00:00+00:00"


def _result(task_id: str = GAZE_TASK, **overrides: Any) -> dict[str, Any]:
    task = generate_task(task_id)
    kwargs: dict[str, Any] = {
        "task": task,
        "records": synthetic_records(task),
        "provenance": _FAKE_PROVENANCE,
        "study_mode": "synthetic",
        "timestamp": _FIXED_TIME,
        "camera_class": "none",
        "capture_mode": "synthetic_replay",
        "records_source": "synthetic",
    }
    kwargs.update(overrides)
    return build_result(**kwargs)


# --- the document ---------------------------------------------------------------------


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_a_synthetic_run_of_every_task_is_a_valid_result(task_id: str) -> None:
    assert validate_result(_result(task_id)) == []


def test_the_golden_document_still_matches() -> None:
    """The whole envelope, frozen. A new field is a diff, not a surprise in a shared file.

    Never edit the fixture by hand -- it is the output of the call below and nothing else.
    Regenerate it deliberately, read the diff, then commit it:

        uv run python -c "import tests.test_eye_eval_runner as t; \
            t.GOLDEN.write_text(t.dump_result(t._result()))"
    """
    doc = _result()
    assert GOLDEN.exists(), f"{GOLDEN} is missing; it is the frozen output of build_result()"
    assert dump_result(doc) == GOLDEN.read_text(encoding="utf-8")


def test_the_generator_and_schema_versions_are_stamped() -> None:
    doc = _result()
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["software"]["generator"] == GENERATOR


def test_provenance_travels_with_the_number() -> None:
    """A number without the machine that produced it is not a measurement (METRICS.md)."""
    doc = _result()
    assert doc["machine"]["cpu_model"] == "Example CPU 1000"
    assert doc["machine"]["os_name"] == "ExampleOS"
    assert doc["software"]["yazses_version"] == "9.9.9"
    assert doc["display"]["display_count"] == 1
    assert doc["display"]["topology_fingerprint"].startswith("sha256:")


def test_the_study_mode_fixes_the_data_class() -> None:
    """ADR-v2-150 Rule 6: the class is a fact about collection, not a later choice."""
    assert _result(study_mode="synthetic")["privacy"]["data_class"] == "A"
    task = generate_task(GAZE_TASK)
    qa = build_result(
        task=task, records=synthetic_records(task), provenance=_FAKE_PROVENANCE,
        study_mode="community_qa", timestamp=_FIXED_TIME, camera_class="integrated",
        capture_mode="live", records_source="recorded",
    )
    assert qa["privacy"]["data_class"] == "B"
    assert validate_result(qa) == []


def test_research_without_a_protocol_id_is_refused_by_the_schema() -> None:
    """Relabelling an artifact after collection is not consent (ADR-v2-150 Rule 2)."""
    problems = validate_result(_result(study_mode="research"))
    assert any("protocol_id" in p for p in problems), problems
    assert validate_result(_result(study_mode="research", protocol_id="EYE-2026-01/v1")) == []


def test_raw_media_and_identifier_flags_are_always_false() -> None:
    privacy = _result()["privacy"]
    assert privacy["raw_media_retained"] is False
    assert privacy["contains_personal_identifiers"] is False
    assert privacy["aggregates_only"] is True


# --- missing is never zero --------------------------------------------------------------


def test_a_blocked_run_reports_no_numbers_at_all() -> None:
    """Every metric becomes an explicit marker, because none of them was measured.

    This is the path where a zero is most tempting and most wrong: "0 false activations"
    and "nobody looked for false activations" are the two readings `METRICS.md` forbids
    collapsing, and a blocked run is entirely the second.
    """
    doc = _result(FACE_SWITCH_TASK, records=[], records_source="none",
                  blocked_reason="permission_denied")
    assert doc["run"]["verdict"] == "BLOCKED"
    assert doc["metrics"], "a blocked run still names every metric it did not measure"
    for name, value in doc["metrics"].items():
        assert isinstance(value, dict), f"metrics.{name} is {value!r}, not a missing marker"
        assert value == {"value": None, "reason": "permission_denied"}
    assert validate_result(doc) == []


def test_the_blocked_key_set_is_the_same_key_set_a_real_run_reports() -> None:
    """Derived from a live tally, never hand-written beside it -- the two would drift."""
    for task_id in TASK_IDS:
        task = generate_task(task_id)
        live = set(tally(task, synthetic_records(task)))
        blocked = set(tally(task, [], blocked_reason="not_supported"))
        assert live == blocked, task_id


def test_an_unrecorded_count_is_a_marker_not_a_zero() -> None:
    """Synthetic records carry no timings, so every timing metric says so."""
    metrics = tally(generate_task(HEAD_POINTER_TASK),
                    synthetic_records(generate_task(HEAD_POINTER_TASK)))
    assert metrics["accidental_click_count_total"] == {"value": None, "reason": "not_measured"}
    assert metrics["movement_time_ms_p50"] == {"value": None, "reason": "not_measured"}
    assert metrics["hit"] == 24


def test_every_missing_reason_the_runner_emits_is_in_the_schema_vocabulary() -> None:
    for task_id in TASK_IDS:
        task = generate_task(task_id)
        for value in tally(task, []).values():
            if isinstance(value, dict):
                assert value["reason"] in MISSING_REASONS


# --- counting -------------------------------------------------------------------------


def test_gaze_counts_wrong_target_and_fallback_separately() -> None:
    """METRICS.md: fallback is safer than a wrong target and must not be one 'error'."""
    task = generate_task(GAZE_TASK)
    records = [
        {"trial_index": 0, "outcome": "correct", "trial_time_ms": 800},
        {"trial_index": 1, "outcome": "wrong_target", "trial_time_ms": 1200},
        {"trial_index": 2, "outcome": "fallback_no_route"},
        {"trial_index": 3, "outcome": "invalid_tracking"},
    ]
    metrics = tally(task, records)
    assert metrics["trials"] == 4
    assert metrics["wrong_target"] == 1
    assert metrics["fallback_no_route"] == 1
    assert metrics["correct_target_rate"] == 0.25
    assert metrics["trial_time_ms_p50"] == 1000


def test_false_activations_per_hour_uses_the_tasks_own_scored_duration() -> None:
    """The primary face-switch safety metric, computed rather than eyeballed."""
    task = generate_task(FACE_SWITCH_TASK)
    records = [
        {"block_id": "neutral", "block_type": "neutral", "false_activation_count": 2},
        {"block_id": "speaking", "block_type": "speaking", "false_activation_count": 1},
    ]
    metrics = tally(task, records)
    assert metrics["scored_duration_s"] == 900  # three five-minute blocks
    assert metrics["false_activation_count_total"] == 3
    assert metrics["false_activations_per_hour"] == 12.0


def test_no_per_trial_record_reaches_the_document() -> None:
    """Only aggregates are published, so an outcomes file cannot smuggle anything in."""
    task = generate_task(GAZE_TASK)
    doc = build_result(
        task=task,
        records=[{"trial_index": 0, "outcome": "correct", "trial_time_ms": 4242}],
        provenance=_FAKE_PROVENANCE, study_mode="community_qa", timestamp=_FIXED_TIME,
        camera_class="integrated", capture_mode="live", records_source="recorded",
    )
    text = dump_result(doc)
    assert "trial_index" not in text
    assert doc["metrics"]["trial_time_ms_p50"] == 4242  # the aggregate, not the record


# --- the verdict ----------------------------------------------------------------------


def test_a_complete_run_passes_and_a_short_one_is_partial() -> None:
    task = generate_task(GAZE_TASK)
    assert completeness_verdict(task, synthetic_records(task)) == "PASS"
    assert completeness_verdict(task, synthetic_records(task)[:10]) == "PARTIAL"
    assert completeness_verdict(task, []) == "FAIL"
    assert completeness_verdict(task, [], blocked_reason="not_supported") == "BLOCKED"


def test_one_lost_tracker_makes_a_complete_run_partial() -> None:
    task = generate_task(GAZE_TASK)
    records = synthetic_records(task)
    records[0] = {**records[0], "outcome": "invalid_tracking"}
    assert completeness_verdict(task, records) == "PARTIAL"


def test_a_wrong_target_is_data_and_does_not_lower_the_verdict() -> None:
    """The verdict describes the protocol. A rate threshold here would be a promotion
    gate, and `design/eye-control/EVALUATION.md` sets those from cross-person evidence."""
    task = generate_task(GAZE_TASK)
    records = [{**r, "outcome": "wrong_target"} for r in synthetic_records(task)]
    assert completeness_verdict(task, records) == "PASS"
    assert tally(task, records)["correct_target_rate"] == 0.0


def test_the_tester_can_override_the_computed_verdict() -> None:
    """EVALUATION.md 'Failure reporting': the tester selects one. Both are recorded."""
    doc = _result(verdict="FAIL")
    assert doc["run"]["verdict"] == "FAIL"
    assert doc["run"]["completeness_verdict"] == "PASS"
    assert doc["run"]["verdict_source"] == "tester"
    assert doc["run"]["verdict"] in VERDICTS


def test_every_unusable_outcome_is_an_outcome_the_task_can_produce() -> None:
    """Guard the guard: a typo here would silently stop downgrading a broken run."""
    from yazses.eyeeval import TASK_OUTCOMES

    for task_id, unusable in UNUSABLE_OUTCOMES.items():
        assert set(unusable) <= set(TASK_OUTCOMES[task_id]), task_id


# --- supplied outcome files -------------------------------------------------------------


def test_an_unknown_record_field_is_refused_not_ignored() -> None:
    """A misspelled count would otherwise become a silent zero -- and an invented field
    would be a place to put something the programme promised not to collect."""
    task = generate_task(GAZE_TASK)
    problems = check_records(task, [{"trial_index": 0, "outcome": "correct", "miss_cnt": 2}])
    assert len(problems) == 1
    assert "miss_cnt" in problems[0]


def test_an_unknown_outcome_is_refused() -> None:
    task = generate_task(GAZE_TASK)
    problems = check_records(task, [{"trial_index": 0, "outcome": "sort_of_worked"}])
    assert problems and "sort_of_worked" in problems[0]


def test_a_well_formed_outcomes_file_has_no_problems() -> None:
    for task_id in TASK_IDS:
        task = generate_task(task_id)
        assert check_records(task, synthetic_records(task)) == [], task_id


def test_every_synthetic_record_field_is_one_the_task_declares() -> None:
    for task_id in TASK_IDS:
        task = generate_task(task_id)
        allowed = set(TASK_RECORDS[task_id])
        for record in synthetic_records(task):
            assert set(record) <= allowed, (task_id, record)


# --- settings ---------------------------------------------------------------------------


def test_only_enum_shaped_settings_survive() -> None:
    """A number or a flag cannot carry a path; a string is kept only when it cannot.

    `model_path` is the setting this rule exists for: on a real install it is an absolute
    path under the user's home directory, and it lives in the same config section as the
    settings a gaze result legitimately reports.
    """
    kept = safe_settings(
        {
            "gaze.enabled": True,
            "gaze.calibration_points": 9,
            "gaze.confidence_min": 0.5,
            "gaze.backend": "mediapipe",
            "gaze.model_path": "/home/someone/.cache/yazses/face_landmarker.task",
            "gaze.note": "Sentence with spaces.",
        }
    )
    assert kept == {
        "gaze.enabled": True,
        "gaze.calibration_points": 9,
        "gaze.confidence_min": 0.5,
        "gaze.backend": "mediapipe",
    }


def test_the_config_hash_changes_with_the_settings() -> None:
    a = _result(settings={"gaze.enabled": True})["config"]
    b = _result(settings={"gaze.enabled": False})["config"]
    assert a["config_hash"] != b["config_hash"]


# --- writing ----------------------------------------------------------------------------


def test_write_result_writes_canonical_json(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "result.json"
    written = write_result(_result(), target)
    assert written == target
    text = target.read_text(encoding="utf-8")
    assert text.endswith("}\n")
    assert json.loads(text)["schema_version"] == SCHEMA_VERSION


def test_an_invalid_document_is_refused_and_no_file_appears(tmp_path: Path) -> None:
    """The validator runs before the write. After it, it would be a post-mortem."""
    doc = _result()
    doc["study_mode"] = "definitely_research"
    target = tmp_path / "result.json"
    with pytest.raises(EyeEvalRunError):
        write_result(doc, target)
    assert not target.exists()


def test_the_summary_names_the_verdict_and_the_counts() -> None:
    text = summarize(_result())
    assert "PASS" in text
    assert "40 recorded of 40 asked for" in text
    assert "correct_target=40" in text
    assert "not measured" in text
    assert "not that the feature was accurate" in text
