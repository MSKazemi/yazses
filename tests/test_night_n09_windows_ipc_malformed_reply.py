"""The Windows named-pipe client turns a malformed daemon reply into IpcCallError.

The Unix client (``yazses.ipc.client.JsonRpcClient.call``) wraps
``Response.from_json`` so that a daemon which closes without answering, or
answers with something that is not a JSON-RPC response, surfaces as one typed
``IpcCallError`` with code ``INTERNAL_ERROR`` (-32603). The Windows transport
(``yazses.platform.windows.ipc.NamedPipeIpcClient.call``) called it unwrapped,
so the same daemon fault leaked ``ValueError`` / ``JSONDecodeError`` /
``UnicodeDecodeError`` past every ``except IpcCallError`` in the CLI, tray and
MCP server, and tracebacked on Windows only.

pywin32 is faked through ``sys.modules`` so this runs on any OS: no Windows,
no named pipe, no daemon.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from yazses.ipc.client import IpcCallError, IpcUnreachableError
from yazses.ipc.protocol import INTERNAL_ERROR
from yazses.platform.windows import ipc as win_ipc


class _FakePywinError(Exception):
    def __init__(self, winerror: int = 2) -> None:
        super().__init__(winerror)
        self.winerror = winerror


def _install_fake_pywin32(monkeypatch: pytest.MonkeyPatch, reply: bytes) -> dict[str, list]:
    """Fake win32pipe/win32file/pywintypes; the pipe answers ``reply`` then EOF."""
    record: dict[str, list] = {"written": [], "closed": []}
    chunks = [reply[i : i + 7] for i in range(0, len(reply), 7)] if reply else []

    pywintypes = types.ModuleType("pywintypes")
    pywintypes.error = _FakePywinError  # type: ignore[attr-defined]

    win32pipe = types.ModuleType("win32pipe")
    win32pipe.WaitNamedPipe = lambda name, timeout_ms: None  # type: ignore[attr-defined]

    win32file = types.ModuleType("win32file")
    win32file.GENERIC_READ = 0x80000000  # type: ignore[attr-defined]
    win32file.GENERIC_WRITE = 0x40000000  # type: ignore[attr-defined]
    win32file.OPEN_EXISTING = 3  # type: ignore[attr-defined]
    win32file.CreateFile = lambda *args: "fake-handle"  # type: ignore[attr-defined]

    def _write(handle, data):  # noqa: ANN001, ANN202
        record["written"].append(bytes(data))
        return 0, len(data)

    def _read(handle, size):  # noqa: ANN001, ANN202
        return 0, (chunks.pop(0) if chunks else b"")

    win32file.WriteFile = _write  # type: ignore[attr-defined]
    win32file.ReadFile = _read  # type: ignore[attr-defined]
    win32file.CloseHandle = lambda handle: record["closed"].append(handle)  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "pywintypes", pywintypes)
    monkeypatch.setitem(sys.modules, "win32pipe", win32pipe)
    monkeypatch.setitem(sys.modules, "win32file", win32file)
    return record


def _client() -> win_ipc.NamedPipeIpcClient:
    # A generous wait: the exchange runs on a worker thread and the fake answers
    # at once, so this never elapses; it only keeps a loaded CI box from timing out.
    return win_ipc.NamedPipeIpcClient(Path("daemon.sock"), timeout_s=10.0)


MALFORMED_REPLIES = {
    # ReadFile returned no bytes before any newline. (A real server hang-up
    # usually makes ReadFile raise ERROR_BROKEN_PIPE instead, which the client
    # reports as IpcUnreachableError before parsing; this covers the case where
    # the read ends cleanly with nothing in the buffer.)
    "empty": b"",
    "not-json": b"this is not json\n",
    "truncated-json": b'{"jsonrpc": "2.0", "id": 1, "res\n',
    "json-array": b"[1, 2, 3]\n",
    "json-string": b'"hello"\n',
    "wrong-jsonrpc-version": b'{"jsonrpc": "1.0", "id": 1, "result": 1}\n',
    "invalid-utf8": b"\xff\xfe\xfa\n",
    "error-not-object": b'{"jsonrpc": "2.0", "id": 1, "error": "boom"}\n',
    "error-code-not-int": b'{"jsonrpc": "2.0", "id": 1, "error": {"code": "x", "message": "m"}}\n',
}


@pytest.mark.parametrize("reply", list(MALFORMED_REPLIES.values()), ids=list(MALFORMED_REPLIES))
def test_malformed_reply_is_one_typed_internal_error(monkeypatch, reply):
    _install_fake_pywin32(monkeypatch, reply)
    with pytest.raises(IpcCallError) as info:
        _client().call("status")
    err = info.value
    assert err.error.code == INTERNAL_ERROR
    assert "status" in err.error.message
    # The daemon answered (or hung up) — it is not "unreachable", so `start`'s
    # readiness poll and `status` must not report it as not running.
    assert not isinstance(err, IpcUnreachableError)
    # The parse failure is kept as the cause for the log, not thrown away.
    assert isinstance(err.__cause__, ValueError)


def test_well_formed_result_still_returns(monkeypatch):
    record = _install_fake_pywin32(monkeypatch, b'{"jsonrpc": "2.0", "id": 1, "result": {"state": "idle"}}\n')
    assert _client().call("status") == {"state": "idle"}
    assert record["written"] and record["written"][0].endswith(b"\n")
    assert record["closed"] == ["fake-handle"]


def test_well_formed_error_reply_keeps_its_own_code(monkeypatch):
    _install_fake_pywin32(
        monkeypatch,
        b'{"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Unknown method"}}\n',
    )
    with pytest.raises(IpcCallError) as info:
        _client().call("nope")
    assert info.value.error.code == -32601
    assert info.value.__cause__ is None


def test_windows_and_unix_clients_agree_on_the_message(monkeypatch):
    """Same daemon fault, same words on both transports."""
    _install_fake_pywin32(monkeypatch, b"garbage\n")
    with pytest.raises(IpcCallError) as info:
        _client().call("toggle")
    assert info.value.error.message == "Daemon sent a malformed reply to 'toggle'"
