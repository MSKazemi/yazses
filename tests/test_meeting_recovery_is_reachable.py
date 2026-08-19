"""A meeting that crashed mid-way must be readable, and must be mentioned.

`session.py` streams every finalized live line to `live.jsonl` all through a meeting, and
`append_live_line`'s docstring says why: *"so a daemon crash mid-meeting still leaves a
partial transcript on disk"*. `list_meetings` then sets ``recoverable: True`` on any
meeting that never finalized but left that file.

Two things were wrong with the other end of that.

**The reader could not read it.** `read_live_lines` decoded with strict UTF-8, outside its
`try`. A write cut in the middle of a multi-byte character — which is exactly how this
file gets damaged, since the whole point is that the process died mid-write — made the
decode raise `UnicodeDecodeError` for the **entire file**, discarding every complete line
before the tear along with it. The recovery artefact was unreadable in the one situation
it exists for.

**Nothing mentioned it.** `read_live_lines` had no callers anywhere in `src/`, and
`yazses meeting list` — the only place `recoverable` would ever be seen — computed the
flag and printed the meeting without it. There is no `meeting recover` command either. So
an hour-long meeting cut short by a crash left its partial transcript on disk with nothing
in the product acknowledging it existed.

The listing now says so and reports how many lines are there. Whether a dedicated
`meeting recover` command should exist is a separate, larger question; this makes the data
findable, which it was not.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from yazses.meeting import store


class _Cfg:
    def __init__(self, root: Path):
        self.output_dir = str(root)


@pytest.fixture
def meeting_dir(tmp_path) -> Path:
    d = tmp_path / "2026-08-19-1000"
    d.mkdir(parents=True)
    store.write_meta(d, {"id": "2026-08-19-1000", "status": "recording"})
    return d


def test_a_torn_write_does_not_lose_the_whole_file(meeting_dir: Path) -> None:
    """The crash this file exists for must not be the crash that destroys it."""
    store.append_live_line(meeting_dir, "we were discussing the budget")
    store.append_live_line(meeting_dir, "unicode survives: héllo — ünïcode")
    # A write cut mid-character: a lone UTF-8 lead byte with no continuation.
    with (meeting_dir / "live.jsonl").open("ab") as fh:
        fh.write(b'{"text": "tor\xc3')

    rows = store.read_live_lines(meeting_dir)
    assert [r["text"] for r in rows] == [
        "we were discussing the budget",
        "unicode survives: héllo — ünïcode",
    ], "a torn final line took the readable ones with it"


def test_a_truncated_json_line_is_still_skipped(meeting_dir: Path) -> None:
    """The pre-existing guard must survive the decode change."""
    store.append_live_line(meeting_dir, "good line")
    with (meeting_dir / "live.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"text": "half a rec')
    assert [r["text"] for r in store.read_live_lines(meeting_dir)] == ["good line"]


def test_an_absent_file_is_empty_not_an_error(tmp_path) -> None:
    assert store.read_live_lines(tmp_path) == []


def test_an_unfinished_meeting_is_flagged_recoverable(tmp_path, meeting_dir: Path) -> None:
    store.append_live_line(meeting_dir, "something was said")
    listed = store.list_meetings(_Cfg(tmp_path))
    assert listed and listed[0].get("recoverable") is True
    assert len(store.read_live_lines(listed[0]["dir"])) == 1


def test_a_finished_meeting_is_not_flagged(tmp_path, meeting_dir: Path) -> None:
    """A guard that flagged everything would make the warning noise."""
    store.write_meta(meeting_dir, {"id": "x", "status": "done"})
    store.append_live_line(meeting_dir, "something was said")
    listed = store.list_meetings(_Cfg(tmp_path))
    assert listed and not listed[0].get("recoverable")


def test_the_listing_actually_mentions_it() -> None:
    """The flag was computed and dropped at the one place a user would see it.

    Read out of the source rather than driven, because the command loads real config and
    the platform paths; what matters is that the branch consults `recoverable` and reads
    the lines at all. The behaviour it depends on is covered above.
    """
    from yazses import cli

    source = inspect.getsource(cli)
    assert 'm.get("recoverable")' in source, "meeting list still ignores the flag"
    assert "read_live_lines" in source, (
        "nothing in the CLI reads the recovery file — it had no caller in src/ at all"
    )


def test_the_writer_is_wired_so_the_file_exists_to_recover() -> None:
    """The premise. Without the writer, none of the above matters."""
    from yazses.meeting import session

    assert "append_live_line" in inspect.getsource(session), (
        "the session no longer streams live lines, so there is nothing to recover"
    )
