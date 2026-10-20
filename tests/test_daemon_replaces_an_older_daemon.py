"""After an upgrade the new daemon replaces the old one instead of exiting as a duplicate.

A daemon reads its permissions, config and code once, at start. The macOS report (#562,
#578) is a daemon from three days earlier answering with the permission it read before it
was granted, while every relaunch of the app exited as a duplicate. Only a **strictly
older** daemon is replaced; an equal or newer one, or one that will not say, is left
alone and reported as a duplicate exactly as before.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yazses.config import Config
from yazses.core import daemon as daemon_mod
from yazses.core.daemon import Daemon
from yazses.core.takeover import is_older
from yazses.ipc.client import IpcUnreachableError
from yazses.platform import get_platform


@pytest.mark.parametrize(
    ("incumbent", "mine", "expected"),
    [
        ("2.40.0", "2.43.1", True),
        ("2.43.0", "2.43.1", True),
        ("2.9.0", "2.10.0", True),        # numeric, not lexicographic
        ("2.43.1", "2.43.1", False),      # a duplicate start, not an upgrade
        ("2.44.0", "2.43.1", False),      # never displace a newer one
        ("2.43.1.dev3", "2.43.1", False),  # a suffix alone is not a reason
        (None, "2.43.1", False),          # an old daemon that reports no version
        ("unknown", "2.43.1", False),
        ("2.40.0", None, False),
        ("2.40.0", "garbage", False),
        (2.40, "2.43.1", False),          # wrong type from a malformed reply
    ],
)
def test_only_a_strictly_older_daemon_is_replaced(incumbent, mine, expected):
    assert is_older(incumbent, mine) is expected


class _FakeLock:
    """Held by someone else until `held_for` acquire attempts have failed."""

    instances: list[_FakeLock] = []

    held_for = 0

    def __init__(self, _path) -> None:
        self.attempts = 0
        self.held_for = _FakeLock.held_for
        _FakeLock.instances.append(self)

    def acquire(self) -> bool:
        self.attempts += 1
        return self.attempts > self.held_for


class _FakeClient:
    def __init__(self, version, calls, unreachable=False):
        self._version, self._calls, self._unreachable = version, calls, unreachable

    def call(self, method, **_):
        self._calls.append(method)
        if self._unreachable:
            raise IpcUnreachableError("/nowhere")
        if method == "status":
            # The incumbent's toast queue must survive being asked its version.
            assert _.get("consume_notifications") is False
            return {"version": self._version} if self._version is not None else {}
        return {"ok": True}


@pytest.fixture
def start(monkeypatch):
    """Run `_acquire_instance_lock` against a lock someone else holds, with a fake
    incumbent reporting `version`. Returns (acquired, rpc methods called)."""
    monkeypatch.setattr(daemon_mod, "_running_version", lambda: "2.43.1")
    monkeypatch.setattr(daemon_mod, "_TAKEOVER_WAIT_S", 0.6)
    real_sleep = daemon_mod.time.sleep
    monkeypatch.setattr(daemon_mod.time, "sleep", lambda _s: real_sleep(0.01))

    def run(version, *, held_for=1, unreachable=False):
        _FakeLock.held_for = held_for
        _FakeLock.instances = []
        monkeypatch.setattr("yazses.system.single_instance.SingleInstanceLock", _FakeLock)
        calls: list[str] = []
        real = get_platform()
        d = Daemon(config=Config(), platform=real)
        d._platform = SimpleNamespace(
            paths=real.paths,
            ipc_client_factory=lambda _sock: _FakeClient(version, calls, unreachable),
        )
        return d._acquire_instance_lock(), calls

    return run


def test_an_older_daemon_is_asked_to_stop_and_replaced(start):
    acquired, calls = start("2.40.0")

    assert acquired is True
    assert calls == ["status", "shutdown"]


def test_an_equal_version_is_a_duplicate_and_is_not_touched(start):
    acquired, calls = start("2.43.1")

    assert acquired is False
    assert calls == ["status"]


def test_a_newer_daemon_is_never_displaced(start):
    acquired, calls = start("2.50.0")

    assert acquired is False
    assert "shutdown" not in calls


def test_a_daemon_that_reports_no_version_is_left_alone(start):
    acquired, calls = start(None)

    assert acquired is False
    assert "shutdown" not in calls


def test_an_unreachable_incumbent_is_reported_as_before(start):
    """Lock held but nothing answering the socket: not ours to kill."""
    acquired, calls = start("2.40.0", unreachable=True)

    assert acquired is False
    assert "shutdown" not in calls


def test_an_older_daemon_that_will_not_leave_is_reported_not_forced(start):
    acquired, calls = start("2.40.0", held_for=10_000)

    assert acquired is False
    assert calls == ["status", "shutdown"]


def test_with_the_real_file_lock_the_new_daemon_takes_over_when_the_old_one_lets_go(
    monkeypatch, tmp_path
):
    """The fakes above prove the decision; this proves the OS lock really changes hands.
    The old daemon holds the real lock and releases it when asked to shut down."""
    from yazses.system.single_instance import SingleInstanceLock

    monkeypatch.setattr(daemon_mod, "_running_version", lambda: "2.43.1")
    old = SingleInstanceLock(tmp_path / "daemon.lock")
    assert old.acquire()

    class _OldDaemonClient:
        def call(self, method, **_):
            if method == "status":
                return {"version": "2.40.0"}
            old.release()  # shutdown: the old daemon exits and the OS frees the lock
            return {"ok": True}

    real = get_platform()
    d = Daemon(config=Config(), platform=real)
    d._platform = SimpleNamespace(
        paths=SimpleNamespace(data_dir=tmp_path, ipc_socket=tmp_path / "ipc.sock"),
        ipc_client_factory=lambda _sock: _OldDaemonClient(),
    )

    assert d._acquire_instance_lock() is True
    # and it is now genuinely ours: a third daemon is refused
    assert SingleInstanceLock(tmp_path / "daemon.lock").acquire() is False
