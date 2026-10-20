"""#497: a language profile switches as one coherent unit, or not at all.

The resolver, the atomic writer and the CLI already existed. What these tests pin
is the part that made the guarantee checkable rather than assumed:

* the committed candidate is re-read through the real loader and refused unless it
  is exactly the plan -- planned ``[stt]`` keys, no collateral section change, and a
  coherent match for the requested profile -- with the original left byte-for-byte;
* the command grammar travels with the speech language (``auto``) and an explicit
  pin is preserved but reported, by status, plan, doctor, CLI and Settings alike;
* the default English install is unchanged: no write, no new doctor row, no
  Chinese-only import.

Offline: model cache and dependency probes are injected; nothing is downloaded.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from yazses import cli
from yazses.config import Config, SttConfig, load_config, load_config_checked
from yazses.language import derive_status, list_profiles, resolve_profile
from yazses.language.service import (
    apply_language_change,
    committed_candidate_validator,
    prepare_language_change,
)
from yazses.settingsui import language_view
from yazses.system import configedit
from yazses.system.configedit import (
    ConfigChange,
    ConfigEditValidationError,
    set_config_keys_atomic,
)
from yazses.system.doctor import _language_profile_checks
from yazses.system.firstrun import ensure_recommended_config

runner = CliRunner()

_READY = dict(
    missing_modules_fn=lambda _mods: [],
    blocked_probe=lambda _packages: None,
    cache_probe=lambda _model: True,
)


def _english(path, *, extra: str = "") -> None:
    path.write_text(
        '[stt]\n'
        'engine = "faster-whisper"\n'
        'model = "base.en"\n'
        'language = "en"\n'
        'chinese_script = ""\n'
        '\n[hotkey]\n'
        'key = "right_alt"\n' + extra,
        encoding="utf-8",
    )


def _no_temp_left(directory) -> bool:
    return not list(directory.glob(".config.toml.*.tmp"))


# --- the atomic writer's validate hook -------------------------------------------


def test_validate_hook_sees_the_complete_candidate_while_the_target_is_original(tmp_path):
    p = tmp_path / "config.toml"
    _english(p)
    original = p.read_bytes()
    seen = {}

    def validate(candidate):
        seen["candidate"] = tomllib.loads(candidate.read_text(encoding="utf-8"))["stt"]
        seen["target"] = p.read_bytes()

    set_config_keys_atomic(
        p,
        [ConfigChange("stt", "model", "small"), ConfigChange("stt", "language", "zh")],
        validate=validate,
    )

    assert seen["target"] == original
    assert seen["candidate"]["model"] == "small"
    assert seen["candidate"]["language"] == "zh"
    assert tomllib.loads(p.read_text(encoding="utf-8"))["stt"]["language"] == "zh"


def test_a_refusing_validate_hook_leaves_the_original_byte_for_byte(tmp_path):
    p = tmp_path / "config.toml"
    _english(p)
    original = p.read_bytes()

    def refuse(_candidate):
        raise ConfigEditValidationError("not what was planned")

    with pytest.raises(ConfigEditValidationError):
        set_config_keys_atomic(
            p,
            [ConfigChange("stt", "model", "small"), ConfigChange("stt", "language", "zh")],
            validate=refuse,
        )

    assert p.read_bytes() == original
    assert _no_temp_left(tmp_path)


# --- the language service proves the candidate means the plan --------------------


def test_a_collateral_section_change_refuses_the_whole_switch(tmp_path, monkeypatch):
    """An editor defect that also touches [hotkey] must not ride along."""
    p = tmp_path / "config.toml"
    _english(p)
    original = p.read_bytes()
    real = configedit._set_config_key_unlocked

    def also_touch_hotkey(path, section, key, value, **kwargs):
        out = real(path, section, key, value, **kwargs)
        if key == "language":
            real(path, "hotkey", "key", "left_ctrl", quote=True)
        return out

    monkeypatch.setattr(configedit, "_set_config_key_unlocked", also_touch_hotkey)

    result = apply_language_change(p, "zh-CN", **_READY)

    assert not result.ok
    assert result.category == "transaction"
    assert "[hotkey]" in result.error
    assert p.read_bytes() == original
    assert _no_temp_left(tmp_path)


def test_a_planned_key_the_loader_would_not_keep_refuses_the_switch(tmp_path, monkeypatch):
    """Half a switch -- speech moved to zh, script never landed -- is never committed."""
    p = tmp_path / "config.toml"
    _english(p)
    original = p.read_bytes()
    real = configedit._set_config_key_unlocked

    def drop_script(path, section, key, value, **kwargs):
        if key == "chinese_script":
            return "skipped"
        return real(path, section, key, value, **kwargs)

    monkeypatch.setattr(configedit, "_set_config_key_unlocked", drop_script)

    result = apply_language_change(p, "zh-TW", **_READY)

    assert not result.ok
    assert result.category == "transaction"
    assert "chinese_script" in result.error
    assert p.read_bytes() == original


def test_validator_accepts_exactly_the_plan_and_rejects_another_profile(tmp_path):
    p = tmp_path / "config.toml"
    _english(p)
    plan = resolve_profile("zh-CN", load_config(p))

    good = tmp_path / "good.toml"
    good.write_text(
        p.read_text(encoding="utf-8")
        .replace('model = "base.en"', 'model = "small"')
        .replace('language = "en"', 'language = "zh"')
        .replace('chinese_script = ""', 'chinese_script = "simplified"'),
        encoding="utf-8",
    )
    committed_candidate_validator(p, plan)(good)

    wrong = tmp_path / "wrong.toml"
    wrong.write_text(
        good.read_text(encoding="utf-8").replace('"simplified"', '"traditional"'),
        encoding="utf-8",
    )
    with pytest.raises(ConfigEditValidationError, match="chinese_script"):
        committed_candidate_validator(p, plan)(wrong)


def test_round_trip_on_a_first_run_config_touches_only_the_profile_keys(tmp_path):
    """en -> zh-CN -> zh-TW -> en on the real seeded file; every other section intact."""
    p = tmp_path / "config.toml"
    assert ensure_recommended_config(p)
    seeded = load_config_checked(p).config

    for profile in ("zh-CN", "zh-TW", "en"):
        result = apply_language_change(p, profile, **_READY)
        assert result.ok, (profile, result.error)
        assert derive_status(load_config(p)).profile_match == profile

    final = load_config_checked(p).config
    for name in Config.__dataclass_fields__:
        if name != "stt":
            assert getattr(final, name) == getattr(seeded, name), name
    # Returning to English kept the multilingual model the Mandarin switch chose:
    # no forced base.en download (preserve mode, ADR-v2-140).
    assert final.stt.model == "small"
    assert final.stt.language == "en"
    assert final.stt.chinese_script == ""


def test_switching_to_english_on_a_default_english_install_writes_nothing(tmp_path):
    p = tmp_path / "config.toml"
    assert ensure_recommended_config(p)
    original = p.read_bytes()

    result = apply_language_change(p, "en", **_READY)

    assert result.ok
    assert result.changed is False
    assert p.read_bytes() == original


# --- command grammar travels with the profile -------------------------------------


def _cfg(language="en", script="", model="base.en", commands_language="auto", enabled=True):
    cfg = Config()
    cfg.stt = SttConfig(model=model, language=language, chinese_script=script)
    cfg.commands.language = commands_language
    cfg.commands.enabled = enabled
    return cfg


def test_status_resolves_the_grammar_the_daemon_resolves():
    status = derive_status(_cfg("zh", "simplified", "small"))

    assert status.command_language == "zh"
    assert status.command_grammar_available
    assert not status.command_language_pinned
    assert status.warnings == ()


def test_a_pinned_grammar_that_contradicts_speech_is_reported_not_refused():
    status = derive_status(_cfg("zh", "simplified", "small", commands_language="en"))

    assert status.coherent
    assert status.profile_match == "zh-CN"
    assert status.command_language == "en"
    assert status.command_language_pinned
    assert len(status.warnings) == 1
    assert "pinned" in status.warnings[0]


def test_disabled_commands_raise_no_grammar_warning():
    status = derive_status(
        _cfg("zh", "simplified", "small", commands_language="en", enabled=False)
    )

    assert status.warnings == ()
    assert not status.commands_enabled


def test_a_bare_stt_section_uses_the_shipped_command_defaults():
    status = derive_status(SttConfig(model="small", language="zh", chinese_script="traditional"))

    assert status.command_language == "zh"
    assert status.commands_enabled


def test_plan_names_the_grammar_change_and_preserves_an_explicit_pin():
    auto = resolve_profile("zh-CN", _cfg())
    assert (auto.command_language_before, auto.command_language_after) == ("en", "zh")
    assert auto.warnings == ()
    assert not any(m.section == "commands" for m in auto.mutations)

    pinned = resolve_profile("zh-CN", _cfg(commands_language="en"))
    assert pinned.command_language_after == "en"
    assert not any(m.section == "commands" for m in pinned.mutations)
    assert any("stays pinned" in w for w in pinned.warnings)


# --- doctor -----------------------------------------------------------------------


def test_doctor_default_english_output_is_unchanged():
    assert _language_profile_checks(Config()) == [
        ("Language profile", "OK", "en — English speech; Han-script normalisation off"),
    ]


def test_doctor_warns_when_an_english_profile_has_a_pinned_mandarin_grammar():
    rows = _language_profile_checks(_cfg(commands_language="zh"))

    grammar = next(row for row in rows if row[0] == "Command grammar")
    assert grammar[1] == "WARN"
    assert "'zh'" in grammar[2]


def test_doctor_mandarin_profile_reports_a_pinned_english_grammar():
    cfg = _cfg("zh", "traditional", "small", commands_language="en")
    with patch("yazses.system.deps.missing_modules", return_value=[]):
        rows = _language_profile_checks(cfg)

    assert ("Language profile", "OK") == rows[0][:2]
    grammar = next(row for row in rows if row[0] == "Command grammar")
    assert grammar[1] == "WARN"


# --- CLI ---------------------------------------------------------------------------


def _platform(config_file):
    return SimpleNamespace(
        paths=SimpleNamespace(
            config_file=config_file,
            ipc_socket=config_file.with_suffix(".sock"),
        ),
        lifecycle=SimpleNamespace(is_running=lambda: False),
    )


def test_cli_status_reports_the_mandarin_grammar_and_a_pin_warning(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[stt]\nmodel = "small"\nlanguage = "zh"\nchinese_script = "simplified"\n'
        '\n[commands]\nlanguage = "en"\n',
        encoding="utf-8",
    )
    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        text = runner.invoke(cli.app, ["language", "status"])
        js = runner.invoke(cli.app, ["language", "status", "--json"])

    assert text.exit_code == 0, text.output
    assert "English Tier-1 [pinned]" in text.output
    assert "warning:" in text.output
    payload = json.loads(js.output)
    assert payload["command_language"] == "en"
    assert payload["command_support"] == "available"
    assert len(payload["warnings"]) == 1


def test_cli_dry_run_shows_the_grammar_that_follows_speech(tmp_path):
    p = tmp_path / "config.toml"
    _english(p)
    before = p.read_bytes()
    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(cli.app, ["language", "set", "zh-CN", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "Command grammar: en -> zh" in result.output
    assert p.read_bytes() == before


# --- Settings view-model (Qt-free) -------------------------------------------------


def test_settings_profile_choices_come_from_the_registry():
    choices = language_view.profile_choices()

    assert choices[0] == (language_view.CUSTOM_LABEL, "")
    assert [value for _label, value in choices[1:]] == [p.id for p in list_profiles()]


def test_settings_preview_is_rendered_from_the_shared_plan(tmp_path):
    p = tmp_path / "config.toml"
    _english(p, extra='\n[commands]\nlanguage = "en"\n')
    prepared = prepare_language_change(
        p,
        "zh-CN",
        missing_modules_fn=lambda _mods: ["opencc"],
        blocked_probe=lambda _packages: None,
        cache_probe=lambda _model: False,
    )

    hint = language_view.preview_hint(prepared)
    assert "chinese_script" in hint
    assert "stays pinned" in hint
    assert "download speech model small" in hint
    assert hint.endswith("Nothing changes until Apply.")

    question = language_view.confirmation_message(prepared)
    assert question is not None
    assert "small" in question and "will not be changed" in question


def test_settings_asks_nothing_when_no_preparation_is_needed(tmp_path):
    p = tmp_path / "config.toml"
    _english(p)
    prepared = prepare_language_change(p, "zh-CN", **_READY)

    assert language_view.confirmation_message(prepared) is None
    assert "Spoken commands follow: en → zh." in language_view.preview_hint(prepared)


# --- FND-08: the English path pays for nothing Chinese -----------------------------


def test_english_status_plan_and_settings_import_no_chinese_only_module():
    code = (
        "import sys\n"
        "from yazses.config import Config\n"
        "from yazses.language import derive_status, resolve_profile\n"
        "from yazses.settingsui.language_view import profile_choices\n"
        "cfg = Config()\n"
        "assert derive_status(cfg).profile_match == 'en'\n"
        "assert resolve_profile('en', cfg).mutations == ()\n"
        "profile_choices()\n"
        "bad = [m for m in ('yazses.commands.grammars.zh', 'opencc') if m in sys.modules]\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
