"""Section-aware TOML key setter (backs `yazses hotkey set`, etc.)."""
from __future__ import annotations

import tomllib

from yazses.system.configedit import set_config_key


def test_creates_file_when_missing(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "hotkey", "key", "right_ctrl")
    assert p.read_text() == '[hotkey]\nkey = "right_ctrl"\n'


def test_replaces_existing_key_in_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[hotkey]\n# a comment\nkey = "right_alt"\n\n[stt]\nmodel = "small.en"\n')
    set_config_key(p, "hotkey", "key", "space")
    t = p.read_text()
    assert 'key = "space"' in t
    assert 'key = "right_alt"' not in t
    assert "# a comment" in t              # comments preserved
    assert 'model = "small.en"' in t       # other sections untouched


def test_inserts_key_when_section_exists_without_it(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[hotkey]\nhold_threshold_ms = 500\n')
    set_config_key(p, "hotkey", "key", "left_alt")
    t = p.read_text()
    assert 'key = "left_alt"' in t
    assert "hold_threshold_ms = 500" in t


def test_appends_section_when_missing(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[stt]\nmodel = "small.en"\n')
    set_config_key(p, "hotkey", "key", "right_shift")
    t = p.read_text()
    assert "[hotkey]" in t
    assert 'key = "right_shift"' in t
    assert 'model = "small.en"' in t


def test_does_not_touch_same_key_name_in_other_section(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[other]\nkey = "keep-me"\n\n[hotkey]\nkey = "right_alt"\n')
    set_config_key(p, "hotkey", "key", "space")
    t = p.read_text()
    assert 'key = "keep-me"' in t          # [other].key untouched
    assert 'key = "space"' in t


def test_unquoted_value(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "hotkey", "hold_threshold_ms", 700, quote=False)
    assert "hold_threshold_ms = 700" in p.read_text()


def test_default_quote_infers_bare_rendering_for_numbers(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "accessibility", "vad_threshold", 0.002)
    assert "vad_threshold = 0.002" in p.read_text()
    assert '"0.002"' not in p.read_text()


def test_default_quote_infers_true_false_for_bool(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "accessibility", "enabled", True)
    set_config_key(p, "accessibility", "verbose", False)
    t = p.read_text()
    assert "enabled = true" in t
    assert "verbose = false" in t


def test_default_quote_still_quotes_strings(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "hotkey", "key", "right_ctrl")
    assert 'key = "right_ctrl"' in p.read_text()


def test_default_quote_escapes_special_characters_in_strings(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "stt", "prompt", 'say "hi"\\bye')
    parsed = tomllib.loads(p.read_text())
    assert parsed["stt"]["prompt"] == 'say "hi"\\bye'


def test_round_trip_preserves_value_types(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "accessibility", "vad_threshold", 0.002)
    set_config_key(p, "accessibility", "retries", 3)
    set_config_key(p, "accessibility", "enabled", True)
    set_config_key(p, "hotkey", "key", "right_ctrl")

    parsed = tomllib.loads(p.read_text())
    assert parsed["accessibility"]["vad_threshold"] == 0.002
    assert isinstance(parsed["accessibility"]["vad_threshold"], float)
    assert parsed["accessibility"]["retries"] == 3
    assert isinstance(parsed["accessibility"]["retries"], int)
    assert parsed["accessibility"]["enabled"] is True
    assert parsed["hotkey"]["key"] == "right_ctrl"


def test_explicit_quote_true_overrides_inference(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "accessibility", "vad_threshold", 0.002, quote=True)
    assert 'vad_threshold = "0.002"' in p.read_text()


def test_explicit_quote_false_overrides_inference(tmp_path):
    p = tmp_path / "config.toml"
    set_config_key(p, "hotkey", "hold_threshold_ms", "700", quote=False)
    assert "hold_threshold_ms = 700" in p.read_text()
