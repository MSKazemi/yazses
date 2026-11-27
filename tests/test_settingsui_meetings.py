"""The Meetings page's decisions over real meeting folders. No Qt, no models."""
from __future__ import annotations

import json

import pytest

from yazses.settingsui import meetings


def _meeting(root, name="20261126-100000", *, status="done", transcript=True):
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "meeting.json").write_text(
        json.dumps({"id": name, "status": status, "duration_s": 125.0}), encoding="utf-8"
    )
    if transcript:
        utterances = [
            {"speaker": "speaker_0", "start": 0.0, "end": 2.0, "text": "Good morning."},
            {"speaker": "speaker_1", "start": 3.0, "end": 5.0, "text": "Hello there."},
        ]
        words = [
            {"speaker": u["speaker"], "start": u["start"], "end": u["end"], "text": u["text"]}
            for u in utterances
        ]
        (folder / "transcript.json").write_text(
            json.dumps({
                "text": "Good morning. Hello there.", "language": "en", "diarized": True,
                "utterances": utterances, "words": words,
                "speakers": {"speaker_0": "Speaker 1", "speaker_1": "Speaker 2"},
            }),
            encoding="utf-8",
        )
    return folder


def _listing(folder, **meta):
    return {"id": folder.name, "dir": str(folder), "status": "done", "duration_s": 125.0, **meta}


def test_a_row_names_the_meeting_by_date_and_length(tmp_path):
    folder = _meeting(tmp_path)
    (row,) = meetings.meeting_rows([_listing(folder)])
    assert row.title == "2026-11-26 10:00"
    assert "2m" in row.detail
    assert row.finished


def test_an_unfinished_meeting_says_so(tmp_path):
    folder = _meeting(tmp_path, status="recording", transcript=False)
    (row,) = meetings.meeting_rows([_listing(folder, status="recording", recoverable=True)])
    assert not row.finished
    assert "unfinished" in row.detail


def test_an_id_that_is_not_a_timestamp_is_shown_as_it_is(tmp_path):
    (row,) = meetings.meeting_rows([{"id": "standup", "dir": str(tmp_path)}])
    assert row.title == "standup"


def test_the_transcript_names_each_speaker(tmp_path):
    text = meetings.transcript_text(_meeting(tmp_path))
    assert "Speaker 1" in text and "Hello there." in text


@pytest.mark.parametrize("content", (None, "{ not json", "[1, 2]"))
def test_a_missing_or_corrupt_transcript_is_explained_not_raised(tmp_path, content):
    folder = _meeting(tmp_path, transcript=False)
    if content is not None:
        (folder / "transcript.json").write_text(content, encoding="utf-8")
    assert "No finished transcript" in meetings.transcript_text(folder)
    assert meetings.speakers(folder) == {}


def test_an_unfinished_meeting_shows_its_live_draft(tmp_path):
    folder = _meeting(tmp_path, transcript=False)
    (folder / "live.jsonl").write_text(
        json.dumps({"t": 1.0, "text": "draft words"}) + "\n", encoding="utf-8"
    )
    assert "draft words" in meetings.transcript_text(folder)


def test_renaming_writes_the_new_name_into_the_meeting(tmp_path):
    folder = _meeting(tmp_path)
    meetings.rename(folder, {"speaker_0": "Alice", "speaker_1": ""}, "md")
    assert meetings.speakers(folder)["speaker_0"] == "Alice"
    assert "Alice" in (folder / "transcript.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("fmt", ("txt", "md", "srt", "vtt", "json"))
def test_export_writes_a_copy_and_leaves_the_meeting_alone(tmp_path, fmt):
    folder = _meeting(tmp_path / "meetings")
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    dest = tmp_path / f"out.{fmt}"
    assert meetings.export(folder, fmt, dest) == dest
    assert "Hello there." in dest.read_text(encoding="utf-8")
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


def test_export_refuses_to_write_inside_the_meeting_folder(tmp_path):
    folder = _meeting(tmp_path)
    with pytest.raises(ValueError):
        meetings.export(folder, "md", folder / "transcript.md")


def test_the_live_view_reports_time_lines_and_a_stall():
    view = meetings.live_view({
        "ok": True, "enabled": True, "active": True, "elapsed_s": 75.4,
        "stalled_s": 20.0, "live_lines": ["one", "two"],
    })
    assert (view.active, view.clock, view.lines) == (True, "00:01:15", ("one", "two"))
    assert view.warning


def test_the_live_view_of_no_daemon_is_inactive():
    view = meetings.live_view(None)
    assert (view.active, view.running) == (False, False)


def test_finalizing_is_not_mistaken_for_idle():
    view = meetings.live_view({"ok": True, "enabled": True, "active": False, "finalizing": True})
    assert view.finalizing and not view.active


def test_the_title_reads_the_id_the_daemon_really_writes():
    """`time.strftime("%Y%m%d-%H%M%S")` in `core/daemon.py`."""
    (row,) = meetings.meeting_rows([{"id": "20261126-190401", "dir": "x"}])
    assert row.title == "2026-11-26 19:04"


def test_a_busy_daemon_is_its_own_live_state():
    view = meetings.live_view({"unresponsive": True})
    assert view.busy and not view.running and not view.active
