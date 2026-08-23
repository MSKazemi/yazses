"""`yazses remote --stop`: the one teardown allowed to lie about having succeeded.

`remote/local_proxy.py` is one of exactly two paths in the daemon that can send what the
user actually said off this machine (ADR-019; the other is the loopback LLM cleanup). So
"Remote session disconnected." is a privacy claim, not a status line -- and it was made
unconditionally:

* `_handle_remote_stop` dropped the forwarder from the daemon **before** tearing it down,
  then caught everything `disconnect()` raised with a `log.warning` and returned
  `{"ok": True}`. `RemoteForwarder.disconnect` clears `self._process` only on its last
  line, so a `terminate()`/`kill()` that raises leaves the SSH child alive with the
  tunnel up -- and the daemon has already forgotten it, so no later `--stop` can reach
  it. The user is told the session is closed.
* the CLI's failure branch printed to **stdout** and exited **0**, unlike the start
  branch three lines below it (`err=True` + `Exit(1)`). It was also unreachable, because
  the handler above could not return anything but ok.
* `--stop` required a positional `host` it then discarded: `yazses remote --stop` exited
  2 with "Missing argument 'host'", so closing a session meant retyping the host the
  daemon already knows.

The handler is exercised directly rather than over a socket: what is guarded is what the
answer says and what the daemon still holds afterwards, neither of which the transport
touches.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from yazses.cli import app
from yazses.core.daemon import Daemon
from yazses.ipc.protocol import Request

runner = CliRunner()


class _Forwarder:
    """A forwarder whose teardown fails the way a real one can.

    `subprocess.Popen.terminate()` raises `ProcessLookupError` when the child is reaped
    between the `poll()` and the signal, and `PermissionError` when it has changed
    credentials -- both real, both rare, and both silent today.
    """

    def __init__(self, exc: Exception | None = None) -> None:
        self._exc = exc
        self.disconnect_calls = 0

    def disconnect(self) -> None:
        self.disconnect_calls += 1
        if self._exc is not None:
            raise self._exc


def _daemon(forwarder) -> Daemon:
    """A Daemon with only the parts this handler touches.

    `object.__new__` rather than the constructor: constructing one loads a model, opens a
    socket and installs signal handlers, none of which decide what a stop reports.
    """
    daemon = object.__new__(Daemon)
    daemon._lock = threading.RLock()
    daemon._state = SimpleNamespace(state=None)
    daemon._remote_forwarder = forwarder
    daemon._remote_injector = object()
    return daemon


def _stop(daemon: Daemon) -> dict:
    return daemon._handle_remote_stop(Request(id=1, method="remote_stop", params={}))


# --- the daemon's answer -------------------------------------------------------------


def test_a_clean_disconnect_reports_ok_and_forgets_the_session():
    fwd = _Forwarder()
    daemon = _daemon(fwd)

    result = _stop(daemon)

    assert result["ok"] is True
    assert fwd.disconnect_calls == 1
    assert daemon._remote_forwarder is None
    assert daemon._remote_injector is None


def test_a_failed_disconnect_is_not_reported_as_success():
    """The whole point: the tunnel may still be up, so the answer must not say it isn't."""
    daemon = _daemon(_Forwarder(ProcessLookupError("no such process")))

    result = _stop(daemon)

    assert result["ok"] is False
    assert "no such process" in str(result.get("reason", ""))


def test_a_failed_disconnect_leaves_the_handle_reachable_for_a_retry():
    """A forwarder the daemon has dropped can never be torn down again.

    `disconnect()` sets `_stopping`/`_connected` before it touches the process and clears
    `_process` only after, so a second attempt still has a live handle to kill -- but
    only if the daemon kept the object.
    """
    fwd = _Forwarder(PermissionError("operation not permitted"))
    daemon = _daemon(fwd)

    _stop(daemon)

    assert daemon._remote_forwarder is fwd
    assert daemon._remote_injector is not None

    fwd._exc = None
    assert _stop(daemon)["ok"] is True
    assert fwd.disconnect_calls == 2
    assert daemon._remote_forwarder is None


def test_restoring_the_handle_never_clobbers_a_session_started_meanwhile():
    """`disconnect()` runs outside the lock (it blocks up to 5 s), so a `remote_start`
    can land in between. Putting the old handle back unconditionally would then discard
    the new session's forwarder and leak *that* tunnel instead."""
    newcomer = _Forwarder()
    daemon = _daemon(None)

    class _RacingForwarder(_Forwarder):
        def disconnect(self) -> None:
            daemon._remote_forwarder = newcomer
            super().disconnect()

    daemon._remote_forwarder = _RacingForwarder(OSError("teardown failed"))

    result = _stop(daemon)

    assert result["ok"] is False
    assert daemon._remote_forwarder is newcomer


def test_no_session_at_all_is_still_a_clean_stop():
    daemon = _daemon(None)
    assert _stop(daemon)["ok"] is True


# --- what the CLI does with that answer ----------------------------------------------


def _cli(call_result: dict):
    client = SimpleNamespace(call=lambda method, **kw: call_result)
    return SimpleNamespace(
        paths=SimpleNamespace(ipc_socket="/nonexistent/yazses.sock"),
        ipc_client_factory=lambda _sock: client,
    )


def test_stop_does_not_require_the_host_it_throws_away():
    with patch("yazses.cli.get_platform", return_value=_cli({"ok": True})):
        result = runner.invoke(app, ["remote", "--stop"])

    assert result.exit_code == 0, result.output
    assert "disconnected" in result.stdout


def test_a_failed_stop_exits_nonzero_and_says_so_on_stderr():
    """A script that pipes `yazses remote --stop` could not tell the two apart."""
    with patch(
        "yazses.cli.get_platform",
        return_value=_cli({"ok": False, "reason": "teardown failed"}),
    ):
        result = runner.invoke(app, ["remote", "--stop"])

    assert result.exit_code == 1
    assert "teardown failed" in result.stderr
    assert "disconnected" not in result.stdout


def test_connecting_still_requires_a_host_and_says_which_command_needs_it():
    """Making the argument optional must not turn a typo into a silent no-op."""
    with patch("yazses.cli.get_platform", return_value=_cli({"ok": True})):
        result = runner.invoke(app, ["remote"])

    assert result.exit_code == 1
    assert "host" in result.stderr.lower()
