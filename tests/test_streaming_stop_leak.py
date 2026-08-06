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
from unittest.mock import MagicMock

import numpy as np

from yazses.config import AccessibilityConfig, Config, StreamingConfig
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.stt.streaming import StreamingEngine


class _CountingModel:
    """Records how many decodes the loop performed."""

    def __init__(self) -> None:
        self.calls = 0

    def transcribe(self, audio, language="en"):
        self.calls += 1
        seg = MagicMock()
        seg.text = " hello"
        return [seg], MagicMock()


def test_request_stop_ends_the_decode_loop():
    model = _CountingModel()
    engine = StreamingEngine(model, partial_interval_ms=20)
    engine.start()
    engine.push(np.zeros(16000, dtype=np.float32))  # 1 s — above the decode floor
    time.sleep(0.1)
    assert model.calls > 0                          # loop is genuinely running

    engine.request_stop()
    engine._thread.join(timeout=2.0)
    assert not engine._thread.is_alive()            # exits within one cycle

    after = model.calls
    time.sleep(0.1)
    assert model.calls == after                     # and decodes no more


def test_request_stop_does_not_block_on_an_in_flight_decode():
    """Hold-release must stay on the hot path even mid-decode."""

    class _SlowModel:
        def transcribe(self, audio, language="en"):
            time.sleep(0.5)
            return [], MagicMock()

    engine = StreamingEngine(_SlowModel(), partial_interval_ms=10)
    engine.start()
    engine.push(np.zeros(16000, dtype=np.float32))
    time.sleep(0.05)                                # let a slow decode start

    t0 = time.monotonic()
    engine.request_stop()
    assert time.monotonic() - t0 < 0.1              # returns immediately
    engine.stop()                                   # blocking variant cleans up


def test_stop_is_safe_before_start():
    engine = StreamingEngine(_CountingModel(), partial_interval_ms=10)
    engine.request_stop()                           # never started — must not raise
    engine.stop()


def _daemon(mocker):
    cfg = replace(
        Config(),
        streaming=StreamingConfig(enabled=True),
        accessibility=AccessibilityConfig(vad_threshold=0.01),
    )
    d = Daemon(config=cfg, platform=get_platform())
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
