"""Wake-Word Activation (ADR-v2-033) + Vocal-Strain Guard (ADR-v2-034) — pure cores."""
from __future__ import annotations

from dataclasses import dataclass

from yazses.voicehealth.strain import should_suggest_break, strain_level
from yazses.wakeword.detector import should_activate


# ---- wake-word -------------------------------------------------------------

@dataclass
class _WwCfg:
    enabled: bool = True
    keyword: str = "hey yaz"
    threshold: float = 0.5
    cooldown_ms: int = 2000


def test_disabled_never_activates():
    assert should_activate(0.99, 9999, _WwCfg(enabled=False)) is False


def test_activates_on_score_and_cooldown():
    assert should_activate(0.8, 3000, _WwCfg()) is True


def test_below_threshold_no_activation():
    assert should_activate(0.3, 3000, _WwCfg()) is False


def test_within_cooldown_debounced():
    assert should_activate(0.9, 500, _WwCfg(cooldown_ms=2000)) is False


# ---- vocal-strain ----------------------------------------------------------

@dataclass
class _VhCfg:
    enabled: bool = True
    threshold: float = 0.6
    min_samples: int = 5


def test_strain_level_healthy_low():
    assert strain_level(0.0, 0.0, 25.0) == 0.0


def test_strain_level_high():
    # high jitter/shimmer, low HNR → near 1.0
    assert strain_level(0.05, 0.2, 0.0) == 1.0


def test_strain_level_midrange_bounded():
    v = strain_level(0.01, 0.05, 10.0)
    assert 0.0 < v < 1.0


def test_break_suggested_when_trend_high():
    assert should_suggest_break([0.7, 0.8, 0.9, 0.7, 0.8], _VhCfg()) is True


def test_no_break_when_below_threshold():
    assert should_suggest_break([0.1, 0.2, 0.1, 0.2, 0.1], _VhCfg()) is False


def test_no_break_when_too_few_samples():
    assert should_suggest_break([0.9, 0.9], _VhCfg(min_samples=5)) is False


def test_disabled_never_suggests():
    assert should_suggest_break([0.9] * 10, _VhCfg(enabled=False)) is False


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "wakeword" in slugs and "voicehealth" in slugs
    assert Config().wakeword.enabled is False and Config().voicehealth.enabled is False
