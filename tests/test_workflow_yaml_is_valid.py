"""GitHub Actions workflows must parse the way GitHub parses them.

`yaml.safe_load` is not that. YAML resolves a duplicate mapping key by keeping the
last one **silently**, so a workflow with `id-token: write` listed twice loads
cleanly in Python and is rejected by GitHub at validation time — the run appears
with no jobs at all and no log to read, which is a genuinely confusing failure.

That happened here: a `permissions:` block already had `id-token: write` for
SignPath OIDC, an edit added it again for build provenance, a `safe_load` check
passed, and the Windows workflow failed on push.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / ".github/workflows").glob("*.yml"))


class _StrictLoader(yaml.SafeLoader):
    """SafeLoader that refuses duplicate keys instead of silently overwriting."""


def _no_duplicate_keys(loader, node, deep=False):
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


def test_there_are_workflows_to_check():
    """Guards against the glob silently matching nothing."""
    assert len(WORKFLOWS) >= 5


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_duplicate_keys(path: Path):
    yaml.load(path.read_text(encoding="utf-8"), _StrictLoader)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_job_has_steps_and_a_runner(path: Path):
    """A structural check a parse alone does not make."""
    doc = yaml.load(path.read_text(encoding="utf-8"), _StrictLoader)
    for name, job in (doc.get("jobs") or {}).items():
        if "uses" in job:      # a reusable-workflow call has no steps of its own
            continue
        assert job.get("runs-on"), f"{path.name}:{name} has no runs-on"
        assert job.get("steps"), f"{path.name}:{name} has no steps"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_attestation_jobs_declare_the_permissions_they_need(path: Path):
    """`attest-build-provenance` fails at runtime without both of these, and the
    failure surfaces only on a tag build — the one run nobody wants to debug."""
    doc = yaml.load(path.read_text(encoding="utf-8"), _StrictLoader)
    for name, job in (doc.get("jobs") or {}).items():
        steps = job.get("steps") or []
        if not any("attest-build-provenance" in str(s.get("uses", "")) for s in steps):
            continue
        perms = job.get("permissions") or {}
        assert perms.get("id-token") == "write", f"{path.name}:{name} needs id-token: write"
        assert perms.get("attestations") == "write", f"{path.name}:{name} needs attestations: write"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_grants_a_write_permission_at_the_top_level(path: Path):
    """A write scope belongs to the job that uses it, never to the file.

    A top-level `permissions:` block is inherited by every job that does not declare
    its own, so `contents: write` at the top of a file is a standing grant to whatever
    is added to that file next -- and what gets added next is written by someone
    reading the job above it, not the header. Three workflows here were in exactly
    that state, and the three most exposed ones: `dependabot-sbom.yml`,
    `first-interaction.yml` and `labeler.yml` all run on `pull_request_target`, which
    is the trigger that hands out a genuinely writable token.

    Keeping the top read-only costs one repeated line per job -- job-level permissions
    replace the top-level block rather than merging with it -- and buys a file where
    adding a job cannot silently widen what it can do.
    """
    doc = yaml.load(path.read_text(encoding="utf-8"), _StrictLoader)
    top = doc.get("permissions")
    assert top is not None, (
        f"{path.name} declares no top-level permissions, so every job inherits the "
        "repository default rather than a stated one"
    )
    if isinstance(top, dict):
        writes = sorted(k for k, v in top.items() if v == "write")
        assert not writes, (
            f"{path.name} grants {writes} to every job in the file. Move it onto the "
            "job that needs it (remembering that a job block replaces this one, so "
            "any read scopes it also uses have to be repeated there)."
        )
    else:
        assert top in ("read-all", "none"), f"{path.name} has top-level permissions: {top!r}"


def test_some_job_actually_needs_a_write_permission():
    """The vacuity anchor for the check above.

    If every write scope ever disappeared -- or the parse quietly started returning
    nothing -- that test would pass on all 29 files while asserting nothing at all.
    This project publishes releases, pushes to an APT branch and comments on pull
    requests, so at least one job must be asking for write somewhere.
    """
    granted = {
        f"{path.name}:{name}": sorted(k for k, v in perms.items() if v == "write")
        for path in WORKFLOWS
        for name, job in (
            yaml.load(path.read_text(encoding="utf-8"), _StrictLoader).get("jobs") or {}
        ).items()
        for perms in [job.get("permissions") or {}]
        if isinstance(perms, dict) and any(v == "write" for v in perms.values())
    }
    assert len(granted) >= 5, (
        "almost no job asks for a write permission any more, which means the "
        f"top-level check is guarding an empty set: {granted}"
    )
