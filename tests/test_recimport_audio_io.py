"""Audio decode to 16 kHz mono float32 — ADR-v2-125 (recimport/audio_io.py)."""
from __future__ import annotations

import wave

import numpy as np
import pytest

pytest.importorskip("faster_whisper")  # PyAV decode path rides in with faster-whisper

from yazses.recimport.audio_io import load_audio  # noqa: E402


def _write_wav(path, seconds=0.5, sr=16000):
    n = int(seconds * sr)
    samples = (np.sin(np.linspace(0, 40 * np.pi, n)) * 8000).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.tobytes())


def test_load_wav_returns_16k_mono_float32(tmp_path):
    f = tmp_path / "tone.wav"
    _write_wav(f)
    audio, sr = load_audio(f)
    assert sr == 16000
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert abs(len(audio) - 8000) < 400  # ~0.5s at 16 kHz
