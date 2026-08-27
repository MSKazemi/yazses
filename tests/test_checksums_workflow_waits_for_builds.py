"""`checksums.yml` must not hash an asset that a build is about to overwrite.

v2.32.0 published a SHA256SUMS.txt that matched **neither** Windows installer. The
release was run twice for the same tag; on the second run every asset already existed
from the first, so the workflow's "wait for the assets to appear" loop -- which counts
*names* -- was satisfied on its first poll, hashed the previous run's binaries, and the
still-running Windows build overwrote both .exe two to three minutes later. The .deb and
.dmg matched only because their builds happened to finish ten seconds earlier.

A name is not a file. Presence cannot express freshness, and no amount of extra waiting
fixes a check that is already true.

The two repairs are checked here because neither can be exercised without cutting a tag:

* a wait on the producer **workflow runs**, which is the only thing that knows whether an
  asset is still being written; and
* a post-upload check that nothing was written *after* SHA256SUMS.txt -- the one signal
  that makes no timing assumption at all.

Windows builds are unsigned, so this hash is the only integrity signal a Windows user has
(`docs/code-signing.md` tells them to verify it), and Chocolatey and Scoop derive their
manifests from it, so a wrong value stops `choco upgrade` outright.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML ships with the docs group")

_WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
_CHECKSUMS = _WORKFLOWS / "checksums.yml"
_ARTIFACT_SUFFIXES = (".exe", ".dmg", ".deb")

_needs_shell = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("jq")),
    reason="the workflow's own shell needs bash and jq",
)


def _steps() -> list[dict]:
    doc = yaml.safe_load(_CHECKSUMS.read_text(encoding="utf-8"))
    return doc["jobs"]["checksums"]["steps"]


def _step(prefix: str) -> dict:
    hits = [s for s in _steps() if s.get("name", "").startswith(prefix)]
    assert len(hits) == 1, f"expected exactly one step named {prefix!r}, got {len(hits)}"
    return hits[0]


def _producers_from_the_workflows() -> set[str]:
    """Every workflow that attaches an installer to a release, read off the files.

    Derived rather than listed. A hand-written set is the defect it is meant to catch:
    a fourth producer added later would simply not be waited for, and the failure only
    shows up as a wrong hash on a tag nobody re-checks.
    """
    found = set()
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in (doc.get("jobs") or {}).values():
            for step in job.get("steps") or []:
                uses = step.get("uses") or ""
                text = ""
                if "action-gh-release" in uses:
                    text = str((step.get("with") or {}).get("files", ""))
                elif "gh release upload" in (step.get("run") or ""):
                    text = step["run"]
                if any(suffix in text for suffix in _ARTIFACT_SUFFIXES):
                    found.add(path.name)
    return found


def _listed_producers() -> set[str]:
    run = _step("Wait for the builds")["run"]
    line = [ln for ln in run.splitlines() if ln.strip().startswith("producers=")]
    assert len(line) == 1, f"expected one `producers=` assignment, got {line}"
    return set(line[0].split("=", 1)[1].strip().strip('"').split())


def test_the_derivation_finds_producers_at_all() -> None:
    """Guards the guard: an empty derived set would make the comparison vacuous."""
    assert _producers_from_the_workflows(), (
        "no workflow was detected as attaching a .deb/.dmg/.exe -- the detector below "
        "is broken, not the workflow set"
    )


def test_every_workflow_that_attaches_an_installer_is_waited_for() -> None:
    missing = _producers_from_the_workflows() - _listed_producers()
    assert not missing, (
        f"checksums.yml does not wait for {sorted(missing)}, which attach release "
        "artifacts -- their output can be overwritten after the hashing step"
    )


def test_it_does_not_wait_for_a_workflow_that_ships_nothing() -> None:
    """Waiting for an unrelated workflow would stall every release for no gain."""
    extra = _listed_producers() - _producers_from_the_workflows()
    assert not extra, f"waits for {sorted(extra)}, which attach no release artifact"


def test_the_proof_step_runs_after_the_upload() -> None:
    """Checking before the upload proves nothing: the file is not there yet."""
    names = [s.get("name", "") for s in _steps()]
    upload = next(i for i, n in enumerate(names) if n.startswith("Attach SHA256SUMS"))
    proof = next(i for i, n in enumerate(names) if n.startswith("Prove SHA256SUMS"))
    assert proof > upload, f"proof step runs before the upload: {names}"


def _shim(tmp_path: Path, name: str, body: str) -> None:
    p = tmp_path / name
    p.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)


def _run(step_name: str, tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    script = tmp_path / "step.sh"
    script.write_text(_step(step_name)["run"], encoding="utf-8")
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}", **env},
    )


_ASSETS = """{{"assets":[
  {{"name":"SHA256SUMS.txt","updatedAt":"2026-08-26T13:40:00Z"}},
  {{"name":"YazSes-2.32.0-windows-x64.exe","updatedAt":"{exe}"}},
  {{"name":"yazses_2.32.0_amd64.deb","updatedAt":"2026-08-26T13:20:00Z"}}
]}}"""


@_needs_shell
def test_the_proof_fails_on_an_asset_written_after_the_checksum_file(tmp_path) -> None:
    """The exact v2.32.0 shape: the .exe was rewritten minutes after the hashing."""
    _shim(tmp_path, "gh", f"cat <<'JSON'\n{_ASSETS.format(exe='2026-08-26T13:43:00Z')}\nJSON\n")
    out = _run("Prove SHA256SUMS", tmp_path, TAG="v2.32.0")
    assert out.returncode == 1, out.stdout + out.stderr
    assert "YazSes-2.32.0-windows-x64.exe" in out.stdout
    assert "yazses_2.32.0_amd64.deb" not in out.stdout, "flagged an asset that is older"


@_needs_shell
def test_the_proof_passes_when_every_asset_predates_the_checksum_file(tmp_path) -> None:
    """The other direction -- a check that always fails would be no check at all."""
    _shim(tmp_path, "gh", f"cat <<'JSON'\n{_ASSETS.format(exe='2026-08-26T13:30:00Z')}\nJSON\n")
    out = _run("Prove SHA256SUMS", tmp_path, TAG="v2.32.0")
    assert out.returncode == 0, out.stdout + out.stderr
    assert "ok:" in out.stdout


@_needs_shell
def test_the_proof_fails_when_the_checksum_file_is_absent(tmp_path) -> None:
    """A missing SHA256SUMS.txt must not read as "nothing is newer than it"."""
    _shim(tmp_path, "gh", 'cat <<\'JSON\'\n{"assets":[]}\nJSON\n')
    out = _run("Prove SHA256SUMS", tmp_path, TAG="v2.32.0")
    assert out.returncode == 1, out.stdout + out.stderr
    assert "not attached" in out.stdout


@_needs_shell
def test_the_wait_blocks_while_a_producer_run_is_still_going(tmp_path) -> None:
    """The whole point: a second poll only happens if the first one did not proceed.

    `sleep` is shimmed to a counter so the test does not spend the workflow's real
    minute per poll -- what is under test is that it loops at all, not how long for.
    """
    _shim(
        tmp_path,
        "gh",
        'n=$(cat "$TMPD/calls" 2>/dev/null || echo 0); echo $((n+1)) > "$TMPD/calls"\n'
        'if [ "$n" -lt 3 ]; then echo in_progress; else echo completed; fi\n',
    )
    _shim(tmp_path, "sleep", 'echo "slept $1" >> "$TMPD/sleeps"\n')
    out = _run("Wait for the builds", tmp_path, TAG="v2.32.0", TMPD=str(tmp_path), GH_REPO="MSKazemi/yazses")
    assert out.returncode == 0, out.stdout + out.stderr
    assert (tmp_path / "sleeps").exists(), (
        "never slept, so it never waited for the in-progress build:\n" + out.stdout
    )
    assert "still building" in out.stdout


@_needs_shell
def test_the_wait_proceeds_when_nothing_is_running(tmp_path) -> None:
    """A finished (or never-triggered) leg must not cost the release 45 minutes."""
    _shim(tmp_path, "gh", "echo completed\n")
    _shim(tmp_path, "sleep", 'echo "slept $1" >> "$TMPD/sleeps"\n')
    out = _run("Wait for the builds", tmp_path, TAG="v2.32.0", TMPD=str(tmp_path), GH_REPO="MSKazemi/yazses")
    assert out.returncode == 0, out.stdout + out.stderr
    assert not (tmp_path / "sleeps").exists(), "waited even though nothing was running"


@_needs_shell
def test_an_unreachable_api_does_not_hang_the_release(tmp_path) -> None:
    """A gh failure must read as "no run", not as "still running" forever.

    The opposite choice would turn any API blip into a 45-minute stall on every leg.
    """
    _shim(tmp_path, "gh", "exit 1\n")
    _shim(tmp_path, "sleep", 'echo "slept $1" >> "$TMPD/sleeps"\n')
    out = _run("Wait for the builds", tmp_path, TAG="v2.32.0", TMPD=str(tmp_path), GH_REPO="MSKazemi/yazses")
    assert out.returncode == 0, out.stdout + out.stderr
    assert not (tmp_path / "sleeps").exists()
