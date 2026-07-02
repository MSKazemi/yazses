"""Smart-Paste (ADR-v2-036) + Audio-Anchored Scrubbing (ADR-v2-037) — pure cores."""
from __future__ import annotations

import pytest

from yazses.scrub.index import TimedWord, find_word, range_bounds, slice_bounds
from yazses.smartpaste.adapt import adapt, classify_surface


# ---- smart-paste -----------------------------------------------------------

def test_classify_surface_by_app():
    assert classify_surface("Alacritty") == "terminal"
    assert classify_surface("VSCode") == "code"
    assert classify_surface("Thunderbird") == "email"
    assert classify_surface("Obsidian") == "markdown"


def test_classify_surface_role_fallback():
    assert classify_surface("SomeApp", "terminal") == "terminal"
    assert classify_surface("SomeApp", "document frame") == "rich"
    assert classify_surface("SomeApp", "") == "plain"


def test_adapt_markdown_bullet_and_url():
    assert adapt("* buy milk", "markdown") == "- buy milk"
    assert adapt("see https://x.com now", "markdown") == "see <https://x.com> now"


def test_adapt_code_and_terminal_untouched():
    assert adapt("* not a bullet", "code") == "* not a bullet"
    assert adapt("see https://x.com", "terminal") == "see https://x.com"


def test_adapt_empty():
    assert adapt("", "markdown") == ""


# ---- audio scrubbing -------------------------------------------------------

WORDS = [
    TimedWord("the", 0.0, 0.2),
    TimedWord("report", 0.2, 0.7),
    TimedWord("is", 0.7, 0.9),
    TimedWord("report", 0.9, 1.4),
]


def test_find_word_returns_last_match():
    assert find_word(WORDS, "report") == 3  # last occurrence
    assert find_word(WORDS, "Report.") == 3  # case/punct insensitive


def test_find_word_missing():
    assert find_word(WORDS, "missing") is None
    assert find_word(WORDS, "") is None


def test_slice_bounds():
    assert slice_bounds(WORDS, 1) == (0.2, 0.7)


def test_range_bounds_span_and_order():
    assert range_bounds(WORDS, 1, 3) == (0.2, 1.4)
    assert range_bounds(WORDS, 3, 1) == (0.2, 1.4)  # order-insensitive


def test_slice_bounds_out_of_range():
    with pytest.raises(IndexError):
        slice_bounds(WORDS, 99)


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "smartpaste" in slugs and "scrub" in slugs
    assert Config().smartpaste.enabled is False and Config().scrub.enabled is False
