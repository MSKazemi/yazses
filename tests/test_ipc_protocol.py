"""Tests for ipc.protocol, ipc.server, and ipc.client.

Server↔client integration tests use AF_UNIX sockets in a tmp_path so they're
hermetic and run only on POSIX. Pure protocol tests run everywhere.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from yazses.ipc.client import IpcCallError, IpcUnreachableError, JsonRpcClient
from yazses.ipc.protocol import (
    HANDLER_FAILED,
    METHOD_NOT_FOUND,
    Request,
    Response,
    RpcError,
)
from yazses.ipc.server import JsonRpcServer

# ---- Pure protocol round-trips ------------------------------------------


def test_request_round_trip():
    req = Request(method="status", params={"verbose": True}, id=1)
    parsed = Request.from_json(req.to_json())
    assert parsed.method == "status"
    assert parsed.params == {"verbose": True}
    assert parsed.id == 1


def test_response_round_trip_result():
    resp = Response(id=1, result={"state": "idle"})
    parsed = Response.from_json(resp.to_json())
    assert parsed.id == 1
    assert parsed.result == {"state": "idle"}
    assert parsed.error is None


def test_response_round_trip_error():
    resp = Response(id=2, error=RpcError(code=-32601, message="not found"))
    parsed = Response.from_json(resp.to_json())
    assert parsed.error is not None
    assert parsed.error.code == -32601
    assert parsed.error.message == "not found"


def test_request_rejects_wrong_jsonrpc_version():
    bad = '{"jsonrpc":"1.0","method":"x","params":{},"id":1}'
    with pytest.raises(ValueError):
        Request.from_json(bad)


# ---- Server / client integration ----------------------------------------

pytestmark_unix = pytest.mark.skipif(
    sys.platform not in ("linux", "darwin"),
    reason="Unix-domain sockets are POSIX-only",
)


@pytest.fixture
def server_factory():
    """Yields a function (handlers_dict) -> running JsonRpcServer + path.
    Cleans the server up after the test.

    Uses a short /tmp directory rather than pytest's tmp_path because
    macOS's AF_UNIX sun_path field is only 104 bytes; pytest's tmp_path
    on macOS CI runners (under /Users/runner/work/_temp/...) can exceed
    that limit.
    """
    import tempfile

    started: list[JsonRpcServer] = []
    sock_dir = tempfile.TemporaryDirectory(prefix="nv-", dir="/tmp")

    def _make(handlers):
        socket_path = Path(sock_dir.name) / "t.sock"
        srv = JsonRpcServer.unix(socket_path)
        for name, fn in handlers.items():
            srv.register(name, fn)
        srv.serve_in_thread()
        started.append(srv)
        # Tiny wait so the listening socket is ready when the test connects.
        for _ in range(20):
            if socket_path.exists():
                break
            time.sleep(0.01)
        return srv, socket_path

    yield _make

    for srv in started:
        srv.shutdown()
    sock_dir.cleanup()


@pytestmark_unix
def test_simple_call_round_trip(server_factory):
    _, sock = server_factory({"echo": lambda req: {"text": req.params["text"]}})
    client = JsonRpcClient.unix(sock)
    assert client.is_reachable()
    result = client.call("echo", text="hello")
    assert result == {"text": "hello"}


@pytestmark_unix
def test_unknown_method_raises_method_not_found(server_factory):
    _, sock = server_factory({"ping": lambda req: "pong"})
    client = JsonRpcClient.unix(sock)
    with pytest.raises(IpcCallError) as excinfo:
        client.call("nope")
    assert excinfo.value.error.code == METHOD_NOT_FOUND


@pytestmark_unix
def test_handler_exception_returns_handler_failed(server_factory):
    def boom(_req):
        raise RuntimeError("nope")

    _, sock = server_factory({"boom": boom})
    client = JsonRpcClient.unix(sock)
    with pytest.raises(IpcCallError) as excinfo:
        client.call("boom")
    assert excinfo.value.error.code == HANDLER_FAILED


@pytestmark_unix
def test_unreachable_socket_raises():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="nv-", dir="/tmp") as d:
        client = JsonRpcClient.unix(Path(d) / "missing.sock", timeout_s=0.5)
        assert client.is_reachable() is False
        with pytest.raises(IpcUnreachableError):
            client.call("status")
