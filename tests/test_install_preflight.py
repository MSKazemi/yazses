"""The install.sh preflight gate and its --dry-run mode.

`install.sh` installs with `uv tool install --from git+...` and builds `evdev` from
source (that package publishes an sdist and no wheels at all). Both facts mean the
script has hard prerequisites it cannot supply itself -- a `git` binary and a C
toolchain. Before the preflight existed, a machine missing either got a failure from
deep inside uv's output ("Git executable not found") long after the script had started
work, which read as a YazSes bug rather than a missing package.

These tests pin the properties that matter: it detects a missing prerequisite and
stops *before* touching the network or sudo, it stays silent on a healthy machine, and
`--dry-run` reports what it would do while changing nothing. The dry run is a trust
surface -- the script is meant to be piped from the internet into a shell, so "show me
first" has to be true, not merely documented.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

linux_only = pytest.mark.skipif(
    sys.platform != "linux", reason="install.sh provisions Linux only"
)

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = REPO_ROOT / "install.sh"

# Enough of a userland for the script to reach the preflight and render its message.
# `git`, `cc`/`gcc` and `apt-get` are deliberately absent so the no-package-manager
# branch is the one under test -- it must not try to install anything.
_STUB_TOOLS = ("bash", "uname", "python3", "cat", "sed")


def _isolated_path(tmp_path: Path) -> Path:
    """A PATH containing only _STUB_TOOLS -- no git, no compiler, no apt-get."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for tool in _STUB_TOOLS:
        resolved = shutil.which(tool)
        if resolved is None:
            pytest.skip(f"{tool} unavailable; cannot build an isolated PATH")
        (fake_bin / tool).symlink_to(resolved)
    return fake_bin


@linux_only
def test_preflight_aborts_when_git_and_compiler_are_missing(tmp_path: Path) -> None:
    """A machine without git or cc is told exactly what to install, and nothing runs."""
    fake_bin = _isolated_path(tmp_path)

    result = subprocess.run(
        [shutil.which("bash") or "bash", str(INSTALL_SH)],
        env={"PATH": str(fake_bin), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 1, f"expected a hard failure, got {result.returncode}"
    combined = result.stdout + result.stderr
    assert "Missing prerequisites" in combined
    # Both absent tools are named -- a message listing only one sends the user
    # round the loop twice.
    assert "git" in combined
    assert "build-essential" in combined
    # It must stop at the gate, not part-way through an install.
    assert "Installing uv" not in combined
    assert "Installing YazSes" not in combined


@linux_only
def test_preflight_does_not_invoke_apt_without_a_way_to_be_root(tmp_path: Path) -> None:
    """apt present but no sudo and not root: say so, and do not run apt anyway."""
    fake_bin = _isolated_path(tmp_path)
    # A tripwire: if the script ever reaches apt-get without privilege, this prints.
    apt_stub = fake_bin / "apt-get"
    apt_stub.write_text('#!/bin/sh\necho "APT-GET WAS INVOKED"\n', encoding="utf-8")
    apt_stub.chmod(0o755)

    result = subprocess.run(
        [shutil.which("bash") or "bash", str(INSTALL_SH)],
        env={"PATH": str(fake_bin), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 1
    combined = result.stdout + result.stderr
    assert "Neither root nor sudo" in combined
    assert "APT-GET WAS INVOKED" not in combined


@linux_only
def test_preflight_is_silent_when_prerequisites_are_present() -> None:
    """On a healthy machine the gate finds nothing -- no spurious package install.

    Runs the detection block itself rather than the whole script, which would go on
    to install YazSes for real.
    """
    if shutil.which("git") is None or (
        shutil.which("cc") is None and shutil.which("gcc") is None
    ):
        pytest.skip("this machine is itself missing a prerequisite")

    source = INSTALL_SH.read_text(encoding="utf-8")
    start = source.index('missing_pkgs=""')
    end = source.index('if [ -n "$missing_pkgs" ]')
    detection = source[start:end]

    result = subprocess.run(
        [shutil.which("bash") or "bash", "-c", f'{detection}\necho "[${{missing_pkgs}}]"'],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", (
        f"preflight flagged a package on a machine that has everything: {result.stdout!r}"
    )


@linux_only
def test_dry_run_changes_nothing_and_says_what_it_would_do(tmp_path: Path) -> None:
    """--dry-run reports each step and installs nothing.

    The tripwires matter more than the output: a dry run that actually invoked apt-get
    or uv would be worse than having no dry run at all, because the whole point is that
    a user can inspect a piped-from-the-internet script before trusting it.
    """
    if shutil.which("git") is None:
        pytest.skip("this machine is itself missing a prerequisite")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for tool in (*_STUB_TOOLS, "git", "mktemp", "rm"):
        resolved = shutil.which(tool)
        if resolved is None:
            pytest.skip(f"{tool} unavailable; cannot build the probe PATH")
        (fake_bin / tool).symlink_to(resolved)
    # Tripwires: reaching either of these during a dry run is a bug.
    for name in ("apt-get", "uv", "sudo"):
        stub = fake_bin / name
        stub.write_text(f'#!/bin/sh\necho "{name.upper()} WAS INVOKED"\n', encoding="utf-8")
        stub.chmod(0o755)

    result = subprocess.run(
        [shutil.which("bash") or "bash", str(INSTALL_SH), "--dry-run"],
        env={"PATH": str(fake_bin), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"dry run should succeed, got {result.returncode}: {combined}"
    assert "APT-GET WAS INVOKED" not in combined
    assert "UV WAS INVOKED" not in combined
    assert "SUDO WAS INVOKED" not in combined
    # It has to actually describe the install, or it is a no-op pretending to be a preview.
    assert "[dry-run]" in combined
    assert "uv tool install" in combined
    assert "yazses setup" in combined
    assert "Dry run complete" in combined


@linux_only
def test_help_exits_cleanly_without_doing_anything(tmp_path: Path) -> None:
    """--help is usable on a machine with nothing installed."""
    fake_bin = _isolated_path(tmp_path)

    result = subprocess.run(
        [shutil.which("bash") or "bash", str(INSTALL_SH), "--help"],
        env={"PATH": str(fake_bin), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "--dry-run" in combined
    assert "Missing prerequisites" not in combined


@linux_only
def test_unknown_option_is_rejected_rather_than_ignored(tmp_path: Path) -> None:
    """A typo'd flag must not silently fall through into a real install."""
    fake_bin = _isolated_path(tmp_path)

    result = subprocess.run(
        [shutil.which("bash") or "bash", str(INSTALL_SH), "--dryrun"],
        env={"PATH": str(fake_bin), "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 1
    assert "unknown option" in (result.stdout + result.stderr)
