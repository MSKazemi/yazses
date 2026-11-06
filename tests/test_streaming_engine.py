"""Tests for the StreamingEngine (LocalAgreement streaming policy)."""
from __future__ import annotations

import time

import numpy as np

from yazses.stt.streaming import PartialHypothesis, StreamingEngine, _common_prefix


class MockSttEngine:
    """Fake SttEngine whose decode_window returns predictable transcriptions.

    StreamingEngine drives backends only through the ``decode_window`` seam
    (yazses.stt.base.SttEngine) — never a raw WhisperModel.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self._call_count = 0

    def decode_window(self, audio) -> str:
        if self._call_count < len(self._responses):
            text = self._responses[self._call_count]
        else:
            text = self._responses[-1] if self._responses else ""
        self._call_count += 1
        return text


def test_common_prefix():
    assert _common_prefix("hello world", "hello wor") == "hello wor"
    assert _common_prefix("hello", "world") == ""
    assert _common_prefix("", "hello") == ""
    assert _common_prefix("abc", "abc") == "abc"


class ScriptedStopToken:
    """Stands in for the decode loop's stop ``Event``: lets exactly ``cycles`` decodes run.

    Driving ``_decode_loop`` on the test thread with this token makes the loop
    deterministic -- no background thread, no sleeps, no timing window in which a
    partial may or may not have been produced yet.
    """

    def __init__(self, cycles: int) -> None:
        self._left = cycles
        self._stopped = False

    def is_set(self) -> bool:
        return self._stopped

    def wait(self, timeout: float | None = None) -> bool:
        if self._left <= 0:
            self._stopped = True
        self._left -= 1
        return self._stopped


def run_decode_cycles(engine: StreamingEngine, cycles: int) -> None:
    engine._decode_loop(ScriptedStopToken(cycles))  # noqa: SLF001


def test_streaming_engine_emits_partial(sine_audio_3s):
    """Two agreeing decodes confirm their common prefix and emit it as one partial."""
    engine = StreamingEngine(MockSttEngine(["hello wor", "hello world"]), partial_interval_ms=100)
    engine.push(sine_audio_3s)

    run_decode_cycles(engine, 1)
    assert engine.get_partial() is None  # one decode alone confirms nothing

    run_decode_cycles(engine, 1)
    assert engine.get_partial() == PartialHypothesis(
        text="hello wor", is_stable=True, char_count=len("hello wor")
    )
    assert engine.get_partial() is None  # the slot is consumed by reading it


def test_streaming_engine_commit_returns_text(sine_audio_3s):
    """commit() should return the final transcript."""
    engine_backend = MockSttEngine(["hello world"])
    engine = StreamingEngine(engine_backend, partial_interval_ms=50)
    engine.start()
    engine.push(sine_audio_3s)
    time.sleep(0.2)
    result = engine.commit()
    assert isinstance(result, str)


def test_streaming_engine_commit_empty_audio():
    """commit() with no audio should return empty string."""
    engine_backend = MockSttEngine([])
    engine = StreamingEngine(engine_backend, partial_interval_ms=50)
    engine.start()
    result = engine.commit()
    assert result == ""


def test_streaming_engine_reset():
    """reset() should clear all state."""
    engine_backend = MockSttEngine(["hello"])
    engine = StreamingEngine(engine_backend, partial_interval_ms=50)
    engine.start()
    engine.push(np.zeros(16000, dtype=np.float32))
    engine.reset()
    assert engine._cumulative_chars == 0  # noqa: SLF001
    assert engine._last_emitted == ""  # noqa: SLF001
