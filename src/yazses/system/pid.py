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

_DATA_DIR = Path.home() / ".local" / "share" / "yazses"
_PID_FILE = _DATA_DIR / "daemon.pid"
_LOCK_FILE = _DATA_DIR / "daemon.lock"


def write_pid() -> None:
    _PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def read_pid() -> int | None:
    """The daemon's PID: from the lock if it is held, else the PID file."""
    from yazses.system.single_instance import holder_pid

    held = holder_pid(_LOCK_FILE)
    if held is not None and held > 0:
        return held
    if held is not None:  # held, but the PID bytes were unreadable
        return _read_pid_file()
    # Nobody holds the lock. Trust that over a PID file left behind by a crash, but only
    # where locking actually works — otherwise fall back rather than claim "not running".
    if _LOCK_FILE.exists() and _locking_supported():
        return None
    return _read_pid_file()


def _read_pid_file() -> int | None:
    if not _PID_FILE.exists():
        return None
    try:
        return int(_PID_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def _locking_supported() -> bool:
    from yazses.system import single_instance

    return single_instance.fcntl is not None or single_instance.msvcrt is not None


def clear_pid() -> None:
    _PID_FILE.unlink(missing_ok=True)


def is_running() -> bool:
    """True when a YazSes daemon is alive. Must agree with what starting one will do."""
    from yazses.system.single_instance import holder_pid

    if holder_pid(_LOCK_FILE) is not None:
        return True  # the lock is held — a daemon is running, whatever the PID file says

    pid = _read_pid_file()
    if pid is None:
        return False
    if _LOCK_FILE.exists() and _locking_supported():
        # The lock is free, so no daemon holds it; a leftover PID file is not evidence.
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it — assume it's running.
        return True
    # Guard against recycled PIDs: verify the process is actually our daemon.
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_text()
        return "yazses" in cmdline
    except OSError:
        return True
