"""`ci-gate` is the one stable check a branch ruleset can require (#462, ADR-024 §9).

The Tests workflow produces a matrix of check names (``test (ubuntu-latest, 3.12)``,
``GUI (Qt) — windows-latest``, ...) that changes whenever a leg is added or renamed.
A ruleset cannot list those without drifting, so ``ci-gate`` aggregates them: it
``needs`` every blocking job and passes only when each one's result is ``success``.

An aggregate gate fails in quiet ways, and each test below pins one of them:

* **A blocking job drops out of ``needs``.** The gate stays green and stops guarding
  that job, and no run will ever show it. So the expected set is *derived from the
  workflow file*, never written out here. A hand-written list is this repository's
  most repeated defect: it agrees with the file on the day it is written and then
  goes stale without failing.
* **An advisory job becomes a need.** ``freebsd`` is ``continue-on-error`` because it
  is allowed to fail (CI_POLICY.md §9). As a need, it could make every PR unmergeable.
* **The gate skips.** GitHub reports a skipped required check as "Success" and lets
  the PR merge ("Using conditions to control job execution"). ``if: always()`` is
  the only condition under which the gate always runs and gives a real verdict.
* **The gate is filtered out.** With a ``paths`` filter on the workflow, a PR that
  did not touch those paths would never get the check and would wait on it forever.
* **The verdict code passes something it should not.** The embedded script is run
  here against ``needs`` payloads for success, failure, cancellation, skip and
  malformed or empty input. The same script text runs in CI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "test.yml"
GATE = "ci-gate"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


@pytest.fixture(scope="module")
def workflow() -> dict:
    return _load(WORKFLOW)


@pytest.fixture(scope="module")
def jobs(workflow: dict) -> dict:
    return workflow["jobs"]


@pytest.fixture(scope="module")
def gate(jobs: dict) -> dict:
    assert GATE in jobs, f"test.yml has no `{GATE}` job; the ruleset requires it by name"
    return jobs[GATE]


def advisory_jobs(jobs: dict) -> set[str]:
    """Jobs allowed to fail as a whole: a literal ``continue-on-error: true``.

    An *expression* (the ``test`` matrix's ``${{ matrix.experimental == true }}``)
    does not make the job advisory. It makes one leg advisory, and the job's other
    legs are blocking, so the job stays a need.
    """
    return {name for name, job in jobs.items() if job.get("continue-on-error") is True}


def blocking_jobs(jobs: dict) -> set[str]:
    return set(jobs) - advisory_jobs(jobs) - {GATE}


def _needs(gate: dict) -> list[str]:
    needs = gate.get("needs")
    # A bare string is valid YAML for one need. Normalise it so that the comparison
    # below is about the job set, not about the spelling.
    return [needs] if isinstance(needs, str) else list(needs or [])


def _verdict_step(gate: dict) -> dict:
    steps = [s for s in gate.get("steps", []) if "NEEDS_JSON" in (s.get("env") or {})]
    assert len(steps) == 1, "ci-gate must have exactly one step that reads NEEDS_JSON"
    return steps[0]


# ── The derivation is shown to find something, both ways ──────────────────────


def test_the_derivation_finds_the_jobs_it_exists_for(jobs: dict) -> None:
    """A guard that iterates is green on an empty set. Anchor it in both directions."""
    blocking = blocking_jobs(jobs)
    assert {"repo-hygiene", "test"} <= blocking, blocking
    assert "freebsd" in advisory_jobs(jobs), (
        "freebsd is no longer `continue-on-error: true`. If it was promoted to "
        "blocking, that is fine: update this anchor, and the gate test below will "
        "require it to be a need."
    )


# ── needs: every blocking job, no advisory job ────────────────────────────────


def test_the_gate_needs_every_blocking_job(jobs: dict, gate: dict) -> None:
    missing = blocking_jobs(jobs) - set(_needs(gate))
    assert not missing, (
        f"blocking job(s) {sorted(missing)} are not in ci-gate's `needs`. The gate "
        "would pass without them, and branch protection requires only the gate. "
        "Add them, or mark the job `continue-on-error: true` and record why "
        "(CI_POLICY.md §9)."
    )


def test_no_advisory_job_can_turn_the_gate_red(jobs: dict, gate: dict) -> None:
    leaked = advisory_jobs(jobs) & set(_needs(gate))
    assert not leaked, (
        f"advisory job(s) {sorted(leaked)} are needs of ci-gate. They are allowed "
        "to fail, so as needs they would block every PR."
    )


def test_the_gate_needs_nothing_that_does_not_exist(jobs: dict, gate: dict) -> None:
    needs = _needs(gate)
    assert len(needs) == len(set(needs)), f"duplicate needs: {needs}"
    unknown = set(needs) - set(jobs)
    assert not unknown, f"ci-gate needs undefined job(s): {sorted(unknown)}"
    assert GATE not in needs


def test_no_blocking_job_can_skip(jobs: dict) -> None:
    """The gate fails a ``skipped`` need, so a job-level ``if:`` would fail it.

    That is the safe reading of "skipped unexpectedly". A blocking job that has to
    be conditional, for example path-scoped, needs an explicit, tested skip
    allowance in the gate first. It should not be discovered as a red gate on the
    first PR that does not match the condition.
    """
    conditional = sorted(name for name in blocking_jobs(jobs) if "if" in jobs[name])
    assert not conditional, (
        f"blocking job(s) {conditional} have a job-level `if:`; ci-gate treats their "
        "skip as a failure. Extend the gate deliberately before adding one."
    )


# ── The gate always runs, under one stable name ───────────────────────────────


def test_the_gate_always_runs(gate: dict) -> None:
    condition = str(gate.get("if", "")).strip()
    assert condition in {"always()", "${{ always() }}"}, (
        f"ci-gate has `if: {condition or '<none>'}`. Without always() it skips when "
        "a need fails, and a skipped required check counts as passed."
    )


def test_the_gate_has_one_stable_name(gate: dict) -> None:
    assert gate.get("name") == GATE, "the check name is what the ruleset requires"
    assert "strategy" not in gate, "a matrix would turn the stable name into many names"
    assert "continue-on-error" not in gate, "the gate itself must be able to fail"
    assert isinstance(gate.get("timeout-minutes"), int)


def test_no_other_workflow_reports_a_check_called_ci_gate() -> None:
    """Two jobs with the same check name make the requirement ambiguous."""
    owners = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for job_id, job in (_load(path).get("jobs") or {}).items():
            if GATE in (job_id, (job or {}).get("name")):
                owners.append(f"{path.name}:{job_id}")
    assert owners == [f"test.yml:{GATE}"], owners


def test_the_gate_is_present_on_every_pull_request_to_main(workflow: dict) -> None:
    """A path or type filter would leave the required check pending forever."""
    # YAML 1.1 parses the key `on:` as boolean True.
    triggers = workflow.get(True, workflow.get("on")) or {}
    pr = triggers.get("pull_request")
    assert isinstance(pr, dict), "test.yml must run on pull_request"
    assert "main" in pr.get("branches", []), pr
    for key in ("paths", "paths-ignore", "branches-ignore"):
        assert key not in pr, (
            f"test.yml's pull_request trigger has `{key}`. A PR the filter excludes "
            "would never report ci-gate, and a required check that never reports "
            "blocks the merge forever (CI_POLICY.md §4)."
        )
    types = pr.get("types")
    if types is not None:
        assert {"opened", "synchronize", "reopened"} <= set(types), types
    assert "main" in (triggers.get("push") or {}).get("branches", []), (
        "main pushes must keep producing the gate on the merged commit"
    )


# ── The verdict reads only the needs context ──────────────────────────────────


def test_the_gate_executes_nothing_from_the_checkout(gate: dict) -> None:
    uses = [s.get("uses", "") for s in gate.get("steps", [])]
    assert not any(str(u).startswith("actions/checkout") for u in uses), (
        "ci-gate computes its verdict from `needs` alone and checks nothing out"
    )


def test_results_reach_the_script_as_data_not_as_code(gate: dict) -> None:
    step = _verdict_step(gate)
    assert step["env"]["NEEDS_JSON"] == "${{ toJSON(needs) }}"
    assert "${{" not in step["run"], "no expression interpolation inside the script"
    assert step.get("shell") == "python3 {0}", (
        "the verdict tests below run the script with Python; keep the shell matching"
    )


def _run_verdict(gate: dict, tmp_path: Path, needs_json: str | None):
    script = tmp_path / "ci_gate_verdict.py"
    script.write_text(_verdict_step(gate)["run"], encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "NEEDS_JSON"}
    if needs_json is not None:
        env["NEEDS_JSON"] = needs_json
    return subprocess.run(
        [sys.executable, str(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _payload(jobs: dict, **overrides: str) -> str:
    """A needs context shaped like GitHub's: one entry per need, result + outputs."""
    results = {name: "success" for name in sorted(blocking_jobs(jobs))}
    results.update(overrides)
    return json.dumps({name: {"result": r, "outputs": {}} for name, r in results.items()})


def test_all_blocking_jobs_green_passes(jobs: dict, gate: dict, tmp_path: Path) -> None:
    proc = _run_verdict(gate, tmp_path, _payload(jobs))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "blocking jobs succeeded" in proc.stdout


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", "", "neutral"])
def test_any_non_success_result_fails_the_gate(
    jobs: dict, gate: dict, tmp_path: Path, result: str
) -> None:
    proc = _run_verdict(gate, tmp_path, _payload(jobs, gui=result))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert f"gui={result}" in proc.stdout, "the failing job must be named in the log"


@pytest.mark.parametrize(
    "needs_json",
    [None, "", "null", "{}", "[]", "not json", '{"test": "success"}', '{"test": {}}'],
    ids=["unset", "empty-string", "null", "empty-object", "list", "malformed",
         "not-an-object-entry", "no-result-key"],
)
def test_an_unreadable_or_empty_verdict_is_not_green(
    gate: dict, tmp_path: Path, needs_json: str | None
) -> None:
    """A check that cannot parse its input must fail rather than report compliance."""
    proc = _run_verdict(gate, tmp_path, needs_json)
    assert proc.returncode == 1, proc.stdout + proc.stderr
