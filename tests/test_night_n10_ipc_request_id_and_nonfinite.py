"""A request's `id` and numbers must keep the daemon's reply valid JSON.

On 8a72bbc6 `Request.from_json` accepted any `id` and Python's lenient number
parsing: `"id":1e400` became `inf`, and the server echoed it back as the bare token
`Infinity` -- not JSON (RFC 8259 §6), so a non-Python caller could not parse the
reply. `NaN`/`Infinity` literals in `params` reached handlers too, and an object,
array or boolean `id` was echoed although JSON-RPC 2.0 allows only String, Number
or Null. All of these must now leave `from_json` as ValueError, which both servers
already answer with PARSE_ERROR and a null id.

Synthetic bytes only; real AF_UNIX sockets in a short /tmp directory.
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from yazses.ipc.protocol import PARSE_ERROR, Request
from yazses.ipc.server import JsonRpcServer


def _strict_loads(text: str) -> object:
    """Parse as a non-Python consumer would: NaN/Infinity are errors."""

    def _refuse(token: str) -> object:
        raise ValueError(f"non-JSON constant {token}")

    return json.loads(text, parse_constant=_refuse)


@pytest.mark.parametrize(
    "line",
    [
        '{"jsonrpc":"2.0","method":"ping","id":1e400}',
        '{"jsonrpc":"2.0","method":"ping","id":-1e400}',
        '{"jsonrpc":"2.0","method":"ping","id":NaN}',
        '{"jsonrpc":"2.0","method":"ping","id":Infinity}',
        '{"jsonrpc":"2.0","method":"ping","id":true}',
        '{"jsonrpc":"2.0","method":"ping","id":false}',
        '{"jsonrpc":"2.0","method":"ping","id":{"a":1}}',
        '{"jsonrpc":"2.0","method":"ping","id":[1]}',
    ],
)
def test_an_invalid_id_is_a_value_error(line: str) -> None:
    with pytest.raises(ValueError):
        Request.from_json(line)


@pytest.mark.parametrize(
    "line",
    [
        '{"jsonrpc":"2.0","method":"ping","params":{"x":NaN},"id":1}',
        '{"jsonrpc":"2.0","method":"ping","params":{"x":-Infinity},"id":1}',
        '{"jsonrpc":"2.0","method":"ping","params":{"x":[1e999]},"id":1}',
    ],
)
def test_a_non_finite_number_in_params_is_a_value_error(line: str) -> None:
    with pytest.raises(ValueError):
        Request.from_json(line)


@pytest.mark.parametrize(
    ("raw_id", "expected"),
    [("7", 7), ('"abc"', "abc"), ("null", None), ("1.5", 1.5), ("-3", -3), ("12345678901234567890", 12345678901234567890)],
)
def test_valid_ids_still_parse(raw_id: str, expected: object) -> None:
    req = Request.from_json(f'{{"jsonrpc":"2.0","method":"ping","params":{{"v":2.5}},"id":{raw_id}}}')
    assert req.id == expected
    assert type(req.id) is type(expected)
    assert req.params == {"v": 2.5}


def test_a_missing_id_is_still_none() -> None:
    assert Request.from_json('{"jsonrpc":"2.0","method":"ping"}').id is None


# ---- over a real socket ---------------------------------------------------

_unix_only = pytest.mark.skipif(
    sys.platform not in ("linux", "darwin"),
    reason="Unix-domain sockets are POSIX-only",
)


@pytest.fixture
def echo_server() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="nv-", dir="/tmp") as d:
        path = Path(d) / "t.sock"
        srv = JsonRpcServer.unix(path)
        srv.register("ping", lambda req: "pong")
        srv.register("echo", lambda req: req.params)
        srv.serve_in_thread()
        for _ in range(100):
            if path.exists():
                break
            time.sleep(0.01)
        try:
            yield path
        finally:
            srv.shutdown()


def _exchange(path: Path, payload: bytes) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(5.0)
        s.connect(str(path))
        s.sendall(payload)
        buf = bytearray()
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
    return bytes(buf).decode("utf-8").rstrip("\n")


@_unix_only
@pytest.mark.parametrize(
    "payload",
    [
        b'{"jsonrpc":"2.0","method":"ping","id":1e400}\n',
        b'{"jsonrpc":"2.0","method":"ping","id":NaN}\n',
        b'{"jsonrpc":"2.0","method":"echo","params":{"x":Infinity},"id":1}\n',
    ],
)
def test_the_reply_is_strict_json_with_a_parse_error(echo_server: Path, payload: bytes) -> None:
    reply = _strict_loads(_exchange(echo_server, payload))
    assert isinstance(reply, dict)
    assert reply["id"] is None
    assert reply["error"]["code"] == PARSE_ERROR


@_unix_only
@pytest.mark.parametrize("bad_id", [b"true", b'{"a":1}', b"[1]"])
def test_a_non_scalar_id_is_not_echoed(echo_server: Path, bad_id: bytes) -> None:
    reply = _strict_loads(_exchange(echo_server, b'{"jsonrpc":"2.0","method":"ping","id":' + bad_id + b"}\n"))
    assert isinstance(reply, dict)
    assert reply["id"] is None
    assert reply["error"]["code"] == PARSE_ERROR


@_unix_only
def test_a_valid_request_is_unchanged(echo_server: Path) -> None:
    reply = _strict_loads(_exchange(echo_server, b'{"jsonrpc":"2.0","method":"ping","id":"q-1"}\n'))
    assert reply == {"jsonrpc": "2.0", "id": "q-1", "result": "pong"}
