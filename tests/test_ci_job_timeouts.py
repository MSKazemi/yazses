"""Every job in `test.yml` declares its own `timeout-minutes` (CI_POLICY.md §8).

A job without one inherits GitHub's six-hour default, and nothing turns red while it
waits: on PR #625 `repo-hygiene` sat in a hung `apt-get update` for 78 minutes until it
was cancelled by hand. The job list is read from the workflow, not written out here, so a
job added later is covered the moment it exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

TEST_YML = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "test.yml"
JOBS = yaml.safe_load(TEST_YML.read_text(encoding="utf-8"))["jobs"]


def test_the_workflow_has_jobs_to_check() -> None:
    assert len(JOBS) >= 5, "test.yml parsed to almost no jobs; the guard below would be inert"


@pytest.mark.parametrize("name", sorted(JOBS))
def test_every_job_declares_a_timeout(name: str) -> None:
    timeout = JOBS[name].get("timeout-minutes")
    assert isinstance(timeout, int) and 0 < timeout <= 60, (
        f"job {name!r} in test.yml needs `timeout-minutes` (1-60); without it a hang holds "
        "a runner for GitHub's 6-hour default"
    )
