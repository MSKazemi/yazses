"""The Qt half of "one settings window": the lock, the local socket, and raising the window.

``QLocalServer`` / ``QLocalSocket`` only: a Unix domain socket in the user's runtime
directory, or a named pipe on Windows, open to this user alone. No address and no port
(ADR-019, pinned by ``tests/test_egress_inventory.py``). The decisions and the message format
are in :mod:`yazses.settingsui.single_window`.

PySide6 is imported inside functions, like the rest of ``settingsui/``.
"""
from __future__ import annotations

import getpass
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from yazses.settingsui import single_window as sw
from yazses.system.single_instance import (
    SingleInstanceLock,
    holder_pid,
    locks_unsupported,
)
from yazses.system.wincon import allow_foreground

log = logging.getLogger(__name__)

#: The longest one connection attempt may take before the lock is looked at again.
_CONNECT_MS = 500


class SingleWindow:
    """What the open window holds: the lock, and the server later launches talk to.

    A request that arrives before :meth:`attach` (the window is still being built) waits for
    it, and so does the answer.
    """

    def __init__(self, release: Callable[[], None] | None = None) -> None:
        self._release = release
        self._server: Any = None
        self._handler: Callable[[sw.ShowRequest], None] | None = None
        self._waiting: list[tuple[sw.ShowRequest, Any]] = []

    def listen(self, endpoint: str) -> bool:
        """Accept requests on *endpoint*. Only the holder of the lock may call this."""
        try:
            from PySide6.QtNetwork import QLocalServer
        except ImportError as exc:
            log.warning("A later launch cannot reach this window: %s", exc)
            return False
        if os.path.isabs(endpoint):  # a socket file; a Windows pipe name is not a path
            os.makedirs(os.path.dirname(endpoint), exist_ok=True)
        # A window that crashed leaves its socket file behind, and listening on it would
        # fail. We hold the lock, so no live window owns it.
        QLocalServer.removeServer(endpoint)
        server = QLocalServer()
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        server.newConnection.connect(self._accept)
        if not server.listen(endpoint):
            log.warning("A later launch cannot reach this window: %s", server.errorString())
            return False
        self._server = server
        return True

    def attach(self, handler: Callable[[sw.ShowRequest], None]) -> None:
        """Give requests to *handler*, on the GUI thread, including any already waiting."""
        self._handler = handler
        self._deliver()

    def close(self) -> None:
        """Stop listening, then free the lock. Safe to call twice.

        In that order: closing removes the socket file, which after the lock is free could be
        the next window's.
        """
        server, self._server = self._server, None
        if server is not None:
            try:
                server.close()
            except RuntimeError:  # Qt already destroyed it
                pass
        self._waiting.clear()
        release, self._release = self._release, None
        if release is not None:
            release()

    def _accept(self) -> None:
        while self._server is not None and self._server.hasPendingConnections():
            connection = self._server.nextPendingConnection()
            connection.readyRead.connect(partial(self._read, connection))
            self._read(connection)  # the line may have arrived before the signal was wired

    def _read(self, connection: Any) -> None:
        if not connection.canReadLine():
            if connection.bytesAvailable() > sw.MAX_REQUEST_BYTES:
                connection.abort()
            return
        request = sw.decode_request(bytes(connection.readLine().data()))
        if request is None:
            connection.abort()
            return
        self._waiting.append((request, connection))
        self._deliver()

    def _deliver(self) -> None:
        while self._handler is not None and self._waiting:
            request, connection = self._waiting.pop(0)
            try:
                self._handler(request)
            except Exception:  # noqa: BLE001 - no answer, so the sender reports it
                log.exception("Could not show the window for a later launch")
                continue
            # The sender closes once it has read this; closing here could drop it on
            # Windows. A sender that already gave up makes the write a no-op.
            connection.write(sw.ACK)
            connection.flush()


def send_request(endpoint: str, request: sw.ShowRequest, timeout_s: float) -> bool:
    """Hand *request* to the window listening on *endpoint*. Blocking.

    True only once that window says it acted. Needs no event loop.
    """
    try:
        from PySide6.QtNetwork import QLocalSocket
    except ImportError as exc:
        log.warning("Cannot reach the open window: %s", exc)
        return False
    deadline = time.monotonic() + timeout_s

    def _left() -> int:
        return max(0, int((deadline - time.monotonic()) * 1000))

    connection = QLocalSocket()
    try:
        connection.connectToServer(endpoint)
        if not connection.waitForConnected(max(1, min(_left(), _CONNECT_MS))):
            return False
        connection.write(sw.encode_request(request))
        connection.flush()
        if connection.bytesToWrite():
            connection.waitForBytesWritten(_left())
        reply = b""
        while True:
            reply += bytes(connection.readAll().data())
            if b"\n" in reply:
                break
            if not _left() or not connection.waitForReadyRead(_left()):
                reply += bytes(connection.readAll().data())
                break
        return reply.startswith(sw.ACK)
    finally:
        connection.abort()


@dataclass(frozen=True)
class Claim:
    """The answer to "may this process open the window?"."""

    outcome: sw.Outcome
    window: SingleWindow
    #: The process holding the lock when it did not answer, if it could be read.
    holder: int | None = None


def _user() -> str:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - no passwd entry; the config path still tells users apart
        return ""


def claim_window(
    platform: Any,
    config_file: Path,
    request: sw.ShowRequest,
    *,
    wait_s: float = sw.WAIT_S,
) -> Claim:
    """Become the one window for *config_file*, or send *request* to the one that is open.

    Needs a Qt application object. A lock that cannot be taken at all (an unwritable data
    directory, a filesystem without file locks) opens the window unguarded: settings must
    stay reachable.
    """
    tag = sw.instance_tag(config_file, _user())
    lock_path = sw.lock_file(platform.paths.data_dir, tag)
    endpoint = platform.local_endpoint(platform.paths, tag)
    lock = SingleInstanceLock(lock_path)

    def _acquire() -> bool:
        if lock.acquire():
            return True
        error = lock.error
        if error is not None and locks_unsupported(error):
            raise error  # nobody holds it, and nobody ever could
        return False

    def _forward(seconds: float) -> bool:
        holder = holder_pid(lock_path)
        if holder is not None and holder > 0:
            # Before the request: on Windows the open window may take the foreground only
            # if the process that has that right (this one, just launched) allows it.
            allow_foreground(holder)
        return send_request(endpoint, request, seconds)

    try:
        outcome = sw.claim(_acquire, _forward, wait_s=wait_s)
    except OSError as exc:
        log.warning("Cannot tell whether the settings window is already open: %s", exc)
        return Claim(sw.Outcome.OWNER, SingleWindow())
    if outcome is not sw.Outcome.OWNER:
        holder = holder_pid(lock_path) if outcome is sw.Outcome.UNANSWERED else None
        return Claim(outcome, SingleWindow(), holder)
    window = SingleWindow(lock.release)
    try:
        window.listen(endpoint)
    except OSError as exc:
        log.warning("A later launch cannot reach this window: %s", exc)
    return Claim(outcome, window)


def raise_window(window: Any, token: str = "") -> None:
    """Bring *window* to the front, restoring it if minimised, as far as the desktop allows.

    *token* is the later launch's activation token. It is put in the environment for the
    activation, which is where Qt's Wayland backend takes one from. A desktop that refuses to
    move the focus is asked to flag the window instead.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    previous = os.environ.get(sw.ACTIVATION_ENV)
    if token:
        os.environ[sw.ACTIVATION_ENV] = token
    try:
        state = window.windowState()
        if state & Qt.WindowState.WindowMinimized:
            # Clears only that bit, so a maximised window comes back maximised.
            window.setWindowState(state & ~Qt.WindowState.WindowMinimized)
        window.show()
        window.raise_()
        # A question already on screen stays in front of the window that asked it.
        target = QApplication.activeModalWidget() or window
        target.raise_()
        target.activateWindow()
        QApplication.alert(window)
    finally:
        # Used once; processes this window starts later must not inherit it.
        if previous is None:
            os.environ.pop(sw.ACTIVATION_ENV, None)
        else:
            os.environ[sw.ACTIVATION_ENV] = previous
