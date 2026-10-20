"""`yazses eye-eval` — the command, not the library behind it.

The library is covered by `test_eye_eval_runner.py`. What can only be checked here is that
the command is reachable from the **real** entry point, that its refusals happen before
anything is written, and that the no-camera dry run CI depends on actually works end to
end. A passing unit test is not evidence that a shipped CLI works: every `.exe` and `.app`
in this project once entered through `cli.app()` and skipped three fixes that only
`cli.main()` had.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer.main
from typer.testing import CliRunner

from yazses.cli import _EYE_EVAL_SECTIONS, _EYE_EVAL_TASKS, app
from yazses.eyeeval import FEATURES, TASK_IDS, VERDICTS

runner = CliRunner()


def _out(tmp_path: Path) -> Path:
    return tmp_path / "result.json"


# --- reachability ----------------------------------------------------------------------


def test_the_command_is_reachable_from_the_real_entry_point() -> None:
    """`cli.app` and `cli.main` both exist and a shipped binary enters through `app()`.

    Asking the live Click tree rather than importing the function: a command that is only
    importable is a command no user can run.
    """
    assert "eye-eval" in typer.main.get_command(app).commands


def test_the_help_lists_exactly_the_tasks_the_fixtures_define() -> None:
    """The `--help` string is hardcoded, because `yazses.eyeeval` must not be imported at
    CLI module scope. A hand-written set beside a generated one is the defect, so this is
    the test that keeps the two the same."""
    assert [part.strip() for part in _EYE_EVAL_TASKS.split("|")] == list(TASK_IDS)


def test_every_evaluation_feature_has_a_config_section() -> None:
    """`_EYE_EVAL_SECTIONS` decides which settings a result records; a missing entry would
    raise mid-run, after the tester has already done the task."""
    from yazses.config import Config
    from yazses.eyeeval import TASK_FEATURES

    cfg = Config()
    for task_id in TASK_IDS:
        section = _EYE_EVAL_SECTIONS[TASK_FEATURES[task_id]]
        assert hasattr(cfg, section), section
    assert set(_EYE_EVAL_SECTIONS) <= set(FEATURES)


# --- the synthetic dry run -------------------------------------------------------------


@pytest.mark.parametrize("task_id", TASK_IDS)
def test_a_synthetic_dry_run_writes_a_valid_result(tmp_path: Path, task_id: str) -> None:
    """No camera, no network, no hardware — this is the leg CI runs."""
    from yazses.eyeeval import validate_result

    target = _out(tmp_path)
    result = runner.invoke(app, ["eye-eval", task_id, "--synthetic", "-o", str(target)])
    assert result.exit_code == 0, result.output
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert validate_result(doc) == []
    assert doc["study_mode"] == "synthetic"
    assert doc["camera"] == {"camera_class": "none", "capture_mode": "synthetic_replay"}
    assert doc["run"]["verdict"] in VERDICTS


def test_the_summary_is_printed_and_says_nothing_was_sent(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["eye-eval", "gaze_routing_4_pane", "--synthetic", "-o", str(_out(tmp_path))]
    )
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output
    assert "40 recorded of 40 asked for" in result.output
    assert "Nothing was sent anywhere" in result.output


def test_a_dry_run_is_byte_identical_twice(tmp_path: Path) -> None:
    """Everything but the timestamp is deterministic, so a CI diff means a real change."""
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    for target in (first, second):
        assert runner.invoke(
            app, ["eye-eval", "gaze_routing_4_pane", "--synthetic", "-o", str(target)]
        ).exit_code == 0
    a, b = json.loads(first.read_text(encoding="utf-8")), json.loads(second.read_text(encoding="utf-8"))
    a.pop("timestamp"), b.pop("timestamp")
    assert a == b


# --- study mode is never inferred -------------------------------------------------------


def test_a_real_run_must_name_its_study_mode(tmp_path: Path) -> None:
    outcomes = tmp_path / "trials.json"
    outcomes.write_text(json.dumps([{"trial_index": 0, "outcome": "correct"}]), encoding="utf-8")
    result = runner.invoke(
        app, ["eye-eval", "gaze_routing_4_pane", "--outcomes", str(outcomes),
              "--camera-class", "integrated", "-o", str(_out(tmp_path))]
    )
    assert result.exit_code == 1
    assert "--study-mode is required" in result.output
    assert not _out(tmp_path).exists()


def test_community_qa_is_settable_explicitly(tmp_path: Path) -> None:
    outcomes = tmp_path / "trials.json"
    outcomes.write_text(json.dumps([{"trial_index": 0, "outcome": "correct"}]), encoding="utf-8")
    target = _out(tmp_path)
    result = runner.invoke(
        app, ["eye-eval", "gaze_routing_4_pane", "--outcomes", str(outcomes),
              "--study-mode", "community_qa", "--camera-class", "integrated", "-o", str(target)]
    )
    assert result.exit_code == 0, result.output
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["study_mode"] == "community_qa"
    assert doc["privacy"]["data_class"] == "B"
    assert doc["run"]["verdict"] == "PARTIAL"  # 1 trial of 40


def test_a_synthetic_run_cannot_call_itself_community_qa(tmp_path: Path) -> None:
    """Nobody performed the task. ADR-v2-150 Rule 1 in the direction nobody expects."""
    result = runner.invoke(
        app, ["eye-eval", "gaze_routing_4_pane", "--synthetic",
              "--study-mode", "community_qa", "-o", str(_out(tmp_path))]
    )
    assert result.exit_code == 1
    assert "no person performed the task" in result.output
    assert not _out(tmp_path).exists()


def test_research_mode_needs_a_protocol_id_not_a_flag(tmp_path: Path) -> None:
    outcomes = tmp_path / "trials.json"
    outcomes.write_text(json.dumps([{"trial_index": 0, "outcome": "correct"}]), encoding="utf-8")
    argv = ["eye-eval", "gaze_routing_4_pane", "--outcomes", str(outcomes),
            "--study-mode", "research", "--camera-class", "integrated",
            "-o", str(_out(tmp_path))]
    refused = runner.invoke(app, argv)
    assert refused.exit_code == 1
    assert "--protocol-id" in refused.output
    assert not _out(tmp_path).exists()

    accepted = runner.invoke(app, [*argv, "--protocol-id", "EYE-STUDY-2026-01/v1"])
    assert accepted.exit_code == 0, accepted.output
    doc = json.loads(_out(tmp_path).read_text(encoding="utf-8"))
    assert doc["protocol"]["protocol_id"] == "EYE-STUDY-2026-01/v1"
    assert doc["privacy"]["data_class"] == "C"


# --- blocked is a valid result ----------------------------------------------------------


def test_a_blocked_run_is_recorded_with_its_reason(tmp_path: Path) -> None:
    """EVALUATION.md: a reproducible FAIL/PARTIAL/BLOCKED result is a valid contribution."""
    target = _out(tmp_path)
    result = runner.invoke(
        app, ["eye-eval", "face_switch_blocks", "--blocked", "permission_denied",
              "--study-mode", "community_qa", "-o", str(target)]
    )
    assert result.exit_code == 0, result.output
    assert "BLOCKED" in result.output
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["run"]["blocked_reason"] == "permission_denied"
    assert all(isinstance(v, dict) for v in doc["metrics"].values()), doc["metrics"]


def test_an_invented_blocked_reason_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["eye-eval", "face_switch_blocks", "--blocked", "the_dog_ate_it",
              "--study-mode", "community_qa", "-o", str(_out(tmp_path))]
    )
    assert result.exit_code == 1
    assert "not a recognised reason" in result.output


# --- argument hygiene --------------------------------------------------------------------


def test_exactly_one_source_of_outcomes_is_required(tmp_path: Path) -> None:
    none_given = runner.invoke(
        app, ["eye-eval", "gaze_routing_4_pane", "--study-mode", "ci", "-o", str(_out(tmp_path))]
    )
    assert none_given.exit_code == 1
    assert "exactly one of --synthetic" in none_given.output
    both = runner.invoke(
        app, ["eye-eval", "gaze_routing_4_pane", "--synthetic", "--blocked", "not_supported",
              "--study-mode", "ci", "-o", str(_out(tmp_path))]
    )
    assert both.exit_code == 1


def test_an_unknown_task_lists_the_real_ones(tmp_path: Path) -> None:
    result = runner.invoke(app, ["eye-eval", "gaze-4target", "--synthetic", "-o", str(_out(tmp_path))])
    assert result.exit_code == 1
    for task_id in TASK_IDS:
        assert task_id in result.output


def test_an_outcomes_file_with_an_invented_field_is_refused(tmp_path: Path) -> None:
    """The field could hold desktop text; the misspelling could become a silent zero."""
    outcomes = tmp_path / "trials.json"
    outcomes.write_text(json.dumps([{"trial_index": 0, "outcome": "correct", "window_title": "x"}]), encoding="utf-8")
    result = runner.invoke(
        app, ["eye-eval", "gaze_routing_4_pane", "--outcomes", str(outcomes),
              "--study-mode", "community_qa", "--camera-class", "integrated",
              "-o", str(_out(tmp_path))]
    )
    assert result.exit_code == 1
    assert "window_title" in result.output
    assert not _out(tmp_path).exists()


def test_a_real_run_must_name_its_camera_class(tmp_path: Path) -> None:
    outcomes = tmp_path / "trials.json"
    outcomes.write_text(json.dumps([{"trial_index": 0, "outcome": "correct"}]), encoding="utf-8")
    result = runner.invoke(
        app, ["eye-eval", "gaze_routing_4_pane", "--outcomes", str(outcomes),
              "--study-mode", "community_qa", "-o", str(_out(tmp_path))]
    )
    assert result.exit_code == 1
    assert "--camera-class is required" in result.output


def test_the_tester_can_state_their_own_verdict(tmp_path: Path) -> None:
    target = _out(tmp_path)
    result = runner.invoke(
        app, ["eye-eval", "gaze_routing_4_pane", "--synthetic", "--verdict", "fail",
              "-o", str(target)]
    )
    assert result.exit_code == 0, result.output
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["run"]["verdict"] == "FAIL"
    assert doc["run"]["completeness_verdict"] == "PASS"
    assert "tester-stated" in result.output


def test_the_command_opens_no_network_primitive() -> None:
    """Offline-first is the product (ADR-011). `tests/test_egress_inventory.py` owns the
    tree-wide rule; this pins the two modules this command added, by name."""
    import ast

    import yazses.eyeeval.provenance as prov
    import yazses.eyeeval.runner as run_mod

    forbidden = {"urllib", "http", "socket", "requests", "httpx", "aiohttp", "smtplib",
                 "asyncio", "webbrowser", "subprocess"}
    for module in (prov, run_mod):
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden, (module.__name__, alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden, (module.__name__, node.module)
