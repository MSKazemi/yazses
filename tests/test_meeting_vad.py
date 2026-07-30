"""Meeting-mode VAD backend selection + graceful fallback — ADR-v2-127 (P4)."""
from __future__ import annotations

import numpy as np

from yazses.config import AccessibilityConfig, MeetingConfig
from yazses.meeting import vad

ACC = AccessibilityConfig(vad_threshold=0.01)


def test_default_backend_is_calibrated():
    is_silent = vad.build_is_silent(MeetingConfig(), ACC)
    assert is_silent(np.zeros(1000, dtype="float32")) is True
    assert is_silent(np.ones(1000, dtype="float32")) is False


def test_silero_selected_when_available(monkeypatch):
    sentinel = lambda chunk: "sentinel-result"
    monkeypatch.setattr(vad, "_build_silero", lambda config: sentinel)
    is_silent = vad.build_is_silent(MeetingConfig(vad_backend="silero"), ACC)
    assert is_silent is sentinel


def test_silero_missing_falls_back_to_calibrated(monkeypatch):
    def boom(config):
        raise ImportError("no silero-vad")

    monkeypatch.setattr(vad, "_build_silero", boom)
    is_silent = vad.build_is_silent(MeetingConfig(vad_backend="silero"), ACC)
    # behaves like the calibrated gate
    assert is_silent(np.zeros(1000, dtype="float32")) is True
    assert is_silent(np.ones(1000, dtype="float32")) is False


def test_silero_none_falls_back_to_calibrated(monkeypatch):
    monkeypatch.setattr(vad, "_build_silero", lambda config: None)
    is_silent = vad.build_is_silent(MeetingConfig(vad_backend="silero"), ACC)
    assert is_silent(np.zeros(1000, dtype="float32")) is True
