"""Tests for the systemd user unit YazSes installs for itself.

Pure text and path logic, so these run on any platform. The behaviour they protect is
"is it running when I sit down?", which no other test in the suite covers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from yazses.platform.linux import autostart


def test_unit_restarts_on_failure_but_not_after_a_clean_stop():
    """`yazses stop` exits cleanly; restarting then would fight the user, not heal."""
    text = autostart.unit_text("/usr/bin/yazses-daemon")

    assert "Restart=on-failure" in text
    assert "Restart=always" not in text


def test_unit_bounds_the_crash_loop():
    """A persistently broken machine must stop retrying and stay diagnosable."""
    text = autostart.unit_text("/usr/bin/yazses-daemon")

    assert "StartLimitIntervalSec=60" in text
    assert "StartLimitBurst=5" in text


def test_unit_carries_the_display_so_x11_injection_works():
    text = autostart.unit_text("/usr/bin/yazses-daemon")

    assert "PassEnvironment=DISPLAY XAUTHORITY" in text


def test_unit_starts_with_the_graphical_session():
    text = autostart.unit_text("/usr/bin/yazses-daemon")

    assert "WantedBy=graphical-session.target" in text
    assert "After=graphical-session.target sound.target" in text


def test_unit_runs_the_command_it_was_given():
    text = autostart.unit_text("/opt/weird path/yazses-daemon")

    assert "ExecStart=/opt/weird path/yazses-daemon" in text


def test_resolve_prefers_the_console_script_next_to_this_interpreter(tmp_path, monkeypatch):
    """A `yazses-daemon` earlier on PATH belongs to some *other* install.

    Picking it would mean login starts a different YazSes than the one being configured —
    which works right up until an upgrade moves one of them.
    """
    env = tmp_path / "env" / "bin"
    env.mkdir(parents=True)
    (env / "yazses-daemon").write_text("#!/bin/sh\n")
    (env / "python").write_text("")
    other = tmp_path / "other"
    other.mkdir()
    (other / "yazses-daemon").write_text("#!/bin/sh\n")

    monkeypatch.setattr(sys, "executable", str(env / "python"))
    monkeypatch.setenv("PATH", str(other))

    assert autostart.resolve_daemon_command() == str(env / "yazses-daemon")


def test_resolve_falls_back_to_the_module_when_no_console_script_exists(tmp_path, monkeypatch):
    """A source checkout has no console script; the interpreter still works."""
    env = tmp_path / "bin"
    env.mkdir(parents=True)
    (env / "python").write_text("")
    monkeypatch.setattr(sys, "executable", str(env / "python"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    command = autostart.resolve_daemon_command()

    assert command.endswith("-m yazses.main")
    assert str(env / "python") in command


def test_needs_rewrite_detects_a_moved_binary():
    """The upgrade failure: unit still enabled, ExecStart now points at nothing."""
    old = autostart.unit_text("/old/path/yazses-daemon")
    new = autostart.unit_text("/new/path/yazses-daemon")

    assert autostart.needs_rewrite(old, new) is True
    assert autostart.needs_rewrite(new, new) is False
    assert autostart.needs_rewrite(None, new) is True


def test_needs_rewrite_ignores_trailing_whitespace():
    text = autostart.unit_text("/usr/bin/yazses-daemon")

    assert autostart.needs_rewrite(text + "\n\n", text) is False


def test_service_path_is_the_systemd_user_directory():
    assert autostart.service_path().parts[-3:] == ("systemd", "user", "yazses.service")
    assert autostart.service_path().is_absolute()


# ---- installing it: what the user sees, and what happens when it fails -------
# `yazses start` calls this, so systemctl's own narration would land in the middle of
# the start output and a bare CalledProcessError would tell the user only "exit 1".

def _lifecycle(tmp_path, monkeypatch):
    import shutil as _shutil

    from yazses.platform.base import Paths
    from yazses.platform.linux.lifecycle import LinuxLifecycle

    monkeypatch.setattr(_shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return LinuxLifecycle(
        Paths(
            config_dir=tmp_path / "config",
            state_dir=tmp_path / "state",
            cache_dir=tmp_path / "cache",
            log_dir=tmp_path / "log",
            data_dir=tmp_path / "data",
        )
    )


def test_install_autostart_never_lets_systemctl_narrate_to_the_user(tmp_path, monkeypatch):
    import subprocess

    calls = []

    def _run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, stdout="Created symlink …\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    _lifecycle(tmp_path, monkeypatch).install_autostart()

    assert calls, "systemctl was never invoked"
    for argv, kw in calls:
        assert kw.get("capture_output") is True, f"{argv} would print straight at the user"


def test_install_autostart_raises_with_the_reason_systemctl_gave(tmp_path, monkeypatch):
    import subprocess

    def _run(argv, **kw):
        if "enable" in argv:
            return subprocess.CompletedProcess(
                argv, 1, stdout="", stderr="Failed to enable unit: Access denied\n"
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _run)
    with pytest.raises(RuntimeError, match="Access denied"):
        _lifecycle(tmp_path, monkeypatch).install_autostart()
