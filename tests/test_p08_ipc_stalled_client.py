"""A client that stalls mid-request must not kill the IPC connection thread.

The server reads a request line with a per-connection socket timeout. A client
that sends part of a line and then goes quiet (a hung CLI, a script that forgot
the newline, a process stopped under a debugger) made ``recv`` raise
``TimeoutError``. Nothing in ``_handle_connection`` caught it, so the exception
escaped the ``ipc-conn`` thread and ``threading.excepthook`` printed a full
traceback into the daemon log -- which reads like a daemon crash to anyone later
diagnosing a real fault. The same applied to a peer that reset the connection
before finishing its line.

Real AF_UNIX sockets in a short /tmp directory; synthetic bytes only. Linux and
macOS only (the Windows named-pipe server is a separate implementation).
"""

from __future__ import annotations

import socket
import struct
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from yazses.ipc.client import JsonRpcClient
from yazses.ipc.server import JsonRpcServer

pytestmark = pytest.mark.skipif(
    sys.platform not in ("linux", "darwin"),
    reason="Unix-domain sockets are POSIX-only",
)


@pytest.fixture
def server() -> Iterator[Path]:
    # Short /tmp path: macOS AF_UNIX sun_path is only 104 bytes.
    with tempfile.TemporaryDirectory(prefix="nv-", dir="/tmp") as d:
        path = Path(d) / "t.sock"
        srv = JsonRpcServer.unix(path)
        srv.register("ping", lambda req: "pong")
        srv.serve_in_thread()
        for _ in range(100):
            if path.exists():
                break
            time.sleep(0.01)
        try:
            yield path
        finally:
            srv.shutdown()


@pytest.fixture
def thread_errors() -> Iterator[list[threading.ExceptHookArgs]]:
    seen: list[threading.ExceptHookArgs] = []
    old = threading.excepthook
    threading.excepthook = seen.append
    try:
        yield seen
    finally:
        threading.excepthook = old


def _wait_for_conn_threads(deadline_s: float) -> None:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        if not any(t.name == "ipc-conn" for t in threading.enumerate()):
            return
        time.sleep(0.01)


def test_partial_line_then_silence_does_not_escape_the_thread(server, thread_errors):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(10.0)
        s.connect(str(server))
        s.sendall(b'{"jsonrpc":"2.0","method":"pi')  # no newline, then nothing
        # The server gives up on its own read timeout and hangs up.
        assert s.recv(4096) == b""
    _wait_for_conn_threads(2.0)
    assert [a.exc_type for a in thread_errors] == []
    assert JsonRpcClient.unix(server).call("ping") == "pong"


def test_connect_then_silence_does_not_escape_the_thread(server, thread_errors):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(10.0)
        s.connect(str(server))
        assert s.recv(4096) == b""
    _wait_for_conn_threads(2.0)
    assert [a.exc_type for a in thread_errors] == []
    assert JsonRpcClient.unix(server).call("ping") == "pong"


@pytest.mark.skipif(sys.platform != "linux", reason="SO_LINGER reset semantics verified on Linux only")
def test_peer_reset_mid_line_does_not_escape_the_thread(server, thread_errors):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(str(server))
    s.sendall(b'{"jsonrpc":"2.0"')
    # Linger 0 makes close() a reset where the platform supports it for AF_UNIX;
    # where it is a plain close the server just sees EOF. Either must be quiet.
    s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    s.close()
    _wait_for_conn_threads(3.0)
    assert [a.exc_type for a in thread_errors] == []
    assert JsonRpcClient.unix(server).call("ping") == "pong"
