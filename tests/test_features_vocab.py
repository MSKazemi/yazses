"""Capabilities table + personal dictionary (vocabulary) management."""
from __future__ import annotations

from yazses.config import Config, load_config
from yazses.system.configedit import set_config_key
from yazses.system.features import (
    feature_status,
    find_feature,
    toggleable_slugs,
)
from yazses.system.vocabulary import add_vocab, load_vocab, remove_vocab, vocab_path

# ---- feature_status: capabilities on/off ----------------------------------

def _by_name(features):
    return {f.name: f.on for f in features}


def test_defaults_mostly_off_core_on():
    feats = _by_name(feature_status(Config()))
    assert feats["Dictation core"] is True
    assert feats["Voice commands"] is True           # on by default
    assert feats["Cocktail Filter (voice focus)"] is False
    assert feats["Glance-Type (camera)"] is False
    assert feats["Read-Back Loop"] is False


def test_enabling_a_feature_reflects_in_status():
    cfg = Config()
    cfg.cocktail.enabled = True
    cfg.gaze.enabled = True
    feats = _by_name(feature_status(cfg))
    assert feats["Cocktail Filter (voice focus)"] is True
    assert feats["Glance-Type (camera)"] is True


def test_read_back_needs_both_tts_and_mode():
    cfg = Config()
    cfg.tts.enabled = True
    cfg.accessibility.read_back = "off"
    assert _by_name(feature_status(cfg))["Read-Back Loop"] is False
    cfg.accessibility.read_back = "final"
    assert _by_name(feature_status(cfg))["Read-Back Loop"] is True


# ---- feature toggles: enable/disable write the right config ----------------

def _apply(config_file, writes):
    for section, key, value, quote in writes:
        set_config_key(config_file, section, key, value, quote=quote)


def test_toggle_names_are_unique_and_nonempty():
    slugs = toggleable_slugs()
    assert slugs                       # there are toggleable features
    assert len(slugs) == len(set(slugs))
    assert "cocktail" in slugs
    assert "dysfluency" in slugs


def test_core_feature_is_not_toggleable():
    core = next(f for f in feature_status(Config()) if f.name == "Dictation core")
    assert core.toggleable is False


def test_enable_then_disable_a_simple_boolean(tmp_path):
    cfg_file = tmp_path / "config.toml"
    feat = find_feature(Config(), "punch-in")
    _apply(cfg_file, feat.on_writes)
    assert load_config(cfg_file).punch_in.enabled is True
    _apply(cfg_file, feat.off_writes)
    assert load_config(cfg_file).punch_in.enabled is False


def test_enable_read_back_sets_both_keys(tmp_path):
    cfg_file = tmp_path / "config.toml"
    feat = find_feature(Config(), "read-back")
    _apply(cfg_file, feat.on_writes)
    cfg = load_config(cfg_file)
    assert cfg.tts.enabled is True
    assert cfg.accessibility.read_back != "off"
    # disabling is enough to switch the capability off
    _apply(cfg_file, feat.off_writes)
    assert load_config(cfg_file).accessibility.read_back == "off"


def test_llm_cleanup_writes_nested_section(tmp_path):
    cfg_file = tmp_path / "config.toml"
    feat = find_feature(Config(), "llm-cleanup")
    _apply(cfg_file, feat.on_writes)
    assert load_config(cfg_file).filters.disfluency.llm_enabled is True


def test_unknown_slug_returns_none():
    assert find_feature(Config(), "does-not-exist") is None


# ---- vocabulary: the personal dictionary -----------------------------------

def test_add_then_load(tmp_path):
    p = vocab_path(tmp_path)
    add_vocab(p, ["Kubernetes", "kubectl"])
    assert load_vocab(p) == ["Kubernetes", "kubectl"]


def test_add_dedupes_case_insensitively(tmp_path):
    p = vocab_path(tmp_path)
    add_vocab(p, ["GitHub"])
    add_vocab(p, ["github", "Redis"])
    words = load_vocab(p)
    assert words.count("GitHub") == 1
    assert "Redis" in words
    assert "github" not in words  # the existing casing is kept


def test_remove(tmp_path):
    p = vocab_path(tmp_path)
    add_vocab(p, ["alpha", "beta", "gamma"])
    remove_vocab(p, "beta")
    assert load_vocab(p) == ["alpha", "gamma"]


def test_load_missing_is_empty(tmp_path):
    assert load_vocab(vocab_path(tmp_path)) == []
