"""Tests for the systemd user unit YazSes installs for itself.

Pure text and path logic, so these run on any platform. The behaviour they protect is
"is it running when I sit down?", which no other test in the suite covers.
"""
from __future__ import annotations

import sys

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
