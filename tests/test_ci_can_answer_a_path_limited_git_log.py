"""The test job's checkout must be able to answer `git log -- <path>`.

`hooks/sitemap_dates.py` gives each sitemap entry the date of the last commit that
touched that page, so rebuilding the site does not make hundreds of old pages look
newly edited. It asks git:

    git log -1 --format=%cs -- docs/index.md

That query is *path-limited*, and deciding which commits touched a path requires the
commit trees. `actions/checkout` with `filter: tree:0` fetches none of them, so git
falls back to pulling trees one at a time from the promisor remote; the hook's 10 s
timeout expires, it returns `None`, and the date becomes `""`.

The result was a CI failure that no developer machine could reproduce -- red on all
eight matrix legs, green in every local checkout -- for a hook that is completely
correct. Measured against real clones of this repository:

    --filter=tree:0     fatal: could not fetch <tree> from promisor remote
    --filter=blob:none  2026-08-26

`blob:none` keeps the trees and skips the file contents, which is where nearly all of
the size is. `fetch-depth: 0` is a separate requirement (the packaging guards compare
manifests against the latest release *tag*) and is not what broke this.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "test.yml"


def _checkout_steps(job: dict) -> list[dict]:
    return [
        step
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("actions/checkout")
    ]


@pytest.fixture(scope="module")
def jobs() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def test_the_test_job_does_not_use_a_treeless_clone(jobs: dict) -> None:
    steps = _checkout_steps(jobs["test"])
    assert steps, "the test job no longer checks the repository out"
    for step in steps:
        filt = (step.get("with") or {}).get("filter")
        assert filt != "tree:0", (
            "a treeless clone cannot answer `git log -- <path>`, which "
            "hooks/sitemap_dates.py needs; use blob:none"
        )


def test_the_test_job_still_fetches_the_whole_history(jobs: dict) -> None:
    """Guards the fix in the other direction.

    Dropping the filter is not the same as dropping `fetch-depth: 0`, and without the
    tags the packaging-manifest guards hit their shallow-clone skip and pass silently.
    """
    steps = _checkout_steps(jobs["test"])
    depths = [(step.get("with") or {}).get("fetch-depth") for step in steps]
    assert 0 in depths, "the packaging guards need the tags; keep fetch-depth: 0"


def test_the_hook_that_needs_the_trees_still_asks_a_path_limited_question() -> None:
    """If the hook stops needing path-limited history, this constraint can be relaxed.

    Pinned so the workflow comment cannot outlive the reason for it.
    """
    source = (
        Path(__file__).resolve().parents[1] / "hooks" / "sitemap_dates.py"
    ).read_text(encoding="utf-8")
    assert '"log", "-1", "--format=%cs", "--", relative' in source, (
        "sitemap_dates.py no longer runs a path-limited git log -- "
        "re-check whether the checkout filter still matters"
    )
