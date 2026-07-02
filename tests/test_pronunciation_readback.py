"""Pronunciation Feedback (ADR-v2-041) + Personal Read-Back Voice (ADR-v2-042) — pure cores."""
from __future__ import annotations

from yazses.config import PronunciationConfig, TtsConfig
from yazses.pronunciation.score import PhonemeScore, classify, overall_score, problem_phonemes
from yazses.readback.clone import clone_ready, select_clone_backend


# ---- pronunciation ---------------------------------------------------------

def test_classify_bands():
    assert classify(0.9) == "good"
    assert classify(0.5) == "fair"
    assert classify(0.2) == "poor"


def test_overall_score_mean_and_empty():
    scores = [PhonemeScore("th", 0.8), PhonemeScore("r", 0.4)]
    assert round(overall_score(scores), 6) == 0.6
    assert overall_score([]) == 0.0


def test_problem_phonemes_below_poor_threshold():
    cfg = PronunciationConfig()
    scores = [PhonemeScore("th", 0.8), PhonemeScore("r", 0.3), PhonemeScore("l", 0.2)]
    assert problem_phonemes(scores, cfg) == ["r", "l"]


# ---- personal read-back ----------------------------------------------------

def test_clone_ready():
    assert clone_ready(5.0) is True
    assert clone_ready(1.0) is False
    assert clone_ready(3.0) is True  # boundary inclusive


def test_select_clone_backend_default_permissive():
    assert select_clone_backend(TtsConfig()) == "openvoice"


def test_select_clone_backend_known_and_unknown():
    assert select_clone_backend(TtsConfig(clone_backend="f5")) == "f5"
    assert select_clone_backend(TtsConfig(clone_backend="xtts")) == "xtts"
    # unknown / empty never silently picks a non-commercial engine
    assert select_clone_backend(TtsConfig(clone_backend="bogus")) == "openvoice"
    assert select_clone_backend(TtsConfig(clone_backend="")) == "openvoice"


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "pronunciation" in slugs and "readback_clone" in slugs
    assert Config().pronunciation.enabled is False and Config().tts.clone_voice is False
