"""The fast/full lane split in `test.yml` keeps a blocking path for every change (#535).

A lane that stops being selected, or a gate that stops depending on a job, turns nothing
red; PRs just go green on less evidence. This file pins the eight fixtures from the issue
(the table in `.github/CI_POLICY.md` section 5), `scripts/ci_gate.py`'s rules, and the
shape of `test.yml` that both rely on.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
TEST_YML = WORKFLOWS / "test.yml"


def _load(name: str):
    """Load a script as a module; `scripts/` is not a package, so it cannot be imported."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classifier = _load("classify_changes")
gate = _load("ci_gate")

#: (fixture, changed paths, scopes, takes the full lane, path-filtered workflows it fires).
#: Every PR also runs the fast lane, the Linux baseline and ci-gate in test.yml, and the
#: unfiltered workflows (CodeQL, dependency review, the labeler, campaign preflight).
FIXTURES = [
    (
        "typo-only docs PR",
        ["docs/features/meeting.md"],
        {"docs_design"},
        False,
        {"docs.yml"},
    ),
    (
        "new ADR / design page",
        ["design/adr/adr-099-example.md", "design/adr/README.md"],
        {"docs_design"},
        False,
        {"docs.yml"},
    ),
    (
        "Python runtime change",
        ["src/yazses/postprocess/numbers.py"],
        {"python_core"},
        True,
        set(),
    ),
    (
        "test-only change",
        ["tests/test_numbers.py"],
        {"tests"},
        True,
        set(),
    ),
    (
        "Windows packaging change",
        ["packaging/windows/msix/AppxManifest.xml"],
        {"windows", "packaging"},
        True,
        {"build-windows.yml", "msix-validate.yml"},
    ),
    (
        "Android change",
        ["android/core/postprocess/src/main/kotlin/Numbers.kt"],
        {"android"},
        False,
        {"android-test.yml"},
    ),
    (
        "workflow/security change",
        [".github/workflows/codeql.yml"],
        {"workflow_security"},
        True,
        set(),
    ),
    (
        "previously unseen top-level path",
        ["a-new-top-level-tree/thing.py"],
        {"unknown"},
        True,
        set(),
    ),
]

IDS = [name for name, *_ in FIXTURES]


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8")) or {}


def _pr_paths(doc: dict) -> list[str] | None:
    # YAML 1.1 parses the key on: as boolean True.
    triggers = doc.get(True, doc.get("on")) or {}
    event = triggers.get("pull_request") if isinstance(triggers, dict) else None
    return event.get("paths") if isinstance(event, dict) else None


def _glob(pattern: str) -> re.Pattern[str]:
    """GitHub's `paths:` glob: `**` crosses `/`, `*` does not. Every filter in this repo
    uses only those two (tests/test_classify_changes.py fails on any other form)."""
    out = re.escape(pattern).replace(r"\*\*", "\0").replace(r"\*", "[^/]*")
    return re.compile(out.replace("\0", ".*") + r"\Z")


def _filtered_workflows_fired_by(paths: list[str]) -> set[str]:
    fired = set()
    for path in sorted(WORKFLOWS.glob("*.yml")):
        patterns = _pr_paths(_workflow(path.name))
        if patterns and any(_glob(p).match(f) for p in patterns for f in paths):
            fired.add(path.name)
    return fired


@pytest.fixture(scope="module")
def jobs() -> dict:
    return _workflow("test.yml")["jobs"]


def _gated_on_the_decision(job: dict) -> bool:
    return "needs.changes.outputs.full" in str(job.get("if", ""))


# --- the fixtures


@pytest.mark.parametrize(("name", "paths", "scopes", "full", "fired"), FIXTURES, ids=IDS)
def test_each_fixture_classifies_and_routes_as_documented(
    name: str, paths: list[str], scopes: set[str], full: bool, fired: set[str]
) -> None:
    got = classifier.classify(paths)
    assert got == scopes
    assert classifier.needs_full_lane(got) is full


@pytest.mark.parametrize(("name", "paths", "scopes", "full", "fired"), FIXTURES, ids=IDS)
def test_each_fixture_fires_the_specialized_workflows_documented(
    name: str, paths: list[str], scopes: set[str], full: bool, fired: set[str]
) -> None:
    assert _filtered_workflows_fired_by(paths) == fired


def test_a_change_that_skips_the_full_lane_still_has_a_specialized_check() -> None:
    """Skipping the matrix is safe only because something built for that change runs:
    the strict docs build for docs/design, the Gradle tests for Android."""
    for name, paths, _, full, fired in FIXTURES:
        if not full:
            assert fired, f"{name} skips the full lane and fires no specialized workflow"


def test_the_fixtures_cover_every_case_the_issue_names() -> None:
    assert len(FIXTURES) == 8


def test_only_docs_design_and_android_skip_the_full_lane() -> None:
    """Widening this set is a decision to run less CI; it should be a reviewed diff here."""
    assert classifier.BASELINE_ONLY == {"docs_design", "android"}


@pytest.mark.parametrize(
    "scopes",
    [set(), {"unknown"}, {"docs_design", "unknown"}, {"docs_design", "python_core"},
     {"android", "release"}],
    ids=["none", "unknown", "docs+unknown", "docs+runtime", "android+release"],
)
def test_anything_outside_the_baseline_scopes_takes_the_full_lane(scopes: set[str]) -> None:
    assert classifier.needs_full_lane(scopes) is True


def test_one_root_file_in_a_docs_pr_takes_the_full_lane() -> None:
    """Root files are deliberately unknown (#534); unknown means more validation."""
    assert classifier.needs_full_lane(classifier.classify(["docs/index.md", "README.md"]))


# --- the gate


def _needs(full_lane: str = "success") -> dict[str, dict]:
    """`toJSON(needs)` as GitHub renders it, with every full-lane job at `full_lane`."""
    results = {"changes": "success", "repo-hygiene": "success", "test-linux": "success"}
    results |= {job: full_lane for job in gate.FULL_LANE_JOBS}
    return {job: {"result": result, "outputs": {}} for job, result in results.items()}


def test_the_gate_passes_a_full_run_that_succeeded() -> None:
    assert gate.verdict(_needs(), "true") == []


def test_the_gate_passes_a_fast_run_whose_full_lane_was_skipped() -> None:
    assert gate.verdict(_needs("skipped"), "false") == []


def test_the_gate_fails_when_the_full_lane_was_skipped_but_selected() -> None:
    assert len(gate.verdict(_needs("skipped"), "true")) == len(gate.FULL_LANE_JOBS)


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "", None])
@pytest.mark.parametrize("job", ["changes", "repo-hygiene", "test-linux"])
def test_the_gate_fails_when_an_always_on_job_did_not_succeed(job: str, result: str) -> None:
    needs = _needs("skipped")
    needs[job]["result"] = result
    assert gate.verdict(needs, "false") == [f"{job}: {result}"]


@pytest.mark.parametrize("result", ["failure", "cancelled"])
@pytest.mark.parametrize("full", ["true", "false"])
def test_the_gate_fails_on_a_failed_or_cancelled_full_lane_job(result: str, full: str) -> None:
    needs = _needs("success" if full == "true" else "skipped")
    needs["test"]["result"] = result
    assert gate.verdict(needs, full) == [f"test: {result}"]


@pytest.mark.parametrize("full", ["", "maybe", "True"])
def test_the_gate_fails_without_a_clear_lane_decision(full: str) -> None:
    """The classifier crashing or printing nothing must not read as 'fast was enough'."""
    assert gate.verdict(_needs(), full)


def test_the_gate_command_reads_its_inputs_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import json

    monkeypatch.setenv("NEEDS", json.dumps(_needs("skipped")))
    monkeypatch.setenv("FULL", "false")
    assert gate.main() == 0
    monkeypatch.setenv("FULL", "true")
    assert gate.main() == 1
    assert "::error::" in capsys.readouterr().out


@pytest.mark.parametrize("raw", ["", "not json", "[]", "{}"])
def test_the_gate_command_fails_on_missing_results(
    monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    monkeypatch.setenv("NEEDS", raw)
    monkeypatch.setenv("FULL", "true")
    assert gate.main() == 1


# --- the workflow contract


def test_the_jobs_gated_on_the_decision_are_the_ones_the_gate_forgives(jobs: dict) -> None:
    """A job gated in the YAML but not in FULL_LANE_JOBS fails every fast run; a job in
    FULL_LANE_JOBS but no longer gated could be skipped for some other reason and pass."""
    gated = {name for name, job in jobs.items() if _gated_on_the_decision(job)}
    assert gated - {"freebsd"} == gate.FULL_LANE_JOBS


@pytest.mark.parametrize("name", sorted(gate.FULL_LANE_JOBS | {"freebsd"}))
def test_a_full_lane_job_runs_unless_the_decision_is_explicitly_false(
    jobs: dict, name: str
) -> None:
    """`!= 'false'`, not `== 'true'`: an empty or garbled decision runs more CI, not less."""
    assert jobs[name]["if"] == "needs.changes.outputs.full != 'false'"
    assert jobs[name]["needs"] == "changes"


def test_the_gate_depends_on_every_blocking_job(jobs: dict) -> None:
    needs = set(jobs["ci-gate"]["needs"])
    advisory = {name for name, job in jobs.items() if job.get("continue-on-error") is True}
    assert advisory == {"freebsd"}
    assert needs == set(jobs) - {"ci-gate"} - advisory


def test_the_gate_always_reports(jobs: dict) -> None:
    """Without always(), a failed dependency skips the gate, and a skipped required check
    counts as passing."""
    assert jobs["ci-gate"]["if"] == "always()"
    assert jobs["ci-gate"].get("name") == "ci-gate"


def test_the_always_on_jobs_are_not_conditional(jobs: dict) -> None:
    for name in ("changes", "repo-hygiene", "test-linux"):
        assert "if" not in jobs[name], f"{name} must run on every PR"


def test_the_linux_baseline_runs_the_same_steps_as_the_matrix(jobs: dict) -> None:
    """`test-linux` is the matrix leg moved out so it can run on every PR. Its steps are
    a copy, so this is what stops the copy drifting from the original."""
    assert jobs["test-linux"]["steps"] == jobs["test"]["steps"]
    assert jobs["test-linux"]["name"] == "test (${{ matrix.os }}, ${{ matrix.python-version }})"


def test_the_matrix_excludes_exactly_the_baseline_leg(jobs: dict) -> None:
    baseline = jobs["test-linux"]["strategy"]["matrix"]
    leg = {"os": baseline["os"][0], "python-version": baseline["python-version"][0]}
    assert len(baseline["os"]) == len(baseline["python-version"]) == 1
    assert jobs["test"]["strategy"]["matrix"]["exclude"] == [leg]


def test_the_only_required_workflow_is_never_path_filtered() -> None:
    """CI_POLICY section 4: no broad paths-ignore on the only stable required check."""
    triggers = _workflow("test.yml")[True]
    for event in ("pull_request", "push"):
        assert "paths" not in triggers[event]
        assert "paths-ignore" not in triggers[event]


def test_a_manual_full_run_is_available() -> None:
    triggers = _workflow("test.yml")[True]
    assert "workflow_dispatch" in triggers
    assert triggers["push"]["branches"] == ["main"]


def test_the_changes_job_takes_the_full_lane_on_any_doubt() -> None:
    """Non-PR events and the `ci:full` label short-circuit to full, the diff is taken
    without rename detection, and the step runs under pipefail."""
    step = next(
        s for s in _workflow("test.yml")["jobs"]["changes"]["steps"] if s.get("id") == "lanes"
    )
    run = step["run"]
    assert step["shell"] == "bash"
    assert 'if [ "$EVENT_NAME" != "pull_request" ]' in run
    assert "ci:full" in step["env"]["FULL_LABEL"]
    assert "git diff --name-only --no-renames HEAD^1 HEAD" in run
    assert run.count('echo "full=true" >> "$GITHUB_OUTPUT"') == 3
