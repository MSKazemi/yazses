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
