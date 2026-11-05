"""`daemon.log` is owner-only on POSIX, including after rotation.

At `log_level = "DEBUG"` the daemon writes the dictated text into `daemon.log`. The file was
opened by a stock `RotatingFileHandler`, so it took the process umask (`022` on nearly every
Linux and macOS login): `0644` inside a `0755` directory, readable by every other local
account. The other plaintext stores were fixed by `system/private_files.py`; the log was
missed because it is not written through those helpers.

Rotation is the case a one-off chmod would miss: `doRollover` renames the live file to `.1`
and then re-opens the base name, creating a new file under the umask. The handler must make
that one private as well. Windows uses ACLs, which none of this touches.
"""
from __future__ import annotations

import logging
import os
import stat
import sys
import types
from pathlib import Path

import pytest

from yazses.core.daemon import Daemon

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or os.name != "posix",
    reason="POSIX permission bits; Windows uses ACLs, which this does not set",
)


def _mode(p: Path) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


@pytest.fixture
def umask022():
    old = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(old)


def _configure(log_dir: Path) -> logging.Handler:
    """Run the real `Daemon._configure_logging` against `log_dir`; return its file handler."""
    fake = types.SimpleNamespace(
        _config=types.SimpleNamespace(general=types.SimpleNamespace(log_level="INFO")),
        _platform=types.SimpleNamespace(paths=types.SimpleNamespace(log_dir=log_dir)),
    )
    root = logging.getLogger()
    before = set(map(id, root.handlers))
    Daemon._configure_logging(fake)  # type: ignore[arg-type]
    added = [h for h in root.handlers if id(h) not in before]
    assert len(added) == 1, added
    return added[0]


@pytest.fixture
def handler(tmp_path, umask022):
    log_dir = tmp_path / "state" / "log"
    h = _configure(log_dir)
    try:
        yield h
    finally:
        logging.getLogger().removeHandler(h)
        h.close()


def test_a_new_daemon_log_is_owner_only_under_umask_022(handler, tmp_path):
    log_dir = tmp_path / "state" / "log"
    assert _mode(log_dir / "daemon.log") == 0o600
    assert _mode(log_dir) == 0o700


def test_a_looser_existing_log_and_directory_are_tightened(tmp_path, umask022):
    log_dir = tmp_path / "state" / "log"
    log_dir.mkdir(parents=True)
    log_dir.chmod(0o755)
    target = log_dir / "daemon.log"
    target.write_text("old line\n", encoding="utf-8")
    target.chmod(0o644)
    h = _configure(log_dir)
    try:
        assert _mode(target) == 0o600
        assert _mode(log_dir) == 0o700
        assert "old line" in target.read_text(encoding="utf-8")  # appended to, not truncated
    finally:
        logging.getLogger().removeHandler(h)
        h.close()


def test_a_tighter_existing_log_is_not_widened(tmp_path, umask022):
    log_dir = tmp_path / "log"
    log_dir.mkdir(mode=0o700)
    target = log_dir / "daemon.log"
    target.write_text("", encoding="utf-8")
    target.chmod(0o400)
    # A read-only log cannot be opened for append, so `_configure_logging` logs a warning
    # and installs no handler (it must not chmod the file looser to get in). Either way
    # the mode must not grow.
    root = logging.getLogger()
    before = set(map(id, root.handlers))
    fake = types.SimpleNamespace(
        _config=types.SimpleNamespace(general=types.SimpleNamespace(log_level="INFO")),
        _platform=types.SimpleNamespace(paths=types.SimpleNamespace(log_dir=log_dir)),
    )
    Daemon._configure_logging(fake)  # type: ignore[arg-type]
    for h in [h for h in root.handlers if id(h) not in before]:
        root.removeHandler(h)
        h.close()
    assert _mode(target) == 0o400


def test_the_log_stays_owner_only_across_rotation(handler, tmp_path):
    log_dir = tmp_path / "state" / "log"
    for old in ("daemon.log.1", "daemon.log.2"):  # backups from before the fix: world-readable
        (log_dir / old).write_text("legacy\n", encoding="utf-8")
        (log_dir / old).chmod(0o644)
    handler.doRollover()  # type: ignore[attr-defined]
    handler.doRollover()  # type: ignore[attr-defined]
    names = sorted(p.name for p in log_dir.iterdir())
    assert "daemon.log" in names and "daemon.log.1" in names and "daemon.log.2" in names, names
    for name in names:
        assert _mode(log_dir / name) == 0o600, (name, oct(_mode(log_dir / name)))
