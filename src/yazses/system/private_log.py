"""The daemon's rotating log file, kept owner-only.

``daemon.log`` records what the daemon decided, and at ``log_level = "DEBUG"`` the text the
user dictated. ``logging.handlers.RotatingFileHandler`` opens it with the process umask, which
is ``022`` on almost every Linux and macOS login, so it landed ``0644`` -- readable by every
other local account. This subclass gives it the same shape as the other plaintext stores
(``system/private_files.py``): created ``0600``, a looser pre-existing file tightened, and the
same for the rotated ``daemon.log.1`` .. ``.N`` backups.

Rotation is the part a plain "chmod after open" misses. ``doRollover`` renames the live file
to ``.1`` (a rename keeps the mode) and then *re-opens the base name*, which creates a brand
new file under the umask. Overriding ``_open`` covers that re-open as well as the first one.
Backups that predate this fix are tightened after each rollover.

On Windows (``os.name != "posix"``) every helper it calls is a no-op, so behaviour there is
the stock handler's.
"""
from __future__ import annotations

import os
from logging.handlers import RotatingFileHandler

from yazses.system.private_files import ensure_private_file


class PrivateRotatingFileHandler(RotatingFileHandler):
    """``RotatingFileHandler`` whose live file and backups are never group/other readable."""

    def _open(self):  # type: ignore[no-untyped-def]
        # Create the file 0600 (or tighten it) *before* the stock open, which would
        # otherwise create it under the umask. Never widens; best effort on exotic FS.
        ensure_private_file(self.baseFilename)
        return super()._open()

    def doRollover(self) -> None:  # noqa: N802 -- stdlib name
        super().doRollover()
        for i in range(1, self.backupCount + 1):
            backup = self.rotation_filename(f"{self.baseFilename}.{i}")
            if os.path.exists(backup):
                ensure_private_file(backup)
