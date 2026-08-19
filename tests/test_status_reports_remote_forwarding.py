"""No surface said your dictation was being sent to another machine.

`yazses remote <host>` opens an SSH tunnel and routes every transcript to an agent on the
far end. That is one of exactly two paths ADR-019 lists as able to transmit what you said,
and the project's central claim is that nothing leaves this machine.

The daemon has published `remote_connected` since that feature shipped. Nothing read it —
not `yazses status`, not the tray, not `doctor`. Found by mapping all 36 status keys to
their consumers; seven had none, and this was the one that mattered.

## `state` cannot stand in for it

The daemon sets `REMOTE_ACTIVE` when the tunnel comes up, but a hold-to-talk burst moves it
through `RECORDING` → `TRANSCRIBING` and `_on_hold_end` finishes at `IDLE`. So `state` says
"remote" only until the *next* thing you dictate — after which `yazses status` reads exactly
like a local session, for the whole rest of the connection.

## Why it is worth a line even though the user started it

They started it deliberately; they did not necessarily start it *recently*. A tunnel
survives a lunch break and a change of task, and the one command whose job is to say what
the daemon is doing said nothing about the only state in which words leave the computer.

The tray is deliberately left alone: its five colours have documented meanings and adding a
sixth is a design change, not a fix. `yazses status` is where the docs already point.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses.cli import app


class _Client:
    def __init__(self, status):
        self._status = status

    def is_reachable(self):
        return True

    def call(self, _method, **_kw):
        return self._status


BASE = {
    "state": "idle",
    "hotkey": "right_ctrl",
    "model": "base.en",
    "injection_backend": "XdotoolInjector",
    "uptime_s": 60.0,
    "ready": True,
}


@pytest.fixture
def run(monkeypatch):
    from yazses import cli

    def _go(status_extra):
        class _Lifecycle:
            def read_pid(self):
                return 1234

            def is_running(self):
                return True

        class _Paths:
            ipc_socket = "/tmp/nope.sock"
            data_dir = "/tmp"
            config_file = "/tmp/config.toml"

        class _Platform:
            name = "linux"
            lifecycle = _Lifecycle()
            paths = _Paths()

            @staticmethod
            def ipc_client_factory(_s):
                return _Client({**BASE, **status_extra})

        monkeypatch.setattr(cli, "get_platform", lambda: _Platform())
        return CliRunner().invoke(app, ["status"])

    return _go


def test_an_active_remote_session_is_reported(run) -> None:
    result = run({"remote_connected": True})
    assert result.exit_code == 0, result.output
    assert "remote:" in result.output
    assert "being sent" in result.output


def test_it_is_reported_even_when_the_state_has_moved_on(run) -> None:
    """The case that made this invisible: `state` is IDLE for the rest of the session."""
    result = run({"remote_connected": True, "state": "idle"})
    assert "remote:" in result.output


def test_a_local_session_says_nothing_about_remote(run) -> None:
    """The expensive direction: a line on every status would be noise, and worse,
    would stop meaning anything when it mattered."""
    result = run({"remote_connected": False})
    assert result.exit_code == 0, result.output
    assert "remote:" not in result.output


def test_an_older_daemon_without_the_field_says_nothing(run) -> None:
    """A status payload predating the field must not read as 'remote is on'."""
    result = run({})
    assert result.exit_code == 0, result.output
    assert "remote:" not in result.output


def test_the_daemon_still_publishes_the_field() -> None:
    """The whole line rests on it; a rename must fail here rather than silently
    returning to no surface at all."""
    import inspect

    from yazses.core.daemon import Daemon

    assert '"remote_connected"' in inspect.getsource(Daemon)


def test_the_state_field_is_not_a_substitute() -> None:
    """Pinned so nobody 'simplifies' this away by pointing at `state`.

    `_on_hold_end` returns the state to IDLE after a burst, so REMOTE_ACTIVE does not
    survive the first thing you say.
    """
    import inspect

    from yazses.core.daemon import Daemon

    source = inspect.getsource(Daemon._on_hold_end)
    assert "self._state.state = TrayState.IDLE" in source, (
        "the burst no longer ends at IDLE — re-check whether `state` now survives a "
        "remote session, in which case this line could be derived from it"
    )
