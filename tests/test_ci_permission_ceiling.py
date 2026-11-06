"""No workflow job gains a write scope without a reviewed change here (CI_POLICY.md §7, #537).

`test_workflow_yaml_is_valid.py` keeps every top-level `permissions:` block read-only, so a
write scope can only come from a job. That stops a standing grant to every job in a file;
it does not stop one job from quietly asking for more. A job-level `permissions:` block
*replaces* the top-level one, so `packages: write` added to a test job, or `contents:
write` added to a job that runs the shared setup composite, would pass every other guard.

This file pins the ceiling. `WRITE_GRANTS` is every job's effective write scopes on the
day it was written, and the workflows are compared with it both ways:

* a job that gains a write scope, or a new job that holds one, fails until the scope is
  added here, so the widening is a line a reviewer reads in the same diff;
* a job that drops one fails until its entry shrinks, so the ceiling never stays wider
  than what is used.

`write-all` and any other string except `read-all` / `none` are refused outright. Reuse
through `./.github/actions/*` cannot widen a token (that composite declares no
`permissions:`, see `test_ci_composite_actions.py`), and this file is what shows that the
jobs calling it did not widen theirs either.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

#: `workflow:job` -> the scopes it may hold at `write`. Read from the workflows on
#: 2026-11-06 (main 6cd4a27f). Growing this is a security decision: say why in the PR.
WRITE_GRANTS: dict[str, frozenset[str]] = {
    "apt-repo.yml:update-apt-repo": frozenset({"contents", "actions"}),
    "build-macos.yml:build": frozenset({"contents", "id-token", "attestations"}),
    "build-windows.yml:build": frozenset({"contents", "id-token", "attestations"}),
    "channel-drift.yml:watch": frozenset({"issues"}),
    "checksums.yml:checksums": frozenset({"contents"}),
    "codeql.yml:analyze": frozenset({"security-events"}),
    "dependabot-sbom.yml:refresh-sbom": frozenset({"contents"}),
    "dependency-review.yml:dependency-review": frozenset({"pull-requests"}),
    "docker.yml:build": frozenset({"packages", "id-token", "attestations"}),
    "docs.yml:deploy": frozenset({"pages", "id-token"}),
    "first-interaction.yml:greet": frozenset({"issues", "pull-requests"}),
    "huggingface-publish.yml:publish": frozenset({"id-token"}),
    "labeler.yml:label": frozenset({"pull-requests"}),
    "release-complete.yml:verify": frozenset({"contents"}),
    "release.yml:publish-mcp-registry": frozenset({"id-token"}),
    "release.yml:publish-pypi": frozenset({"id-token"}),
    "release.yml:release-linux": frozenset({"contents", "id-token", "attestations"}),
    "scorecard.yml:analysis": frozenset({"security-events", "id-token"}),
}

_STRING_FORMS = ("read-all", "none")


def _jobs() -> dict[str, tuple[object, object]]:
    """`workflow:job` -> (the job's `permissions`, the file's top-level `permissions`)."""
    jobs: dict[str, tuple[object, object]] = {}
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for name, job in (doc.get("jobs") or {}).items():
            jobs[f"{path.name}:{name}"] = ((job or {}).get("permissions"), doc.get("permissions"))
    return jobs


JOBS = _jobs()


def _effective_writes(job_perms: object, top_perms: object) -> frozenset[str]:
    """A job block replaces the file's block; with no job block the file's applies."""
    perms = top_perms if job_perms is None else job_perms
    if isinstance(perms, str):
        assert perms in _STRING_FORMS, f"permissions: {perms!r} is not allowed (CI_POLICY.md §7)"
        return frozenset()
    return frozenset(scope for scope, level in (perms or {}).items() if level == "write")


def test_the_scan_sees_the_jobs() -> None:
    assert len(JOBS) >= 40, f"only {len(JOBS)} jobs parsed; the ceiling below would be inert"


@pytest.mark.parametrize("label", sorted(JOBS))
def test_no_job_uses_a_string_permission_other_than_read_all_or_none(label: str) -> None:
    for perms in JOBS[label]:
        if isinstance(perms, str):
            assert perms in _STRING_FORMS, (
                f"{label} sets `permissions: {perms}`. `write-all` grants every scope; list "
                "the scopes the job needs instead (CI_POLICY.md §7)"
            )


def test_no_job_holds_a_write_scope_beyond_the_ceiling() -> None:
    actual = {label: _effective_writes(*perms) for label, perms in JOBS.items()}
    grown = {
        label: sorted(scopes - WRITE_GRANTS.get(label, frozenset()))
        for label, scopes in actual.items()
        if scopes - WRITE_GRANTS.get(label, frozenset())
    }
    assert not grown, (
        f"these jobs hold write scopes the ceiling does not list: {grown}. Grant write at "
        "the narrowest job boundary (CI_POLICY.md §7 rule 1); if the job really needs it, "
        "add it to WRITE_GRANTS and say why in the PR."
    )


def test_the_ceiling_is_no_wider_than_what_the_jobs_hold() -> None:
    actual = {label: _effective_writes(*perms) for label, perms in JOBS.items()}
    unused = {
        label: sorted(scopes - actual.get(label, frozenset()))
        for label, scopes in WRITE_GRANTS.items()
        if scopes - actual.get(label, frozenset())
    }
    assert not unused, (
        f"WRITE_GRANTS allows scopes these jobs no longer hold (or the job is gone): {unused}. "
        "Shrink the entry so the ceiling cannot be re-used silently."
    )
