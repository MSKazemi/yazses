"""Single-instance lock — prevents the duplicate-daemon double-typing bug.

Two YazSes daemons (the detached `yazses start` path + the systemd unit) could
run at once, both grabbing the hotkey and injecting every burst twice. An
exclusive file lock makes a second daemon refuse to start. The lock is advisory
(flock), held for the process lifetime, and auto-released on exit/crash.
"""
from __future__ import annotations

import os

from yazses.system.single_instance import SingleInstanceLock


def test_second_acquire_fails_while_first_holds(tmp_path):
    path = str(tmp_path / "daemon.lock")
    a = SingleInstanceLock(path)
    b = SingleInstanceLock(path)
    assert a.acquire() is True
    assert b.acquire() is False          # another process/instance holds it
    a.release()
    assert b.acquire() is True           # released → now available
    b.release()


def test_same_instance_reacquire_is_idempotent(tmp_path):
    a = SingleInstanceLock(str(tmp_path / "daemon.lock"))
    assert a.acquire() is True
    assert a.acquire() is True           # already held by us — still True, no conflict
    a.release()


def test_release_without_acquire_is_safe(tmp_path):
    SingleInstanceLock(str(tmp_path / "daemon.lock")).release()  # must not raise


def test_lock_file_records_pid(tmp_path):
    import os

    path = tmp_path / "daemon.lock"
    lock = SingleInstanceLock(str(path))
    assert lock.acquire() is True
    assert path.read_text(encoding="utf-8").strip() == str(os.getpid())
    lock.release()


def test_acquire_creates_missing_parent_dir(tmp_path):
    lock = SingleInstanceLock(str(tmp_path / "nested" / "dir" / "daemon.lock"))
    assert lock.acquire() is True
    lock.release()


# ---- daemon integration: a second daemon refuses to start -------------------

def test_daemon_refuses_to_start_when_lock_held(tmp_path, monkeypatch):
    """If another process holds the lock, the daemon's guard returns False."""
    import types

    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    d = Daemon(config=Config(), platform=get_platform())
    # Point the daemon's lock at an isolated path so the test never touches the
    # real ~/.local/share/yazses state.
    d._platform = types.SimpleNamespace(
        paths=types.SimpleNamespace(data_dir=tmp_path),
    )
    holder = SingleInstanceLock(str(tmp_path / "daemon.lock"))
    assert holder.acquire() is True
    try:
        assert d._acquire_instance_lock() is False   # second daemon refused
    finally:
        holder.release()
    # Once released, a daemon can acquire it.
    assert d._acquire_instance_lock() is True
    d._instance_lock.release()


# --- the lock as the authority on "is a daemon running?" ----------------------------


def test_holder_pid_is_none_when_nobody_holds_the_lock(tmp_path):
    from yazses.system.single_instance import holder_pid

    path = tmp_path / "daemon.lock"
    path.write_text("", encoding="utf-8")

    assert holder_pid(path) is None


def test_holder_pid_is_none_for_a_lock_that_was_never_created(tmp_path):
    from yazses.system.single_instance import holder_pid

    assert holder_pid(tmp_path / "absent.lock") is None


def test_holder_pid_reports_the_live_holder(tmp_path):
    from yazses.system.single_instance import SingleInstanceLock, holder_pid

    path = tmp_path / "daemon.lock"
    lock = SingleInstanceLock(path)
    assert lock.acquire()
    try:
        assert holder_pid(path) == os.getpid()
    finally:
        lock.release()

    assert holder_pid(path) is None, "release must make it free again"


def test_is_running_trusts_the_lock_when_the_pid_file_is_missing(tmp_path, monkeypatch):
    """The bug this fixes: status said "not running" while a daemon was running.

    With no PID file under a live daemon, `yazses status` reported nothing running and
    the next start then refused with "another daemon is already running" — two commands
    contradicting each other, neither actionable.
    """
    from yazses.system import pid as pid_module
    from yazses.system.single_instance import SingleInstanceLock

    lock_file = tmp_path / "daemon.lock"
    monkeypatch.setattr(pid_module, "_LOCK_FILE", lock_file)
    monkeypatch.setattr(pid_module, "_PID_FILE", tmp_path / "daemon.pid")

    lock = SingleInstanceLock(lock_file)
    assert lock.acquire()
    try:
        assert pid_module.is_running() is True
        assert pid_module.read_pid() == os.getpid()
    finally:
        lock.release()


def test_is_running_is_false_for_a_pid_file_left_by_a_crash(tmp_path, monkeypatch):
    """The other direction: a stale PID file must not fake a running daemon."""
    from yazses.system import pid as pid_module

    lock_file = tmp_path / "daemon.lock"
    lock_file.write_text("", encoding="utf-8")  # exists, unheld — a crashed daemon's leftovers
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")  # a live pid, but not holding the lock
    monkeypatch.setattr(pid_module, "_LOCK_FILE", lock_file)
    monkeypatch.setattr(pid_module, "_PID_FILE", pid_file)

    assert pid_module.is_running() is False
