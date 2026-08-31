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

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SNAPCRAFT = ROOT / "snap" / "snapcraft.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "snap.yml"


#: The step under test is a GitHub Actions `run:` block on a Linux runner, and this
#: test executes it verbatim. Asking whether the host has a shell is the wrong
#: question, twice over: `shutil.which("bash")` is truthy on a GitHub Windows runner
#: (it finds the WSL launcher, which exits 1 with "no installed distributions"), and
#: macOS has a real bash yet still cannot run this step, because it calls `timeout 900`
#: -- GNU coreutils, absent there. That is the exact reason both macOS legs were red.
#: So the condition is the one the workflow itself states.
needs_the_workflow_runner = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the publish step is a Linux `run:` block and calls GNU `timeout`",
)


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


def _publish_script() -> str:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return next(
        step["run"]
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("id") == "publish"
    )


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
    """Both the upload hint and the explicit release call target stable.

    The explicit ``snapcraft release`` is the mechanism -- it is the half that has
    been observed to publish. ``--release`` on the upload is a belt-and-braces hint
    whose effect after a timed-out review poll is **unverified**: revisions 388/389
    establish only that omitting it leaves no channel, which does not establish that
    including it defers one. Pinned here so neither half is dropped by accident, not
    as a claim that the deferred path works.
    """
    script = _publish_script()
    assert 'snapcraft upload "$SNAP_FILE" --release=stable,edge' in script
    assert 'snapcraft release yazses "$REV" stable,edge' in script


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


def test_upload_poll_failure_cannot_skip_the_revision_release() -> None:
    """snapcraft may accept the upload and then exit 120 after its review poll.

    The revision lookup and explicit release must still run in that case.  A
    trailing ``|| true`` did not reliably defeat the runner's ``bash -e`` and
    v2.31.0 stopped immediately after the store created revision 388.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    upload = text.index('timeout 900 snapcraft upload "$SNAP_FILE" --release=stable,edge')
    revision_lookup = text.index("REV=\"\"", upload)
    guarded_block = text[text.rfind("set +e", 0, upload):revision_lookup]

    assert guarded_block.startswith("set +e")
    assert "UPLOAD_STATUS=${PIPESTATUS[0]}" in guarded_block
    assert "set -e" in guarded_block


def test_revision_lookup_captures_before_parsing() -> None:
    """One transient failure must skip an iteration, not kill the retry loop.

    `set -e` is back on at this point, so a failing command substitution inside an
    assignment aborts the whole step.  The earlier form assigned the pipeline
    directly, so a single nonzero exit from ``snapcraft revisions`` -- a store
    blip, or a lost pipe on its final flush surfacing as 120 under ``pipefail`` --
    killed the job on the first pass of the very loop written to retry it.
    Measured: ``REV=$(false | awk ...)`` in this loop dies on iteration 1, while
    ``if ROWS=$(false); then`` runs all ten.

    Note the awk program itself reads to EOF -- it guards with ``!found`` and
    prints in ``END`` -- so it never closes the producer's stdout early.  Guard
    the assignment, not the reader.
    """
    script = _publish_script()
    start = script.index("store_revision() {")
    lookup = script[start:script.index("\n}", start)]

    assert "rows=$(snapcraft revisions yazses 2>/dev/null) || return 0" in lookup, (
        "the store query must be captured into a variable and its status swallowed; "
        "assigning the pipeline directly kills the step on the first transient failure"
    )
    # A single `|` only. The lookarounds exclude the `||` of `|| return 0`, which
    # is the very construct that swallows the status this test is here to protect.
    assert not re.search(r"snapcraft revisions[^\n]*(?<!\|)\|(?!\|)", lookup), (
        "`snapcraft revisions` must not be piped into awk — that is the form that died"
    )
    assert '<<<"$rows"' in lookup
    assert "END { if (found) print revision }" in lookup


@needs_the_workflow_runner
@pytest.mark.parametrize("arch", ["amd64", "arm64"])
def test_publish_recovers_after_upload_poll_timeout(tmp_path: Path, arch: str) -> None:
    """Exercise the workflow shell, including the production failure boundary.

    The fake upload exits 124 after acceptance, and the revision command emits
    enough output to exceed a pipe buffer after putting the match first. The old
    live-pipe lookup died there; capture-then-parse must reach release and verify
    the stable channel for both matrix architectures.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "snapcraft-calls"
    snapcraft = fake_bin / "snapcraft"
    snapcraft.write_text(
        """#!/bin/sh
set -eu
case "$1" in
  upload)
    printf '%s\\n' "$*" >> "$SNAPCRAFT_CALLS"
    echo "Status: processing"
    exit 124
    ;;
  revisions)
    printf '388 uploaded %s 2.31.0 -\\n' "$ARCH"
    i=0
    while [ "$i" -lt 5000 ]; do
      printf '%s uploaded other 0.0.0 -\\n' "$i"
      i=$((i + 1))
    done
    ;;
  release)
    printf '%s\\n' "$*" >> "$SNAPCRAFT_CALLS"
    ;;
  status)
    printf 'yazses %s stable 2.31.0\\n' "$ARCH"
    ;;
  *)
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    snapcraft.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "ARCH": arch,
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "SNAPCRAFT_CALLS": str(calls),
            "SNAPCRAFT_STORE_CREDENTIALS": "test-only",
            "SNAP_FILE": f"yazses_2.31.0_{arch}.snap",
        }
    )

    result = subprocess.run(
        ["bash", "-e", "-c", _publish_script()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.read_text(encoding="utf-8") == (
        f"upload yazses_2.31.0_{arch}.snap --release=stable,edge\n"
        "release yazses 388 stable,edge\n"
    )
    assert f"latest/stable is 2.31.0 on {arch} (revision 388)" in result.stdout


def test_a_publish_timeout_explains_itself() -> None:
    """A bare "timed out after 20 minutes" points at the wrong half of the problem.

    Measured on run 31906962075: `snapcraft upload` transfers the file, the store
    accepts the credentials, and then it answers `Status: processing` 971 times —
    about once a second for nineteen unbroken minutes. The upload succeeds; the
    store's review of the revision is what does not finish.

    Without that said out loud, the next person reads a red publish step as broken
    credentials and goes to re-export a login that is demonstrably working. This is
    the same class of defect as the silent stall it replaced: the run reports
    something true and useless.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = [s for job in workflow["jobs"].values() for s in job.get("steps", [])]

    publish = [s for s in steps if s.get("id") == "publish"]
    assert publish, "the publish step needs an `id` for a later step to condition on"

    explainers = [
        s for s in steps
        if "steps.publish.outcome == 'failure'" in str(s.get("if", ""))
    ]
    assert explainers, (
        "nothing explains a failed publish. A timeout here means the revision is "
        "queued for store review, not that the pipeline is broken."
    )

    body = " ".join(str(s.get("run", "")) for s in explainers).lower()
    for cue in ("processing", "review", "latest/stable"):
        assert cue in body, f"the explanation never mentions {cue!r}"


def test_the_explanation_does_not_turn_a_failed_publish_green() -> None:
    """The job must still fail. Nothing reached `latest/stable`, and a green workflow
    that published nothing is precisely the failure this area exists to prevent —
    two releases went out that way before the timeout was added."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if step.get("id") == "publish":
                assert "continue-on-error" not in step, (
                    "the publish step must not swallow its own failure — explaining a "
                    "failure is not the same as tolerating it"
                )


def _fake_store(tmp_path: Path, revisions: str) -> tuple[Path, Path]:
    """A stand-in `snapcraft` whose `revisions` table is fixed by the caller.

    Returns the directory to put on PATH and the file every mutating call appends
    to, so a test can assert on *which* store operations happened rather than only
    on the exit code. That distinction is the whole subject here: the defect was an
    upload that should not have been made, and it exited 0 every time.
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    calls = tmp_path / "snapcraft-calls"
    snapcraft = fake_bin / "snapcraft"
    snapcraft.write_text(
        f"""#!/bin/sh
set -eu
case "$1" in
  upload)
    printf '%s\\n' "$*" >> "$SNAPCRAFT_CALLS"
    ;;
  revisions)
    printf 'Rev.\\tUploaded\\tArches\\tVersion\\tChannels\\n'
{revisions}
    ;;
  release)
    printf '%s\\n' "$*" >> "$SNAPCRAFT_CALLS"
    ;;
  status)
    printf 'yazses %s stable 2.31.0\\n' "$ARCH"
    ;;
  *)
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    snapcraft.chmod(0o755)
    return fake_bin, calls


def _run_publish(tmp_path: Path, fake_bin: Path, calls: Path, arch: str, **extra: str):
    env = os.environ.copy()
    env.update(
        {
            "ARCH": arch,
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "SNAPCRAFT_CALLS": str(calls),
            "SNAPCRAFT_STORE_CREDENTIALS": "test-only",
            "SNAP_FILE": f"yazses_2.31.0_{arch}.snap",
        }
    )
    env.update(extra)
    return subprocess.run(
        ["bash", "-e", "-c", _publish_script()],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


@needs_the_workflow_runner
@pytest.mark.parametrize("arch,revision", [("amd64", "388"), ("arm64", "389")])
def test_a_published_version_is_released_not_uploaded_again(
    tmp_path: Path, arch: str, revision: str
) -> None:
    """Re-running the job for a version the store already publishes must upload nothing.

    A tag is immutable and the version comes from the tag, so a re-run can only be
    the same release. The old form uploaded anyway, and every duplicate entered the
    store's review queue on its own: 2.30.0 collected twenty revisions and 2.31.0
    eighteen, of which eight never took a channel. Each one the queue did not clear
    became a rejected revision and one more "Status update for version … of YazSes
    has been rejected" email — about two hundred of them, all from this.

    Both arches are exercised because the guard is per-architecture; a lookup that
    ignored `Arches` would let one arch's publish suppress the other's upload, which
    is issue #267 again from the other direction.
    """
    table = (
        "    printf '388\\t2026-08-24T11:43:49Z\\tamd64\\t2.31.0\\tlatest/edge,latest/stable\\n'\n"
        "    printf '389\\t2026-08-24T11:43:52Z\\tarm64\\t2.31.0\\tlatest/edge,latest/stable\\n'"
    )
    fake_bin, calls = _fake_store(tmp_path, table)
    result = _run_publish(tmp_path, fake_bin, calls, arch)

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.read_text(encoding="utf-8") == f"release yazses {revision} stable,edge\n", (
        "the store already publishes this version/arch, so the only call may be the "
        "release of the existing revision — an upload here is the duplicate"
    )
    assert "already publishes" in result.stdout


@needs_the_workflow_runner
def test_a_channel_less_revision_does_not_block_the_retry(tmp_path: Path) -> None:
    """The guard must not refuse the one case a re-run is actually for.

    `snapcraft revisions` renders "still in review" and "rejected" identically, as
    `-` in the Channels column. Keying the guard on *any* revision would therefore
    make a rejected upload permanently unretryable, so it is keyed on a revision
    that already holds a channel.
    """
    table = "    printf '390\\t2026-08-24T11:46:49Z\\tamd64\\t2.31.0\\t-\\n'"
    fake_bin, calls = _fake_store(tmp_path, table)
    result = _run_publish(tmp_path, fake_bin, calls, "amd64")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.read_text(encoding="utf-8") == (
        "upload yazses_2.31.0_amd64.snap --release=stable,edge\n"
        "release yazses 390 stable,edge\n"
    )


@needs_the_workflow_runner
def test_force_upload_overrides_the_guard(tmp_path: Path) -> None:
    """A packaging-only rebuild at an unchanged version needs a way through.

    The guard is the right default and the wrong absolute, so `force_upload` exists.
    Without it the only escape from a bad published revision would be a version bump.
    """
    table = (
        "    printf '388\\t2026-08-24T11:43:49Z\\tamd64\\t2.31.0\\tlatest/edge,latest/stable\\n'"
    )
    fake_bin, calls = _fake_store(tmp_path, table)
    result = _run_publish(tmp_path, fake_bin, calls, "amd64", FORCE_UPLOAD="true")

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.read_text(encoding="utf-8").startswith(
        "upload yazses_2.31.0_amd64.snap --release=stable,edge\n"
    ), "force_upload must reach the upload"


def test_force_upload_is_reachable_from_the_workflow_ui() -> None:
    """A guard with an escape hatch nobody can press is a guard with none.

    The step reads `$FORCE_UPLOAD`; the value has to come from a declared
    `workflow_dispatch` input and be wired into the step's env, or the only way
    past the guard would be to edit the workflow.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow[True] if True in workflow else workflow["on"]
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert "force_upload" in inputs, (
        "the publish step consults $FORCE_UPLOAD but no workflow_dispatch input "
        "declares it — the hatch is unreachable from the Actions UI"
    )
    assert inputs["force_upload"].get("default") in (False, "false"), (
        "force_upload must default to off; the guard is the point"
    )

    publish = next(
        s for job in workflow["jobs"].values() for s in job.get("steps", [])
        if s.get("id") == "publish"
    )
    assert "FORCE_UPLOAD" in publish.get("env", {}), (
        "the input is declared but never reaches the step's environment"
    )
