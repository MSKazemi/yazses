"""`yazses start` leaves YazSes set up for the next login.

`install_autostart()` exists so a pipx / uv-tool / pip install gets a login service like
the packaged installs do. Nothing called it except `yazses autostart enable`, so the
ordinary path was: install, start, dictate, reboot, and the daemon is silently gone.
These pin the wiring, and the three cases where it must *not* fire.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


class _Lifecycle:
    def __init__(self, *, installed=False, install_raises=None, query_raises=None):
        self.installed = installed
        self._install_raises = install_raises
        self._query_raises = query_raises
        self.install_calls = 0

    def is_autostart_installed(self):
        if self._query_raises is not None:
            raise self._query_raises
        return self.installed

    def install_autostart(self):
        self.install_calls += 1
        if self._install_raises is not None:
            raise self._install_raises
        self.installed = True


class _Platform:
    def __init__(self, lifecycle):
        self.lifecycle = lifecycle


def _start(monkeypatch, lifecycle, *, outcome="ready", argv=("start",)):
    platform = _Platform(lifecycle)
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    monkeypatch.setattr(cli, "_warn_unmet_prereqs", lambda: None)
    monkeypatch.setattr(cli, "_spawn_daemon", lambda p: None)
    monkeypatch.setattr(cli, "_restart_daemon", lambda p: None)
    monkeypatch.setattr(cli, "_wait_until_ready", lambda p, timeout=20.0: (outcome, {}))
    monkeypatch.setattr(cli, "_report_start_outcome", lambda p, o, i: None)
    lifecycle.is_running = lambda: False
    lifecycle.clear_pid = lambda: None
    return runner.invoke(cli.app, list(argv))


def test_start_sets_up_autostart_when_it_is_missing(monkeypatch):
    lc = _Lifecycle(installed=False)
    r = _start(monkeypatch, lc)
    assert r.exit_code == 0, r.output
    assert lc.install_calls == 1
    assert "start automatically at login" in r.output
    assert "autostart disable" in r.output  # always name the way back out


def test_start_is_silent_when_autostart_is_already_installed(monkeypatch):
    lc = _Lifecycle(installed=True)
    r = _start(monkeypatch, lc)
    assert r.exit_code == 0, r.output
    assert lc.install_calls == 0
    assert "login" not in r.output


def test_no_autostart_flag_opts_out(monkeypatch):
    lc = _Lifecycle(installed=False)
    r = _start(monkeypatch, lc, argv=("start", "--no-autostart"))
    assert r.exit_code == 0, r.output
    assert lc.install_calls == 0


def test_start_still_wires_autostart_while_the_model_is_loading(monkeypatch):
    # A slow first run is exactly the case this exists for — the user who has just
    # installed is the one who will otherwise lose the daemon at the next reboot.
    lc = _Lifecycle(installed=False)
    r = _start(monkeypatch, lc, outcome="loading")
    assert r.exit_code == 0, r.output
    assert lc.install_calls == 1


def test_start_does_not_wire_a_daemon_that_died(monkeypatch):
    # Nothing should schedule a crashing daemon to run at every login.
    lc = _Lifecycle(installed=False)
    _start(monkeypatch, lc, outcome="died")
    assert lc.install_calls == 0


def test_a_failed_install_is_reported_but_never_fails_the_start(monkeypatch):
    lc = _Lifecycle(installed=False, install_raises=RuntimeError("systemctl not found"))
    r = _start(monkeypatch, lc)
    assert r.exit_code == 0, r.output          # dictation is running; that is the job
    assert "could not set YazSes to start at login" in r.output
    assert "systemctl not found" in r.output
    assert "autostart enable" in r.output      # how to retry


def test_an_unanswerable_query_does_not_trigger_an_install(monkeypatch):
    # If we cannot tell whether autostart is set up, changing it is a guess.
    lc = _Lifecycle(query_raises=OSError("dbus unavailable"))
    r = _start(monkeypatch, lc)
    assert r.exit_code == 0, r.output
    assert lc.install_calls == 0


@pytest.mark.parametrize("attr", ["install_autostart", "is_autostart_installed"])
def test_a_backend_without_autostart_support_is_left_alone(monkeypatch, attr):
    # Not every platform backend implements autostart; `start` must still work.
    monkeypatch.delattr(_Lifecycle, attr)
    lc = _Lifecycle(installed=False)
    r = _start(monkeypatch, lc)
    assert r.exit_code == 0, r.output
    assert lc.install_calls == 0
