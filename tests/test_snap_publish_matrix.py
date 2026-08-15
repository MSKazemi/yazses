"""Every architecture the snap declares must actually reach `stable`.

Issue #267: `snap/snapcraft.yaml` declared `platforms: [amd64, arm64]` and the
packaging table advertised "incl. arm64", but `.github/workflows/snap.yml` — the
**only** publisher to `latest/stable` — ran on a single amd64 runner. So stable
carried an amd64 revision and nothing else, and `snap install yazses` on a
Raspberry Pi could not resolve a revision at all. arm64 existed only on `edge`,
fed by the snapcraft.io build service, and drifted two releases behind.

The declaration and the publisher were in separate files with nothing tying them
together, so the gap was invisible until someone queried the store API. This
module is that tie: add a platform to snapcraft.yaml without giving it a runner
and the suite fails here rather than in a user's `snap install`.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SNAPCRAFT = ROOT / "snap" / "snapcraft.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "snap.yml"


def _declared_platforms() -> set[str]:
    """Architectures from snapcraft.yaml's top-level `platforms:` mapping.

    Parsed by hand rather than with a YAML loader: the entries are valueless keys
    (`amd64:` with nothing after it), and the repo has no yaml dependency in its
    test extra.
    """
    lines = SNAPCRAFT.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "platforms:")
    found: set[str] = set()
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            break  # dedented to the next top-level key
        match = re.fullmatch(r"\s{2}([A-Za-z0-9_-]+):\s*", line)
        if match:
            found.add(match.group(1))
    return found


def _matrix_arches() -> set[str]:
    """Architectures the publish workflow actually builds a job for."""
    return set(re.findall(r"^\s*-\s*arch:\s*([A-Za-z0-9_-]+)\s*$", WORKFLOW.read_text(encoding="utf-8"), re.M))


def test_snapcraft_declares_the_expected_platforms() -> None:
    assert _declared_platforms() == {"amd64", "arm64"}, (
        "the declared snap platforms changed — update the publish matrix in "
        f"{WORKFLOW.relative_to(ROOT)} to match, then update this expectation"
    )


def test_every_declared_platform_has_a_publish_job() -> None:
    """The regression that shipped: a declared arch with no runner never reaches stable."""
    missing = _declared_platforms() - _matrix_arches()
    assert not missing, (
        f"snapcraft.yaml declares {sorted(missing)} but {WORKFLOW.relative_to(ROOT)} builds no "
        f"job for it. That workflow is the only publisher to latest/stable, so those "
        f"architectures would exist on edge at best and `snap install yazses` would fail "
        f"outright on them (issue #267)."
    )


def test_no_publish_job_for_an_undeclared_platform() -> None:
    """The mirror image: a runner for an arch snapcraft will not build wastes a
    job and publishes nothing."""
    extra = _matrix_arches() - _declared_platforms()
    assert not extra, f"{WORKFLOW.relative_to(ROOT)} builds {sorted(extra)}, absent from snapcraft.yaml `platforms:`"


@pytest.mark.parametrize("arch,runner", [("amd64", "ubuntu-latest"), ("arm64", "ubuntu-24.04-arm")])
def test_each_arch_uses_a_native_runner(arch: str, runner: str) -> None:
    """snapcraft builds for the host architecture, so the runner label *is* the
    architecture selection. A wrong label silently produces a second amd64 snap."""
    text = WORKFLOW.read_text(encoding="utf-8")
    block = re.search(rf"-\s*arch:\s*{arch}\s*\n\s*runner:\s*(\S+)", text)
    assert block, f"no matrix entry for {arch}"
    assert block.group(1) == runner, f"{arch} builds on {block.group(1)}, expected {runner}"


def test_matrix_does_not_fail_fast() -> None:
    """One arch failing must not cancel the other and leave stable half-updated —
    that asymmetry is exactly what #267 was."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"fail-fast:\s*false", text), (
        "the snap matrix must set fail-fast: false, or a failing arch cancels the "
        "other and stable gets updated for one architecture only"
    )


def test_publish_targets_stable() -> None:
    """If this ever drops to edge-only, every architecture stops reaching users."""
    assert re.search(r"release:\s*stable,edge", WORKFLOW.read_text(encoding="utf-8")), (
        "the snap publish step no longer releases to stable"
    )


def test_artifact_name_is_arch_qualified() -> None:
    """Two matrix jobs uploading one artifact name collide; the second job fails
    and takes its publish with it."""
    text = WORKFLOW.read_text(encoding="utf-8")
    upload = re.search(r"name:\s*(yazses-snap-.+)$", text, re.M)
    assert upload, "the snap artifact upload step is gone"
    assert "matrix.arch" in upload.group(1), (
        f"artifact name {upload.group(1)!r} is not arch-qualified — the two matrix "
        "jobs would collide"
    )


def test_the_publish_step_cannot_hang_for_the_whole_job() -> None:
    """A hung upload must fail loudly, not consume the job budget in silence.

    v2.20.0 and v2.21.0 both built a good snap and then stalled in
    `Publish to Snap Store` until the 60-minute job timeout killed it. GitHub
    reports that outcome as **cancelled**, which reads like a human pressed stop —
    so two releases went by with `latest/stable` sitting on 2.19.0 and nothing in
    the run list looking like a failure.

    This module already exists because a silent non-publish "hid a stuck-at-1.2.0
    store for 9 releases" (snap.yml's own words). A hang is the same failure
    wearing a different hat: the build is fine, the store never gets it, and the
    signal is indistinguishable from noise. A step-level timeout shorter than the
    job's turns it back into an error someone will see.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Publish to Snap Store")
    # The step ends where the next one begins, or at end of file.
    nxt = text.find("\n      - name:", start + 1)
    step = text[start:nxt if nxt != -1 else len(text)]

    match = re.search(r"^\s*timeout-minutes:\s*(\d+)\s*$", step, re.M)
    assert match, (
        "the Snap Store publish step has no timeout-minutes, so a stalled upload "
        "runs until the job's own limit and is reported as 'cancelled' rather than "
        "as the failure it is"
    )
    step_limit = int(match.group(1))

    job_match = re.search(r"^\s{4}timeout-minutes:\s*(\d+)\s*$", text, re.M)
    assert job_match, "the snap job no longer declares a timeout"
    assert step_limit < int(job_match.group(1)), (
        f"the publish step's timeout ({step_limit}m) must be shorter than the job's "
        f"({job_match.group(1)}m), or the job limit fires first and the outcome is "
        f"'cancelled' again"
    )
