"""`yazses restart` destroyed a meeting's write-up, and the daemon was already saying so.

Stopping a meeting starts a post-pass: batch diarization over the whole recording, then the
minutes. `_handle_meeting_stop` sets `meeting_finalizing` and runs that work inline. The
SIGTERM handler does not wait for it, and `yazses restart` sends SIGTERM, sleeps **one
second**, then SIGKILLs any survivor.

So stopping the daemon in that window kills the write-up. The rolling `live.jsonl` survives
— the store flags such folders recoverable — but the accurate speaker labels and the minutes
do not, and there is no `yazses meeting recover` to redo them.

## Why the collision is likely rather than theoretical

`yazses features enable <name>` ends with *"Apply it: yazses restart"*. So the product
itself asks for a restart, routinely, with no idea whether a meeting is being written up.

## The signal already existed

The daemon has published `meeting_finalizing` since Meeting Mode reached the tray, precisely
because *"after a stop the daemon is back to IDLE while diarization and the notes still
run"*. The tray reads it, to grey out "Start meeting". Nothing on the stop path did — so the
one surface that could prevent the loss was the one not asking. Same shape as
`recimport`'s `silent_input`, which only `yazses transcribe` consulted.

## Best-effort on purpose

An unreachable or older daemon answers False and the command proceeds. Refusing to stop a
daemon you cannot query would be worse than the loss this guards against — `yazses restart`
is what someone reaches for when the daemon is wedged.

`--force` follows the house pattern for destructive commands (`corpus destroy --i-mean-it`,
`gitvoice --run --yes`): refuse by default, name the escape.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from yazses.cli import app


class _Client:
    def __init__(self, reachable=True, status=None, raises=False):
        self._reachable, self._status, self._raises = reachable, status or {}, raises

    def is_reachable(self):
        if self._raises:
            raise OSError("socket went away")
        return self._reachable

    def call(self, _method, **_kw):
        return self._status


@pytest.fixture
def daemon(monkeypatch):
    """Patch the platform so no real daemon is touched."""
    from yazses import cli

    state = {"client": _Client(status={"meeting_finalizing": False}), "stopped": False}

    class _Lifecycle:
        def read_pid(self):
            return 4242

        def is_running(self):
            return True

        def stop_daemon(self, _pid):
            state["stopped"] = True

    class _Paths:
        ipc_socket = "/tmp/nonexistent.sock"
        data_dir = "/tmp"
        config_file = "/tmp/config.toml"

    class _Platform:
        name = "linux"
        lifecycle = _Lifecycle()
        paths = _Paths()

        @staticmethod
        def ipc_client_factory(_socket):
            return state["client"]

    monkeypatch.setattr(cli, "get_platform", lambda: _Platform())
    return state


def test_stop_refuses_while_a_meeting_is_being_written_up(daemon) -> None:
    daemon["client"] = _Client(status={"meeting_finalizing": True})
    result = CliRunner().invoke(app, ["stop"])
    assert result.exit_code == 1
    assert not daemon["stopped"], "the daemon was stopped mid write-up"
    assert "still being written up" in result.output
    assert "--force" in result.output


def test_stop_proceeds_when_no_meeting_is_finalizing(daemon) -> None:
    """The expensive direction: a guard that always fired would break `yazses stop`."""
    result = CliRunner().invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert daemon["stopped"]


def test_force_stops_anyway(daemon) -> None:
    daemon["client"] = _Client(status={"meeting_finalizing": True})
    result = CliRunner().invoke(app, ["stop", "--force"])
    assert result.exit_code == 0, result.output
    assert daemon["stopped"]


def test_an_unreachable_daemon_does_not_block_the_stop(daemon) -> None:
    """`yazses restart` is what you reach for when the daemon is wedged."""
    daemon["client"] = _Client(reachable=False)
    result = CliRunner().invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert daemon["stopped"]


def test_an_ipc_error_does_not_block_the_stop(daemon) -> None:
    daemon["client"] = _Client(raises=True)
    result = CliRunner().invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert daemon["stopped"]


def test_an_older_daemon_without_the_field_does_not_block(daemon) -> None:
    """A status payload predating Meeting Mode has no such key."""
    daemon["client"] = _Client(status={"state": "idle"})
    result = CliRunner().invoke(app, ["stop"])
    assert result.exit_code == 0, result.output
    assert daemon["stopped"]


def test_restart_asks_the_same_question() -> None:
    """It is the more dangerous of the two: SIGTERM, one second, SIGKILL."""
    import inspect

    from yazses.cli import restart

    source = inspect.getsource(restart)
    assert "_refuse_while_finalizing(platform" in source
    assert source.index("_refuse_while_finalizing(platform") < source.index(
        "_restart_daemon(platform)"
    )


def test_the_daemon_still_publishes_the_field() -> None:
    """The whole guard rests on it; if it is renamed, this fails rather than the guard
    silently answering False for ever."""
    import inspect

    from yazses.core.daemon import Daemon

    assert '"meeting_finalizing": self._meeting_finalizing' in inspect.getsource(Daemon)
