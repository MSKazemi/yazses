"""Shared voiceprint foundation (design/v2-cognitive-layer §2.1).

Speaker enrollment + embedding, reused by Cocktail Filter (target-speaker gate)
and Voiceprint Mind (personalization). This covers the dependency-free core — the
cosine-similarity math and the target/non-target frame decision the gate needs —
plus the dormancy contract of the embedder factory (the real embedder lives in the
optional `voiceprint` extra). The actual speaker encoder is mocked here.
"""
from __future__ import annotations

import numpy as np

from yazses.config import VoiceprintConfig
from yazses.voiceprint.embedding import Embedding, cosine_similarity, is_target_frame
from yazses.voiceprint.factory import build_embedder

# ---- cosine_similarity (pure) ----------------------------------------------

def test_cosine_identical_is_one():
    v = np.array([1.0, 2.0, 3.0], dtype="float32")
    assert cosine_similarity(v, v) == 1.0


def test_cosine_orthogonal_is_zero():
    a = np.array([1.0, 0.0], dtype="float32")
    b = np.array([0.0, 1.0], dtype="float32")
    assert abs(cosine_similarity(a, b)) < 1e-6


def test_cosine_opposite_is_negative():
    a = np.array([1.0, 0.0], dtype="float32")
    assert cosine_similarity(a, -a) < 0


def test_cosine_zero_vector_is_safe():
    z = np.zeros(4, dtype="float32")
    assert cosine_similarity(z, z) == 0.0  # no div-by-zero, no NaN


# ---- is_target_frame: the personal-VAD gate decision -----------------------

def test_target_frame_above_threshold_kept():
    target = np.array([1.0, 0.0, 0.0], dtype="float32")
    frame = np.array([0.9, 0.1, 0.0], dtype="float32")
    assert is_target_frame(frame, target, threshold=0.6) is True


def test_interferer_frame_below_threshold_dropped():
    target = np.array([1.0, 0.0, 0.0], dtype="float32")
    frame = np.array([0.0, 1.0, 0.0], dtype="float32")  # orthogonal interferer
    assert is_target_frame(frame, target, threshold=0.6) is False


# ---- Embedding dataclass ---------------------------------------------------

def test_embedding_wraps_a_unit_vector():
    e = Embedding(vector=np.array([3.0, 4.0], dtype="float32"))
    # similarity to itself is 1 regardless of magnitude
    assert cosine_similarity(e.vector, e.vector) == 1.0


# ---- build_embedder factory: dormancy + degradation ------------------------

def test_factory_none_when_dormant():
    assert build_embedder(VoiceprintConfig(enabled=False)) is None


def test_factory_degrades_to_none_when_backend_unavailable():
    # enabled but speechbrain/resemblyzer not installed in this env → None
    # (caller treats None as "no voiceprint available" and stays dormant).
    backend = build_embedder(VoiceprintConfig(enabled=True, backend="ecapa"))
    assert backend is None or hasattr(backend, "embed")


def test_factory_unknown_backend_is_none():
    assert build_embedder(VoiceprintConfig(enabled=True, backend="nope")) is None


# ---- encrypted voiceprint store --------------------------------------------

def test_voiceprint_roundtrips_through_encrypted_store(tmp_path):
    import os

    from yazses.learning.crypto import Cipher
    from yazses.voiceprint.store import load_voiceprint, save_voiceprint

    cipher = Cipher(os.urandom(32))
    emb = Embedding(vector=np.array([0.1, 0.2, 0.3, 0.4], dtype="float32"))
    path = tmp_path / "voiceprint.enc"
    save_voiceprint(emb, path, cipher)
    loaded = load_voiceprint(path, cipher)
    assert loaded is not None
    assert np.allclose(loaded.vector, emb.vector)


def test_load_voiceprint_missing_is_none(tmp_path):
    import os

    from yazses.learning.crypto import Cipher
    from yazses.voiceprint.store import load_voiceprint

    assert load_voiceprint(tmp_path / "nope.enc", Cipher(os.urandom(32))) is None


# ---- enrollment flow -------------------------------------------------------

def test_enroll_records_then_embeds():
    from yazses.voiceprint.enroll import enroll

    captured = {}

    def fake_record(seconds, sr):
        captured["seconds"] = seconds
        return np.full(int(seconds * sr), 0.3, dtype="float32")

    class _FakeEmbedder:
        name = "fake"

        def embed(self, audio, sample_rate=16000):
            return Embedding(vector=np.array([float(audio.size), 1.0], dtype="float32"))

    emb = enroll(fake_record, _FakeEmbedder(), seconds=2.0, sample_rate=16000)
    assert captured["seconds"] == 2.0
    assert emb.vector[0] == 32000.0  # 2s * 16000


def test_enroll_rejects_empty_audio():
    import pytest

    from yazses.voiceprint.enroll import enroll

    class _E:
        name = "fake"

        def embed(self, audio, sample_rate=16000):
            return Embedding(vector=np.zeros(2, dtype="float32"))

    with pytest.raises(ValueError):
        enroll(lambda s, sr: np.array([], dtype="float32"), _E(), seconds=1.0)
