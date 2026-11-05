"""A per-call wait on the IPC client, and "slow" told apart from "absent".

The client's default timeout is a short 2 s -- right for `status`, wrong for a call whose
handler is *supposed* to take longer: `ask_human` speaks the question and listens for the
answer, `send_to` waits on the desktop app's link scheme. Both used to be cut off at 2 s
and reported as "YazSes is not running" / "starting up" while the daemon was, in fact,
doing the work (audit r1105e, defect D1).

The timings are scaled down (0.2 s default against a 0.8 s handler) so the suite stays
fast; the margins are wide because the point is the order, not the numbers.

Real AF_UNIX sockets in a short /tmp directory; the Windows client is exercised with
stand-ins for pywin32, which this machine does not have.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from yazses.ipc.client import IpcTimeoutError, IpcUnreachableError, JsonRpcClient
from yazses.ipc.server import JsonRpcServer

_POSIX = pytest.mark.skipif(
    sys.platform not in ("linux", "darwin"), reason="Unix-domain sockets are POSIX-only"
)

SLOW_S = 0.8
SHORT_DEFAULT_S = 0.2


@pytest.fixture
def slow_server() -> Iterator[Path]:
    # Short /tmp path: macOS AF_UNIX sun_path is only 104 bytes.
    with tempfile.TemporaryDirectory(prefix="nv-", dir="/tmp") as d:
        path = Path(d) / "w.sock"
        srv = JsonRpcServer.unix(path)

        def _slow(req):
            time.sleep(SLOW_S)
            return {"ok": True, "echo": dict(req.params)}

        srv.register("slow", _slow)
        srv.register("quick", lambda req: {"ok": True})
        srv.serve_in_thread()
        for _ in range(200):
            if path.exists():
                break
            time.sleep(0.01)
        try:
            yield path
        finally:
            srv.shutdown()


@_POSIX
def test_the_default_wait_still_cuts_a_slow_call_off(slow_server):
    """The short default stays: `status`-style calls must not hang on a wedged daemon."""
    client = JsonRpcClient.unix(slow_server, timeout_s=SHORT_DEFAULT_S)
    with pytest.raises(IpcTimeoutError):
        client.call("slow")


@_POSIX
def test_a_per_call_wait_lets_a_slow_handler_finish(slow_server):
    client = JsonRpcClient.unix(slow_server, timeout_s=SHORT_DEFAULT_S)
    reply = client.call("slow", wait_s=10.0, question="proceed?")
    assert reply == {"ok": True, "echo": {"question": "proceed?"}}, (
        "wait_s must not be forwarded to the daemon as a parameter"
    )


@_POSIX
def test_wait_s_is_per_call_not_sticky(slow_server):
    client = JsonRpcClient.unix(slow_server, timeout_s=SHORT_DEFAULT_S)
    assert client.call("slow", wait_s=10.0)["ok"]
    with pytest.raises(IpcTimeoutError):
        client.call("slow")


@_POSIX
def test_a_daemon_parameter_named_timeout_s_still_reaches_the_daemon(slow_server):
    """`ask_human` has a daemon-side `timeout_s`; the per-call wait must not shadow it."""
    client = JsonRpcClient.unix(slow_server, timeout_s=SHORT_DEFAULT_S)
    assert client.call("slow", wait_s=10.0, timeout_s=30.0)["echo"] == {"timeout_s": 30.0}


@_POSIX
def test_a_slow_daemon_is_a_timeout_and_an_absent_one_is_not(slow_server, tmp_path):
    slow = JsonRpcClient.unix(slow_server, timeout_s=SHORT_DEFAULT_S)
    with pytest.raises(IpcTimeoutError) as slow_exc:
        slow.call("slow")
    assert slow_exc.value.timeout_s == SHORT_DEFAULT_S
    assert isinstance(slow_exc.value, IpcUnreachableError), "existing handlers keep catching it"

    absent = JsonRpcClient.unix(tmp_path / "nobody-listens.sock", timeout_s=SHORT_DEFAULT_S)
    with pytest.raises(IpcUnreachableError) as absent_exc:
        absent.call("quick")
    assert not isinstance(absent_exc.value, IpcTimeoutError)


# --- the Windows client, against stand-ins for pywin32 ---------------------------


class _FakePywin:
    """Just enough of pywintypes/win32file/win32pipe for `NamedPipeIpcClient.call`."""

    GENERIC_READ = 1
    GENERIC_WRITE = 2
    OPEN_EXISTING = 3

    def __init__(self, *, wait_error: int | None = None, reply: bytes | None = None):
        self.wait_error = wait_error
        self.reply = reply
        self.wait_ms: list[int] = []
        self.sent: list[bytes] = []
        self._closed = threading.Event()

        outer = self

        class _Error(Exception):
            def __init__(self, winerror: int) -> None:
                super().__init__(winerror)
                self.winerror = winerror

        self.error = _Error
        self.pywintypes = SimpleNamespace(error=_Error)
        self.win32pipe = SimpleNamespace(WaitNamedPipe=self._wait_named_pipe)
        self.win32file = SimpleNamespace(
            GENERIC_READ=1, GENERIC_WRITE=2, OPEN_EXISTING=3,
            CreateFile=lambda *a, **k: object(),
            WriteFile=lambda handle, data: outer.sent.append(data),
            ReadFile=outer._read_file,
            CloseHandle=lambda handle: outer._closed.set(),
        )

    def _wait_named_pipe(self, name, ms):
        self.wait_ms.append(ms)
        if self.wait_error is not None:
            raise self.error(self.wait_error)

    def _read_file(self, handle, size):
        if self.reply is not None:
            return 0, self.reply
        self._closed.wait(10)  # a wedged daemon: nothing arrives until the handle closes
        raise self.error(995)

    def install(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "pywintypes", self.pywintypes)
        monkeypatch.setitem(sys.modules, "win32file", self.win32file)
        monkeypatch.setitem(sys.modules, "win32pipe", self.win32pipe)


def _windows_client(timeout_s: float):
    from yazses.platform.windows.ipc import NamedPipeIpcClient

    return NamedPipeIpcClient(Path("yazses-test.sock"), timeout_s=timeout_s)


def test_windows_client_a_silent_pipe_is_a_timeout_that_names_the_wait(monkeypatch):
    from yazses.platform.windows.ipc import IpcTimeoutError as WinTimeout

    _FakePywin().install(monkeypatch)
    started = time.monotonic()
    with pytest.raises(IpcTimeoutError) as caught:
        _windows_client(timeout_s=5.0).call("slow", wait_s=0.3)
    assert isinstance(caught.value, WinTimeout)
    assert isinstance(caught.value, IpcUnreachableError)
    assert caught.value.timeout_s == 0.3
    assert time.monotonic() - started < 4.0, "wait_s, not the 5 s default, bounded the call"


def test_windows_client_default_wait_applies_without_wait_s(monkeypatch):
    fake = _FakePywin()
    fake.install(monkeypatch)
    with pytest.raises(IpcTimeoutError) as caught:
        _windows_client(timeout_s=0.3).call("slow")
    assert caught.value.timeout_s == 0.3
    assert fake.wait_ms == [300]


def test_windows_client_wait_s_also_bounds_the_connect(monkeypatch):
    fake = _FakePywin()
    fake.install(monkeypatch)
    with pytest.raises(IpcTimeoutError):
        _windows_client(timeout_s=0.1).call("slow", wait_s=0.25)
    assert fake.wait_ms == [250]


def test_windows_client_all_instances_busy_is_a_timeout_not_absence(monkeypatch):
    _FakePywin(wait_error=121).install(monkeypatch)  # ERROR_SEM_TIMEOUT
    with pytest.raises(IpcTimeoutError):
        _windows_client(timeout_s=0.1).call("slow")


def test_windows_client_a_missing_pipe_is_unreachable_not_a_timeout(monkeypatch):
    _FakePywin(wait_error=2).install(monkeypatch)  # ERROR_FILE_NOT_FOUND
    with pytest.raises(IpcUnreachableError) as caught:
        _windows_client(timeout_s=0.1).call("slow")
    assert not isinstance(caught.value, IpcTimeoutError)


def test_windows_client_a_reply_comes_back_and_wait_s_is_not_forwarded(monkeypatch):
    fake = _FakePywin(reply=b'{"jsonrpc": "2.0", "id": 1, "result": {"ok": true}}\n')
    fake.install(monkeypatch)
    assert _windows_client(timeout_s=0.1).call("slow", wait_s=2.0, timeout_s=30.0) == {"ok": True}
    sent = json.loads(fake.sent[0])
    assert sent["params"] == {"timeout_s": 30.0}, "wait_s is the client's, never the daemon's"
