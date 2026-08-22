"""CLI status messages show the *configured* hotkey, not the platform default.

`start`/`test` used to print `platform.default_hotkey` ("space"), which is wrong
whenever the user configured a different `[hotkey] key` (e.g. "right_alt") — the
daemon binds the configured key but the message said "space". `_resolved_hotkey`
reads the configured key, falling back to the platform default.
"""
from __future__ import annotations

import types
from pathlib import Path

from yazses import cli


def _fake_platform(config_file: Path, default="space"):
    return types.SimpleNamespace(
        default_hotkey=default,
        paths=types.SimpleNamespace(config_file=config_file),
    )


def test_resolved_hotkey_uses_configured_key(tmp_path):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[hotkey]\nkey = \"right_alt\"\n", encoding="utf-8")
    assert cli._resolved_hotkey(_fake_platform(cfg)) == "right_alt"


def test_resolved_hotkey_falls_back_to_platform_default(tmp_path):
    missing = tmp_path / "absent.toml"
    assert cli._resolved_hotkey(_fake_platform(missing, default="space")) == "space"


# ---- dedicated command key -------------------------------------------------

def test_command_key_defaults_to_empty():
    from yazses.config import Config

    assert Config().hotkey.command_key == ""


def test_command_key_round_trips_through_config(tmp_path):
    from yazses.config import load_config
    from yazses.system.configedit import set_config_key

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[hotkey]\nkey = "right_alt"\n', encoding="utf-8")
    set_config_key(cfg_file, "hotkey", "command_key", "right_ctrl")
    assert load_config(cfg_file).hotkey.command_key == "right_ctrl"
    # 'off' clears it
    set_config_key(cfg_file, "hotkey", "command_key", "")
    assert load_config(cfg_file).hotkey.command_key == ""
    # the dictation key was never disturbed
    assert load_config(cfg_file).hotkey.key == "right_alt"


# ---- the offered keys, and the clash that used to slip through --------------


def _run(monkeypatch, tmp_path, argv, *, config: str = ""):
    """Run a `yazses hotkey ...` command against a throwaway config file."""
    from typer.testing import CliRunner

    cfg = tmp_path / "config.toml"
    cfg.write_text(config, encoding="utf-8")
    monkeypatch.setattr(cli, "get_platform", lambda: _fake_platform(cfg, default="right_alt"))
    result = CliRunner().invoke(cli.app, argv)
    return result, cfg


def test_the_macos_spelling_is_accepted(monkeypatch, tmp_path):
    """Every backend binds `right_option`; the CLI used to refuse it outright."""
    result, cfg = _run(monkeypatch, tmp_path, ["hotkey", "set", "right_option"])
    assert result.exit_code == 0, result.output
    assert "right_option" in cfg.read_text(encoding="utf-8")


def test_auto_can_be_chosen_again(monkeypatch, tmp_path):
    """`auto` is the shipped default. Offering only bindable keys made picking
    one a door that closed behind you."""
    result, cfg = _run(
        monkeypatch, tmp_path, ["hotkey", "set", "auto"], config='[hotkey]\nkey = "space"\n'
    )
    assert result.exit_code == 0, result.output
    assert 'key = "auto"' in cfg.read_text(encoding="utf-8")


def test_an_unbindable_key_is_still_refused(monkeypatch, tmp_path):
    result, cfg = _run(monkeypatch, tmp_path, ["hotkey", "set", "f13"])
    assert result.exit_code == 1
    assert "f13" not in cfg.read_text(encoding="utf-8")


def test_a_command_key_aliasing_the_dictation_key_is_refused(monkeypatch, tmp_path):
    """`right_option` and `right_alt` are one physical key. The check compared
    raw strings, so this clash was written happily and command mode then
    swallowed every dictation burst."""
    result, cfg = _run(
        monkeypatch,
        tmp_path,
        ["hotkey", "command", "right_option"],
        config='[hotkey]\nkey = "right_alt"\n',
    )
    assert result.exit_code == 1
    assert "command_key" not in cfg.read_text(encoding="utf-8")


def test_a_clash_against_the_default_key_is_caught(monkeypatch, tmp_path):
    """With the shipped config the dictation key is the sentinel `auto`, which
    never equalled a real key name — so the clash check was blind on exactly the
    config every new install starts with."""
    result, cfg = _run(
        monkeypatch, tmp_path, ["hotkey", "command", "right_alt"], config='[hotkey]\nkey = "auto"\n'
    )
    assert result.exit_code == 1, result.output
    assert "command_key" not in cfg.read_text(encoding="utf-8")


def test_the_command_key_does_not_accept_auto(monkeypatch, tmp_path):
    """`auto` means "the platform's default *dictation* key" — as a command key
    it would alias onto the dictation key on most machines."""
    result, cfg = _run(monkeypatch, tmp_path, ["hotkey", "command", "auto"])
    assert result.exit_code == 1
    assert "command_key" not in cfg.read_text(encoding="utf-8")
