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

Symbolic links are never followed to change a mode:

* a *file* is opened with ``O_NOFOLLOW`` and its mode is changed with ``fchmod`` on the
  descriptor that was opened, so a symlink planted at ``d/live.jsonl`` pointing at a
  ``0644`` file elsewhere is neither written through nor chmod-ed. The write functions
  raise ``OSError`` (``ELOOP``) for a symlinked file, because an owner-only store that
  quietly writes somewhere else is not owner-only; :func:`ensure_private_file`, being
  best effort, logs and leaves it alone;
* a *directory* that is a symlink is left exactly as it is: it is used (users do point a
  data directory at another disk), but the target's mode is not changed through it, and
  the same holds for the parent directory the write functions tighten. Where the link
  leads is the user's decision, not something this module may "fix" by chmod.

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


# Where the platform lacks O_NOFOLLOW the flag is 0 and `_is_symlink` is the only guard.
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)


def _is_symlink(path: Path) -> bool:
    try:
        return os.path.islink(path)
    except OSError:
        return False


def _fd_tighten(fd: int, path: Path) -> None:
    """Drop group/other bits from the file ``fd`` is open on. Best effort, never raises."""
    try:
        mode = os.fstat(fd).st_mode
        if mode & _GROUP_OTHER:
            os.fchmod(fd, mode & ~_GROUP_OTHER & 0o7777)
    except OSError:
        log.debug("could not tighten permissions on %s", path, exc_info=True)


def _tighten(path: Path) -> None:
    """Drop group/other bits from an existing ``path``. Best effort, never raises.

    A symlink is left alone (its target is not ours to change). The mode is changed on a
    descriptor opened with ``O_NOFOLLOW``, so a link swapped in after the check is
    refused by the kernel rather than followed. Only when no descriptor can be had (a
    directory the owner cannot read) does it fall back to ``chmod`` by path, and only
    after ``path`` was just seen not to be a link.
    """
    if not _posix() or str(path) in ("", "."):  # never chmod the working directory
        return
    if _is_symlink(path):
        log.debug("not changing permissions through the symlink %s", path)
        return
    nonblock = getattr(os, "O_NONBLOCK", 0)
    for extra in (_O_DIRECTORY, 0):
        try:
            fd = os.open(path, os.O_RDONLY | _O_NOFOLLOW | nonblock | extra)
        except OSError:
            continue
        try:
            _fd_tighten(fd, path)
        finally:
            os.close(fd)
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
    not ours to restrict. If ``path`` is a symlink to a directory it is returned as it is
    and the target's mode is left alone (see the module docstring).
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
    where ``Path.write_text`` would, and with ``ELOOP`` when ``path`` itself is a symlink;
    a failure to change the mode is swallowed.
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
    flags = os.O_WRONLY | os.O_CREAT | _O_NOFOLLOW | (os.O_APPEND if append else os.O_TRUNC)
    fd = os.open(p, flags, PRIVATE_FILE_MODE)
    try:
        _fd_tighten(fd, p)
        fh = os.fdopen(fd, "a" if append else "w", encoding=encoding)
    except BaseException:
        os.close(fd)
        raise
    with fh:
        fh.write(text)


def write_private_bytes(path: str | Path, data: bytes) -> None:
    """``Path.write_bytes`` that creates the file ``0600`` and tightens a looser one.

    Same contract as :func:`write_private_text`, for binary content (ciphertext, SQLite
    side files). The bytes written are exactly ``data``; only the mode differs.
    """
    p = Path(path)
    if not _posix():
        p.write_bytes(data)
        return
    _tighten(p.parent)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_NOFOLLOW, PRIVATE_FILE_MODE)
    try:
        _fd_tighten(fd, p)
        fh = os.fdopen(fd, "wb")
    except BaseException:
        os.close(fd)
        raise
    with fh:
        fh.write(data)


def ensure_private_file(path: str | Path) -> None:
    """Make sure ``path`` exists and is owner-only, without changing its content.

    A missing file is created empty with mode ``0600`` (an empty file is a valid new
    SQLite database, so ``sqlite3.connect`` can then open it with no world-readable
    moment); an existing looser file is tightened. Best effort on the tightening.
    """
    p = Path(path)
    if not _posix():
        return
    try:
        fd = os.open(
            p, os.O_WRONLY | os.O_CREAT | _O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0),
            PRIVATE_FILE_MODE,
        )
    except OSError:
        # Includes ELOOP for a symlink: the link's target is not ours to chmod.
        log.debug("could not pre-create %s", p, exc_info=True)
        return
    try:
        _fd_tighten(fd, p)
    finally:
        os.close(fd)
