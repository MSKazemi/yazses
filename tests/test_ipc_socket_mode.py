"""The IPC socket must be owner-only from the instant it exists, not after a chmod."""

from __future__ import annotations

import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

from yazses.ipc import server as server_mod
from yazses.ipc.server import JsonRpcServer

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix-domain socket modes")


def _short_dir() -> tempfile.TemporaryDirectory[str]:
    # AF_UNIX paths are length-limited; pytest's tmp_path can exceed it.
    return tempfile.TemporaryDirectory(prefix="ys")


def test_socket_is_0600_even_if_chmod_never_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind itself must create the file owner-only (umask), so the later chmod is
    only defence in depth. Neutralise chmod and use a permissive 022 umask."""
    monkeypatch.setattr(server_mod.os, "chmod", lambda *a, **k: None)
    old = os.umask(0o022)
    try:
        with _short_dir() as d:
            path = Path(d) / "s.sock"
            srv = JsonRpcServer.unix(path)
            srv.serve_in_thread()
            try:
                assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
            finally:
                srv.shutdown()
    finally:
        os.umask(old)


def test_umask_is_restored_after_serve_in_thread() -> None:
    old = os.umask(0o022)
    try:
        with _short_dir() as d:
            srv = JsonRpcServer.unix(Path(d) / "s.sock")
            srv.serve_in_thread()
            srv.shutdown()
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(old)


def test_umask_is_restored_when_bind_fails() -> None:
    old = os.umask(0o022)
    try:
        # Parent is a file, so mkdir/bind fails.
        with _short_dir() as d:
            blocker = Path(d) / "f"
            blocker.write_text("x")
            srv = JsonRpcServer.unix(blocker / "s.sock")
            with pytest.raises(OSError):
                srv.serve_in_thread()
        assert os.umask(0o022) == 0o022
    finally:
        os.umask(old)
