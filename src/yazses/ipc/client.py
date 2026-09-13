"""JSON-RPC client for the daemon's Unix-domain socket."""

from __future__ import annotations

import itertools
import socket
from pathlib import Path
from typing import Any

from yazses.ipc.protocol import NOT_REACHABLE, Request, Response, RpcError


class IpcCallError(RuntimeError):
    """Raised when an RPC call returns a JSON-RPC error."""

    def __init__(self, error: RpcError) -> None:
        super().__init__(f"[{error.code}] {error.message}")
        self.error = error


class IpcUnreachableError(IpcCallError):
    """Raised when the daemon socket isn't listening.

    ``socket_path`` is typed ``Path | str`` because it is only ever formatted
    into the message, and the Windows transport's identifier is a named pipe
    (``\\\\.\\pipe\\yazses-…``) rather than a filesystem path.
    """

    def __init__(self, socket_path: Path | str, cause: Exception | None = None) -> None:
        super().__init__(RpcError(code=NOT_REACHABLE, message=f"Daemon not reachable at {socket_path}"))
        self.socket_path = socket_path
        self.cause = cause


class JsonRpcClient:
    """Synchronous JSON-RPC client.

    Each call opens a fresh connection, sends one request line, reads one
    response line, closes. Cheap; latency is dominated by daemon handler work.
    """

    _DEFAULT_TIMEOUT_S = 2.0

    def __init__(self, socket_path: Path, timeout_s: float = _DEFAULT_TIMEOUT_S) -> None:
        self._socket_path = socket_path
        self._timeout_s = timeout_s
        self._id_seq = itertools.count(1)

    @classmethod
    def unix(cls, socket_path: Path, timeout_s: float = _DEFAULT_TIMEOUT_S) -> JsonRpcClient:
        return cls(socket_path, timeout_s=timeout_s)

    def is_reachable(self) -> bool:
        try:
            with self._connect():
                return True
        except OSError:
            return False

    def call(self, method: str, **params: Any) -> Any:
        request = Request(method=method, params=params, id=next(self._id_seq))
        try:
            with self._connect() as conn:
                conn.sendall(request.to_json().encode("utf-8") + b"\n")
                line = self._recv_line(conn)
        except OSError as exc:
            raise IpcUnreachableError(self._socket_path, cause=exc) from exc
        response = Response.from_json(line.decode("utf-8"))
        if response.error is not None:
            raise IpcCallError(response.error)
        return response.result

    # ------------------------------------------------------------------

    def _connect(self) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._timeout_s)
        sock.connect(str(self._socket_path))
        return sock

    @staticmethod
    def _recv_line(conn: socket.socket) -> bytes:
        buf = bytearray()
        while b"\n" not in buf:
            chunk = conn.recv(4096)
            if not chunk:
                break
            buf.extend(chunk)
        line, _, _ = bytes(buf).partition(b"\n")
        return line
