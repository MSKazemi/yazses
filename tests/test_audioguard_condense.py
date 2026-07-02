"""Ambient Audio-Event Guard (ADR-v2-061) + On-Device Condense (ADR-v2-062) — pure cores."""
from __future__ import annotations

from yazses.audioguard.policy import EventDebouncer, event_policy
from yazses.condense.extract import condense


# ---- audio-event guard -----------------------------------------------------

def test_event_policy():
    assert event_policy("doorbell") == "pause"
    assert event_policy("alarm") == "pause"
    assert event_policy("knock") == "notify"
    assert event_policy("wind") == "ignore"
    assert event_policy("") == "ignore"


def test_debouncer_fires_once_then_suppresses():
    d = EventDebouncer(cooldown_frames=3)
    assert d.fire("doorbell") == "pause"   # first → fires
    assert d.fire("doorbell") is None      # same label, cooling down
    d.tick(); d.tick(); d.tick()           # cooldown elapses
    assert d.fire("doorbell") == "pause"   # fires again


def test_debouncer_ignores_non_actionable():
    d = EventDebouncer()
    assert d.fire("wind") is None          # ignored label never fires


def test_debouncer_different_label_fires_immediately():
    d = EventDebouncer(cooldown_frames=10)
    assert d.fire("doorbell") == "pause"
    assert d.fire("alarm") == "pause"      # a different actionable label isn't suppressed


# ---- condense --------------------------------------------------------------

def test_condense_picks_informative_sentences():
    text = (
        "The migration project is the top priority this quarter. "
        "It was a nice day. "
        "The migration project needs the database migration finished first."
    )
    out = condense(text, max_sentences=2)
    # the two migration-heavy sentences win over the filler one
    assert "It was a nice day." not in out
    assert out.count("migration") >= 2


def test_condense_preserves_original_order():
    text = "Alpha beta alpha. Gamma. Alpha beta gamma alpha."
    out = condense(text, max_sentences=2)
    assert out == "Alpha beta alpha. Alpha beta gamma alpha."


def test_condense_short_text_unchanged():
    assert condense("Just one sentence.", max_sentences=2) == "Just one sentence."
    assert condense("", max_sentences=2) == ""


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "audioguard" in slugs and "condense" in slugs
    assert Config().audioguard.enabled is False and Config().condense.enabled is False
