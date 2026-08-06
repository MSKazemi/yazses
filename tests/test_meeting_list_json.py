"""yazses meeting list --json (issue #49)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from typer.testing import CliRunner

from yazses.cli import app


def test_meeting_list_json_empty(tmp_path: Path) -> None:
    meetings_root = tmp_path / "meetings"
    meetings_root.mkdir()
    fake_cfg = mock.Mock()
    fake_cfg.meeting = mock.Mock()
    fake_cfg.meeting.output_dir = str(meetings_root)

    with mock.patch("yazses.config.load_config", return_value=fake_cfg), mock.patch(
        "yazses.cli.get_platform"
    ) as gp:
        gp.return_value.paths.config_file = tmp_path / "cfg.toml"
        result = CliRunner().invoke(app, ["meeting", "list", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []


def test_meeting_list_json_contains_ids(tmp_path: Path) -> None:
    meetings_root = tmp_path / "meetings"
    m1 = meetings_root / "20260101T120000"
    m1.mkdir(parents=True)
    (m1 / "meeting.json").write_text(
        json.dumps({"id": "20260101T120000", "num_speakers": 2, "has_notes": False}),
        encoding="utf-8",
    )

    fake_cfg = mock.Mock()
    fake_cfg.meeting = mock.Mock()
    fake_cfg.meeting.output_dir = str(meetings_root)

    with mock.patch("yazses.config.load_config", return_value=fake_cfg), mock.patch(
        "yazses.cli.get_platform"
    ) as gp:
        gp.return_value.paths.config_file = tmp_path / "cfg.toml"
        result = CliRunner().invoke(app, ["meeting", "list", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert any(item.get("id") == "20260101T120000" for item in data)
