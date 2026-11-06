"""#497 FND-06/07/08: a feature toggle cannot half-apply a language profile.

`yazses language set` and the Settings language row resolve a profile as one unit,
but two other surfaces wrote the same `[stt]` keys one at a time:
`yazses features enable chinese-script` (and its Settings row) wrote
`chinese_script = "simplified"` onto the default `base.en` + `en` install, the
invalid combination ADR-v2-140 opens with; `features enable stt-parakeet`/`stt-moonshine`
on a Mandarin profile wrote an engine that loads an English-only checkpoint, so the
daemon refuses dictation at its next start. `yazses doctor` then reported FAIL and
`yazses language status` exited 1 -- for a state a single command had produced.

Both surfaces now ask the same resolver `doctor` uses (`derive_status`) before
writing, and refuse -- writing nothing -- only when the toggle would *add* a
coherence problem. A toggle that leaves the language settings as coherent as they
were, or repairs them, is untouched. The firing-rate tests pin how rarely the guard
can fire (AGENTS.md rule 9).

Offline: dependency probes are injected; nothing is installed or downloaded, and
every config file lives under ``tmp_path``.
"""
from __future__ import annotations

import copy
import dataclasses
import subprocess
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config, load_config
from yazses.language.status import derive_status, feature_toggle_refusal
from yazses.settingsui.controller import SettingsController
from yazses.system import deps
from yazses.system.features import feature_status, find_feature

runner = CliRunner()


def _cfg(**stt) -> Config:
    cfg = Config()
    cfg.stt = dataclasses.replace(cfg.stt, **stt)
    return cfg


def _mandarin(script: str = "simplified") -> Config:
    return _cfg(model="small", language="zh", chinese_script=script)


def _writes(slug: str, cfg: Config | None = None) -> tuple:
    feat = find_feature(cfg or Config(), slug)
    assert feat is not None, slug
    return feat.on_writes


# --- the pure check ------------------------------------------------------------------


def test_han_script_on_the_default_english_install_is_refused_with_the_profile_command():
    reason = feature_toggle_refusal(Config(), _writes("chinese-script"))

    assert reason
    assert "chinese_script" in reason
    assert "yazses language set zh-CN" in reason
    assert "yazses language set zh-TW" in reason


def test_han_script_on_a_mandarin_config_without_a_pinned_script_is_allowed():
    # The toggle's own job: pin the script on speech that is already Mandarin.
    cfg = _mandarin(script="")
    assert derive_status(cfg).coherent

    assert feature_toggle_refusal(cfg, _writes("chinese-script")) == ""


@pytest.mark.parametrize("slug", ["stt-parakeet", "stt-moonshine"])
def test_an_english_only_engine_on_a_mandarin_profile_is_refused(slug):
    cfg = _mandarin()

    reason = feature_toggle_refusal(cfg, _writes(slug, cfg))

    assert reason
    assert slug.removeprefix("stt-") in reason
    assert "faster-whisper" in reason


@pytest.mark.parametrize("slug", ["stt-parakeet", "stt-moonshine"])
def test_an_english_only_engine_on_the_default_english_install_is_allowed(slug):
    assert feature_toggle_refusal(Config(), _writes(slug)) == ""


def test_a_config_that_is_already_incoherent_is_not_blamed_on_the_toggle():
    # base.en + zh is broken before the toggle; adding the script adds no new problem.
    cfg = _cfg(model="base.en", language="zh", chinese_script="")
    assert not derive_status(cfg).coherent

    assert feature_toggle_refusal(cfg, _writes("chinese-script")) == ""


def test_writes_outside_the_language_keys_are_never_judged():
    cfg = _mandarin()

    assert feature_toggle_refusal(cfg, (("streaming", "enabled", "true", False),)) == ""
    assert feature_toggle_refusal(cfg, (("stt", "persian_normalisation", "true", False),)) == ""
    assert feature_toggle_refusal(cfg, ()) == ""


def test_the_check_does_not_mutate_the_config_it_is_given():
    cfg = Config()
    before = copy.deepcopy(cfg.stt)

    feature_toggle_refusal(cfg, _writes("chinese-script"))

    assert cfg.stt == before


def _firing(cfg: Config) -> set[str]:
    return {
        feat.slug
        for feat in feature_status(cfg)
        if feat.toggleable and feature_toggle_refusal(cfg, feat.on_writes)
    }


def test_firing_rate_on_the_default_english_install_is_exactly_the_han_script_toggle():
    # Every other toggle in the registry enables on a fresh install exactly as before.
    assert _firing(Config()) == {"chinese-script"}


def test_firing_rate_on_a_mandarin_profile_is_exactly_the_english_only_engines():
    assert _firing(_mandarin()) == {"stt-parakeet", "stt-moonshine"}


# --- `yazses features enable` --------------------------------------------------------


def _use_config(monkeypatch, path: Path) -> Path:
    monkeypatch.setattr(
        cli, "get_platform",
        lambda: types.SimpleNamespace(paths=types.SimpleNamespace(config_file=path)),
    )
    monkeypatch.setattr(deps, "missing_modules", lambda modules: [])
    monkeypatch.setattr(deps, "install_blocked_reason", lambda packages, env=None: None)

    def no_install(*_a, **_k):  # pragma: no cover - reached only on a regression
        raise AssertionError("a refused enable must not install anything")

    monkeypatch.setattr(deps, "install_packages", no_install)
    return path


def test_cli_refuses_han_script_on_english_and_leaves_the_file_byte_for_byte(monkeypatch, tmp_path):
    path = _use_config(monkeypatch, tmp_path / "config.toml")
    path.write_text('[stt]\nmodel = "base.en"\nlanguage = "en"\n', encoding="utf-8")
    before = path.read_bytes()

    result = runner.invoke(cli.app, ["features", "enable", "chinese-script"])

    assert result.exit_code == 1, result.output
    assert "yazses language set zh-CN" in result.output
    assert "Apply it:" not in result.output
    assert path.read_bytes() == before


def test_cli_still_pins_the_script_on_a_mandarin_config(monkeypatch, tmp_path):
    path = _use_config(monkeypatch, tmp_path / "config.toml")
    path.write_text('[stt]\nmodel = "small"\nlanguage = "zh"\n', encoding="utf-8")

    result = runner.invoke(cli.app, ["features", "enable", "chinese-script"])

    assert result.exit_code == 0, result.output
    stt = load_config(path).stt
    assert (stt.model, stt.language, stt.chinese_script) == ("small", "zh", "simplified")
    assert derive_status(load_config(path)).profile_match == "zh-CN"


def test_cli_refuses_an_english_only_engine_on_a_mandarin_profile(monkeypatch, tmp_path):
    path = _use_config(monkeypatch, tmp_path / "config.toml")
    path.write_text(
        '[stt]\nmodel = "small"\nlanguage = "zh"\nchinese_script = "traditional"\n',
        encoding="utf-8",
    )
    before = path.read_bytes()

    result = runner.invoke(cli.app, ["features", "enable", "stt-parakeet", "--force"])

    assert result.exit_code == 1, result.output
    assert path.read_bytes() == before


def test_cli_disable_of_a_stray_han_script_still_repairs_the_config(monkeypatch, tmp_path):
    path = _use_config(monkeypatch, tmp_path / "config.toml")
    path.write_text(
        '[stt]\nmodel = "base.en"\nlanguage = "en"\nchinese_script = "simplified"\n',
        encoding="utf-8",
    )

    result = runner.invoke(cli.app, ["features", "disable", "chinese-script"])

    assert result.exit_code == 0, result.output
    assert derive_status(load_config(path)).coherent


# --- Settings: the same check, the same words ----------------------------------------


def _controller(cfg: Config, writes: list) -> SettingsController:
    return SettingsController(
        load_config=lambda: cfg,
        writer=lambda section, key, value, quote: writes.append((section, key, value)),
        deps_probe=lambda _modules: [],
        blocked_probe=lambda _packages: None,
    )


def test_settings_refuses_han_script_on_english_and_writes_nothing():
    writes: list = []

    result = _controller(Config(), writes).set_enabled("chinese-script", True)

    assert not result.ok
    assert "yazses language set zh-CN" in (result.error or "")
    assert writes == []


def test_settings_refuses_an_english_only_engine_on_mandarin(monkeypatch):
    writes: list = []

    result = _controller(_mandarin(), writes).set_enabled("stt-parakeet", True, confirmed=True)

    assert not result.ok
    assert writes == []


def test_settings_turning_a_stray_han_script_off_is_never_refused():
    writes: list = []
    cfg = _cfg(chinese_script="simplified")

    result = _controller(cfg, writes).set_enabled("chinese-script", False)

    assert result.ok, result.error
    assert writes == [("stt", "chinese_script", "")]


def test_settings_pins_the_script_on_a_mandarin_config():
    writes: list = []

    result = _controller(_mandarin(script=""), writes).set_enabled("chinese-script", True)

    assert result.ok, result.error
    assert writes == [("stt", "chinese_script", "simplified")]


# --- FND-08: the default English path pays for nothing Chinese -----------------------


def test_default_english_dictation_path_imports_no_chinese_only_module():
    """The pieces the daemon builds for `base.en` + `en`, in a clean interpreter.

    The Han-script normaliser is off (no wrapper, no OpenCC), the command grammar is
    English, every toggle's coherence check runs, and neither OpenCC nor the Mandarin
    grammar module is imported along the way.
    """
    code = (
        "import sys\n"
        "from yazses.config import Config\n"
        "from yazses.postprocess.han_script import build_han_normaliser\n"
        "from yazses.commands.grammars.registry import get_grammar, resolve_command_language\n"
        "from yazses.commands.grammars.en import ENGLISH_GRAMMAR\n"
        "from yazses.language.status import feature_toggle_refusal\n"
        "from yazses.system.features import feature_status\n"
        "cfg = Config()\n"
        "assert (cfg.stt.engine, cfg.stt.model, cfg.stt.language, cfg.stt.chinese_script)"
        " == ('faster-whisper', 'base.en', 'en', ''), cfg.stt\n"
        "assert build_han_normaliser(cfg.stt) is None\n"
        "lang = resolve_command_language(cfg.commands.language, cfg.stt.language)\n"
        "assert lang == 'en' and get_grammar(lang) is ENGLISH_GRAMMAR\n"
        "for f in feature_status(cfg):\n"
        "    feature_toggle_refusal(cfg, f.on_writes)\n"
        "bad = [m for m in ('opencc', 'yazses.commands.grammars.zh') if m in sys.modules]\n"
        "assert not bad, bad\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
