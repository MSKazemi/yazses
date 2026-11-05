"""Malformed input and unserialisable replies must not kill a connection thread.

Real AF_UNIX sockets in a short /tmp directory; synthetic bytes only. Each case
asserts (a) the caller gets a well-formed JSON-RPC error reply, (b) no exception
escaped the per-connection thread (``threading.excepthook`` never fired), and
(c) the server still answers the next connection.

The Windows named-pipe mirror (``platform/windows/ipc.py``) shares the parse and
serialise logic but cannot be run without pywin32: it is covered here only by a
source-level guard, and its runtime behaviour is UNVERIFIED.
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from yazses.ipc.client import JsonRpcClient
from yazses.ipc.protocol import (
    HANDLER_FAILED,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    Request,
    Response,
)
from yazses.ipc.server import JsonRpcServer

pytestmark = pytest.mark.skipif(
    sys.platform not in ("linux", "darwin"),
    reason="Unix-domain sockets are POSIX-only",
)


@pytest.fixture
def server() -> Iterator[tuple[JsonRpcServer, Path]]:
    # Short /tmp path: macOS AF_UNIX sun_path is only 104 bytes.
    with tempfile.TemporaryDirectory(prefix="nv-", dir="/tmp") as d:
        path = Path(d) / "t.sock"
        srv = JsonRpcServer.unix(path)
        srv.register("ping", lambda req: "pong")
        srv.register("a_set", lambda req: {1, 2, 3})
        srv.register("some_bytes", lambda req: b"\xff\x00")
        srv.register("nested_set", lambda req: {"k": [{"x": {1}}]})
        srv.serve_in_thread()
        for _ in range(100):
            if path.exists():
                break
            time.sleep(0.01)
        try:
            yield srv, path
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


def _raw_exchange(path: Path, payload: bytes) -> bytes:
    """Send raw bytes (caller supplies the newline), read until EOF."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(5.0)
        s.connect(str(path))
        s.sendall(payload)
        out = bytearray()
        while True:
            try:
                chunk = s.recv(4096)
            except ConnectionResetError:
                break
            if not chunk:
                break
            out.extend(chunk)
        return bytes(out)


def _error_code(reply: bytes) -> int:
    assert reply.endswith(b"\n"), f"no reply line: {reply!r}"
    body = json.loads(reply)
    assert "error" in body, body
    return int(body["error"]["code"])


def _assert_server_alive(path: Path) -> None:
    assert JsonRpcClient.unix(path).call("ping") == "pong"


def _settle() -> None:
    # The per-connection thread may finish just after the client sees EOF.
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if not any(t.name == "ipc-conn" for t in threading.enumerate()):
            return
        time.sleep(0.01)


# ---- the two defects ------------------------------------------------------


def test_deeply_nested_array_gets_parse_error(server, thread_errors):
    _, path = server
    depth = 100_000
    payload = b"[" * depth + b"]" * depth + b"\n"
    reply = _raw_exchange(path, payload)
    _settle()
    assert _error_code(reply) == PARSE_ERROR
    assert thread_errors == []
    _assert_server_alive(path)


def test_deeply_nested_object_gets_parse_error(server, thread_errors):
    _, path = server
    depth = 100_000
    payload = b'{"a":' * depth + b"1" + b"}" * depth + b"\n"
    reply = _raw_exchange(path, payload)
    _settle()
    assert _error_code(reply) == PARSE_ERROR
    assert thread_errors == []
    _assert_server_alive(path)


@pytest.mark.parametrize("method", ["a_set", "some_bytes", "nested_set"])
def test_unserialisable_result_gets_handler_failed(server, thread_errors, method):
    _, path = server
    req = Request(method=method, id=7).to_json().encode() + b"\n"
    reply = _raw_exchange(path, req)
    _settle()
    assert _error_code(reply) == HANDLER_FAILED
    body = json.loads(reply)
    assert body["id"] == 7
    # Fixed message: no echo of the offending content.
    assert "{1, 2, 3}" not in body["error"]["message"]
    assert "xff" not in body["error"]["message"]
    assert thread_errors == []
    _assert_server_alive(path)


def test_response_to_json_still_raises_for_unserialisable_result():
    # The fallback lives in the transports; the framing layer is unchanged.
    with pytest.raises(TypeError):
        Response(id=1, result={1}).to_json()


# ---- unchanged behaviour --------------------------------------------------


def test_oversize_frame_still_invalid_request(server, thread_errors):
    _, path = server
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(5.0)
        s.connect(str(path))
        try:
            s.sendall(b"x" * 1_100_000)
        except (BrokenPipeError, ConnectionResetError):
            pass
        out = bytearray()
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                out.extend(chunk)
        except ConnectionResetError:
            pass
    _settle()
    if out:  # the reply may be lost to a reset once the server closes
        assert _error_code(bytes(out)) == INVALID_REQUEST
    assert thread_errors == []
    _assert_server_alive(path)


def test_non_utf8_still_parse_error(server, thread_errors):
    _, path = server
    reply = _raw_exchange(path, b'{"jsonrpc":"2.0","method":"\xff\xfe"}\n')
    _settle()
    assert _error_code(reply) == PARSE_ERROR
    assert thread_errors == []
    _assert_server_alive(path)


@pytest.mark.parametrize(
    "payload", [b"not json\n", b"[1,2]\n", b"null\n", b'{"jsonrpc":"1.0"}\n']
)
def test_other_malformed_json_still_parse_error(server, thread_errors, payload):
    _, path = server
    reply = _raw_exchange(path, payload)
    _settle()
    assert _error_code(reply) == PARSE_ERROR
    assert thread_errors == []


def test_unknown_method_still_method_not_found(server, thread_errors):
    _, path = server
    reply = _raw_exchange(path, Request(method="nope", id=3).to_json().encode() + b"\n")
    assert _error_code(reply) == METHOD_NOT_FOUND
    assert json.loads(reply)["id"] == 3
    assert thread_errors == []


# ---- Windows mirror (UNVERIFIED at runtime) ------------------------------


def test_windows_mirror_handles_the_same_failures():
    """Source-level guard: pywin32 is unavailable here, so the pipe server
    cannot be exercised. This only asserts the mirror carries the same catches."""
    src = (Path(__file__).resolve().parents[1] / "src/yazses/platform/windows/ipc.py").read_text(
        encoding="utf-8"
    )
    assert "RecursionError" in src
    assert "HANDLER_FAILED" in src and "TypeError" in src
