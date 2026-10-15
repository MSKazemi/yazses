"""The one entry point CI calls for the non-hardware eye-control evaluation (#424).

`scripts/eye_eval_ci.py` runs the camera-free slice of `design/eye-control/EVALUATION.md`
E0-E2 and leaves a small validated record per OS; `.github/workflows/eye-eval-ci.yml` calls
it on ubuntu, macOS and Windows. The matrix itself cannot run here, so what is asserted is
everything that decides whether a hosted run would mean anything:

1. **A failing check still leaves a record, and a missing leg is a failure.** A guard that
   iterates is green on an empty collection, so the matrix judge is proved on an *empty*
   directory, on a missing OS, on a failed leg and on a malformed record.
2. **Each guard is shown able to fail.** The lazy-import check is run against an interpreter
   that has already imported a fake `cv2`; the newline test simulates Windows text mode.
3. **It needs the base install only.** The script runs to completion in a child interpreter
   in which `cv2`, `mediapipe` and `PySide6` are unimportable.
4. **Nothing machine- or person-identifying reaches the artifact**, including through the
   quoted output of a failing check (a traceback names the checkout path), and Windows
   spellings of those paths are handled.
5. **The workflow keeps its contract**: read-only token, a cancellable PR group, no
   fail-fast, an upload that survives a failed leg, and a verdict job that counts legs.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "eye_eval_ci.py"
WORKFLOW = ROOT / ".github" / "workflows" / "eye-eval-ci.yml"
STAMP = "2026-10-15T00:00:00+00:00"


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ci = _load(SCRIPT, "eye_eval_ci_under_test")


def _good_record(system: str = "Linux", commit: str | None = "0123456789ab") -> dict[str, Any]:
    checks = [{"id": "lazy_imports", "status": "PASS", "detail": "ok"}]
    doc = ci.build_record(checks, STAMP)
    doc["platform_system"] = system
    doc["software"] = {**doc["software"], "git_commit": commit}
    return doc


def _put(root: Path, leg: str, doc: Any) -> None:
    target = root / f"eye-eval-ci-{leg}" / ci.RECORD_NAME
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(doc), encoding="utf-8")


# --- a run ------------------------------------------------------------------------------


def test_a_run_passes_and_writes_a_valid_record(tmp_path: Path) -> None:
    assert ci.main(["--out-dir", str(tmp_path), "--require-commit", "--timestamp", STAMP]) == 0
    doc = json.loads((tmp_path / ci.RECORD_NAME).read_text(encoding="utf-8"))
    assert ci.validate_record(doc, require_commit=True) == []
    assert doc["overall"] == "PASS"
    assert doc["study_mode"] == "ci"
    ids = {c["id"] for c in doc["checks"]}
    assert {"lazy_imports", "task_fixtures", "determinism", "replay:face_switch", "replay:grounding"} <= ids
    assert {f"result:{t}" for t in ci.TASK_IDS} <= ids
    # the provenance the issue asks for: runner OS/arch and commit
    assert doc["platform_system"] == ci.platform.system()
    assert doc["machine"]["arch"] not in ("", "unknown")
    assert doc["software"]["git_commit"]
    # the record states its own limits
    assert "real webcam accuracy" in doc["does_not_prove"]
    produced = sorted(p.name for p in (tmp_path / ci.RESULTS_DIR).iterdir())
    assert produced == sorted(f"{t}.json" for t in ci.TASK_IDS)


def test_the_artifact_is_deterministic_for_a_fixed_timestamp(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    assert ci.main(["--out-dir", str(first), "--timestamp", STAMP]) == 0
    assert ci.main(["--out-dir", str(second), "--timestamp", STAMP]) == 0
    for rel in [ci.RECORD_NAME, *(f"{ci.RESULTS_DIR}/{t}.json" for t in ci.TASK_IDS)]:
        assert (first / rel).read_bytes() == (second / rel).read_bytes(), rel


def test_a_failing_check_still_leaves_a_record_and_a_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken() -> str:
        raise AssertionError("fixture drifted")

    monkeypatch.setattr(ci, "check_task_fixtures", broken)
    assert ci.main(["--out-dir", str(tmp_path), "--timestamp", STAMP]) == 1
    doc = json.loads((tmp_path / ci.RECORD_NAME).read_text(encoding="utf-8"))
    assert doc["overall"] == "FAIL"
    failed = [c for c in doc["checks"] if c["status"] == "FAIL"]
    assert [c["id"] for c in failed] == ["task_fixtures"]
    assert "fixture drifted" in failed[0]["detail"]
    assert "FAIL task_fixtures" in capsys.readouterr().out


def test_a_missing_commit_is_a_failure_only_when_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = ci.collect_provenance

    def no_commit() -> Any:
        return dataclasses.replace(real(), git_commit=None)

    monkeypatch.setattr(ci, "collect_provenance", no_commit)
    assert ci.main(["--out-dir", str(tmp_path / "lax"), "--timestamp", STAMP]) == 0
    assert ci.main(["--out-dir", str(tmp_path / "strict"), "--require-commit", "--timestamp", STAMP]) == 1
    doc = json.loads((tmp_path / "strict" / ci.RECORD_NAME).read_text(encoding="utf-8"))
    assert any(c["id"] == "record" and c["status"] == "FAIL" for c in doc["checks"])


def test_an_unwritable_output_directory_exits_2(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert ci.main(["--out-dir", str(blocker / "sub"), "--timestamp", STAMP]) == 2


# --- the base install is enough ---------------------------------------------------------


def _blocker_env(tmp_path: Path, blocked: set[str]) -> dict[str, str]:
    sim = _load(ROOT / "scripts" / "simulate-missing-deps.py", "simulate_missing_deps_for_eye_ci")
    site = tmp_path / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(sim._SITECUSTOMIZE.format(blocked=blocked), encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(site), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    return env


def test_it_runs_to_completion_with_the_heavy_modules_unimportable(tmp_path: Path) -> None:
    env = _blocker_env(tmp_path, set(ci.HEAVY_MODULES))
    # the blocker must block even a module that IS installed, or this proves nothing
    probe = subprocess.run(
        [sys.executable, "-c", "import cv2, mediapipe, PySide6"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert probe.returncode != 0
    assert "ModuleNotFoundError" in probe.stderr
    out = tmp_path / "out"
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--out-dir", str(out), "--timestamp", STAMP],
        env=env, capture_output=True, text=True, check=False, cwd=tmp_path,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    doc = json.loads((out / ci.RECORD_NAME).read_text(encoding="utf-8"))
    assert doc["overall"] == "PASS"
    assert done.stdout.isascii()


def test_the_lazy_import_check_fails_when_a_heavy_module_is_loaded_at_startup(tmp_path: Path) -> None:
    """Guard the guard: a child interpreter that already holds `cv2` must fail the check."""
    site = tmp_path / "site"
    site.mkdir()
    (site / "cv2.py").write_text("", encoding="utf-8")
    (site / "sitecustomize.py").write_text("import cv2\n", encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(site), env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    code = (
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('m', {str(SCRIPT)!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "print(m._check('lazy_imports', m.check_lazy_imports))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    assert "'status': 'FAIL'" in done.stdout and "loaded cv2" in done.stdout


# --- the matrix judge -------------------------------------------------------------------


def test_the_judge_passes_three_good_legs(tmp_path: Path) -> None:
    for leg, system in (("Linux", "Linux"), ("macOS", "Darwin"), ("Windows", "Windows")):
        _put(tmp_path, leg, _good_record(system))
    code, lines = ci.collect_matrix(tmp_path)
    assert code == 0, lines
    assert lines[-1].startswith("matrix: PASS")


def test_the_judge_fails_on_an_empty_directory(tmp_path: Path) -> None:
    code, lines = ci.collect_matrix(tmp_path)
    assert code == 1
    assert sum(line.startswith("MISSING") for line in lines) == 3


def test_the_judge_fails_on_a_directory_that_does_not_exist(tmp_path: Path) -> None:
    assert ci.collect_matrix(tmp_path / "nope")[0] == 1


def test_the_judge_names_the_leg_that_never_uploaded(tmp_path: Path) -> None:
    _put(tmp_path, "Linux", _good_record("Linux"))
    _put(tmp_path, "macOS", _good_record("Darwin"))
    code, lines = ci.collect_matrix(tmp_path)
    assert code == 1
    assert any(line.startswith("MISSING") and "Windows" in line for line in lines)


def test_the_judge_fails_a_leg_whose_checks_failed(tmp_path: Path) -> None:
    bad = _good_record("Windows")
    bad["checks"].append({"id": "determinism", "status": "FAIL", "detail": "differs"})
    bad["overall"] = "FAIL"
    _put(tmp_path, "Linux", _good_record("Linux"))
    _put(tmp_path, "macOS", _good_record("Darwin"))
    _put(tmp_path, "Windows", bad)
    code, lines = ci.collect_matrix(tmp_path)
    assert code == 1
    assert any(line.startswith("FAIL") and "determinism" in line for line in lines)


def test_the_judge_refuses_a_record_that_says_pass_over_failed_checks(tmp_path: Path) -> None:
    lying = _good_record("Linux")
    lying["checks"][0]["status"] = "FAIL"  # overall still says PASS
    assert any("overall" in p for p in ci.validate_record(lying))
    _put(tmp_path, "Linux", lying)
    assert ci.collect_matrix(tmp_path, ("Linux",))[0] == 1


def test_the_judge_refuses_a_record_of_no_checks() -> None:
    empty = _good_record()
    empty["checks"] = []
    assert any("empty" in p for p in ci.validate_record(empty))


def test_the_judge_refuses_unreadable_and_duplicate_and_mismatched_legs(tmp_path: Path) -> None:
    (tmp_path / "eye-eval-ci-Linux").mkdir()
    (tmp_path / "eye-eval-ci-Linux" / ci.RECORD_NAME).write_text("{not json", encoding="utf-8")
    code, lines = ci.collect_matrix(tmp_path, ("Linux",))
    assert code == 1 and lines[0].startswith("UNREADABLE")

    dup = tmp_path / "dup"
    _put(dup, "a", _good_record("Linux"))
    _put(dup, "b", _good_record("Linux"))
    assert ci.collect_matrix(dup, ("Linux",))[0] == 1

    mixed = tmp_path / "mixed"
    _put(mixed, "Linux", _good_record("Linux", commit="aaaaaaaaaaaa"))
    _put(mixed, "Windows", _good_record("Windows", commit="bbbbbbbbbbbb"))
    code, lines = ci.collect_matrix(mixed, ("Linux", "Windows"))
    assert code == 1 and any(line.startswith("MISMATCH") for line in lines)


def test_the_judge_requires_a_commit_on_every_leg(tmp_path: Path) -> None:
    _put(tmp_path, "Linux", _good_record("Linux", commit=None))
    code, lines = ci.collect_matrix(tmp_path, ("Linux",))
    assert code == 1 and any("git_commit" in line for line in lines)


def test_collect_mode_is_wired_to_the_exit_code(tmp_path: Path) -> None:
    assert ci.main(["--collect", str(tmp_path)]) == 1


# --- privacy ----------------------------------------------------------------------------


def test_a_record_with_an_identifier_or_a_forbidden_key_is_refused() -> None:
    leaky = _good_record()
    leaky["checks"][0]["detail"] = "see /home/someone/work"
    assert any("home directory" in p for p in ci.validate_record(leaky))
    keyed = _good_record()
    keyed["hostname"] = "x"
    assert any("hostname" in p for p in ci.validate_record(keyed))


@pytest.mark.parametrize(
    "text",
    [
        'File "C:\\Users\\runneradmin\\work\\yazses\\scripts\\x.py", line 3',
        "File '/Users/runner/work/yazses/x.py'",
        "File '/home/runner/work/yazses/x.py'",
    ],
)
def test_scrub_removes_user_paths_in_every_spelling(text: str) -> None:
    cleaned = ci.scrub(text)
    for leaked in ("runneradmin", "/Users/runner", "/home/runner"):
        assert leaked not in cleaned


def test_scrub_removes_this_checkout_in_both_spellings() -> None:
    root = str(ci.ROOT)
    assert root not in ci.scrub(f"Traceback in {root}/scripts/x.py")
    assert ci.ROOT.as_posix() not in ci.scrub(f"in {ci.ROOT.as_posix()}/scripts/x.py")
    # a Windows traceback spells the same checkout with backslashes
    backslashed = str(PureWindowsPath("C:/Users/someone/yazses/scripts/x.py"))
    assert "someone" not in ci.scrub(backslashed)


def test_a_failing_check_does_not_publish_the_checkout_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> str:
        raise AssertionError(f"could not read {ci.ROOT}/tests/fixtures/x.json")

    monkeypatch.setattr(ci, "check_task_fixtures", broken)
    assert ci.main(["--out-dir", str(tmp_path), "--timestamp", STAMP]) == 1
    text = (tmp_path / ci.RECORD_NAME).read_text(encoding="utf-8")
    assert str(ci.ROOT) not in text and "<path>" in text


def test_the_test_selection_is_derived_posix_and_not_empty(tmp_path: Path) -> None:
    files = ci.eye_eval_test_files()
    assert "tests/test_eye_eval_schema.py" in files
    assert all("\\" not in f and f.startswith("tests/") for f in files)
    fake = tmp_path / "tests"
    fake.mkdir()
    (fake / "test_a.py").write_text("from yazses.eyeeval import x\n", encoding="utf-8")
    (fake / "test_b.py").write_text("import json\n", encoding="utf-8")
    assert ci.eye_eval_test_files(fake) == ["tests/test_a.py"]
    assert ci.eye_eval_test_files(tmp_path / "nowhere") == []


def test_an_empty_test_selection_is_a_failure_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ci, "eye_eval_test_files", lambda *a, **k: [])
    entry = ci._check("pytest:eye_eval", ci._pytest_check)
    assert entry["status"] == "FAIL" and "empty" in entry["detail"]


# --- line endings -----------------------------------------------------------------------


def test_results_and_records_are_written_with_lf_even_where_text_mode_would_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulate Windows text mode: `write_text` turns every newline into CRLF.

    The same result must be the same bytes on every leg, so the writers must not go
    through text mode at all. This fails if either goes back to `write_text`.
    """
    real = Path.write_text

    def crlf_write_text(self: Path, data: str, encoding: Any = None, errors: Any = None, newline: Any = None) -> int:
        return real(self, data.replace("\n", "\r\n"), encoding=encoding, errors=errors, newline="")

    monkeypatch.setattr(Path, "write_text", crlf_write_text)
    assert ci.main(["--out-dir", str(tmp_path), "--timestamp", STAMP]) == 0
    written = [tmp_path / ci.RECORD_NAME, *(tmp_path / ci.RESULTS_DIR).iterdir()]
    assert len(written) == 1 + len(ci.TASK_IDS)
    for path in written:
        data = path.read_bytes()
        assert b"\r" not in data, path.name
        assert data.endswith(b"}\n")


# --- the workflow -----------------------------------------------------------------------


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_the_workflow_token_is_read_only_and_nothing_publishes(workflow: dict[str, Any]) -> None:
    assert workflow["permissions"] == {"contents": "read"}
    text = WORKFLOW.read_text(encoding="utf-8")
    for job in workflow["jobs"].values():
        assert "permissions" not in job
    for forbidden in ("pull_request_target", "git push", "git commit", "gh pr", "gh issue", "secrets."):
        assert forbidden not in text, forbidden


def test_the_workflow_has_a_cancellable_pr_group_and_durable_main_runs(workflow: dict[str, Any]) -> None:
    group = workflow["concurrency"]["group"]
    assert "github.event.pull_request.number || github.run_id" in group
    assert workflow["concurrency"]["cancel-in-progress"] is True


def test_the_matrix_is_the_three_hosted_oses_and_never_fails_fast(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["evaluate"]
    assert job["strategy"]["fail-fast"] is False
    runners = job["strategy"]["matrix"]["os"]
    by_system = {"ubuntu-latest": "Linux", "macos-latest": "Darwin", "windows-latest": "Windows"}
    assert {by_system[r] for r in runners} == set(ci.EXPECTED_SYSTEMS)
    assert "continue-on-error" not in job, "a leg that may fail forever is a leg nobody reads"
    assert isinstance(job["timeout-minutes"], int)


def test_the_workflow_uploads_even_when_a_leg_fails_and_judges_the_legs(workflow: dict[str, Any]) -> None:
    steps = workflow["jobs"]["evaluate"]["steps"]
    upload = next(s for s in steps if "upload-artifact" in s.get("uses", ""))
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
    run = next(s for s in steps if "eye_eval_ci.py" in s.get("run", ""))
    assert "--require-commit" in run["run"] and "--out-dir" in run["run"]
    assert run["shell"] == "bash"

    judge = workflow["jobs"]["matrix"]
    assert judge["needs"] == "evaluate"
    assert "cancelled()" in judge["if"]
    collect = next(s for s in judge["steps"] if "--collect" in s.get("run", ""))
    assert "exit" in collect["run"]


def test_the_workflow_installs_the_base_install_only(workflow: dict[str, Any]) -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "uv sync\n" in text
    assert "--extra" not in text and "--all-extras" not in text


def test_the_workflow_triggers_cover_the_files_it_runs(workflow: dict[str, Any]) -> None:
    triggers = workflow[True]
    assert triggers["push"]["paths"] == triggers["pull_request"]["paths"]
    assert "workflow_dispatch" in triggers
    paths = triggers["pull_request"]["paths"]
    assert "scripts/eye_eval_ci.py" in paths
    assert ".github/workflows/eye-eval-ci.yml" in paths
    assert "src/yazses/eyeeval/**" in paths
