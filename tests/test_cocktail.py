"""Cocktail Filter P1 — personal-VAD gate core (design/v2-cognitive-layer §3.2).

Drops audio frames that aren't the enrolled target speaker, so an interfering voice
never reaches STT. The per-frame speaker embedder is injected (mocked) here; the
gate logic itself is pure numpy and fully testable.
"""
from __future__ import annotations

import numpy as np

from yazses.audio.personal_vad import gate

# Target/interferer "embeddings" the fake embedder returns, keyed by a frame's
# first sample value so tests can script which frames are whose.
_TARGET = np.array([1.0, 0.0], dtype="float32")
_INTERFERER = np.array([0.0, 1.0], dtype="float32")


def _embed_by_sign(frame):
    """Fake per-frame embedder: positive frames = target, negative = interferer."""
    return _TARGET if frame[0] >= 0 else _INTERFERER


def test_all_target_frames_pass_through():
    audio = np.full(900, 0.5, dtype="float32")  # all positive → all target
    out = gate(audio, _TARGET, _embed_by_sign, sample_rate=16000, window_ms=10, threshold=0.6)
    assert out.size == audio.size


def test_interferer_frames_are_dropped():
    # First half target (positive), second half interferer (negative).
    audio = np.concatenate([
        np.full(480, 0.5, dtype="float32"),
        np.full(480, -0.5, dtype="float32"),
    ])
    out = gate(audio, _TARGET, _embed_by_sign, sample_rate=16000, window_ms=10, threshold=0.6)
    # Only the target (positive) half survives.
    assert out.size == 480
    assert np.all(out > 0)


def test_all_interferer_yields_empty():
    audio = np.full(480, -0.5, dtype="float32")
    out = gate(audio, _TARGET, _embed_by_sign, sample_rate=16000, window_ms=10, threshold=0.6)
    assert out.size == 0


def test_empty_audio_is_safe():
    out = gate(np.array([], dtype="float32"), _TARGET, _embed_by_sign)
    assert out.size == 0
