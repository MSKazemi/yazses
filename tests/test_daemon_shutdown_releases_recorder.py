"""Regression: the daemon's own teardown must release the push-to-talk recorder.

``_shutdown()`` stopped nearly every subsystem but never the ``AudioRecorder``, so an
input stream opened by a hold still in progress stayed open until the process exited.
Synthetic, platform-neutral: a fake recorder stands in for the microphone.
"""
from __future__ import annotations

import numpy as np
import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform


class _FakeRecorder:
    def __init__(self, raises: bool = False) -> None:
        self.stops = 0
        self.raises = raises

    def stop(self):
        self.stops += 1
        if self.raises:
            raise RuntimeError("device vanished")
        return np.zeros(16000, dtype=np.float32)


@pytest.fixture
def daemon(mocker):
    d = Daemon(config=Config(), platform=get_platform())
    # The real lifecycle backend would delete the running daemon's pid file.
    mocker.patch.object(d._platform.lifecycle, "clear_pid")
    return d


def test_shutdown_stops_an_open_recorder_without_typing(daemon, mocker):
    rec = _FakeRecorder()
    daemon._recorder = rec
    daemon._engine = mocker.MagicMock()
    daemon._injector = mocker.MagicMock()
    daemon._shutdown()
    assert rec.stops == 1
    daemon._engine.transcribe.assert_not_called()
    daemon._injector.type_text.assert_not_called()


def test_shutdown_is_idempotent_with_a_recorder(daemon):
    rec = _FakeRecorder()
    daemon._recorder = rec
    daemon._shutdown()
    daemon._shutdown()  # stop() itself is idempotent; a second teardown must not raise
    assert rec.stops >= 1


def test_shutdown_without_a_recorder_does_not_raise(daemon):
    daemon._recorder = None  # pipeline never built: early stop / model unavailable
    daemon._shutdown()


def test_recorder_stop_raising_does_not_skip_later_steps(daemon, mocker):
    daemon._recorder = _FakeRecorder(raises=True)
    ipc = mocker.MagicMock()
    daemon._ipc_server = ipc
    lock = mocker.MagicMock()
    daemon._instance_lock = lock
    daemon._shutdown()
    ipc.shutdown.assert_called_once()
    lock.release.assert_called_once()


def test_recorder_is_stopped_before_ipc_and_lock(daemon, mocker):
    order: list[str] = []
    rec = _FakeRecorder()
    rec.stop = lambda: order.append("recorder")  # type: ignore[method-assign]
    daemon._recorder = rec
    daemon._ipc_server = mocker.MagicMock()
    daemon._ipc_server.shutdown.side_effect = lambda: order.append("ipc")
    daemon._instance_lock = mocker.MagicMock()
    daemon._instance_lock.release.side_effect = lambda: order.append("lock")
    daemon._shutdown()
    assert order == ["recorder", "ipc", "lock"]
