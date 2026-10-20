"""A failed library install is a failed command, and it says what state it left.

`features enable` writes the config key and then installs the feature's libraries.
When the install failed it printed the installer's error, then "Apply it:  yazses
restart", and exited **0** — so a script, the hands-free preset and a skimming
reader all took it as success, and the capability sat switched on and dead.

The key itself stands on purpose (docs/architecture.md, "When an install fails, the
config key stands"; `settingsui/deps.py` gives the reasoning), so what changes is
the report: a non-zero exit, the word *dormant*, and the exact retry command. These
run offline: `install_packages` is replaced, nothing is fetched.
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.system import deps

runner = CliRunner()


def _use_config(monkeypatch, path: Path) -> Path:
    monkeypatch.setattr(
        cli, "get_platform",
        lambda: types.SimpleNamespace(paths=types.SimpleNamespace(config_file=path)),
    )
    # The libraries are absent and the environment could install them.
    monkeypatch.setattr(deps, "missing_modules", lambda modules: list(modules))
    monkeypatch.setattr(deps, "install_blocked_reason", lambda packages, env=None: None)
    monkeypatch.setattr("yazses.system.depsize.download_note", lambda slug, missing: "")
    return path


def _install_result(monkeypatch, ok: bool) -> list:
    calls: list = []

    def fake_install(packages, *, echo=print):
        calls.append(tuple(packages))
        if not ok:
            echo("Automatic install failed (network unreachable).")
        return ok

    monkeypatch.setattr(deps, "install_packages", fake_install)
    return calls


def test_a_failed_install_exits_non_zero_and_names_the_retry(monkeypatch, tmp_path):
    cfg = _use_config(monkeypatch, tmp_path / "config.toml")
    calls = _install_result(monkeypatch, ok=False)

    result = runner.invoke(cli.app, ["features", "enable", "prosody"])

    assert calls, "the install was never attempted"
    assert result.exit_code == 1, result.output
    assert "dormant" in result.output
    assert "yazses features enable prosody" in result.output
    assert "Apply it:" not in result.output, "a failed enable must not read as done"
    # The intent is recorded, as the architecture doc promises.
    assert "enabled = true" in cfg.read_text(encoding="utf-8")


def test_a_successful_install_still_reads_as_done(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path / "config.toml")
    _install_result(monkeypatch, ok=True)

    result = runner.invoke(cli.app, ["features", "enable", "prosody"])

    assert result.exit_code == 0, result.output
    assert "Apply it:  yazses restart" in result.output
    assert "dormant" not in result.output


def test_the_retry_command_carries_force_for_an_experimental_feature(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path / "config.toml")
    _install_result(monkeypatch, ok=False)

    result = runner.invoke(cli.app, ["features", "enable", "cocktail", "--force"])

    assert result.exit_code == 1, result.output
    assert "yazses features enable cocktail --force" in result.output


def test_no_install_says_how_to_finish_the_job(monkeypatch, tmp_path):
    _use_config(monkeypatch, tmp_path / "config.toml")
    calls = _install_result(monkeypatch, ok=True)

    result = runner.invoke(cli.app, ["features", "enable", "prosody", "--no-install"])

    assert result.exit_code == 0, result.output
    assert calls == [], "--no-install must not install"
    assert "dormant until they are installed" in result.output
    assert "yazses features enable prosody" in result.output


@pytest.mark.parametrize("ok, code", [(True, 0), (False, 1)])
def test_install_feature_deps_reports_the_outcome(monkeypatch, tmp_path, ok, code):
    from yazses.config import Config
    from yazses.system.features import find_feature

    _use_config(monkeypatch, tmp_path / "config.toml")
    _install_result(monkeypatch, ok=ok)
    feat = find_feature(Config(), "prosody")
    assert cli._install_feature_deps(feat, skip=False) is ok


def test_a_feature_with_nothing_to_install_is_a_success(monkeypatch, tmp_path):
    from yazses.config import Config
    from yazses.system.features import find_feature

    _use_config(monkeypatch, tmp_path / "config.toml")
    feat = find_feature(Config(), "streaming")
    assert not feat.pip_packages
    assert cli._install_feature_deps(feat, skip=False) is True


def test_features_reset_exits_non_zero_when_a_default_feature_did_not_install(
    monkeypatch, tmp_path
):
    """`tray` is on by default and needs PySide6: the one reset row that installs."""
    cfg = _use_config(monkeypatch, tmp_path / "config.toml")
    cfg.write_text("[tray]\nenabled = false\n", encoding="utf-8")
    _install_result(monkeypatch, ok=False)

    result = runner.invoke(cli.app, ["features", "reset", "--yes"])

    assert result.exit_code == 1, result.output
    assert "tray" in result.output and "dormant" in result.output
