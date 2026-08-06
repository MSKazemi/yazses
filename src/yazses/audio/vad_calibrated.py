"""VAD with configurable threshold from accessibility profile."""
from __future__ import annotations

import numpy as np

from yazses.config import AccessibilityConfig


def is_silent_calibrated(audio: np.ndarray, config: AccessibilityConfig) -> bool:
    """RMS-based silence detection using the user-calibrated threshold.

    Drop-in replacement for audio/vad.py:is_silent() that uses
    config.vad_threshold instead of the hardcoded default.
    """
    if audio.size == 0:
        return True
    return bool(np.abs(audio).mean() < config.vad_threshold)


def trailing_energy_falling(
    audio: np.ndarray,
    config: AccessibilityConfig,
    window_ms: int = 250,
    sample_rate: int = 16000,
) -> bool:
    """True when the trailing ``window_ms`` of audio is decaying in amplitude.

    A cheap "speaker is trailing off" signal for Ghost Ahead endpoint anticipation
    (spec-ghost-ahead): split the trailing window into two halves and report
    whether the second half is quieter than the first (``mean(|audio|)`` falling).
    Uses the same metric as the calibrated VAD gate. Returns False on empty or
    too-short audio. Pure, deterministic, no model.
    """
    n = int(window_ms / 1000.0 * sample_rate)
    if audio.size == 0 or n < 2:
        return False
    window = audio[-n:]
    half = window.size // 2
    if half == 0:
        return False
    first = float(np.abs(window[:half]).mean())
    second = float(np.abs(window[half:]).mean())
    return second < first
