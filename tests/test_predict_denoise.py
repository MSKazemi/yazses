"""Predictive completion (ADR-v2-016) + noise-suppression front-end (ADR-v2-015)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from yazses.denoise.frontend import apply_denoise
from yazses.predict.complete import merge_completion, parse_accept


# ---- predictive completion -------------------------------------------------

def test_parse_accept_variants():
    assert parse_accept("accept") == "accept"
    assert parse_accept("Take it.") == "accept"
    assert parse_accept("no") == "decline"
    assert parse_accept("discard") == "decline"


def test_parse_accept_ordinary_speech_is_none():
    assert parse_accept("the quick brown fox") is None
    assert parse_accept("") is None


def test_merge_completion_appends_with_space():
    assert merge_completion("the meeting is", "at three pm") == "the meeting is at three pm"


def test_merge_completion_dedupes_overlap():
    # buffer already ends with the suggestion's leading words
    assert merge_completion("send the report to", "to the team") == "send the report to the team"


def test_merge_completion_empty_cases():
    assert merge_completion("hello", "") == "hello"
    assert merge_completion("", "world") == "world"


def test_merge_completion_case_insensitive_overlap():
    assert merge_completion("Go To The", "the store now") == "Go To The store now"


# ---- denoise passthrough ---------------------------------------------------

@dataclass
class _DnCfg:
    enabled: bool = False
    backend: str = "deepfilternet"
    strength: float = 1.0


def test_denoise_off_is_identity():
    audio = np.array([0.1, -0.2, 0.3], dtype=np.float32)
    out = apply_denoise(audio, _DnCfg(enabled=False))
    assert out is audio  # exact same object → true passthrough


def test_denoise_backend_none_is_identity():
    audio = np.zeros(4, dtype=np.float32)
    assert apply_denoise(audio, _DnCfg(enabled=True, backend="none")) is audio


def test_denoise_missing_backend_falls_back_to_input():
    # enabled + deepfilternet but the extra isn't installed → passthrough, no raise
    audio = np.ones(8, dtype=np.float32)
    out = apply_denoise(audio, _DnCfg(enabled=True, backend="deepfilternet"))
    assert np.array_equal(out, audio)


def test_features_registered():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "denoise" in slugs and "predict" in slugs
