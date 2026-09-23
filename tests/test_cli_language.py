from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from yazses import cli

runner = CliRunner()


def _platform(config_file):
    return SimpleNamespace(paths=SimpleNamespace(config_file=config_file))


def test_language_list_names_supported_profiles_and_scope():
    result = runner.invoke(cli.app, ["language", "list"])

    assert result.exit_code == 0, result.output
    assert "en" in result.output
    assert "zh-CN" in result.output
    assert "zh-TW" in result.output
    assert "Mandarin" in result.output
    assert "small" in result.output


def test_language_status_reports_default_english(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[stt]\nengine = "faster-whisper"\nmodel = "base.en"\nlanguage = "en"\n',
        encoding="utf-8",
    )

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(cli.app, ["language", "status"])

    assert result.exit_code == 0, result.output
    assert "Speech:        en" in result.output
    assert "base.en" in result.output
    assert "Profile match: en" in result.output
    assert "Status:        coherent" in result.output


def test_language_status_reports_custom_compatible_mandarin(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[stt]\n'
        'engine = "faster-whisper"\n'
        'model = "large-v3"\n'
        'language = "zh"\n'
        'chinese_script = "simplified"\n',
        encoding="utf-8",
    )

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(cli.app, ["language", "status"])

    assert result.exit_code == 0, result.output
    assert "Speech:        zh" in result.output
    assert "Script:        simplified" in result.output
    assert "Profile match: zh-CN — custom model" in result.output
    assert "Status:        coherent" in result.output


def test_language_status_invalid_pair_is_nonzero_and_actionable(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[stt]\n'
        'engine = "faster-whisper"\n'
        'model = "base.en"\n'
        'language = "zh"\n'
        'chinese_script = "simplified"\n',
        encoding="utf-8",
    )

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(cli.app, ["language", "status"])

    assert result.exit_code == 1
    assert "Status:        INVALID" in result.output
    assert "English-only" in result.output


def test_language_status_json_is_stable_and_machine_readable(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[stt]\n'
        'engine = "faster-whisper"\n'
        'model = "small"\n'
        'language = "zh"\n'
        'chinese_script = "traditional"\n',
        encoding="utf-8",
    )

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(cli.app, ["language", "status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload == {
        "coherent": True,
        "command_language": "en",
        "command_support": "english-only",
        "custom_model": False,
        "dictation_ready": True,
        "engine": "faster-whisper",
        "model": "small",
        "output_script": "traditional",
        "problems": [],
        "profile_match": "zh-TW",
        "requirements": {
            "blocked_reason": "",
            "model_cached": True,
            "script_dependency_available": True,
        },
        "speech_language": "zh",
    }


def test_language_status_json_keeps_invalid_exit_code_and_problem_details(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[stt]\n'
        'engine = "parakeet"\n'
        'model = "nemo-parakeet-tdt-0.6b-v2"\n'
        'language = "zh"\n'
        'chinese_script = "simplified"\n',
        encoding="utf-8",
    )

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
    ):
        result = runner.invoke(cli.app, ["language", "status", "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["coherent"] is False
    assert payload["profile_match"] == "zh-CN"
    assert any("Mandarin-capable" in item for item in payload["problems"])



def test_language_status_reports_missing_runtime_requirements_without_calling_config_invalid(
    tmp_path,
):
    p = tmp_path / "config.toml"
    p.write_text(
        '[stt]\n'
        'engine = "faster-whisper"\n'
        'model = "small"\n'
        'language = "zh"\n'
        'chinese_script = "simplified"\n',
        encoding="utf-8",
    )

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=["opencc"]),
        patch("yazses.system.deps.install_blocked_reason", return_value=None),
        patch("yazses.stt.download.is_cached", return_value=False),
    ):
        result = runner.invoke(cli.app, ["language", "status", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["coherent"] is True
    assert payload["dictation_ready"] is False
    assert payload["requirements"]["model_cached"] is False
    assert payload["requirements"]["script_dependency_available"] is False
