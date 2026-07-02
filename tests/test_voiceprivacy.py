"""Corpus Voiceprint Scrub (ADR-v2-048) — pure DSP anonymization + writer wiring."""
from __future__ import annotations

import numpy as np

from yazses.voiceprivacy.anonymize import anonymize_clip


def test_preserves_length_and_dtype():
    a = np.sin(np.linspace(0, 40, 800)).astype(np.float32)
    out = anonymize_clip(a, 16000, strength=1.08)
    assert out.shape == a.shape
    assert out.dtype == a.dtype


def test_changes_the_signal():
    a = np.sin(np.linspace(0, 40, 800)).astype(np.float32)
    out = anonymize_clip(a, 16000, strength=1.08)
    # anonymization must actually alter the waveform
    assert not np.allclose(out, a)


def test_identity_strength_and_empty_are_noops():
    a = np.sin(np.linspace(0, 10, 200)).astype(np.float32)
    assert np.allclose(anonymize_clip(a, 16000, strength=1.0), a)
    empty = np.zeros(0, dtype=np.float32)
    assert anonymize_clip(empty, 16000).shape == (0,)


def test_silence_stays_silent():
    z = np.zeros(400, dtype=np.float32)
    out = anonymize_clip(z, 16000, strength=1.1)
    assert np.allclose(out, 0.0)


def test_writer_anonymizes_before_store(tmp_path):
    # the CorpusWriter must run anonymize_clip on the audio before add_event
    from yazses.learning.capture import CorpusWriter

    captured = {}

    class _FakeStore:
        def add_event(self, event, audio, sample_rate):
            captured["audio"] = audio

        def close(self):
            pass

    a = np.sin(np.linspace(0, 40, 800)).astype(np.float32)
    w = CorpusWriter(_FakeStore(), (), anonymize_audio=True, anonymize_strength=1.08)
    w.write({"final_text": "hi"}, a, 16000)
    w.flush()
    w.stop()
    assert "audio" in captured
    assert not np.allclose(captured["audio"], a)  # was scrubbed


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "corpus_scrub" in [f.slug for f in feature_status(Config())]
    assert Config().learning.anonymize_audio is False
