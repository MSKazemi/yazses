"""Owner-only writes for plaintext stores that hold what the user said or copied.

Meeting transcripts, the clipboard history and the scratch notes are plain files. Created
with ``Path.write_text`` they take the process umask, which is ``022`` on almost every
Linux and macOS login, so they landed ``0644`` inside a ``0755`` directory: readable by
every other local account. The learning corpus and the voiceprints are encrypted behind a
``0600`` key (``learning/crypto.py``); these stores are not encrypted, so the mode is the
only protection they have.

Helpers here give them the same owner-only shape:

* directories ``0700``, files ``0600``;
* a file is *created* with mode ``0600`` (``os.open``), so there is no window in which it
  exists world-readable, and a looser pre-existing file or directory is tightened on the
  next write, before the new content goes in;
* tightening only ever removes group/other bits, never adds any, and is best effort: a
  filesystem without POSIX modes (FAT/exFAT, some network mounts) refuses ``chmod``, and
  that must cost the protection, never the write.

On a platform whose ``os.name`` is not ``"posix"`` (Windows) every function behaves exactly
as the plain ``Path`` call it replaces. Permissions there are ACLs, which these helpers do
not touch: this module makes no claim of owner-only protection on Windows.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
_GROUP_OTHER = 0o077


def _posix() -> bool:
    return os.name == "posix"


def _tighten(path: Path) -> None:
    """Drop group/other bits from an existing ``path``. Best effort, never raises."""
    if not _posix() or str(path) in ("", "."):  # never chmod the working directory
        return
    try:
        mode = os.stat(path).st_mode
        if mode & _GROUP_OTHER:
            os.chmod(path, mode & ~_GROUP_OTHER & 0o7777)
    except OSError:
        log.debug("could not tighten permissions on %s", path, exc_info=True)


def private_dir(path: str | Path) -> Path:
    """Create ``path`` (and parents) if missing, owner-only (``0700``); tighten if present.

    Only the leaf is made owner-only: parents are created with the default mode, because
    they may be a directory the user chose (a documents folder, a synced folder) and are
    not ours to restrict.
    """
    p = Path(path)
    if not _posix():
        p.mkdir(parents=True, exist_ok=True)
        return p
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.mkdir(mode=PRIVATE_DIR_MODE)
    except FileExistsError:
        if not p.is_dir():
            raise
    _tighten(p)
    return p


def write_private_text(
    path: str | Path, text: str, *, append: bool = False, encoding: str = "utf-8",
) -> None:
    """``Path.write_text`` / append, creating the file ``0600`` and tightening the rest.

    The containing directory is tightened if it exists (it is never created here; call
    :func:`private_dir` first). The file is opened with mode ``0600`` and, when it already
    existed looser, ``fchmod``-ed down *before* any content is written. Raises ``OSError``
    exactly where ``Path.write_text`` would; a failure to change the mode is swallowed.
    """
    p = Path(path)
    if not _posix():
        if append:
            with p.open("a", encoding=encoding) as fh:
                fh.write(text)
        else:
            p.write_text(text, encoding=encoding)
        return
    _tighten(p.parent)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    fd = os.open(p, flags, PRIVATE_FILE_MODE)
    try:
        try:
            mode = os.fstat(fd).st_mode
            if mode & _GROUP_OTHER:
                os.chmod(p, mode & ~_GROUP_OTHER & 0o7777)
        except OSError:
            log.debug("could not tighten permissions on %s", p, exc_info=True)
        fh = os.fdopen(fd, "a" if append else "w", encoding=encoding)
    except BaseException:
        os.close(fd)
        raise
    with fh:
        fh.write(text)
