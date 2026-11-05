"""Is the daemon running, and which process is it?

Two artifacts can answer that and they used to disagree. The **PID file** is written by
the daemon and removed on a clean exit — but nothing removes it after a kill -9, and
nothing recreates it if it is deleted while the daemon lives. The **lock file** is held by
the OS for the lifetime of the process, so it is exact in both directions: never stale
after a crash, never absent while a daemon runs.

That difference was not academic. With the PID file missing under a live daemon,
``yazses status`` said "not running" while starting one failed with "another YazSes daemon
is already running" — the user was told to start something that then refused to start, and
neither message was actionable. So the lock is the authority here, and the PID file is a
fallback for platforms with no lock primitive.
"""
from __future__ import annotations

import os
from pathlib import Path

from yazses.system.proc import process_alive

# The fallback layout, used only when a caller does not say where the data directory is.
# `LinuxLifecycle` always does: the daemon takes its instance lock at
# ``paths.data_dir / "daemon.lock"`` (``core/daemon.py``), and ``paths.data_dir`` follows
# ``$XDG_DATA_HOME`` through platformdirs. A hard-coded ``~/.local/share`` therefore looked
# for the lock in a different place from where it is held whenever ``XDG_DATA_HOME`` is set,
# so ``is_running()`` said "not running" for a live daemon -- and a sandboxed run wrote and
# deleted the *real* ``daemon.pid``.
_DATA_DIR = Path.home() / ".local" / "share" / "yazses"
_PID_FILE = _DATA_DIR / "daemon.pid"
_LOCK_FILE = _DATA_DIR / "daemon.lock"


def _pid_file(data_dir: Path | None) -> Path:
    return _PID_FILE if data_dir is None else Path(data_dir) / "daemon.pid"


def _lock_file(data_dir: Path | None) -> Path:
    return _LOCK_FILE if data_dir is None else Path(data_dir) / "daemon.lock"


def write_pid(data_dir: Path | None = None) -> None:
    pid_file = _pid_file(data_dir)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")


def read_pid(data_dir: Path | None = None) -> int | None:
    """The daemon's PID: from the lock if it is held, else the PID file."""
    from yazses.system.single_instance import holder_pid

    lock_file = _lock_file(data_dir)
    held = holder_pid(lock_file)
    if held is not None and held > 0:
        return held
    if held is not None:  # held, but the PID bytes were unreadable
        return _read_pid_file(data_dir)
    # Nobody holds the lock. Trust that over a PID file left behind by a crash, but only
    # where locking actually works — otherwise fall back rather than claim "not running".
    if lock_file.exists() and _locking_supported():
        return None
    return _read_pid_file(data_dir)


def _read_pid_file(data_dir: Path | None = None) -> int | None:
    pid_file = _pid_file(data_dir)
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def read_pid_file(data_dir: Path | None = None) -> int | None:
    """The pid written in the pid *file* itself, ignoring the lock. None if absent or unreadable.

    `read_pid` prefers the lock holder, which is the right answer to "who is the daemon"
    and the wrong one to "whose pid file is this": a daemon tearing down still holds the
    lock, so asking `read_pid` would always name itself.
    """
    return _read_pid_file(data_dir)


def _locking_supported() -> bool:
    from yazses.system import single_instance

    return single_instance.fcntl is not None or single_instance.msvcrt is not None


def clear_pid(data_dir: Path | None = None) -> None:
    _pid_file(data_dir).unlink(missing_ok=True)


def is_running(data_dir: Path | None = None) -> bool:
    """True when a YazSes daemon is alive. Must agree with what starting one will do."""
    from yazses.system.single_instance import holder_pid

    lock_file = _lock_file(data_dir)
    if holder_pid(lock_file) is not None:
        return True  # the lock is held — a daemon is running, whatever the PID file says

    pid = _read_pid_file(data_dir)
    if pid is None:
        return False
    if lock_file.exists() and _locking_supported():
        # The lock is free, so no daemon holds it; a leftover PID file is not evidence.
        return False
    # `os.kill(pid, 0)` used to stand here. It is the POSIX idiom and it *terminates*
    # the process on Windows, so `status`, `doctor` and the tray's poll loop each had a
    # path that killed whatever held that PID — the daemon, or after a PID recycle some
    # unrelated program. See `system/proc.py`.
    if not process_alive(pid):
        return False
    # Guard against recycled PIDs: verify the process is actually our daemon.
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text(
            encoding="utf-8", errors="replace"
        )
        return "yazses" in cmdline
    except OSError:
        return True
