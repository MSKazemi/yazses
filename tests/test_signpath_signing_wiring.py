"""The Windows signing path is gated on secrets, so nothing ever executes it.

`build-windows.yml` only signs when four `SIGNPATH_*` secrets are present. They have
never been set, so every green Windows build has taken the `sign == 'false'` branch and
the signing steps have never run even once. A mistake in them is therefore invisible
until the first signed release -- which is the release where a mistake costs the most,
because the Windows installers are the artifacts that would be missing.

One such mistake was already there: `github-artifact-id` was passed `github.run_id`,
which identifies the workflow *run*, not the uploaded *artifact*. These tests read the
workflow itself so the wiring is checked without needing the secrets.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github/workflows/build-windows.yml"


def _steps() -> list[dict]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = doc["jobs"]
    for job in jobs.values():
        steps = job.get("steps") or []
        if any("signpath" in str(s.get("uses", "")).lower() for s in steps):
            return steps
    raise AssertionError("no job in build-windows.yml uses the SignPath action")


def _step_using(steps: list[dict], needle: str) -> dict:
    for step in steps:
        if needle in str(step.get("uses", "")):
            return step
    raise AssertionError(f"no step uses {needle!r}")


def test_the_signing_step_is_handed_an_artifact_id_not_a_run_id():
    """The action's own input description asks for the upload step's artifact-id.

    `github.run_id` is a valid-looking number that identifies something else entirely,
    so SignPath would resolve it to no artifact. Nothing about that is visible until
    the secrets exist.
    """
    steps = _steps()
    sign = _step_using(steps, "signpath/github-action-submit-signing-request")
    value = str(sign["with"]["github-artifact-id"])

    assert "github.run_id" not in value, (
        "github-artifact-id is the id of the uploaded ARTIFACT, not of the workflow run; "
        f"got {value!r}"
    )
    assert "outputs.artifact-id" in value, (
        "github-artifact-id must come from an actions/upload-artifact step's "
        f"artifact-id output; got {value!r}"
    )


def test_the_referenced_upload_step_exists_and_is_an_upload_artifact_step():
    """A `steps.<id>.outputs` reference to a step that has no `id` silently yields ''."""
    steps = _steps()
    sign = _step_using(steps, "signpath/github-action-submit-signing-request")
    value = str(sign["with"]["github-artifact-id"])

    # steps.<id>.outputs.artifact-id
    step_id = value.split("steps.", 1)[1].split(".", 1)[0]
    referenced = [s for s in steps if s.get("id") == step_id]
    assert referenced, (
        f"github-artifact-id references step id {step_id!r}, but no step declares it"
    )
    assert "actions/upload-artifact" in str(referenced[0].get("uses", "")), (
        f"step {step_id!r} is not an actions/upload-artifact step, so it publishes no "
        "artifact-id output"
    )


def test_the_signing_wait_survives_a_policy_that_needs_human_approval():
    """A SignPath Foundation policy may require a person to approve each request.

    The action's default wait is 600 s. Ten minutes is not enough to notice a mail and
    click approve, and the failure mode is a release with no Windows installer at all.
    The upper bound matters too: checksums.yml waits 45 min for producer workflows, and
    a signing wait longer than that would let SHA256SUMS.txt be generated without the
    .exe it is supposed to cover.
    """
    sign = _step_using(_steps(), "signpath/github-action-submit-signing-request")
    wait = int(sign["with"]["wait-for-completion-timeout-in-seconds"])

    assert wait >= 900, f"a {wait}s wait cannot absorb a manual signing approval"
    assert wait <= 2700, (
        f"a {wait}s signing wait can outlast the 2700s producer wait in checksums.yml, "
        "which would publish SHA256SUMS.txt without the Windows installers"
    )


def test_the_signed_binary_replaces_the_unsigned_one_before_it_is_hashed_or_attested():
    """Signing changes the bytes, so everything downstream must see the signed file.

    v2.32.0 published a SHA256SUMS.txt that matched neither Windows installer. That was
    a different cause, but it is the same blast radius: Scoop and Chocolatey derive
    their manifests from those hashes and simply refuse to install on a mismatch.
    """
    steps = _steps()
    names = [str(s.get("name", "")) for s in steps]

    def index_of(predicate) -> int:
        for i, step in enumerate(steps):
            if predicate(step):
                return i
        return -1

    replace = index_of(lambda s: "Replace unsigned installer" in str(s.get("name", "")))
    attest = index_of(lambda s: "attest-build-provenance" in str(s.get("uses", "")))
    release = index_of(lambda s: "action-gh-release" in str(s.get("uses", "")))

    assert replace != -1, f"no step replaces the unsigned installer; steps: {names}"
    assert attest > replace, "provenance is attested before the signed binary is in place"
    assert release > replace, "the release is uploaded before the signed binary is in place"
