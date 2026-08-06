"""`yazses start` / `restart` readiness verification and no-duplicate / self-heal wiring.

These cover the goal that a `start`:
  * never leaves two daemons running (routes an already-running one through restart),
  * routes through systemd when a unit is installed (supervised → self-healing),
  * and reports honestly when the daemon is ready / still loading / crashed on start.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.ipc.client import IpcUnreachableError

runner = CliRunner()


class _Lifecycle:
    def __init__(self, running_seq):
        # running_seq: iterable of bools returned by successive is_running() calls.
        self._running = list(running_seq)
        self.detached_spawns = 0
        self.cleared = 0

    def is_running(self):
        return self._running.pop(0) if self._running else False

    def clear_pid(self):
        self.cleared += 1

    def start_daemon_detached(self):
        self.detached_spawns += 1

    def read_pid(self):
        return None


class _Client:
    def __init__(self, responses):
        # responses: iterable of dicts to return, or IpcUnreachableError instances.
        self._responses = list(responses)

    def call(self, _method):
        item = self._responses.pop(0) if self._responses else IpcUnreachableError("gone")
        if isinstance(item, Exception):
            raise item
        return item


class _Paths:
    ipc_socket = "/tmp/yazses-test.sock"
    config_file = "/tmp/yazses-test-config.toml"
    data_dir = None


class _Platform:
    default_hotkey = "right_ctrl"
    name = "linux"

    def __init__(self, lifecycle, client):
        self.lifecycle = lifecycle
        self.paths = _Paths()
        self._client = client

    def ipc_client_factory(self, _socket):
        return self._client


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    # Never actually sleep or warn during these tests.
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda *_: None)
    monkeypatch.setattr(cli, "_warn_unmet_prereqs", lambda: None)
    monkeypatch.setattr(cli, "_systemd_managed", lambda: False)


# ---- _wait_until_ready -----------------------------------------------------


def test_wait_until_ready_returns_ready_on_idle(monkeypatch):
    lc = _Lifecycle([True, True])
    client = _Client([{"state": "loading"}, {"state": "idle", "ready": True}])
    plat = _Platform(lc, client)
    outcome, info = cli._wait_until_ready(plat, timeout=5.0)
    assert outcome == "ready"
    assert info["state"] == "idle"


def test_wait_until_ready_detects_crash(monkeypatch):
    # PID appears (True) then vanishes (False) → the daemon died during startup.
    lc = _Lifecycle([True, False])
    client = _Client([IpcUnreachableError("x"), {"state": "loading", "last_error": "boom"}])
    plat = _Platform(lc, client)
    outcome, info = cli._wait_until_ready(plat, timeout=5.0)
    assert outcome == "died"


def test_wait_until_ready_error_state_is_death(monkeypatch):
    lc = _Lifecycle([True, True])
    client = _Client([{"state": "error", "last_error": "mic gone"}])
    plat = _Platform(lc, client)
    outcome, info = cli._wait_until_ready(plat, timeout=5.0)
    assert outcome == "died"
    assert info["last_error"] == "mic gone"


def test_wait_until_ready_times_out_as_loading(monkeypatch):
    # Still alive and loading past the deadline → informative, not an error.
    import time as _time

    ticks = iter([0.0, 0.1, 100.0])  # third read is past deadline
    monkeypatch.setattr(_time, "monotonic", lambda: next(ticks))
    lc = _Lifecycle([True, True, True])
    client = _Client([{"state": "loading"}, {"state": "loading"}])
    plat = _Platform(lc, client)
    outcome, _info = cli._wait_until_ready(plat, timeout=1.0)
    assert outcome == "loading"


# ---- _report_start_outcome -------------------------------------------------


def test_report_ready(capsys):
    plat = _Platform(_Lifecycle([]), _Client([]))
    cli._report_start_outcome(plat, "ready", {"state": "idle"})
    assert "started" in capsys.readouterr().out.lower()


def test_report_loading(capsys):
    plat = _Platform(_Lifecycle([]), _Client([]))
    cli._report_start_outcome(plat, "loading", {"state": "loading"})
    assert "loading" in capsys.readouterr().out.lower()


def test_report_died_exits_nonzero_with_reason(capsys):
    plat = _Platform(_Lifecycle([]), _Client([]))
    import typer

    with pytest.raises(typer.Exit) as exc:
        cli._report_start_outcome(plat, "died", {"last_error": "PortAudio not found"})
    assert exc.value.exit_code == 1
    err = capsys.readouterr().err
    assert "failed to start" in err.lower()
    assert "PortAudio not found" in err


# ---- _spawn_daemon routing -------------------------------------------------


def test_spawn_detached_when_no_systemd(monkeypatch):
    monkeypatch.setattr(cli, "_systemd_managed", lambda: False)
    lc = _Lifecycle([])
    plat = _Platform(lc, _Client([]))
    cli._spawn_daemon(plat)
    assert lc.detached_spawns == 1


def test_spawn_via_systemd_when_managed(monkeypatch):
    monkeypatch.setattr(cli, "_systemd_managed", lambda: True)
    calls = []
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a[0]))
    lc = _Lifecycle([])
    plat = _Platform(lc, _Client([]))
    cli._spawn_daemon(plat)
    assert lc.detached_spawns == 0  # NOT an unsupervised process
    assert calls and calls[0][:3] == ["systemctl", "--user", "start"]


# ---- end-to-end start ------------------------------------------------------


def test_start_when_not_running_spawns_and_reports_ready(monkeypatch):
    # is_running: initial check False, then ready-poll sees it up.
    lc = _Lifecycle([False, True, True])
    client = _Client([{"state": "idle", "ready": True}])
    plat = _Platform(lc, client)
    monkeypatch.setattr(cli, "get_platform", lambda: plat)
    result = runner.invoke(cli.app, ["start"])
    assert result.exit_code == 0
    assert lc.detached_spawns == 1
    assert "started" in result.output.lower()


def test_start_when_already_running_restarts_no_duplicate(monkeypatch):
    lc = _Lifecycle([True, True, True])
    client = _Client([{"state": "idle", "ready": True}])
    plat = _Platform(lc, client)
    monkeypatch.setattr(cli, "get_platform", lambda: plat)
    restarted = []
    monkeypatch.setattr(cli, "_restart_daemon", lambda p: restarted.append(p))
    result = runner.invoke(cli.app, ["start"])
    assert result.exit_code == 0
    assert restarted == [plat]  # went through the clean-restart path
    assert lc.detached_spawns == 0  # did NOT spawn a second daemon directly
    assert "restarting" in result.output.lower()


def test_start_reports_failure_when_daemon_crashes(monkeypatch):
    # Not running initially; spawn; PID appears then vanishes → died.
    lc = _Lifecycle([False, True, False])
    client = _Client([{"state": "loading", "last_error": "PortAudio library not found"}])
    plat = _Platform(lc, client)
    monkeypatch.setattr(cli, "get_platform", lambda: plat)
    result = runner.invoke(cli.app, ["start"])
    assert result.exit_code == 1
    assert "failed to start" in result.output.lower()
