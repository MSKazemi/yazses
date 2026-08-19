"""Regression: the streaming decode loop must not outlive the burst that started it.

Only ``commit()`` used to end the loop, and commit only runs on the successful
transcription path. Every early return in ``_on_hold_end`` (silent discard,
cocktail gate, missing recorder) therefore leaked a decode loop that kept
re-decoding its frozen buffer once per interval — forever, one leaked Whisper
decode per second per discarded burst, until the process exited.
"""
from __future__ import annotations

import time
from dataclasses import replace

import numpy as np

from yazses.config import AccessibilityConfig, Config, StreamingConfig
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.stt.streaming import StreamingEngine


class _CountingEngine:
    """Fake SttEngine recording how many window decodes the loop performed."""

    def __init__(self) -> None:
        self.calls = 0

    def decode_window(self, audio) -> str:
        self.calls += 1
        return "hello"


def test_request_stop_ends_the_decode_loop():
    backend = _CountingEngine()
    engine = StreamingEngine(backend, partial_interval_ms=20)
    engine.start()
    engine.push(np.zeros(16000, dtype=np.float32))  # 1 s — above the decode floor
    deadline = time.monotonic() + 5.0               # poll, don't guess CI scheduling
    while backend.calls == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert backend.calls > 0                        # loop is genuinely running

    engine.request_stop()
    engine._thread.join(timeout=2.0)
    assert not engine._thread.is_alive()            # exits within one cycle

    after = backend.calls
    time.sleep(0.1)
    assert backend.calls == after                   # and decodes no more


def test_request_stop_does_not_block_on_an_in_flight_decode():
    """Hold-release must stay on the hot path even mid-decode."""

    class _SlowEngine:
        def decode_window(self, audio) -> str:
            time.sleep(0.5)
            return ""

    engine = StreamingEngine(_SlowEngine(), partial_interval_ms=10)
    engine.start()
    engine.push(np.zeros(16000, dtype=np.float32))
    time.sleep(0.05)                                # let a slow decode start

    t0 = time.monotonic()
    engine.request_stop()
    assert time.monotonic() - t0 < 0.1              # returns immediately
    engine.stop()                                   # blocking variant cleans up


def test_stop_is_safe_before_start():
    engine = StreamingEngine(_CountingEngine(), partial_interval_ms=10)
    engine.request_stop()                           # never started — must not raise
    engine.stop()


def _daemon(mocker):
    cfg = replace(
        Config(),
        streaming=StreamingConfig(enabled=True),
        accessibility=AccessibilityConfig(vad_threshold=0.01),
    )
    d = Daemon(config=cfg, platform=get_platform())
    # `_shutdown()` runs the real lifecycle backend otherwise, and its `clear_pid()`
    # deletes `~/.local/share/yazses/daemon.pid` -- the running daemon's own pid file,
    # on the machine the suite is running on. `system/pid.py` reads the single-instance
    # lock first on Linux, so nothing broke visibly; on a platform without that
    # primitive `yazses status` would report "not running" for a live daemon.
    mocker.patch.object(d._platform.lifecycle, "clear_pid")
    d._engine = mocker.MagicMock()
    d._injector = mocker.MagicMock()
    d._stream_engine = mocker.MagicMock()
    d._note_silent_discard = mocker.MagicMock()
    return d


def test_silent_discard_stops_the_decode_loop(mocker):
    """The path that leaked: audio below the VAD gate is discarded."""
    d = _daemon(mocker)
    d._recorder = mocker.MagicMock()
    d._recorder.stop.return_value = np.zeros(16000, dtype=np.float32)  # silent

    d._on_hold_end()

    d._stream_engine.request_stop.assert_called_once()


def test_missing_recorder_stops_the_decode_loop(mocker):
    """The earliest early-return must not leak either."""
    d = _daemon(mocker)
    d._recorder = None

    d._on_hold_end()

    d._stream_engine.request_stop.assert_called_once()


def test_shutdown_joins_the_decode_loop(mocker):
    d = _daemon(mocker)
    d._shutdown()
    d._stream_engine.stop.assert_called_once()
