"""Style-Consistency Enforcer (ADR-v2-109) + Suggestion-Mode Dictation (ADR-v2-113) — pure cores."""
from __future__ import annotations

from yazses.config import load_config
from yazses.styleguard.loader import build_style_rules, load_rules_file
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


# ---- style-rules.toml loader (ADR-v2-109) -----------------------------------

def test_load_rules_file_missing_file_is_empty(tmp_path):
    assert load_rules_file(tmp_path / "nope.toml") == []


def test_load_rules_file_none_path_is_empty():
    assert load_rules_file(None) == []


def test_load_rules_file_expands_preferred_variants(tmp_path):
    p = tmp_path / "style-rules.toml"
    p.write_text(
        '[[rule]]\npreferred = "e-mail"\nvariants = ["email", "e mail"]\n\n'
        '[[rule]]\npreferred = "cannot"\nvariants = ["can not"]\n'
    )
    rules = load_rules_file(p)
    out, changes = apply_style("Send an Email, an e mail, you can not skip it.", rules)
    assert out == "Send an e-mail, an e-mail, you cannot skip it."
    assert len(changes) == 3


def test_load_rules_file_regex_and_case_sensitivity(tmp_path):
    p = tmp_path / "style-rules.toml"
    p.write_text(
        '[[rule]]\npreferred = "U.S."\nvariants = ["US"]\nignore_case = false\n'
    )
    rules = load_rules_file(p)
    out, _ = apply_style("US and us", rules)
    assert out == "U.S. and us"


def test_load_rules_file_skips_invalid_entry_without_raising(tmp_path):
    p = tmp_path / "style-rules.toml"
    p.write_text(
        '[[rule]]\nvariants = ["no preferred"]\n\n'                # missing preferred
        '[[rule]]\npreferred = "no variants"\nvariants = []\n\n'   # empty variants
        '[[rule]]\npreferred = "e-mail"\nvariants = ["email"]\n'
    )
    rules = load_rules_file(p)
    out, changes = apply_style("Send an Email.", rules)
    assert out == "Send an e-mail."
    assert len(changes) == 1


def test_load_rules_file_unparseable_file_returns_empty(tmp_path):
    p = tmp_path / "style-rules.toml"
    p.write_text("this is = = not valid toml [[[")
    assert load_rules_file(p) == []


# ---- build_style_rules (config wiring) --------------------------------------

def test_build_style_rules_dormant_when_disabled(tmp_path):
    cfg = load_config()  # defaults: styleguard.enabled is False
    assert build_style_rules(cfg, tmp_path) is None


def test_build_style_rules_loads_when_enabled(tmp_path):
    (tmp_path / "style-rules.toml").write_text(
        '[[rule]]\npreferred = "e-mail"\nvariants = ["email"]\n'
    )
    cfg = load_config()
    cfg.styleguard.enabled = True
    rules = build_style_rules(cfg, tmp_path)
    assert rules is not None and len(rules) == 1


def test_config_styleguard_defaults_off():
    cfg = load_config()
    assert cfg.styleguard.enabled is False
    assert cfg.styleguard.path == "style-rules.toml"


def test_config_loads_styleguard_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[styleguard]\nenabled = true\npath = "house-style.toml"\n')
    cfg = load_config(p)
    assert cfg.styleguard.enabled is True
    assert cfg.styleguard.path == "house-style.toml"
