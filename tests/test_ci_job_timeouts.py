"""Every job in every workflow declares its own `timeout-minutes` (CI_POLICY.md §8).

A job without one inherits GitHub's six-hour default, and nothing turns red while it
waits: on PR #625 `repo-hygiene` sat in a hung `apt-get update` for 78 minutes until it
was cancelled by hand. The job list is read from the workflows, not written out here, so
a job added later is covered the moment it exists.

A job that waits for other workflows by design (`checksums`, `publish-channels`,
`release-complete`) carries its own deadline inside a step, and that deadline decides
what a slow build costs: `checksums` treats an advisory leg that never arrives as "hash
what is there", not as failure. A job limit below the job's own deadline would cancel it
first and turn that decision into a red release, so the limit must sit above the waits.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
TEST_YML = WORKFLOWS / "test.yml"
JOBS = yaml.safe_load(TEST_YML.read_text(encoding="utf-8"))["jobs"]

ALL_JOBS = {
    f"{path.name}:{name}": job
    for path in sorted(WORKFLOWS.glob("*.y*ml"))
    for name, job in (yaml.safe_load(path.read_text(encoding="utf-8")).get("jobs") or {}).items()
    # A job that calls a reusable workflow cannot set timeout-minutes; the callee's jobs do.
    if "uses" not in job
}

#: Room left for the job's real work once its waits have run out.
WAIT_MARGIN_MIN = 10


def own_wait_seconds(job: dict) -> int:
    """The longest a job's own steps can spend waiting, read from their shell.

    Two shapes occur: ``deadline=$(( SECONDS + N ))`` and ``for attempt in $(seq 1 N)``
    around a ``sleep S``.
    """
    total = 0
    for step in job.get("steps") or []:
        run = step.get("run") or ""
        total += sum(int(n) for n in re.findall(r"SECONDS\s*\+\s*(\d+)", run))
        for count in re.findall(r"\$\(seq 1 (\d+)\)", run):
            sleeps = re.findall(r"\bsleep (\d+)\b", run)
            total += int(count) * max((int(s) for s in sleeps), default=0)
    return total


def test_the_workflow_has_jobs_to_check() -> None:
    assert len(JOBS) >= 5, "test.yml parsed to almost no jobs; the guard below would be inert"
    assert len(ALL_JOBS) >= 40, "the workflows parsed to almost no jobs; the guards below would be inert"


@pytest.mark.parametrize("name", sorted(JOBS))
def test_every_job_declares_a_timeout(name: str) -> None:
    timeout = JOBS[name].get("timeout-minutes")
    assert isinstance(timeout, int) and 0 < timeout <= 60, (
        f"job {name!r} in test.yml needs `timeout-minutes` (1-60); without it a hang holds "
        "a runner for GitHub's 6-hour default"
    )


@pytest.mark.parametrize("name", sorted(ALL_JOBS))
def test_every_job_in_every_workflow_declares_a_timeout(name: str) -> None:
    timeout = ALL_JOBS[name].get("timeout-minutes")
    # 180 is a sanity bound, not a target: the longest today is the dispatch-only
    # benchmark matrix at 150.
    assert isinstance(timeout, int) and 0 < timeout <= 180, (
        f"job {name} needs `timeout-minutes` (1-180), chosen by the rule in CI_POLICY.md §8; "
        "without it a hang holds a runner for GitHub's 6-hour default"
    )


@pytest.mark.parametrize("name", sorted(n for n, j in ALL_JOBS.items() if own_wait_seconds(j)))
def test_a_waiting_job_outlasts_its_own_deadlines(name: str) -> None:
    job = ALL_JOBS[name]
    waits = own_wait_seconds(job)
    assert job["timeout-minutes"] * 60 >= waits + WAIT_MARGIN_MIN * 60, (
        f"job {name} can wait {waits // 60} min by its own deadlines, but its limit is "
        f"{job['timeout-minutes']} min; raise it to at least {waits // 60 + WAIT_MARGIN_MIN} "
        "so the job's deadline, not the runner, decides how a slow build is treated"
    )


def test_the_wait_reader_sees_both_shapes() -> None:
    job = {"steps": [
        {"run": "deadline=$(( SECONDS + 2700 ))   # 45 minutes\nsleep 60"},
        {"run": "for attempt in $(seq 1 60); do\n  sleep 30\ndone"},
        {"uses": "actions/checkout@v4"},
    ]}
    assert own_wait_seconds(job) == 2700 + 60 * 30


def test_the_known_waiting_jobs_are_found() -> None:
    waiting = {n for n, j in ALL_JOBS.items() if own_wait_seconds(j)}
    assert {
        "checksums.yml:checksums",
        "publish-channels.yml:wait-for-assets",
        "release-complete.yml:verify",
    } <= waiting, waiting
