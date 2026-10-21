"""`yazses stop` tells a running tray that the daemon went away on purpose.

The tray restarts a daemon that disappears, because on Windows nothing else does
(``tray/app.py::unreachable_decision``). It could not tell a crash from a user's
`yazses stop`, so `stop` printed "YazSes stopped" and the tray had a new daemon up
within seconds. Measured on Windows 11: a new PID inside 10 s, every time.

`stop` now leaves a note before it stops the daemon. A tray that finds the daemon
gone and a note written *after the tray itself started* closes instead of restarting
it. A real crash leaves no note, so recovery is unchanged. `yazses restart` never
writes one, so it keeps the tray. A tray launched later ignores an older note by
the same timestamp rule, and `yazses start` removes it. Reading is total: anything
unreadable counts as no note, which is the behaviour before this module existed.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

FILENAME = "stop-requested"


def request_stop(data_dir: str | Path) -> None:
    """Leave the note. Raises OSError when the directory cannot be written."""
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / FILENAME).write_text(f"{time.time():.3f}\n", encoding="utf-8")


def stop_requested_since(data_dir: str | Path, since: float) -> bool:
    """True when a note was left at or after wall-clock time *since*.

    The time is read from the note's contents rather than its mtime, so a file
    system with coarse timestamps cannot round a fresh note into an old one.
    """
    try:
        written = float((Path(data_dir) / FILENAME).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return written >= since


def clear_stop_request(data_dir: str | Path) -> None:
    """Remove the note; a no-op when there is none."""
    note = Path(data_dir) / FILENAME
    try:
        note.unlink(missing_ok=True)
    except OSError:
        log.warning("Could not remove %s", note, exc_info=True)
