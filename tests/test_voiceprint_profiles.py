"""Multi-user voiceprint profile routing (ADR-v2-028) — pure nearest_profile."""
from __future__ import annotations

from yazses.voiceprint.profiles import nearest_profile

PROFILES = {
    "alice": [1.0, 0.0, 0.0],
    "bob": [0.0, 1.0, 0.0],
    "carol": [0.0, 0.0, 1.0],
}


def test_picks_nearest_profile():
    assert nearest_profile([0.9, 0.1, 0.0], PROFILES, min_similarity=0.5) == "alice"
    assert nearest_profile([0.1, 0.95, 0.05], PROFILES, min_similarity=0.5) == "bob"


def test_below_threshold_returns_none():
    # equidistant-ish / low similarity → keep default (None)
    assert nearest_profile([1.0, 1.0, 1.0], PROFILES, min_similarity=0.9) is None


def test_no_profiles_returns_none():
    assert nearest_profile([1.0, 0.0, 0.0], {}) is None


def test_zero_embedding_returns_none():
    assert nearest_profile([0.0, 0.0, 0.0], PROFILES) is None


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "multiprofile" in [f.slug for f in feature_status(Config())]
    assert Config().voiceprint.multi_profile is False
