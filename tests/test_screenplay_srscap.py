"""Screenplay Auto-Format (ADR-v2-110) + Spoken Spaced-Repetition Capture (ADR-v2-112) — pure cores."""
from __future__ import annotations

from yazses.screenplay.fountain import smart_quote_dialogue, to_fountain
from yazses.srscap.cards import Sm2State, detect_fact, sm2_schedule, to_cloze


# ---- screenplay auto-format ------------------------------------------------

def test_to_fountain_scene_and_transition():
    assert to_fountain("scene: interior coffee shop, day") == "INT. COFFEE SHOP - DAY"
    assert to_fountain("scene: exterior street") == "EXT. STREET - DAY"       # default time
    assert to_fountain("transition: cut to") == "CUT TO:"


def test_to_fountain_character_and_action():
    assert to_fountain("Maya (character) where were you") == "MAYA\nwhere were you"
    assert to_fountain("Maya (character)") == "MAYA"                          # cue only
    assert to_fountain("She walks in slowly.") == "She walks in slowly."      # action line


def test_smart_quote_dialogue():
    assert smart_quote_dialogue('say "hello"') == "say “hello”"
    assert smart_quote_dialogue("quote hello unquote") == "“hello”"


# ---- spoken spaced-repetition capture --------------------------------------

def test_detect_fact():
    f = detect_fact("remember that the capital of France is Paris")
    assert f.subject == "the capital of France" and f.predicate == "is" and f.value == "Paris"
    assert detect_fact("just some words") is None
    assert detect_fact("remember that stuff") is None                          # no is/means


def test_to_cloze():
    f = detect_fact("note that HTTP means HyperText Transfer Protocol")
    card = to_cloze(f)
    assert card.cloze == "HTTP means {{c1::HyperText Transfer Protocol}}"
    assert card.back == "HyperText Transfer Protocol"
    assert card.front.endswith("...")


def test_sm2_schedule():
    s = Sm2State()
    s1 = sm2_schedule(s, 5)
    assert s1.reps == 1 and s1.interval == 1
    s2 = sm2_schedule(s1, 5)
    assert s2.reps == 2 and s2.interval == 6
    s3 = sm2_schedule(s2, 4)
    assert s3.reps == 3 and s3.interval > 6           # interval grows by ease
    lapse = sm2_schedule(s3, 1)                        # grade < 3 → lapse
    assert lapse.reps == 0 and lapse.interval == 1


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "screenplay" in slugs and "srscap" in slugs
    assert Config().screenplay.enabled is False and Config().srscap.enabled is False
