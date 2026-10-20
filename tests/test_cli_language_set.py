from __future__ import annotations

import tomllib
from types import SimpleNamespace
from unittest.mock import patch

from typer.testing import CliRunner

from yazses import cli
from yazses.system import configedit

runner = CliRunner()


class _Lifecycle:
    def __init__(self, running: bool = False):
        self.running = running

    def is_running(self) -> bool:
        return self.running


def _platform(config_file, *, running: bool = False):
    return SimpleNamespace(
        paths=SimpleNamespace(
            config_file=config_file,
            ipc_socket=config_file.with_suffix(".sock"),
        ),
        lifecycle=_Lifecycle(running),
    )


def _english_config(path):
    path.write_text(
        '[stt]\n'
        'engine = "faster-whisper"\n'
        'model = "base.en"\n'
        'language = "en"\n'
        'chinese_script = ""\n'
        '\n[hotkey]\n'
        'key = "right_alt"\n',
        encoding="utf-8",
    )


def _ready_prereqs():
    return (
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=True),
    )


def test_language_set_dry_run_has_zero_side_effects(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)
    before = p.read_bytes()

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=["opencc"]),
        patch("yazses.system.deps.install_blocked_reason", return_value=None),
        patch("yazses.system.deps.install_packages") as install,
        patch("yazses.stt.download.is_cached", return_value=False),
        patch("yazses.stt.download.download_stt_model") as download,
    ):
        result = runner.invoke(
            cli.app,
            ["language", "set", "zh-CN", "--dry-run"],
        )

    assert result.exit_code == 0, result.output
    assert p.read_bytes() == before
    assert "base.en" in result.output
    assert "small" in result.output
    assert "not cached" in result.output
    assert "opencc" in result.output
    assert "--dry-run" in result.output
    install.assert_not_called()
    download.assert_not_called()


def test_language_set_no_download_refuses_before_write(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)
    before = p.read_bytes()

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=False),
        patch("yazses.stt.download.download_stt_model") as download,
    ):
        result = runner.invoke(
            cli.app,
            ["language", "set", "zh-CN", "--no-download", "-y"],
        )

    assert result.exit_code == 2
    assert p.read_bytes() == before
    assert "--no-download" in result.output
    download.assert_not_called()


def test_language_set_no_install_refuses_before_write(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)
    before = p.read_bytes()

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=["opencc"]),
        patch("yazses.system.deps.install_blocked_reason", return_value=None),
        patch("yazses.system.deps.install_packages") as install,
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(
            cli.app,
            ["language", "set", "zh-CN", "--no-install", "-y"],
        )

    assert result.exit_code == 2
    assert p.read_bytes() == before
    assert "--no-install" in result.output
    install.assert_not_called()


def test_language_set_blocked_dependency_refuses_before_confirmation_or_write(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)
    before = p.read_bytes()

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=["opencc"]),
        patch(
            "yazses.system.deps.install_blocked_reason",
            return_value="read-only package environment",
        ),
        patch("yazses.system.deps.install_packages") as install,
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(cli.app, ["language", "set", "zh-CN", "-y"])

    assert result.exit_code == 2
    assert p.read_bytes() == before
    assert "read-only package environment" in result.output
    install.assert_not_called()


def test_language_set_dependency_install_failure_keeps_config_byte_exact(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)
    before = p.read_bytes()

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=["opencc"]),
        patch("yazses.system.deps.install_blocked_reason", return_value=None),
        patch("yazses.system.deps.install_packages", return_value=False),
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(cli.app, ["language", "set", "zh-CN", "-y"])

    assert result.exit_code == 2
    assert p.read_bytes() == before
    assert "No config changes were made" in result.output


def test_language_set_model_download_failure_keeps_config_byte_exact(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)
    before = p.read_bytes()

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=False),
        patch(
            "yazses.stt.download.download_stt_model",
            side_effect=RuntimeError("network denied"),
        ),
    ):
        result = runner.invoke(cli.app, ["language", "set", "zh-CN", "-y"])

    assert result.exit_code == 2
    assert p.read_bytes() == before
    assert "No config changes were made" in result.output


def test_language_set_success_installs_downloads_then_commits_coherently(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch(
            "yazses.system.deps.missing_modules",
            side_effect=[["opencc"], ["opencc"], []],
        ),
        patch("yazses.system.deps.install_blocked_reason", return_value=None),
        patch("yazses.system.deps.install_packages", return_value=True) as install,
        patch(
            "yazses.stt.download.is_cached",
            side_effect=[False, False, True],
        ),
        patch(
            "yazses.stt.download.download_stt_model",
            return_value=tmp_path / "small",
        ) as download,
    ):
        result = runner.invoke(cli.app, ["language", "set", "zh-CN", "-y"])

    assert result.exit_code == 0, result.output
    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    assert parsed["stt"]["engine"] == "faster-whisper"
    assert parsed["stt"]["model"] == "small"
    assert parsed["stt"]["language"] == "zh"
    assert parsed["stt"]["chinese_script"] == "simplified"
    assert parsed["hotkey"]["key"] == "right_alt"
    install.assert_called_once()
    download.assert_called_once()
    assert "start it with: yazses start" in result.output


def test_language_set_traditional_uses_same_mandarin_model_and_hant_output(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(cli.app, ["language", "set", "zh-TW", "-y"])

    assert result.exit_code == 0, result.output
    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    assert parsed["stt"]["model"] == "small"
    assert parsed["stt"]["language"] == "zh"
    assert parsed["stt"]["chinese_script"] == "traditional"


def test_language_set_back_to_english_preserves_multilingual_model(tmp_path):
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
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(cli.app, ["language", "set", "en", "-y"])

    assert result.exit_code == 0, result.output
    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    assert parsed["stt"]["model"] == "small"
    assert parsed["stt"]["language"] == "en"
    assert parsed["stt"]["chinese_script"] == ""


def test_language_set_recommended_english_can_restore_base_en(tmp_path):
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
        patch("yazses.stt.download.is_cached", return_value=True),
    ):
        result = runner.invoke(
            cli.app,
            ["language", "set", "en", "--recommended-model", "-y"],
        )

    assert result.exit_code == 0, result.output
    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    assert parsed["stt"]["model"] == "base.en"
    assert parsed["stt"]["language"] == "en"


def test_language_set_no_restart_commits_without_touching_running_daemon(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p, running=True)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=True),
        patch("yazses.cli._restart_daemon") as restart,
    ):
        result = runner.invoke(
            cli.app,
            ["language", "set", "zh-CN", "--no-restart", "-y"],
        )

    assert result.exit_code == 0, result.output
    assert tomllib.loads(p.read_text(encoding="utf-8"))["stt"]["language"] == "zh"
    assert "yazses restart" in result.output
    restart.assert_not_called()


def test_language_set_restarts_running_daemon_once_after_commit(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p, running=True)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=True),
        patch("yazses.cli._refuse_while_finalizing") as guard,
        patch("yazses.cli._restart_daemon") as restart,
        patch("yazses.cli._wait_until_ready", return_value=("ready", {})),
        patch("yazses.cli._report_start_outcome") as report,
    ):
        result = runner.invoke(cli.app, ["language", "set", "zh-CN", "-y"])

    assert result.exit_code == 0, result.output
    assert tomllib.loads(p.read_text(encoding="utf-8"))["stt"]["language"] == "zh"
    guard.assert_called_once()
    restart.assert_called_once()
    report.assert_called_once()


def test_language_set_re_resolves_after_concurrent_config_change(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)
    real_write = configedit.set_config_keys_atomic
    calls = 0

    def conflict_then_write(path, changes, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            p.write_text(
                '[stt]\n'
                'engine = "faster-whisper"\n'
                'model = "small"\n'
                'language = "en"\n'
                'chinese_script = ""\n'
                '\n[hotkey]\n'
                'key = "left_ctrl"\n',
                encoding="utf-8",
            )
            raise configedit.ConfigEditConflictError("changed")
        return real_write(path, changes, **kwargs)

    with (
        patch("yazses.cli.get_platform", return_value=_platform(p)),
        patch("yazses.system.deps.missing_modules", return_value=[]),
        patch("yazses.stt.download.is_cached", return_value=True),
        patch(
            "yazses.system.configedit.set_config_keys_atomic",
            side_effect=conflict_then_write,
        ),
    ):
        result = runner.invoke(cli.app, ["language", "set", "zh-CN", "-y"])

    assert result.exit_code == 0, result.output
    parsed = tomllib.loads(p.read_text(encoding="utf-8"))
    assert parsed["stt"]["model"] == "small"
    assert parsed["stt"]["language"] == "zh"
    assert parsed["stt"]["chinese_script"] == "simplified"
    assert parsed["hotkey"]["key"] == "left_ctrl"
    assert "re-reading and re-resolving" in result.output
    assert calls == 2


def test_language_set_rejects_ambiguous_hong_kong_profile_without_side_effect(tmp_path):
    p = tmp_path / "config.toml"
    _english_config(p)
    before = p.read_bytes()

    with patch("yazses.cli.get_platform", return_value=_platform(p)):
        result = runner.invoke(cli.app, ["language", "set", "zh-HK", "-y"])

    assert result.exit_code == 1
    assert p.read_bytes() == before
    assert "Cantonese" in result.output
