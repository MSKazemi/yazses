"""Quit stops a daemon that does not answer, and a new start replaces a stale one (#578).

Two holes were left after the `before_quit` fix:

* **Quit** sent the IPC ``shutdown`` and, on any failure -- an unreachable socket, a call
  that timed out, a reply that failed -- did nothing more. A daemon that was alive but not
  answering survived Quit with whatever it read at start, which is #578's shape.
  `tray.app.stop_daemon_for_quit` now gives that daemon the lifecycle stop `yazses stop`
  uses. A daemon that *acknowledges* is left to finish on its own.
* **A duplicate start** replaced only a strictly older daemon. One that started before a
  permission was granted -- the reopened-app case -- made the new daemon exit as a
  duplicate. `core/takeover.startup_replacement_reason` now also replaces it, on its own
  ``stale_permissions`` report, only while idle or in error. One that does not answer is
  retried briefly, then named in the log and left running: no answer is not proof.

Everything is faked: the IPC client, the lifecycle, the lock and the clock. No process is
signalled and nothing on the host is read.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from yazses.config import Config
from yazses.core import daemon as daemon_mod
from yazses.core.daemon import Daemon
from yazses.core.takeover import startup_replacement_reason
from yazses.ipc.client import IpcCallError, IpcTimeoutError, IpcUnreachableError
from yazses.ipc.protocol import INTERNAL_ERROR, RpcError
from yazses.platform import get_platform
from yazses.tray.app import stop_daemon_for_quit

_MINE = "2.50.0"
_STALE = ["input_monitoring"]


# ---- the start-up rule (pure) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        # Older: replaced whatever its state, exactly as before this change.
        ({"version": "2.43.1"}, "older"),
        ({"state": "recording", "version": "2.43.1"}, "older"),
        # Predates a grant: replaced only while idle or in error, and not in a meeting.
        ({"state": "idle", "version": _MINE, "stale_permissions": _STALE}, "permissions"),
        ({"state": "error", "version": _MINE, "stale_permissions": _STALE}, "permissions"),
        ({"state": "recording", "version": _MINE, "stale_permissions": _STALE}, None),
        ({"state": "loading", "version": _MINE, "stale_permissions": _STALE}, None),
        ({"state": "idle", "version": _MINE, "stale_permissions": _STALE,
          "meeting_active": True}, None),
        # Healthy and current, newer, or unsure: never touched.
        ({"state": "idle", "version": _MINE}, None),
        ({"state": "idle", "version": _MINE, "stale_permissions": []}, None),
        ({"state": "idle", "version": "2.51.0", "stale_permissions": _STALE}, "permissions"),
        ({"state": "idle", "version": "2.51.0"}, None),
        ({"state": "idle"}, None),
        (None, None),
        ("idle", None),
    ],
)
def test_which_lock_holders_a_starting_daemon_replaces(status, expected):
    assert startup_replacement_reason(status, _MINE) == expected


# ---- a duplicate start against a stale or silent incumbent ------------------------------


class _Lock:
    """Held by the incumbent until it is told to shut down."""

    def __init__(self) -> None:
        self.released = False

    def acquire(self) -> bool:
        return self.released


class _Incumbent:
    def __init__(self, status, lock: _Lock, *, silent_for: int = 0, calls=None):
        self.status, self.lock, self.silent_for = status, lock, silent_for
        self.calls: list[str] = [] if calls is None else calls

    def call(self, method, **params):
        self.calls.append(method)
        if method == "status":
            assert params.get("consume_notifications") is False
            if self.silent_for > 0:
                self.silent_for -= 1
                raise IpcUnreachableError("/nowhere")
            return self.status
        self.lock.released = True
        return {"ok": True}


@pytest.fixture
def start(monkeypatch):
    monkeypatch.setattr(daemon_mod, "_running_version", lambda: _MINE)
    monkeypatch.setattr(daemon_mod, "_TAKEOVER_WAIT_S", 0.5)
    monkeypatch.setattr(daemon_mod, "_INCUMBENT_ANSWER_WAIT_S", 0.3)
    real_sleep = daemon_mod.time.sleep
    monkeypatch.setattr(daemon_mod.time, "sleep", lambda _s: real_sleep(0.01))

    def run(status, *, silent_for=0, pid=4242):
        lock = _Lock()
        incumbent = _Incumbent(status, lock, silent_for=silent_for)
        real = get_platform()
        d = Daemon(config=Config(), platform=real)
        d._platform = SimpleNamespace(
            paths=real.paths,
            ipc_client_factory=lambda _sock: incumbent,
            lifecycle=SimpleNamespace(read_pid=lambda: pid),
        )
        return d._replace_older_daemon(lock), incumbent.calls

    return run


def test_a_daemon_that_predates_a_grant_is_replaced_by_the_reopened_app(start):
    taken, calls = start({"state": "idle", "version": _MINE, "stale_permissions": _STALE})
    assert taken is True
    assert calls == ["status", "shutdown"]


def test_a_daemon_that_predates_a_grant_is_not_interrupted_mid_dictation(start):
    taken, calls = start(
        {"state": "recording", "version": _MINE, "stale_permissions": _STALE}
    )
    assert taken is False
    assert calls == ["status"]


def test_a_healthy_current_daemon_is_never_touched(start):
    taken, calls = start({"state": "idle", "version": _MINE, "stale_permissions": []})
    assert taken is False
    assert "shutdown" not in calls


def test_an_incumbent_still_opening_its_socket_is_asked_again(start):
    """It takes the lock a moment before it listens; a first miss is not the answer."""
    taken, calls = start(
        {"state": "idle", "version": _MINE, "stale_permissions": _STALE}, silent_for=3
    )
    assert taken is True
    assert calls == ["status"] * 4 + ["shutdown"]


def test_a_silent_incumbent_is_named_and_left_running(start, caplog):
    caplog.set_level(logging.ERROR, logger="yazses.core.daemon")
    taken, calls = start({"state": "idle"}, silent_for=10_000, pid=4242)
    assert taken is False
    assert "shutdown" not in calls
    assert len(calls) >= 2, "it is asked more than once before it is reported"
    message = " ".join(r.getMessage() for r in caplog.records)
    assert "pid 4242" in message and "has not answered" in message
    assert "yazses restart" in message


def test_a_silent_incumbent_without_a_pid_file_is_still_reported(start, caplog):
    caplog.set_level(logging.ERROR, logger="yazses.core.daemon")
    taken, _calls = start({"state": "idle"}, silent_for=10_000, pid=None)
    assert taken is False
    assert "has not answered" in " ".join(r.getMessage() for r in caplog.records)


# ---- Quit ----------------------------------------------------------------------------


class _Client:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    def call(self, method, **_):
        self.calls.append(method)
        if self.error is not None:
            raise self.error
        return {"ok": True}


class _Lifecycle:
    """`alive_for` is how many `is_running` checks after the stop still find it up."""

    def __init__(self, *, running=True, pid=777, alive_for=0, fail=False) -> None:
        self.running, self.pid, self.alive_for, self.fail = running, pid, alive_for, fail
        self.stopped: list[int] = []

    def is_running(self) -> bool:
        if self.fail:
            raise OSError("ps failed")
        if self.stopped:
            if self.alive_for <= 0:
                return False
            self.alive_for -= 1
        return self.running

    def read_pid(self):
        return self.pid

    def stop_daemon(self, pid: int) -> None:
        self.stopped.append(pid)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def _quit(client, lifecycle, **kw):
    clock = _Clock()
    return stop_daemon_for_quit(
        client, lifecycle, wait_s=1.0, poll_s=0.1, clock=clock, sleep=clock.sleep, **kw
    )


def test_an_acknowledged_shutdown_is_left_to_finish():
    """The normal path: no signal, even if the daemon is still tearing down."""
    life = _Lifecycle(running=True)
    assert _quit(_Client(), life) == "asked"
    assert life.stopped == []


@pytest.mark.parametrize(
    "error",
    [
        IpcUnreachableError("/nowhere"),
        IpcTimeoutError("/nowhere"),  # accepted the connection, never answered
        IpcCallError(RpcError(code=INTERNAL_ERROR, message="shutdown raised")),
        RuntimeError("x"),
    ],
)
def test_a_live_daemon_that_does_not_take_shutdown_is_stopped(error):
    """#578: Quit used to swallow this, and the daemon outlived it for days."""
    life = _Lifecycle(running=True, pid=777, alive_for=3)
    assert _quit(_Client(error), life) == "signalled"
    assert life.stopped == [777]


def test_no_answer_and_no_process_is_nothing_to_stop():
    life = _Lifecycle(running=False)
    assert _quit(_Client(IpcUnreachableError("/nowhere")), life) == "not-running"
    assert life.stopped == []


def test_no_pid_file_signals_nothing():
    life = _Lifecycle(running=True, pid=None)
    assert _quit(_Client(IpcUnreachableError("/nowhere")), life) == "not-running"
    assert life.stopped == []


def test_a_daemon_that_outlives_the_stop_is_reported_and_quit_does_not_hang(caplog):
    caplog.set_level(logging.ERROR, logger="yazses.tray.app")
    life = _Lifecycle(running=True, pid=777, alive_for=10_000)
    assert _quit(_Client(IpcUnreachableError("/nowhere")), life) == "still-running"
    assert life.stopped == [777], "signalled once, never escalated"
    assert "pid 777" in caplog.text and "yazses restart" in caplog.text


def test_quit_never_raises_when_the_lifecycle_does():
    life = _Lifecycle(fail=True)
    assert _quit(_Client(IpcUnreachableError("/nowhere")), life) == "still-running"
    assert life.stopped == []
