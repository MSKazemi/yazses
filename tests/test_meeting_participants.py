"""Cross-meeting participant enrollment (fakes, no model/crypto) — ADR-v2-127 P5."""
from __future__ import annotations

import json

import numpy as np
import pytest

from yazses.config import MeetingConfig
from yazses.meeting import participants, store
from yazses.meeting.session import WavFileSink
from yazses.voiceprint.embedding import Embedding

SR = 1000


class _FakeEmbedder:
    def embed(self, audio, sample_rate=16000):
        # a deterministic direction so nearest_profile matches it later
        return Embedding(vector=np.array([1.0, 0.0], dtype="float32"))


class _IdentityCipher:
    def encrypt(self, b):
        return b

    def decrypt(self, b):
        return b


def _cfg(tmp_path):
    return MeetingConfig(
        output_dir=str(tmp_path / "meetings"),
        participants_dir=str(tmp_path / "participants"),
    )


def _stored_meeting(tmp_path, *, with_audio=True):
    cfg = _cfg(tmp_path)
    d = store.new_meeting(cfg, "m1")
    (d / "transcript.json").write_text(json.dumps({
        "text": "hello world",
        "language": "en",
        "diarized": True,
        "speakers": {"speaker_0": "Speaker 1", "speaker_1": "Speaker 2"},
        "words": [
            {"speaker": "speaker_0", "start": 0.0, "end": 2.0, "text": "hello"},
            {"speaker": "speaker_1", "start": 2.0, "end": 4.0, "text": "world"},
        ],
        "utterances": [
            {"speaker": "speaker_0", "start": 0.0, "end": 2.0, "text": "hello"},
            {"speaker": "speaker_1", "start": 2.0, "end": 4.0, "text": "world"},
        ],
    }), encoding="utf-8")
    if with_audio:
        sink = WavFileSink(d / "audio.wav", sample_rate=SR)
        sink.write(np.ones(4 * SR, dtype="float32"))
        sink.close()
    return cfg, d


def test_enroll_and_load_roundtrip(tmp_path):
    cfg, d = _stored_meeting(tmp_path)
    path = participants.enroll_participant(
        d, "speaker_0", "Alice",
        embedder=_FakeEmbedder(), cipher=_IdentityCipher(), config=cfg, sample_rate=SR,
    )
    assert path.exists()
    loaded = participants.load_participants(cfg, _IdentityCipher())
    assert "Alice" in loaded
    np.testing.assert_allclose(loaded["Alice"], [1.0, 0.0])


def test_enroll_requires_retained_audio(tmp_path):
    cfg, d = _stored_meeting(tmp_path, with_audio=False)
    with pytest.raises(FileNotFoundError):
        participants.enroll_participant(
            d, "speaker_0", "Alice",
            embedder=_FakeEmbedder(), cipher=_IdentityCipher(), config=cfg, sample_rate=SR,
        )


def test_enroll_rejects_unknown_speaker(tmp_path):
    cfg, d = _stored_meeting(tmp_path)
    with pytest.raises(ValueError):
        participants.enroll_participant(
            d, "speaker_9", "Ghost",
            embedder=_FakeEmbedder(), cipher=_IdentityCipher(), config=cfg, sample_rate=SR,
        )


def test_enroll_requires_a_name(tmp_path):
    cfg, d = _stored_meeting(tmp_path)
    with pytest.raises(ValueError):
        participants.enroll_participant(
            d, "speaker_0", "  ",
            embedder=_FakeEmbedder(), cipher=_IdentityCipher(), config=cfg, sample_rate=SR,
        )


def test_load_participants_empty_when_none(tmp_path):
    cfg = _cfg(tmp_path)
    assert participants.load_participants(cfg, _IdentityCipher()) == {}
