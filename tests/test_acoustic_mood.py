"""Acoustic Context Profiles (ADR-v2-039) + Mood Ledger (ADR-v2-040) — pure cores."""
from __future__ import annotations

from yazses.acoustic.profiles import policy_for, should_switch
from yazses.mood.ledger import aggregate, dominant_mood, mood_shift

# ---- acoustic profiles -----------------------------------------------------

def test_policy_for_known_scenes():
    assert policy_for("cafe").denoise is True
    assert policy_for("quiet").denoise is False
    assert policy_for("car").vad_threshold >= policy_for("quiet").vad_threshold


def test_policy_for_unknown_defaults_quiet():
    assert policy_for("spaceship").scene == "quiet"
    assert policy_for("").scene == "quiet"


def test_should_switch_hysteresis():
    assert should_switch("cafe", "quiet", stable_count=3, min_stable=3) is True
    assert should_switch("cafe", "quiet", stable_count=2, min_stable=3) is False


def test_should_switch_same_scene_never():
    assert should_switch("cafe", "cafe", stable_count=99) is False


# ---- mood ledger -----------------------------------------------------------

def test_aggregate_counts():
    assert aggregate(["happy", "Happy", "sad", ""]) == {"happy": 2, "sad": 1}


def test_dominant_mood():
    assert dominant_mood(["neutral", "happy", "happy"]) == "happy"


def test_dominant_mood_empty():
    assert dominant_mood([]) is None
    assert dominant_mood(["", "   "]) is None


def test_mood_shift_improved_declined_stable():
    assert mood_shift(["sad", "sad"], ["happy"]) == "improved"
    assert mood_shift(["happy"], ["angry", "angry"]) == "declined"
    assert mood_shift(["neutral"], ["neutral"]) == "stable"


def test_mood_shift_unknown_on_empty():
    assert mood_shift([], ["happy"]) == "unknown"


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "acoustic_profiles" in slugs and "sentiment" in slugs
    assert Config().acoustic_profiles.enabled is False and Config().sentiment.enabled is False
