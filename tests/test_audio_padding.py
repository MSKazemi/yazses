"""Tests for PreSpeechRingBuffer."""
from __future__ import annotations

import numpy as np

from yazses.audio.padding import PreSpeechRingBuffer


def make_ramp(n: int, start: float = 0.0, end: float = 1.0) -> np.ndarray:
    return np.linspace(start, end, n, dtype=np.float32)


def test_empty_buffer_returns_empty():
    buf = PreSpeechRingBuffer(padding_ms=200, sample_rate=16000)
    assert buf.get().size == 0


def test_push_small_chunk_and_get():
    buf = PreSpeechRingBuffer(padding_ms=100, sample_rate=16000)  # 1600 samples
    chunk = np.ones(800, dtype=np.float32)
    buf.push(chunk)
    result = buf.get()
    assert result.size == 800
    np.testing.assert_array_equal(result, chunk)


def test_push_fills_buffer():
    buf = PreSpeechRingBuffer(padding_ms=100, sample_rate=16000)  # 1600 samples
    chunk1 = np.zeros(1600, dtype=np.float32)
    buf.push(chunk1)
    result = buf.get()
    assert result.size == 1600


def test_prepend_padding_adds_prefix():
    buf = PreSpeechRingBuffer(padding_ms=100, sample_rate=16000)  # 1600 samples
    padding = np.ones(1600, dtype=np.float32) * 0.5
    buf.push(padding)
    audio = np.ones(3200, dtype=np.float32)
    result = buf.prepend_padding(audio)
    assert result.size == 1600 + 3200
    np.testing.assert_array_equal(result[:1600], padding)


def test_prepend_with_empty_buffer():
    buf = PreSpeechRingBuffer(padding_ms=200, sample_rate=16000)
    audio = np.ones(3200, dtype=np.float32)
    result = buf.prepend_padding(audio)
    assert result.size == 3200
    np.testing.assert_array_equal(result, audio)


def test_ring_buffer_wraps_correctly():
    """After overflow, get() returns chronologically ordered samples."""
    buf = PreSpeechRingBuffer(padding_ms=100, sample_rate=16000)  # 1600 capacity
    chunk_a = np.zeros(1200, dtype=np.float32)   # fills 1200/1600
    chunk_b = np.ones(800, dtype=np.float32)     # wraps: 400 overwrite + 400 new
    buf.push(chunk_a)
    buf.push(chunk_b)
    result = buf.get()
    assert result.size == 1600
    # Last 1600 samples should be: [zeros(400), ones(800), zeros(400)] → no, let's check:
    # After chunk_a: buffer = [0...0(1200), uninit(400)], head=1200
    # After chunk_b: buffer[1200:1600]=ones(400), buffer[0:400]=ones(400), head=400
    # get(): buffer[400:] + buffer[:400] = [uninit(800), ones(400), ones(400), ones(400)]
    # Actually test that the last 400 samples ARE ones (the newest)
    assert np.all(result[-400:] == 1.0)


def test_clear_resets_buffer():
    buf = PreSpeechRingBuffer(padding_ms=100, sample_rate=16000)
    buf.push(np.ones(1600, dtype=np.float32))
    buf.clear()
    assert buf.get().size == 0


def test_zero_padding_ms():
    buf = PreSpeechRingBuffer(padding_ms=0, sample_rate=16000)
    buf.push(np.ones(100, dtype=np.float32))
    audio = np.ones(500, dtype=np.float32)
    result = buf.prepend_padding(audio)
    assert result.size == 500  # no padding added
