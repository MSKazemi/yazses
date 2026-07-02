"""Accessibility Continuum — Whisper/Low-Effort Mode (ADR-v2-012) — pure threshold."""
from __future__ import annotations

from dataclasses import dataclass

from yazses.continuum.whisper_mode import effective_vad_threshold


@dataclass
class _Cfg:
    enabled: bool = False
    whisper_mode: bool = False
    whisper_threshold_factor: float = 0.4


def test_disabled_returns_base_threshold():
    assert effective_vad_threshold(0.01, _Cfg()) == 0.01
    # enabled but whisper_mode off → unchanged
    assert effective_vad_threshold(0.01, _Cfg(enabled=True)) == 0.01


def test_whisper_mode_scales_threshold_down():
    eff = effective_vad_threshold(0.01, _Cfg(enabled=True, whisper_mode=True, whisper_threshold_factor=0.4))
    assert abs(eff - 0.004) < 1e-9


def test_factor_is_clamped():
    # factor > 1 clamps to 1.0 (never raises the gate)
    hi = effective_vad_threshold(0.02, _Cfg(enabled=True, whisper_mode=True, whisper_threshold_factor=5.0))
    assert hi == 0.02
    # factor <= 0 clamps to a small positive floor (never zeroes the gate)
    lo = effective_vad_threshold(0.02, _Cfg(enabled=True, whisper_mode=True, whisper_threshold_factor=0.0))
    assert lo == 0.02 * 0.01


def test_feature_registered_and_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "continuum" in slugs
