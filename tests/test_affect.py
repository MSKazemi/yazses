"""Tone-aware formatting (ADR-v2-017) — pure format_affect."""
from __future__ import annotations

from yazses.affect.format import format_affect


def test_excited_adds_exclamation():
    assert format_affect("this is great", "excited", 0.9) == "this is great!"


def test_excited_replaces_trailing_period():
    assert format_affect("we shipped it.", "excited", 0.9) == "we shipped it!"


def test_question_adds_question_mark():
    assert format_affect("are you sure", "question", 0.9) == "are you sure?"


def test_neutral_is_unchanged():
    assert format_affect("just a statement", "neutral", 0.9) == "just a statement"


def test_low_confidence_is_unchanged():
    assert format_affect("this is great", "excited", 0.2, min_confidence=0.6) == "this is great"


def test_existing_terminal_not_stacked():
    assert format_affect("wow!", "excited", 0.9) == "wow!"
    assert format_affect("really?", "question", 0.9) == "really?"


def test_conservative_mode_ignores_wider_labels():
    # 'angry' is only in the expressive table
    assert format_affect("stop that", "angry", 0.9, mode="conservative") == "stop that"


def test_expressive_mode_handles_wider_labels():
    assert format_affect("stop that", "angry", 0.9, mode="expressive") == "stop that!"


def test_trailing_whitespace_preserved():
    assert format_affect("hi there ", "excited", 0.9) == "hi there! "


def test_blank_is_safe():
    assert format_affect("", "excited", 0.9) == ""
    assert format_affect("   ", "excited", 0.9) == "   "


def test_feature_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    assert "affect" in [f.slug for f in feature_status(Config())]
