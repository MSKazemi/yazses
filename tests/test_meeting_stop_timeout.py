"""`meeting stop` must not report a busy daemon as a dead one.

Found by running Meeting Mode on a real machine (#48). Stopping waits for the
in-flight live decode before it answers, which routinely exceeds the 2-second IPC
timeout — and a timeout and an absent daemon raise the same exception. So every
real meeting printed "Daemon is not running." while the daemon went on to
finalize the meeting successfully seconds later.

Telling someone they lost a meeting they did not lose is the worst failure this
command has.
"""

from __future__ import annotations

import types

from typer.testing import CliRunner

import yazses.cli as cli
from yazses.ipc.client import IpcUnreachableError

runner = CliRunner()


def _platform(tmp_path, *, running: bool):
    def factory(_sock):
        def call(_method, **_kw):
            raise IpcUnreachableError(tmp_path / "sock")
        return types.SimpleNamespace(call=call)

    return types.SimpleNamespace(
        paths=types.SimpleNamespace(
            ipc_socket=tmp_path / "sock", config_file=tmp_path / "config.toml",
            data_dir=tmp_path,
        ),
        lifecycle=types.SimpleNamespace(is_running=lambda: running, read_pid=lambda: 1),
        ipc_client_factory=factory,
    )


def test_a_timeout_while_the_daemon_is_alive_is_not_reported_as_dead(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path, running=True))
    result = runner.invoke(cli.app, ["meeting", "stop"])
    assert result.exit_code == 0, "a meeting that is finalizing is not a failure"
    assert "Daemon is not running" not in result.output
    assert "still" in result.output and "finalizing" in result.output
    assert "yazses meeting status" in result.output, "must say how to see the result"


def test_a_genuinely_absent_daemon_still_says_so(tmp_path, monkeypatch):
    """The fix must not swallow the real case."""
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path, running=False))
    result = runner.invoke(cli.app, ["meeting", "stop"])
    assert result.exit_code == 1
    assert "Daemon is not running" in result.output
