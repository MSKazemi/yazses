"""A raising ``on_chunk`` consumer must not be able to kill the microphone stream.

sounddevice registers its PortAudio callback with cffi ``error=paAbort`` (read in
``sounddevice.py``, not executed here), so an exception escaping ``_callback`` aborts
the stream mid-take and ``stop()`` then files it as a lost input device. These tests
drive ``_callback`` directly -- synthetic, no real PortAudio.
"""
from __future__ import annotations

import logging

import numpy as np

from yazses.audio.recorder import AudioRecorder

SR = 16000


def _block(n: int = 160) -> np.ndarray:
    return np.full((n, 1), 0.1, dtype=np.float32)


def test_raising_on_chunk_does_not_escape_and_take_survives(caplog):
    calls: list[int] = []

    def boom(chunk: np.ndarray) -> None:
        calls.append(len(chunk))
        raise ValueError("consumer bug")

    rec = AudioRecorder(sample_rate=SR, on_chunk=boom)
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        for _ in range(5):
            rec._callback(_block(), 160, None, 0)  # must not raise

    assert len(calls) == 5  # consumer still called every chunk
    assert sum(len(c) for c in rec._chunks) == 5 * 160  # nothing lost
    warnings = [r for r in caplog.records if "on_chunk" in r.getMessage()]
    assert len(warnings) == 1  # rate limited: once per recording
    assert rec.stream_interrupted is False


def test_warning_is_rearmed_by_the_next_recording(caplog, mocker):
    rec = AudioRecorder(sample_rate=SR, on_chunk=lambda c: 1 / 0)
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        rec._callback(_block(), 160, None, 0)
        rec._on_chunk_failed = False  # what start() does for a new take
        rec._callback(_block(), 160, None, 0)
    assert len([r for r in caplog.records if "on_chunk" in r.getMessage()]) == 2


def test_healthy_on_chunk_unchanged(caplog):
    got: list[np.ndarray] = []
    rec = AudioRecorder(sample_rate=SR, on_chunk=got.append)
    with caplog.at_level(logging.WARNING, logger="yazses.audio.recorder"):
        rec._callback(_block(), 160, None, 0)
    assert len(got) == 1 and len(rec._chunks) == 1
    assert not caplog.records
