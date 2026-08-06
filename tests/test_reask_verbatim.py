"""Confidence-Gated Re-Ask (ADR-v2-077) + Verbatim⇄Autoformat Toggle (ADR-v2-078) — pure cores."""
from __future__ import annotations

from yazses.reask.confidence import Span, confusion_set, low_confidence_spans, parse_choice
from yazses.verbatim.gate import VerbatimGate, detect_mode_command

# ---- confidence re-ask -----------------------------------------------------

def test_low_confidence_spans_groups_runs():
    tokens = ["the", "cat", "sat", "on", "mat"]
    logprobs = [-0.1, -2.0, -1.5, -0.2, -0.3]
    spans = low_confidence_spans(tokens, logprobs, threshold=-1.0)
    assert spans == [Span(1, 3, "cat sat")]


def test_low_confidence_none_below():
    spans = low_confidence_spans(["a", "b"], [-0.1, -0.2], threshold=-1.0)
    assert spans == []


def test_confusion_set():
    assert set(confusion_set("their")) == {"their", "there", "they're"}
    assert set(confusion_set("There.")) == {"their", "there", "they're"}
    assert confusion_set("elephant") == []


def test_parse_choice_ordinal_and_literal():
    opts = ["their", "there", "they're"]
    assert parse_choice("the second one", opts) == "there"
    assert parse_choice("there", opts) == "there"
    assert parse_choice("option three", opts) == "they're"
    assert parse_choice("none of those", opts) is None


# ---- verbatim toggle -------------------------------------------------------

def test_detect_mode_command():
    assert detect_mode_command("dictate verbatim please") == "verbatim"
    assert detect_mode_command("resume formatting") == "auto"
    assert detect_mode_command("hello world") is None


def test_gate_transitions():
    g = VerbatimGate()
    assert g.is_verbatim() is False        # default auto
    assert g.handle_command("literal mode") is True
    assert g.is_verbatim() is True and g.mode == "verbatim"
    assert g.handle_command("resume formatting") is True
    assert g.is_verbatim() is False
    assert g.handle_command("just some words") is False   # not a mode command


def test_gate_initial_verbatim():
    assert VerbatimGate(mode="verbatim").is_verbatim() is True


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "reask" in slugs and "verbatim" in slugs
    assert Config().reask.enabled is False and Config().verbatim.enabled is False
