"""Slot-Filling Dictation (ADR-v2-063) + Few-Shot Command Spotter (ADR-v2-064) — pure cores."""
from __future__ import annotations

from yazses.cmdspotter.spotter import CommandSpotter, cosine
from yazses.slotfill.fill import Slot, fill_slots

SCHEMA = [
    Slot("title", after=("bug in", "issue in")),
    Slot("severity", choices=("low", "high", "critical")),
    Slot("browser", after=("affects", "browser")),
]


# ---- slot filling ----------------------------------------------------------

def test_fill_slots_keyword_and_choices():
    got = fill_slots("bug in login page, high priority, affects firefox", SCHEMA)
    assert got["title"] == "login"
    assert got["severity"] == "high"
    assert got["browser"] == "firefox"


def test_fill_slots_partial():
    got = fill_slots("critical outage somewhere", SCHEMA)
    assert got == {"severity": "critical"}   # only the enum matched


def test_fill_slots_none_match():
    assert fill_slots("nothing structured here", SCHEMA) == {}
    assert fill_slots("", SCHEMA) == {}


# ---- command spotter -------------------------------------------------------

def test_cosine():
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0     # zero vector guard


def test_spotter_matches_nearest_enrolled():
    s = CommandSpotter(threshold=0.9)
    s.enroll("send", [1.0, 0.0, 0.0])
    s.enroll("stop", [0.0, 1.0, 0.0])
    assert s.match([0.99, 0.01, 0.0]) == "send"
    assert s.match([0.0, 1.0, 0.0]) == "stop"
    assert set(s.labels()) == {"send", "stop"}


def test_spotter_below_threshold_is_none():
    s = CommandSpotter(threshold=0.9)
    s.enroll("send", [1.0, 0.0])
    assert s.match([0.0, 1.0]) is None       # orthogonal → below threshold


def test_spotter_empty_is_none():
    assert CommandSpotter().match([1.0, 2.0]) is None


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "slotfill" in slugs and "cmdspotter" in slugs
    assert Config().slotfill.enabled is False and Config().cmdspotter.enabled is False
