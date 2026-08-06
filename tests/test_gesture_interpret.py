"""Gesture Chords (ADR-v2-043) + Two-Way Interpreter (ADR-v2-044) — pure cores."""
from __future__ import annotations

import pytest

from yazses.gesture.chords import normalize_chord, resolve_chord
from yazses.interpret.turns import parse_pair, route_turn

# ---- gesture chords --------------------------------------------------------

def test_normalize_chord_order_and_dedup():
    assert normalize_chord(["Nod", "hold"]) == "hold+nod"
    assert normalize_chord(["hold", "nod", "hold"]) == "hold+nod"
    assert normalize_chord([" hold ", "", None]) == "hold"


def test_resolve_chord_hit_and_miss():
    mapping = {"hold+nod": "send", "hold+squeeze": "undo"}
    assert resolve_chord(["hold", "nod"], mapping) == "send"
    assert resolve_chord(["nod", "hold"], mapping) == "send"  # order-independent
    assert resolve_chord(["hold"], mapping) is None


# ---- two-way interpreter ---------------------------------------------------

def test_parse_pair():
    assert parse_pair("en-es") == ("en", "es")
    assert parse_pair(" EN - FA ") == ("en", "fa")


def test_parse_pair_invalid():
    with pytest.raises(ValueError):
        parse_pair("en")
    with pytest.raises(ValueError):
        parse_pair("en-")


def test_route_turn_both_directions():
    assert route_turn("en", "en-es") == ("en", "es")
    assert route_turn("es", "en-es") == ("es", "en")


def test_route_turn_outside_pair_is_none():
    assert route_turn("fr", "en-es") is None
    assert route_turn("", "en-es") is None


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "gesture" in slugs and "interpret" in slugs
    assert Config().gesture.enabled is False and Config().interpret.enabled is False
