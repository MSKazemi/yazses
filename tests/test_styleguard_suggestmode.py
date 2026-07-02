"""Style-Consistency Enforcer (ADR-v2-109) + Suggestion-Mode Dictation (ADR-v2-113) — pure cores."""
from __future__ import annotations

from yazses.styleguard.rules import Change, apply_style, load_stylerules
from yazses.suggestmode.critic import diff_to_critic, to_criticmarkup


# ---- style-consistency enforcer --------------------------------------------

def test_load_and_apply_word_rules():
    rules = load_stylerules([
        {"pattern": "email", "replacement": "e-mail"},
        {"pattern": "can not", "replacement": "cannot"},
    ])
    out, changes = apply_style("Send an Email; you can not skip it.", rules)
    assert out == "Send an e-mail; you cannot skip it."
    assert Change("Email", "e-mail") in changes
    assert len(changes) == 2


def test_apply_regex_rule_and_case_sensitivity():
    rules = load_stylerules([{"pattern": r"\d{4}", "replacement": "YEAR", "regex": True}])
    out, _ = apply_style("in 2026 and 2027", rules)
    assert out == "in YEAR and YEAR"
    cs = load_stylerules([{"pattern": "US", "replacement": "U.S.", "ignore_case": False}])
    out2, _ = apply_style("US and us", cs)
    assert out2 == "U.S. and us"                 # only the uppercase token changes


def test_apply_style_no_rules():
    assert apply_style("unchanged", []) == ("unchanged", [])
    assert apply_style("", None) == ("", [])


# ---- suggestion-mode dictation ---------------------------------------------

def test_to_criticmarkup():
    assert to_criticmarkup("insert", text="new") == "{++new++}"
    assert to_criticmarkup("delete", text="old") == "{--old--}"
    assert to_criticmarkup("substitute", old="a", new="b") == "{~~a~>b~~}"
    assert to_criticmarkup("comment", text="fix this") == "{>>fix this<<}"
    assert to_criticmarkup("unknown", text="x") == "x"


def test_diff_to_critic():
    assert diff_to_critic("the cat sat", "the cat sat") == "the cat sat"
    assert diff_to_critic("the cat sat", "the dog sat") == "the {~~cat~>dog~~} sat"
    assert diff_to_critic("the cat", "the cat too") == "the cat {++too++}"
    assert diff_to_critic("the old cat", "the cat") == "the {--old--} cat"


def test_features_registered_off_by_default():
    from yazses.config import Config
    from yazses.system.features import feature_status
    slugs = [f.slug for f in feature_status(Config())]
    assert "styleguard" in slugs and "suggestmode" in slugs
    assert Config().styleguard.enabled is False and Config().suggestmode.enabled is False
