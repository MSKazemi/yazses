"""Compose-in-Target-Language (ADR-v2-049) + Grammar Repair (ADR-v2-050) — pure cores."""
from __future__ import annotations

from yazses.compose.route import compose_route, is_plausible
from yazses.gec.guard import fix_articles, is_minimal_edit

# ---- compose ---------------------------------------------------------------

def test_compose_route_valid_and_same():
    assert compose_route("fa", "en") == ("fa", "en")
    assert compose_route("EN", "en") is None       # same language
    assert compose_route("", "en") is None          # blank source


def test_is_plausible_bounds():
    assert is_plausible("hola mundo", "hello world") is True
    assert is_plausible("hi", "x" * 100) is False   # too long
    assert is_plausible("a long source sentence", "x") is False  # too short


def test_is_plausible_empty():
    assert is_plausible("", "anything") is False
    assert is_plausible("something", "") is False


# ---- grammar repair --------------------------------------------------------

def test_is_minimal_edit_accepts_small_fix():
    assert is_minimal_edit("i go to meeting", "i went to the meeting") is True


def test_is_minimal_edit_rejects_paraphrase():
    assert is_minimal_edit(
        "i go to meeting", "yesterday afternoon we all attended a lengthy corporate session"
    ) is False


def test_is_minimal_edit_empty():
    assert is_minimal_edit("", "") is True
    assert is_minimal_edit("", "text") is False


def test_fix_articles_basic():
    assert fix_articles("a apple") == "an apple"
    assert fix_articles("an dog") == "a dog"


def test_fix_articles_sound_exceptions():
    assert fix_articles("a hour") == "an hour"          # vowel sound, consonant letter
    assert fix_articles("an university") == "a university"  # consonant sound, vowel letter


def test_fix_articles_preserves_capitalization():
    assert fix_articles("An dog barked") == "A dog barked"


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "compose" in slugs and "gec" in slugs
    assert Config().compose.enabled is False and Config().gec.enabled is False
