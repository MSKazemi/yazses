"""Chorded Shortcut Synthesis (ADR-v2-085) + Inline Compute (ADR-v2-086) — pure cores."""
from __future__ import annotations

from yazses.chords.parse import KeyChord, parse_chord, render_chord
from yazses.compute.evaluate import evaluate

# ---- chord synthesis -------------------------------------------------------

def test_parse_chord_modifiers():
    assert parse_chord("press control shift P") == [KeyChord(("ctrl", "shift"), "p")]
    assert parse_chord("command S") == [KeyChord(("super",), "s")]


def test_parse_chord_named_and_fkeys():
    assert parse_chord("hit F5") == [KeyChord((), "F5")]
    assert parse_chord("press page down") == [KeyChord((), "Next")]
    assert parse_chord("escape") == [KeyChord((), "Escape")]
    assert parse_chord("function 12") == [KeyChord((), "F12")]


def test_parse_chord_repeat():
    assert parse_chord("escape twice") == [KeyChord((), "Escape"), KeyChord((), "Escape")]
    assert len(parse_chord("press tab 3 times")) == 3


def test_parse_chord_dedup_and_none():
    assert parse_chord("control control a") == [KeyChord(("ctrl",), "a")]
    assert parse_chord("press the big red button") is None
    assert parse_chord("") is None


def test_render_chord():
    assert render_chord(KeyChord(("ctrl", "shift"), "p")) == "ctrl+shift+p"
    assert render_chord(KeyChord((), "F5")) == "F5"


# ---- inline compute --------------------------------------------------------

def test_evaluate_arithmetic():
    assert evaluate("what's 3 plus 4 times 2") == "11"      # precedence
    assert evaluate("10 minus 3") == "7"
    assert evaluate("compute 8 divided by 2") == "4"


def test_evaluate_percent():
    assert evaluate("what's 15% of 240") == "36"
    assert evaluate("15 percent of 240") == "36"
    assert evaluate("50% of 10") == "5"


def test_evaluate_fractional_and_none():
    assert evaluate("10 divided by 4") == "2.5"
    assert evaluate("hello world") is None                  # no expression
    assert evaluate("just 42") is None                      # no operator
    assert evaluate("5 divided by 0") is None               # zero division guarded


def test_evaluate_unary_minus():
    assert evaluate("minus 5 plus 8") == "3"       # exercises the unary-minus AST branch


def test_safe_eval_rejects_disallowed_nodes():
    import ast

    import pytest

    from yazses.compute.evaluate import _safe_eval
    with pytest.raises(ValueError):
        _safe_eval(ast.parse("'hi'", mode="eval"))       # non-numeric constant
    with pytest.raises(ValueError):
        _safe_eval(ast.parse("foo", mode="eval"))        # disallowed node (Name)


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "chords" in slugs and "compute" in slugs
    assert Config().chords.enabled is False and Config().compute.enabled is False
