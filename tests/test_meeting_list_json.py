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


def test_an_undiarized_meeting_is_not_described_as_having_no_speakers():
    """"0 speaker(s)" on a two-hour recording reads as a failed transcription.

    All three meetings on a real machine are `diarized: false` — speaker
    labelling was never attempted, which is a different statement from "nobody
    spoke". One of them is 8081 seconds long with a 1.7 MB transcript, and it
    listed as `0 speaker(s)`.
    """
    from yazses.cli import _speaker_summary

    assert _speaker_summary({"diarized": False, "num_speakers": 0}) == "not diarized"
    assert _speaker_summary({"diarized": True, "num_speakers": 3}) == "3 speaker(s)"
    assert _speaker_summary({"diarized": True, "num_speakers": 1}) == "1 speaker(s)"


def test_a_meeting_without_the_flag_keeps_the_old_wording():
    """Absent is not False: an older meeting.json says nothing either way, and
    guessing "not diarized" would assert something not in the file."""
    from yazses.cli import _speaker_summary

    assert _speaker_summary({"num_speakers": 2}) == "2 speaker(s)"
    assert _speaker_summary({}) == "? speaker(s)"


def test_uptime_is_readable_at_every_scale():
    """`yazses status` printed `uptime: 48176.17s` for a daemon up 13 hours.

    Nobody converts that in their head, and two decimal places on half a day is
    precision that was never measured. The number matters most when it is large —
    a long uptime is how you notice the daemon predates the upgrade.
    """
    from yazses.cli import _format_uptime

    assert _format_uptime(48176.17) == "13h 22m"
    assert _format_uptime(59.4) == "59s"
    assert _format_uptime(90) == "1m 30s"
    assert _format_uptime(3600) == "1h 0m"
    assert _format_uptime(0) == "0s"
    assert _format_uptime(None) == "unknown"
