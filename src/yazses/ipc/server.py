"""JSON-RPC server bound to a Unix-domain socket.

Each connection is short-lived: client connects, sends one request line,
reads one response line, disconnects. The server runs on a background thread
inside the daemon. macOS reuses this transport; Windows does not -- it has its
own `NamedPipeIpcServer`, which mirrors the request handling here rather than
subclassing it, so a change to either belongs in both. The parsing itself is
shared: both call `Request.from_json` and catch the same exceptions.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from collections.abc import Callable
from pathlib import Path

from yazses.ipc.protocol import (
    HANDLER_FAILED,
    INTERNAL_ERROR,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    Request,
    Response,
    RpcError,
)

log = logging.getLogger(__name__)

Handler = Callable[[Request], object]


class JsonRpcServer:
    """Threaded JSON-RPC server.

    Construct via :meth:`unix` for a Unix-domain socket. Register handlers
    with :meth:`register`, then call :meth:`serve_in_thread` to run.
    """

    _BACKLOG = 8
    _ACCEPT_TIMEOUT_S = 0.5

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path
        self._sock: socket.socket | None = None
        self._handlers: dict[str, Handler] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def unix(cls, socket_path: Path) -> JsonRpcServer:
        return cls(socket_path)

    def register(self, method: str, handler: Handler) -> None:
        self._handlers[method] = handler

    def serve_in_thread(self) -> None:
        self._socket_path.parent.mkdir(parents=True, exist_ok=True)
        # Stale socket from a crashed daemon would block bind; remove it.
        if self._socket_path.exists():
            try:
                self._socket_path.unlink()
            except OSError as exc:
                log.warning("Could not remove stale socket %s: %s", self._socket_path, exc)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(self._socket_path))
        try:
            os.chmod(self._socket_path, 0o600)
        except OSError:
            pass
        sock.listen(self._BACKLOG)
        sock.settimeout(self._ACCEPT_TIMEOUT_S)
        self._sock = sock
        self._thread = threading.Thread(target=self._accept_loop, name="ipc-server", daemon=True)
        self._thread.start()
        log.info("IPC server listening on %s", self._socket_path)

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        try:
            self._socket_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Could not remove socket %s: %s", self._socket_path, exc)

    # ------------------------------------------------------------------

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_connection,
                args=(conn,),
                name="ipc-conn",
                daemon=True,
            ).start()

    def _handle_connection(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(2.0)
            buf = bytearray()
            while b"\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > 1_000_000:
                    self._send_error(conn, None, INVALID_REQUEST, "Request too large")
                    return
            line, _, _ = bytes(buf).partition(b"\n")
            if not line:
                return
            try:
                request = Request.from_json(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                self._send_error(conn, None, PARSE_ERROR, f"Parse error: {exc}")
                return
            handler = self._handlers.get(request.method)
            if handler is None:
                self._send_error(
                    conn, request.id, METHOD_NOT_FOUND, f"Unknown method: {request.method!r}"
                )
                return
            try:
                result = handler(request)
            except Exception as exc:
                log.exception("Handler for %r raised", request.method)
                self._send_error(conn, request.id, HANDLER_FAILED, str(exc))
                return
            self._send(conn, Response(id=request.id, result=result))
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _send(conn: socket.socket, response: Response) -> None:
        try:
            conn.sendall(response.to_json().encode("utf-8") + b"\n")
        except OSError as exc:
            log.warning("Failed to send response: %s", exc)

    def _send_error(
        self,
        conn: socket.socket,
        request_id: int | str | None,
        code: int,
        message: str,
    ) -> None:
        if code == 0:
            code = INTERNAL_ERROR
        self._send(conn, Response(id=request_id, error=RpcError(code=code, message=message)))
