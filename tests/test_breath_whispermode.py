"""Breath-Paced Dictation (ADR-v2-099) + Whisper-Aware Mode (ADR-v2-100) — pure cores."""
from __future__ import annotations

import numpy as np

from yazses.breath.segment import breath_envelope, detect_breath_onsets, segment_by_breath
from yazses.whispermode.detect import is_whispered, spectral_tilt, voicing_ratio, whisper_adaptation


# ---- breath-paced dictation ------------------------------------------------

def test_breath_envelope_smooths():
    env = breath_envelope([1, -1, 1, -1, 1, -1], fs=100, smooth_s=0.03)
    assert env.shape[0] == 6
    assert (env >= 0).all()                         # rectified
    assert breath_envelope([], fs=100).shape[0] == 0


def test_detect_breath_onsets():
    fs = 100
    env = np.zeros(400)
    env[50] = 1.0                                    # burst at 0.5 s
    env[250] = 1.0                                   # burst at 2.5 s
    onsets = detect_breath_onsets(env, fs=fs, min_gap_s=1.0, rel_threshold=0.6)
    assert onsets == [0.5, 2.5]
    assert detect_breath_onsets([], fs=fs) == []
    assert detect_breath_onsets(np.zeros(10), fs=fs) == []   # flat → no onsets


def test_segment_by_breath():
    tokens = ["the", "cat", "sat", "on", "the", "mat"]
    times = [0.0, 0.2, 0.4, 1.6, 1.8, 2.0]
    groups = segment_by_breath(tokens, times, breath_onsets=[1.5])
    assert groups == ["the cat sat", "on the mat"]
    assert segment_by_breath([], [], []) == []
    assert segment_by_breath(["a", "b"], [0.0, 0.1], []) == ["a b"]   # no breaths → one group


# ---- whisper-aware mode ----------------------------------------------------

def test_voicing_ratio_voiced_vs_noise():
    fs = 16000
    t = np.arange(1600) / fs
    voiced = np.sin(2 * np.pi * 150 * t)             # periodic → high voicing
    rng = np.linspace(-1, 1, 1600)
    noise = np.sin(1000 * rng * rng)                 # aperiodic-ish → low voicing
    assert voicing_ratio(voiced) > voicing_ratio(noise)
    assert voicing_ratio([1.0]) == 0.0               # too short
    assert voicing_ratio([2.0, 2.0, 2.0]) == 0.0     # zero-variance → ac[0]==0


def test_spectral_tilt_and_is_whispered():
    fs = 16000
    tilt_flat = spectral_tilt(np.ones(64), fs)       # trivial spectrum
    assert isinstance(tilt_flat, float)
    assert spectral_tilt([1, 2], fs) == 0.0          # too short
    assert is_whispered({"voicing": 0.1, "tilt": -0.5}) is True
    assert is_whispered({"voicing": 0.9, "tilt": -0.5}) is False   # voiced
    assert is_whispered({"voicing": 0.1, "tilt": -3.0}) is False   # steep tilt → not whisper


def test_whisper_adaptation():
    adj = whisper_adaptation()
    assert adj["gain_db"] == 6.0 and adj["vad_scale"] == 0.5
    assert "whisper" in adj["prompt_hint"]


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "breath" in slugs and "whispermode" in slugs
    assert Config().breath.enabled is False and Config().whispermode.enabled is False
