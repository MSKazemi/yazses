"""Beam-Steered Spatial VAD (ADR-v2-098) + Prosodic Auto-Punctuation (ADR-v2-104) — pure cores."""
from __future__ import annotations

import numpy as np

from yazses.prosodypunct.punctuate import punctuate_from_prosody
from yazses.spatialvad.beam import gcc_phat, spatial_gate, tdoa_to_angle


# ---- spatial VAD -----------------------------------------------------------

def test_gcc_phat_recovers_known_delay():
    fs = 16000
    rng = np.arange(400)
    base = np.sin(2 * np.pi * 500 * rng / fs)
    shift = 5                                   # samples: right lags left by 5
    left = np.zeros(420)
    right = np.zeros(420)
    left[:400] = base
    right[shift:shift + 400] = base
    tau = gcc_phat(left, right, fs=fs, max_tau=0.01)
    assert abs(tau - (-shift / fs)) < 1.5 / fs   # left leads → negative tau, within ~1 sample


def test_tdoa_to_angle_and_gate():
    assert tdoa_to_angle(0.0) == 0.0
    assert tdoa_to_angle(1.0, mic_distance_m=0.0) == 0.0        # guard
    # a large tau saturates to ±90°
    assert abs(tdoa_to_angle(1.0, mic_distance_m=0.14)) == 90.0
    assert spatial_gate(10.0, target_angle=0.0, tolerance_deg=35.0) is True
    assert spatial_gate(70.0, target_angle=0.0, tolerance_deg=35.0) is False


# ---- prosodic punctuation --------------------------------------------------

def test_punctuate_sentence_comma_question():
    tokens = ["hello", "there", "how", "are", "you"]
    pauses = [300, 800, 0, 0, 900]              # comma after "hello", period after "there", ? after "you"
    rise = [False, False, False, False, True]
    text = punctuate_from_prosody(tokens, pauses, terminal_rise=rise)
    assert text == "hello, there. how are you?"


def test_punctuate_pitch_reset_boundary():
    tokens = ["done", "next"]
    pauses = [300, 0]                           # short pause but a pitch reset → sentence boundary
    resets = [0.9, 0.0]
    assert punctuate_from_prosody(tokens, pauses, pitch_reset=resets) == "done. next"


def test_punctuate_no_cues_and_short_lists():
    assert punctuate_from_prosody(["a", "b"], [0, 0]) == "a b"
    assert punctuate_from_prosody([], []) == ""
    assert punctuate_from_prosody(["a", "b", "c"], [900]) == "a. b c"   # missing pauses default 0


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "spatialvad" in slugs and "prosodypunct" in slugs
    assert Config().spatialvad.enabled is False and Config().prosodypunct.enabled is False
