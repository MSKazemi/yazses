"""Windows IPC — JSON-RPC over a per-user named pipe.

Reuses the protocol module (:mod:`yazses.ipc.protocol`) for framing; only
the transport differs from the POSIX Unix-socket implementation.

Pipe name is derived from the user's name to keep multi-user systems isolated.
The :class:`Path` argument exists for API compatibility with the Unix server
factory; only the path's basename matters for naming.
"""

from __future__ import annotations

import getpass
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from yazses.ipc.protocol import (
    HANDLER_FAILED,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    NOT_REACHABLE,
    PARSE_ERROR,
    Request,
    Response,
    RpcError,
)

log = logging.getLogger(__name__)


def _pipe_name_from_path(path: Path) -> str:
    """Build a Windows pipe name from a stable path argument.

    Pipes share a flat namespace; we tag with the username so concurrent
    sessions for different users don't collide. The path's stem provides a
    further suffix in case multiple YazSes instances ever co-exist.
    """
    user = getpass.getuser() or "default"
    stem = path.stem or "daemon"
    return rf"\\.\pipe\yazses-{user}-{stem}"


def _close_quietly(win32file, handle) -> None:  # noqa: ANN001
    """Close a pipe handle, swallowing errors. Used on cleanup paths."""
    try:
        win32file.CloseHandle(handle)
    except Exception:  # pragma: no cover - best effort cleanup
        log.debug("CloseHandle failed", exc_info=True)


class NamedPipeIpcServer:
    """JSON-RPC server bound to a Windows named pipe."""

    _PIPE_BUFFER = 65536
    _MAX_INSTANCES = 8
    _ACCEPT_TIMEOUT_MS = 500

    def __init__(self, socket_path: Path) -> None:
        self._pipe_name = _pipe_name_from_path(socket_path)
        self._handlers: dict[str, Callable[[Request], object]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def register(self, method: str, handler: Callable[[Request], object]) -> None:
        self._handlers[method] = handler

    def serve_in_thread(self) -> None:
        self._thread = threading.Thread(target=self._accept_loop, name="ipc-server", daemon=True)
        self._thread.start()
        log.info("IPC server listening on %s", self._pipe_name)

    def shutdown(self) -> None:
        self._stop.set()
        # Open and close a client to unblock ConnectNamedPipe.
        try:
            import win32file  # type: ignore[import-not-found]

            handle = win32file.CreateFile(
                self._pipe_name, 0, 0, None, win32file.OPEN_EXISTING, 0, None
            )
            win32file.CloseHandle(handle)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # ------------------------------------------------------------------

    def _accept_loop(self) -> None:
        import pywintypes  # type: ignore[import-not-found]
        import win32file  # type: ignore[import-not-found]
        import win32pipe  # type: ignore[import-not-found]

        while not self._stop.is_set():
            try:
                handle = win32pipe.CreateNamedPipe(
                    self._pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_BYTE
                    | win32pipe.PIPE_READMODE_BYTE
                    | win32pipe.PIPE_WAIT,
                    self._MAX_INSTANCES,
                    self._PIPE_BUFFER,
                    self._PIPE_BUFFER,
                    0,
                    None,
                )
            except pywintypes.error as exc:
                # Every instance busy, or the name is taken. Backing off beats
                # spinning the CPU, and returning would kill IPC for good.
                if self._stop.is_set():
                    break
                log.warning("CreateNamedPipe failed: %s; retrying", exc)
                self._stop.wait(0.5)
                continue

            try:
                win32pipe.ConnectNamedPipe(handle, None)
            except pywintypes.error:
                # The handle must be closed on this path. Leaking it consumed
                # one of _MAX_INSTANCES (8) permanently, so eight failed
                # accepts — a client that connects and vanishes is enough —
                # left CreateNamedPipe failing forever and the daemon
                # unreachable until restarted.
                _close_quietly(win32file, handle)
                if self._stop.is_set():
                    break
                continue

            threading.Thread(
                target=self._handle_connection,
                args=(handle,),
                name="ipc-conn",
                daemon=True,
            ).start()

    def _handle_connection(self, handle) -> None:  # noqa: ANN001
        import pywintypes  # type: ignore[import-not-found]
        import win32file  # type: ignore[import-not-found]
        import win32pipe  # type: ignore[import-not-found]

        try:
            buf = bytearray()
            while b"\n" not in buf:
                hr, chunk = win32file.ReadFile(handle, 4096)
                if not chunk:
                    return
                buf.extend(chunk)
                if len(buf) > 1_000_000:
                    self._send_error(handle, None, INVALID_REQUEST, "Request too large")
                    return
            line, _, _ = bytes(buf).partition(b"\n")
            try:
                request = Request.from_json(line.decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                self._send_error(handle, None, PARSE_ERROR, f"Parse error: {exc}")
                return
            handler = self._handlers.get(request.method)
            if handler is None:
                self._send_error(handle, request.id, METHOD_NOT_FOUND, f"Unknown method: {request.method!r}")
                return
            try:
                result = handler(request)
            except Exception as exc:
                log.exception("Handler for %r raised", request.method)
                self._send_error(handle, request.id, HANDLER_FAILED, str(exc))
                return
            self._send(handle, Response(id=request.id, result=result))
        except pywintypes.error as exc:
            log.warning("Pipe IO failed: %s", exc)
        finally:
            try:
                win32pipe.DisconnectNamedPipe(handle)
                win32file.CloseHandle(handle)
            except Exception:
                pass

    @staticmethod
    def _send(handle, response: Response) -> None:  # noqa: ANN001
        try:
            import win32file  # type: ignore[import-not-found]

            win32file.WriteFile(handle, response.to_json().encode("utf-8") + b"\n")
        except Exception:
            log.warning("Failed to write response", exc_info=True)

    def _send_error(self, handle, request_id, code: int, message: str) -> None:  # noqa: ANN001
        self._send(handle, Response(id=request_id, error=RpcError(code=code, message=message)))


class IpcCallError(RuntimeError):
    """Raised when an RPC call returns a JSON-RPC error."""

    def __init__(self, error: RpcError) -> None:
        super().__init__(f"[{error.code}] {error.message}")
        self.error = error


class IpcUnreachableError(IpcCallError):
    def __init__(self, pipe_name: str, cause: Exception | None = None) -> None:
        super().__init__(RpcError(code=NOT_REACHABLE, message=f"Daemon not reachable at {pipe_name}"))
        self.pipe_name = pipe_name
        self.cause = cause


class NamedPipeIpcClient:
    """JSON-RPC client over a Windows named pipe."""

    def __init__(self, socket_path: Path, timeout_s: float = 2.0) -> None:
        self._pipe_name = _pipe_name_from_path(socket_path)
        self._timeout_s = timeout_s

    def is_reachable(self) -> bool:
        try:
            import win32file  # type: ignore[import-not-found]

            handle = win32file.CreateFile(
                self._pipe_name, 0, 0, None, win32file.OPEN_EXISTING, 0, None
            )
            win32file.CloseHandle(handle)
            return True
        except Exception:
            return False

    def call(self, method: str, **params: Any) -> Any:
        """Send one request and read one response, bounded by ``timeout_s``.

        The timeout is not decoration: the Unix client applies it with
        ``sock.settimeout`` (``ipc/client.py``), but this one merely *stored*
        it, so a blocking-mode named pipe left ``yazses status``/``stop``
        waiting forever on a daemon that was alive but wedged — the one
        situation where the user most needs the CLI to answer.

        A byte-mode pipe has no per-operation timeout, so the exchange runs on
        a worker thread and the handle is closed on expiry, which unblocks the
        pending ``ReadFile``.
        """
        import pywintypes  # type: ignore[import-not-found]
        import win32file  # type: ignore[import-not-found]
        import win32pipe  # type: ignore[import-not-found]

        request = Request(method=method, params=params, id=1)
        # Bound the connect, too — CreateFile on a pipe whose instances are all
        # busy blocks until one frees up.
        try:
            win32pipe.WaitNamedPipe(self._pipe_name, max(1, int(self._timeout_s * 1000)))
        except pywintypes.error as exc:
            raise IpcUnreachableError(self._pipe_name, cause=exc) from exc
        try:
            handle = win32file.CreateFile(
                self._pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
        except pywintypes.error as exc:
            raise IpcUnreachableError(self._pipe_name, cause=exc) from exc

        outcome: dict[str, Any] = {}

        def _exchange() -> None:
            try:
                win32file.WriteFile(handle, request.to_json().encode("utf-8") + b"\n")
                buf = bytearray()
                while b"\n" not in buf:
                    _, chunk = win32file.ReadFile(handle, 4096)
                    if not chunk:
                        break
                    buf.extend(chunk)
                outcome["buf"] = bytes(buf)
            except BaseException as exc:  # noqa: BLE001 - relayed to the caller
                outcome["exc"] = exc

        worker = threading.Thread(target=_exchange, name="ipc-call", daemon=True)
        worker.start()
        worker.join(self._timeout_s)
        timed_out = worker.is_alive()
        _close_quietly(win32file, handle)
        if timed_out:
            raise IpcUnreachableError(
                self._pipe_name,
                cause=TimeoutError(f"no response within {self._timeout_s}s"),
            )
        if "exc" in outcome:
            raise IpcUnreachableError(self._pipe_name, cause=outcome["exc"])

        line, _, _ = bytes(outcome.get("buf", b"")).partition(b"\n")
        response = Response.from_json(line.decode("utf-8"))
        if response.error is not None:
            raise IpcCallError(response.error)
        return response.result
