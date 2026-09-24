"""A matching version string is not a matching build.

`_stale_daemon_note` asks "does the daemon report the version I have installed?" and
stops there. Two installs routinely report the *same* version while running entirely
different code -- a repository checkout and an installed copy both say `2.39.0`, and
only one of them carries today's fix. `yazses` on PATH can resolve to one and
`yazses-daemon` to the other, so the CLI you type into and the process handling your
dictation are different builds, and every version check agrees they are fine.

Measured on a real machine (2026-09-24). A fix to the hallucination guard was written,
unit-tested, and confirmed working by running `.venv/bin/yazses restart` -- the ACTION
NEEDED banner disappeared and the guard behaved. Meanwhile the daemon actually doing the
dictation was

    /home/mohsen/.local/share/uv/tools/yazses/bin/yazses-daemon

an installed 2.39.0 that had never seen the fix. It went on discarding real speech. The
CLI said 2.39.0, the daemon said 2.39.0, `doctor` printed `Daemon: OK`, and nothing in
the product named the split.

The trap inside the trap: `yazses restart` does not fix it, because the daemon comes back
from whichever install owns `yazses-daemon` on PATH. Restarting reproduces the split,
which is why the check has to say so rather than offering the usual advice.
"""
import os

import pytest

from yazses.system.doctor import _daemon_install_prefix, divergent_build_note

UV_TOOL = "/home/mohsen/.local/share/uv/tools/yazses"
REPO_VENV = "/home/mohsen/scratch/repos/yazses/.venv"


# --- the regression -----------------------------------------------------------

def test_the_real_split_is_reported():
    note = divergent_build_note(REPO_VENV, UV_TOOL)
    assert note, "the exact split that shipped a 'verified' fix nobody was running"
    assert UV_TOOL in note and REPO_VENV in note, "both sides must be named"


def test_it_says_restart_will_not_help():
    """The usual advice is actively wrong here and would send the user in a circle."""
    note = divergent_build_note(REPO_VENV, UV_TOOL)
    assert "restart" in note.lower()
    assert "not fix it" in note


# --- the permissive direction -------------------------------------------------

def test_matching_prefixes_say_nothing():
    assert divergent_build_note(UV_TOOL, UV_TOOL) == ""


def test_trailing_separators_and_dot_segments_are_not_a_split():
    """A cosmetic path difference is not a different build; normalise before comparing."""
    assert divergent_build_note(UV_TOOL, UV_TOOL + "/") == ""
    assert divergent_build_note(UV_TOOL, UV_TOOL + "/./") == ""
    assert divergent_build_note(UV_TOOL + "/bin/..", UV_TOOL) == ""


@pytest.mark.parametrize("daemon_prefix", [None, ""])
def test_an_unknown_daemon_prefix_is_silent(daemon_prefix):
    """The probe is Linux-only. A guard that fires wherever it cannot see is ADR-021's
    dismissed guard -- silence is the correct answer to "I could not tell"."""
    assert divergent_build_note(REPO_VENV, daemon_prefix) == ""


def test_an_unknown_cli_prefix_is_silent():
    assert divergent_build_note("", UV_TOOL) == ""


# --- the probe ----------------------------------------------------------------

def test_the_probe_reads_argv0_not_the_resolved_interpreter(tmp_path, monkeypatch):
    """`/proc/<pid>/exe` is the wrong source and this pins why.

    A uv-managed interpreter is SHARED between environments, so the resolved binary is
    identical for two installs carrying different code -- using it would answer "same
    build" exactly when the answer is "different build". `argv[0]` is the environment's
    own `bin/python`, which is what tells them apart.
    """
    proc = tmp_path / "proc" / "4242"
    proc.mkdir(parents=True)
    (proc / "cmdline").write_bytes(
        f"{UV_TOOL}/bin/python\0{UV_TOOL}/bin/yazses-daemon\0".encode()
    )
    real_open = open

    def fake_open(path, *a, **kw):
        if str(path) == "/proc/4242/cmdline":
            return real_open(proc / "cmdline", *a, **kw)
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", fake_open)
    assert _daemon_install_prefix(4242) == UV_TOOL


def test_the_probe_never_raises_on_a_dead_or_alien_pid():
    """It runs inside `doctor`; a diagnostic that raises takes the whole report down."""
    assert _daemon_install_prefix(999_999_999) is None
    assert _daemon_install_prefix("not-a-pid") is None
    assert _daemon_install_prefix(None) is None


@pytest.mark.skipif(not os.path.isdir("/proc/self"), reason="needs Linux /proc")
def test_the_probe_agrees_with_this_very_process():
    """Ground it in a process whose prefix is knowable independently."""
    import sys
    assert _daemon_install_prefix(os.getpid()) == os.path.normpath(sys.prefix)
