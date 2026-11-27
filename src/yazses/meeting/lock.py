"""One owner per meeting folder at a time — ADR-v2-127.

The daemon writes a meeting folder from the first audio chunk until the post-pass ends,
and ``yazses meeting recover`` / ``relabel`` / ``notes`` / ``summary`` write the same files
from another process. Whoever writes holds this lock.

It is :class:`~yazses.system.single_instance.SingleInstanceLock`, the OS file lock the
daemon already uses on itself: the kernel releases it when its holder exits or crashes, so
it cannot go stale and there is nothing to clean up by hand. The ``.lock`` file stays in
the folder; its presence means nothing, only a held lock does. It is never deleted, because
removing a lock file lets two processes each lock a different file of the same name.
"""
from __future__ import annotations

import errno
import logging
import os
import threading
import time
from pathlib import Path

from yazses.system.single_instance import (
    SingleInstanceLock,
    holder_pid,
    locks_unsupported,
)

log = logging.getLogger(__name__)

LOCK_NAME = ".lock"

# `is_busy` has to take the lock for an instant to learn whether anyone holds it, so an
# acquire that meets such a probe waits it out instead of reporting a busy meeting.
_WAIT_S = 0.5
_RETRY_S = 0.05

# Locks held by this process. Consulted before touching the file: where `flock` is emulated
# with per-process record locks (NFS), the daemon probing its own meeting would be granted
# the lock and would drop it again on closing the probe.
_HELD: set[str] = set()
_GUARD = threading.Lock()


class MeetingBusyError(RuntimeError):
    """Another owner holds the meeting. ``pid`` is its process id when it is known."""

    def __init__(self, meeting_dir: str | Path, pid: int | None = None) -> None:
        super().__init__(f"meeting folder is in use: {meeting_dir}")
        self.pid = pid


def busy_message(meeting_id: str, pid: int | None = None) -> str:
    """Why a command did nothing, and what to do next. Pure."""
    who = f" (process {pid})" if pid is not None and pid > 0 else ""
    return (
        f"Meeting {meeting_id} is in use{who}: it is still recording or being processed, "
        "or another `yazses meeting` command is working on it. Nothing was changed.\n"
        "Next: `yazses meeting status` shows whether it is recording (finish it with "
        "`yazses meeting stop`) or finalizing. Run this command again once that is done."
    )


def _key(path: Path) -> str:
    return os.path.normcase(os.path.realpath(path))


class MeetingLock:
    """The exclusive lock on one meeting folder. Use as a context manager or release()."""

    def __init__(self, meeting_dir: str | Path) -> None:
        self._dir = Path(meeting_dir)
        self._path = self._dir / LOCK_NAME
        self._lock = SingleInstanceLock(self._path)
        self._held_key: str | None = None

    def acquire(self) -> None:
        """Take the lock.

        Raises :class:`MeetingBusyError` when someone else holds it, and ``OSError`` when
        the folder is missing (it is never created here) or the lock file cannot be
        opened. On a filesystem that has no file locks it logs a warning and carries on.
        """
        if self._held_key is not None:
            return
        if not self._dir.is_dir():
            raise FileNotFoundError(errno.ENOENT, "no meeting folder", str(self._dir))
        if self._path.is_symlink():
            # Taking the lock writes a PID into the file; not through a link.
            raise OSError(errno.ELOOP, "refusing to lock through a symlink", str(self._path))
        key = _key(self._path)
        deadline = time.monotonic() + _WAIT_S
        while True:
            with _GUARD:
                ours = key in _HELD
                if not ours:
                    taken = self._lock.acquire()
                    # A filesystem without locks (`[meeting] output_dir` may be on one)
                    # is not contention: refusing would stop every meeting.
                    if not taken and locks_unsupported(self._lock.error):
                        log.warning(
                            "No file locks on the filesystem holding %s (%s); continuing "
                            "without one.", self._dir, self._lock.error,
                        )
                        taken = True
                    if taken:
                        _HELD.add(key)
                        self._held_key = key
                        return
            if time.monotonic() >= deadline:
                pid = os.getpid() if ours else holder_pid(self._path)
                raise MeetingBusyError(self._dir, pid)
            time.sleep(_RETRY_S)

    def release(self) -> None:
        """Give the lock up. A no-op when it is not held."""
        if self._held_key is None:
            return
        with _GUARD:
            self._lock.release()
            _HELD.discard(self._held_key)
            self._held_key = None

    def __enter__(self) -> MeetingLock:
        self.acquire()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.release()


def is_busy(meeting_dir: str | Path) -> bool:
    """True while someone holds this meeting's lock. Creates no file; never raises.

    A momentary answer for display. Code that is about to write must take the lock.
    """
    path = Path(meeting_dir) / LOCK_NAME
    try:
        if path.is_symlink() or not path.is_file():
            return False
        with _GUARD:
            if _key(path) in _HELD:
                return True
            probe = SingleInstanceLock(path)
            if probe.acquire():
                probe.release()
                return False
            return not locks_unsupported(probe.error)
    except OSError:
        return False
