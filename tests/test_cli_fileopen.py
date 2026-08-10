from __future__ import annotations
from unittest.mock import patch
from pathlib import Path
from typer.testing import CliRunner
from yazses.cli import app

runner = CliRunner()


def test_fileopen_cli_aborts_on_no_match(tmp_path):
    (tmp_path / "hello.txt").write_text("hello")
    result = runner.invoke(app, ["fileopen", "unrelated", "--dir", str(tmp_path)])
    assert result.exit_code == 1
    assert "No file matched 'unrelated'" in result.output


@patch("yazses.cli.typer.confirm")
@patch("yazses.fileopen.launcher.launch_file")
def test_fileopen_cli_confirms_and_launches(mock_launch, mock_confirm, tmp_path):
    (tmp_path / "budget-2024.xlsx").write_text("budget")
    (tmp_path / "random.txt").write_text("random")
    
    mock_confirm.return_value = True
    
    result = runner.invoke(app, ["fileopen", "my budget", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Best match: budget-2024.xlsx" in result.output
    
    mock_confirm.assert_called_once()
    mock_launch.assert_called_once_with(tmp_path / "budget-2024.xlsx")


@patch("yazses.fileopen.launcher.launch_file")
def test_fileopen_cli_yes_flag(mock_launch, tmp_path):
    (tmp_path / "budget-2024.xlsx").write_text("budget")
    
    result = runner.invoke(app, ["fileopen", "budget", "--dir", str(tmp_path), "--yes"])
    assert result.exit_code == 0
    assert "Best match" not in result.output  # bypassed confirmation prompt output
    
    mock_launch.assert_called_once_with(tmp_path / "budget-2024.xlsx")
