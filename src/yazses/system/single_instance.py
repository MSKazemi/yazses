"""Single-instance lock for the daemon (reliability — no duplicate daemons).

Two YazSes daemons running at once (the detached ``yazses start`` path and the
systemd unit) each grab the global hotkey and inject, so every dictation lands
twice. An exclusive lock on a lock file makes a second daemon detect the first
and refuse to start. The lock is held for the process lifetime and the OS
releases it automatically on exit or crash — so a stale lock never wedges
startup, unlike a bare PID file.

Cross-platform: POSIX uses ``fcntl.flock``; Windows uses ``msvcrt.locking``
(byte-range lock). On an exotic platform with neither, the lock degrades to a
no-op (``acquire`` returns True), since the IPC layer there is exclusive anyway.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX (Windows)
    fcntl = None  # type: ignore[assignment]

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows
    msvcrt = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# Windows byte-range locks are mandatory, so we lock a single byte far past any
# file content. That guarantees mutual exclusion between daemons while leaving
# the PID bytes at offset 0 freely readable (a byte-0 lock would block readers).
_WIN_LOCK_OFFSET = 1 << 30


def holder_pid(path: str | os.PathLike[str]) -> int | None:
    """PID of the process holding this lock, or ``None`` if nobody holds it.

    The authoritative answer to "is a daemon running?". The lock is owned by the OS, so
    it is released the instant the holder dies — it cannot go stale the way a PID file
    can, and a PID file *did* go stale in practice: with the file missing, `yazses status`
    reported "not running" while a daemon was very much running, and the next start
    attempt then failed with "another daemon is already running". Two commands, two
    opposite answers, and no way for the user to act on either.

    Probing acquires on a fresh file descriptor and releases immediately. On Linux a
    second open file description conflicts with the first even within one process, so
    this reports "held" correctly regardless of who is asking.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        fd = os.open(str(p), os.O_RDWR | getattr(os, "O_BINARY", 0))
    except OSError:
        return None
    try:
        if fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return _read_pid_bytes(fd)  # someone holds it
            fcntl.flock(fd, fcntl.LOCK_UN)  # we took it — so nobody else had it
            return None
        if msvcrt is not None:  # pragma: no cover - Windows
            try:
                os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                return _read_pid_bytes(fd)
            os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            return None
        return None  # no lock primitive: caller falls back to the PID file
    finally:
        try:
            os.close(fd)
        except OSError:  # pragma: no cover
            pass


def _read_pid_bytes(fd: int) -> int | None:
    """Read the PID the holder wrote at offset 0. ``-1`` means "held, PID unknown"."""
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        raw = os.read(fd, 32).decode(errors="replace").strip()
        return int(raw) if raw else -1
    except (OSError, ValueError):
        return -1


class SingleInstanceLock:
    """Exclusive file lock guarding against a second daemon."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = str(path)
        self._fd: int | None = None

    def acquire(self) -> bool:
        """Try to take the lock. True if held by us, False if another holds it."""
        if self._fd is not None:
            return True  # already held by this instance
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        # O_BINARY (Windows only; 0 elsewhere) keeps the PID write byte-exact.
        fd = os.open(
            self._path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0),
            0o644,
        )
        if fcntl is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                return False
        elif msvcrt is not None:  # Windows byte-range lock, far past any content
            try:
                os.lseek(fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError:
                os.close(fd)
                return False
        # else: no lock primitive available — degrade to a no-op (still record pid).
        try:
            pid = str(os.getpid()).encode()
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, pid)
            os.ftruncate(fd, len(pid))  # trim stale bytes from a previous run
        except OSError:  # pragma: no cover - diagnostic write only
            pass
        self._fd = fd
        return True

    def release(self) -> None:
        """Release the lock (no-op if not held). The OS also frees it on exit."""
        if self._fd is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            elif msvcrt is not None:
                os.lseek(self._fd, _WIN_LOCK_OFFSET, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
        except OSError:  # pragma: no cover
            pass
        finally:
            try:
                os.close(self._fd)
            except OSError:  # pragma: no cover
                pass
            self._fd = None
