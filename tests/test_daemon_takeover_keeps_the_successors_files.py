"""A daemon that is replaced must not delete its successor's socket or pid file.

`Daemon._shutdown()` used to release the instance lock before it unlinked the IPC socket
and cleared the pid file. A successor polling that lock (`_replace_older_daemon`, every
0.25 s) could take it, bind its own socket and write its own pid file inside that window
-- and the old daemon then removed both. The successor kept running, unreachable.
"""

from __future__ import annotations

import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.ipc.server import JsonRpcServer
from yazses.platform import get_platform
from yazses.system.single_instance import SingleInstanceLock

# Unix-domain sockets and an fcntl instance lock: every POSIX leg (Linux, macOS,
# FreeBSD). Windows keeps its IPC on a named pipe, which this file does not exercise.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or not hasattr(socket, "AF_UNIX"),
    reason="Unix-domain sockets are POSIX-only",
)

#: Not our pid and never a real one: a successor's pid file only needs different content.
_SUCCESSOR_PID = "999999"


@pytest.fixture
def short_dir():
    # AF_UNIX paths are capped near 104 bytes; pytest's tmp_path can exceed that.
    d = Path(tempfile.mkdtemp(prefix="ys-"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _written_pid_file(plat) -> Path:
    """Where this platform's lifecycle backend actually put the pid file.

    Linux keeps it under ``data_dir``; macOS and Windows at ``paths.pid_file``. Asking the
    disk after ``write_pid()`` keeps the tests right on every OS, and asserting that
    exactly one candidate exists means a test cannot pass on a path nothing ever wrote.
    """
    candidates = list(dict.fromkeys((plat.paths.data_dir / "daemon.pid", plat.paths.pid_file)))
    found = [c for c in candidates if c.exists()]
    assert len(found) == 1, f"expected exactly one pid file, found {found}"
    return found[0]


def _old_daemon(sock_path):
    """A running daemon: lock held, socket bound, pid file written (all asserted)."""
    plat = get_platform()
    plat.paths.data_dir.mkdir(parents=True, exist_ok=True)
    old = Daemon(config=Config(), platform=plat)
    assert old._acquire_instance_lock()
    old._ipc_server = JsonRpcServer.unix(sock_path)
    old._ipc_server.serve_in_thread()
    plat.lifecycle.write_pid()
    pid_file = _written_pid_file(plat)
    assert sock_path.exists(), "precondition: the old daemon's socket must exist"
    return old, plat, pid_file


def test_a_successor_that_takes_over_mid_teardown_keeps_its_socket_and_pid(
    sandbox_paths, short_dir
):
    sock = short_dir / "d.sock"
    old, plat, pid_file = _old_daemon(sock)
    successor: dict[str, object] = {}

    real_release = old._instance_lock.release

    def release_then_the_successor_starts() -> None:
        real_release()  # the lock is free ...
        lock = SingleInstanceLock(plat.paths.data_dir / "daemon.lock")
        assert lock.acquire()  # ... so the successor's poll takes it ...
        srv = JsonRpcServer.unix(sock)  # ... binds ...
        srv.serve_in_thread()
        pid_file.write_text(_SUCCESSOR_PID, encoding="utf-8")  # ... and records itself
        successor.update(lock=lock, srv=srv)

    old._instance_lock.release = release_then_the_successor_starts  # type: ignore[method-assign]
    old._shutdown()
    try:
        assert successor, "the old daemon never released the instance lock"
        assert sock.exists(), "the successor's IPC socket was unlinked by the old daemon"
        assert pid_file.read_text(encoding="utf-8") == _SUCCESSOR_PID, (
            "the successor's pid file was deleted by the old daemon"
        )
    finally:
        if successor:
            successor["srv"].shutdown()  # type: ignore[attr-defined]
            successor["lock"].release()  # type: ignore[attr-defined]


def test_the_instance_lock_is_released_after_the_socket_and_pid_file_are_gone(
    sandbox_paths, short_dir
):
    sock = short_dir / "d.sock"
    old, plat, pid_file = _old_daemon(sock)
    seen: dict[str, bool] = {}
    real_release = old._instance_lock.release

    def spy() -> None:
        seen["socket_gone"] = not sock.exists()
        seen["pid_gone"] = not pid_file.exists()
        real_release()

    old._instance_lock.release = spy  # type: ignore[method-assign]
    old._shutdown()
    assert seen == {"socket_gone": True, "pid_gone": True}


def test_shutdown_leaves_a_pid_file_that_names_another_process(sandbox_paths, short_dir):
    old, plat, pid_file = _old_daemon(short_dir / "d.sock")
    pid_file.write_text(_SUCCESSOR_PID, encoding="utf-8")
    old._shutdown()
    assert pid_file.read_text(encoding="utf-8") == _SUCCESSOR_PID


def test_control_shutdown_still_removes_its_own_pid_file(sandbox_paths, short_dir):
    old, plat, pid_file = _old_daemon(short_dir / "d.sock")
    assert pid_file.read_text(encoding="utf-8").strip() == str(os.getpid())
    old._shutdown()
    assert not pid_file.exists()


def test_a_server_does_not_unlink_a_socket_another_server_bound_since(short_dir):
    sock = short_dir / "s.sock"
    first = JsonRpcServer.unix(sock)
    first.serve_in_thread()
    # The takeover: the successor clears the path and binds its own. The first file is
    # renamed away rather than unlinked, so its inode stays allocated and the second
    # socket cannot be handed the same number (a freed inode may be reused at once).
    second = JsonRpcServer.unix(sock)
    try:
        os.rename(sock, short_dir / "moved.sock")
        second.serve_in_thread()
        first.shutdown()
        assert sock.exists(), "the first server unlinked the second server's socket"
    finally:
        second.shutdown()
    assert not sock.exists(), "a server must still remove its own socket"
