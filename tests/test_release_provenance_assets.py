"""A release that attests its artifacts must also *attach* the attestation.

`actions/attest-build-provenance` writes the provenance bundle into GitHub's
attestations API. `gh attestation verify` finds it there, so from inside the project
the work looks finished -- and issue #116 recorded Signed-Releases as done on that
basis.

OpenSSF Scorecard does not look there. Its `Signed-Releases` check reads the
**filenames of the last five releases' assets** and counts only these suffixes:

    .asc  .sig  .sign  .minisig  .sigstore  .sigstore.json  .intoto.jsonl

So v2.19.0 and v2.20.0 both shipped fully attested and scored **0/10**, and the live
API still reported "Project has not signed or included provenance with any
releases." The gap was never the signing; it was that nothing the verifier can see
was published.

Attaching the bundle is also right on its own merits: someone who downloaded a
release artifact and is now offline, or behind a firewall, can verify it against a
file that came with it rather than against an API call they cannot make.

This guard is deliberately structural rather than a string match on one workflow.
Three workflows attest and attach releases, they were written at different times,
and the previous failure mode here was one of them silently diverging.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github/workflows").glob("*.yml"))

ATTEST_ACTION = "actions/attest-build-provenance"
RELEASE_ACTION = "softprops/action-gh-release"

#: Exactly what Scorecard's Signed-Releases check accepts. Keep in step with
#: https://github.com/ossf/scorecard/blob/main/docs/checks.md#signed-releases
SCORECARD_PROVENANCE_SUFFIXES = (
    ".asc", ".sig", ".sign", ".minisig", ".sigstore", ".sigstore.json", ".intoto.jsonl",
)


def _steps(workflow: dict):
    for job in (workflow.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            yield step


def _uses(step: dict) -> str:
    return str(step.get("uses") or "")


def _release_files(step: dict) -> str:
    return str((step.get("with") or {}).get("files") or "")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _workflows_that_attest_and_release() -> list[Path]:
    found = []
    for path in WORKFLOWS:
        steps = list(_steps(_load(path)))
        attests = any(ATTEST_ACTION in _uses(s) for s in steps)
        releases = any(RELEASE_ACTION in _uses(s) for s in steps)
        if attests and releases:
            found.append(path)
    return found


def test_some_workflow_attests_and_releases():
    """Guard the guard: a rename must not turn this file into a no-op."""
    assert _workflows_that_attest_and_release(), (
        f"no workflow uses both {ATTEST_ACTION} and {RELEASE_ACTION} -- if one was "
        f"renamed, update this test rather than deleting it"
    )


@pytest.mark.parametrize(
    "path", _workflows_that_attest_and_release(), ids=lambda p: p.name
)
def test_an_attesting_release_publishes_a_verifiable_bundle(path: Path):
    """Attesting without attaching leaves Signed-Releases at 0/10 -- silently."""
    release_steps = [s for s in _steps(_load(path)) if RELEASE_ACTION in _uses(s)]
    for step in release_steps:
        files = _release_files(step)
        assert any(suffix in files for suffix in SCORECARD_PROVENANCE_SUFFIXES), (
            f"{path.name}: this workflow attests its build but the release step "
            f"attaches only {files.split() or ['(nothing)']}. Scorecard reads asset "
            f"filenames, not the attestations API, so the provenance is invisible to "
            f"it. Attach the bundle from the attest step's `bundle-path` output with "
            f"one of {list(SCORECARD_PROVENANCE_SUFFIXES)}."
        )


@pytest.mark.parametrize(
    "path", _workflows_that_attest_and_release(), ids=lambda p: p.name
)
def test_the_attest_step_is_addressable_so_its_bundle_can_be_attached(path: Path):
    """`bundle-path` is only reachable through a step `id`."""
    for step in _steps(_load(path)):
        if ATTEST_ACTION in _uses(step):
            assert step.get("id"), (
                f"{path.name}: the {ATTEST_ACTION} step has no `id`, so "
                f"`steps.<id>.outputs.bundle-path` cannot be referenced and the "
                f"bundle cannot be attached to the release"
            )
