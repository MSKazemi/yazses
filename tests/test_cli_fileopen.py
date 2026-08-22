from __future__ import annotations

from unittest.mock import patch

from typer.testing import CliRunner

from yazses.cli import app

runner = CliRunner()


def test_fileopen_cli_aborts_on_no_match(tmp_path):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    result = runner.invoke(app, ["fileopen", "unrelated", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "No file matched 'unrelated'" in result.output


@patch("yazses.cli.typer.confirm")
@patch("yazses.fileopen.launcher.launch_file")
def test_fileopen_cli_confirms_and_launches(mock_launch, mock_confirm, tmp_path):
    (tmp_path / "budget-2024.xlsx").write_text("budget", encoding="utf-8")
    (tmp_path / "random.txt").write_text("random", encoding="utf-8")

    mock_confirm.return_value = True

    result = runner.invoke(app, ["fileopen", "my budget", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Best match: budget-2024.xlsx" in result.output

    mock_confirm.assert_called_once()
    mock_launch.assert_called_once_with(tmp_path / "budget-2024.xlsx")


@patch("yazses.fileopen.launcher.launch_file")
def test_fileopen_cli_yes_flag_skips_the_prompt(mock_launch, tmp_path):
    (tmp_path / "budget-2024.xlsx").write_text("budget", encoding="utf-8")

    result = runner.invoke(app, ["fileopen", "budget", "--dir", str(tmp_path), "--yes"])
    assert result.exit_code == 0
    assert "Best match" not in result.output  # bypassed the confirmation prompt

    mock_launch.assert_called_once_with(tmp_path / "budget-2024.xlsx")


@patch("yazses.fileopen.launcher.launch_file")
def test_fileopen_always_names_the_file_it_opened(mock_launch, tmp_path):
    """`--yes` is the one path where the user never sees the choice being made.

    It picks a file by fuzzy score, so a silent launch leaves them with no way to know
    which of several near-matches actually opened — the case that most needs saying.
    """
    (tmp_path / "budget-2024.xlsx").write_text("budget", encoding="utf-8")

    result = runner.invoke(app, ["fileopen", "budget", "--dir", str(tmp_path), "--yes"])
    assert result.exit_code == 0
    assert "Opened budget-2024.xlsx" in result.output


def _with_config(monkeypatch, tmp_path, body: str):
    """Point the CLI at a throwaway config file containing *body*."""
    import yazses.cli as cli

    # Not in tmp_path itself — that is the directory under search, and a stray
    # config.toml would become one of the candidate files.
    cfg_dir = tmp_path / "_cfg"
    cfg_dir.mkdir(exist_ok=True)
    cfg_file = cfg_dir / "config.toml"
    cfg_file.write_text(body, encoding="utf-8")
    paths = type("Paths", (), {"config_file": cfg_file})()
    monkeypatch.setattr(cli, "get_platform", lambda: type("P", (), {"paths": paths})())


@patch("yazses.fileopen.launcher.launch_file")
def test_fileopen_honours_the_configured_threshold(mock_launch, tmp_path, monkeypatch):
    """`[fileopen] threshold` is documented and user-facing, so it has to be read.

    Asserted by *raising* the bar: "budget" clears the built-in 0.4 comfortably, so a
    miss at 0.99 can only mean the configured value reached `resolve_open`. Lowering
    it instead would prove nothing — the default already matches.
    """
    (tmp_path / "budget-2024.xlsx").write_text("budget", encoding="utf-8")
    _with_config(monkeypatch, tmp_path, "[fileopen]\nthreshold = 0.99\n")

    result = runner.invoke(app, ["fileopen", "budget", "--dir", str(tmp_path), "--yes"])
    assert result.exit_code == 1, result.output
    assert "0.99" in result.output
    mock_launch.assert_not_called()


def test_fileopen_reports_the_threshold_when_nothing_matches(tmp_path):
    """A miss should say what bar was applied, not just that it missed."""
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    result = runner.invoke(app, ["fileopen", "zzzz", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "threshold" in result.output
