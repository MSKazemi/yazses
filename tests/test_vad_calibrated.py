"""Tests for is_silent_calibrated()."""
from __future__ import annotations

import numpy as np

from yazses.audio.vad_calibrated import is_silent_calibrated
from yazses.config import AccessibilityConfig


def test_empty_audio_is_silent():
    config = AccessibilityConfig(vad_threshold=0.01)
    assert is_silent_calibrated(np.array([], dtype=np.float32), config) is True


def test_zero_audio_is_silent():
    config = AccessibilityConfig(vad_threshold=0.01)
    audio = np.zeros(16000, dtype=np.float32)
    assert is_silent_calibrated(audio, config) is True


def test_loud_audio_is_not_silent():
    config = AccessibilityConfig(vad_threshold=0.01)
    audio = np.ones(16000, dtype=np.float32) * 0.5  # RMS = 0.5 >> threshold
    assert is_silent_calibrated(audio, config) is False


def test_below_threshold_is_silent():
    config = AccessibilityConfig(vad_threshold=0.05)
    audio = np.ones(16000, dtype=np.float32) * 0.02  # RMS = 0.02 < 0.05
    assert is_silent_calibrated(audio, config) is True


def test_above_threshold_is_not_silent():
    config = AccessibilityConfig(vad_threshold=0.005)
    audio = np.ones(16000, dtype=np.float32) * 0.01  # RMS = 0.01 > 0.005
    assert is_silent_calibrated(audio, config) is False


def test_high_threshold_passes_all_but_silence():
    """With high threshold, even moderate audio appears silent."""
    config = AccessibilityConfig(vad_threshold=0.5)
    audio = np.ones(16000, dtype=np.float32) * 0.1
    assert is_silent_calibrated(audio, config) is True
