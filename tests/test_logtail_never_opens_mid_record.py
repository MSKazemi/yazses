"""`yazses logs` must never open in the middle of a log record.

The defect these guard: the tail was a blind `content[-lines:]`, so whenever the
boundary fell inside a multi-line record the user's first lines were an orphaned
traceback fragment -- no timestamp, no level, no exception line. Seen on a real log,
where 14 of the 40 default lines were the tail of a `PortAudioError` whose header sat
just outside the window.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from yazses.system.logtail import _MAX_REJOIN, starts_record, tail_records

REPO = Path(__file__).resolve().parents[1]

HEADER = "2026-08-23 23:58:52,028 ERROR yazses.core.daemon: capture failed"
FRAME = '  File "/x/sounddevice.py", line 834, in __init__'
FRAME2 = "    _get_stream_parameters(kind, device, channels)"
FINAL = "sounddevice.PortAudioError: Error querying device -1"


def _record(text: str, lines: int) -> tuple[list[str], str]:
    return tail_records(text.splitlines(), lines)


# --- the pattern must track the format it claims to track -------------------------


def _daemon_log_format() -> str:
    """The format literal the daemon installs, read out of its source.

    Read rather than restated: a pattern hand-written beside a format string is exactly
    the kind of duplicated set that goes stale silently.
    """
    src = (REPO / "src" / "yazses" / "core" / "daemon.py").read_text(encoding="utf-8")
    found = re.findall(r'fmt\s*=\s*"([^"]*%\(asctime\)s[^"]*)"', src)
    assert found, "no asctime log format literal found in core/daemon.py"
    assert len(set(found)) == 1, f"daemon.py installs more than one format: {set(found)}"
    return found[0]


def test_the_record_pattern_matches_what_the_daemons_formatter_produces() -> None:
    formatter = logging.Formatter(_daemon_log_format())
    rendered = formatter.format(
        logging.LogRecord("yazses.core.daemon", logging.INFO, __file__, 1, "hi", None, None)
    )
    assert starts_record(rendered), f"pattern does not match a real record: {rendered!r}"


def test_a_traceback_frame_is_not_a_record_start() -> None:
    for line in (FRAME, FRAME2, FINAL, "", "    ^^^^^^", "Traceback (most recent call last):"):
        assert not starts_record(line), line


# --- the common case must not change ----------------------------------------------


def test_a_window_that_already_starts_at_a_record_is_unchanged() -> None:
    lines = [f"2026-08-23 23:58:5{i},000 INFO yazses: msg {i}" for i in range(9)]
    kept, note = tail_records(lines, 4)
    assert kept == lines[-4:]
    assert note == ""


def test_a_window_covering_the_whole_file_is_unchanged_even_if_it_opens_mid_record() -> None:
    # The file itself begins mid-record; asking for everything must still show everything.
    lines = [FRAME, FINAL, HEADER, "tail"]
    kept, note = tail_records(lines, 99)
    assert kept == lines
    assert note == ""


# --- the defect ---------------------------------------------------------------------


def test_a_window_that_opens_mid_traceback_is_extended_back_to_the_header() -> None:
    lines = ["2026-08-23 23:00:00,000 INFO yazses: earlier", HEADER, FRAME, FRAME2, FINAL]
    kept, note = tail_records(lines, 3)  # would have started at FRAME2
    assert kept[0] == HEADER, f"window still opens mid-record: {kept[0]!r}"
    assert starts_record(kept[0])
    assert kept == lines[1:]
    assert "more than asked" in note


def test_the_note_is_stated_exactly_when_the_slice_moved() -> None:
    clean = [f"2026-08-23 23:58:5{i},000 INFO yazses: m{i}" for i in range(5)]
    assert tail_records(clean, 3)[1] == ""
    dirty = [HEADER, FRAME, FRAME2, FINAL]
    assert tail_records(dirty, 2)[1] != ""


def test_an_orphan_beyond_the_rejoin_bound_is_dropped_not_extended() -> None:
    lines = [HEADER] + [f"  frame {i}" for i in range(_MAX_REJOIN + 50)] + [FINAL, "2026-08-23 23:59:00,000 INFO yazses: after"]
    kept, note = tail_records(lines, 5)
    assert starts_record(kept[0]), kept[0]
    assert kept[0].endswith("after")
    assert "hidden" in note


def test_a_file_that_begins_mid_record_drops_the_headerless_fragment() -> None:
    # Rotation cut the header away entirely -- there is nothing to extend back to.
    lines = [FRAME, FRAME2, FINAL, "2026-08-23 23:59:00,000 INFO yazses: after"]
    kept, note = tail_records(lines, 3)
    assert kept == ["2026-08-23 23:59:00,000 INFO yazses: after"]
    assert "hidden" in note


def test_a_window_that_is_all_continuation_says_so_rather_than_showing_nothing() -> None:
    # No record header anywhere -- a subprocess wrote raw text, or rotation kept only
    # the body. There is nothing to extend back to and nothing ahead to skip forward to.
    lines = [f"  frame {i}" for i in range(20)]
    kept, note = tail_records(lines, 3)
    assert kept == lines[-3:]
    assert "continuation" in note


def test_a_short_traceback_is_rejoined_rather_than_dropped() -> None:
    # Inside the rejoin bound the header is recovered -- the user gets more context,
    # not less. This is the branch the bound exists to *stop* at, not to prevent.
    lines = [HEADER] + [f"  frame {i}" for i in range(20)]
    kept, note = tail_records(lines, 3)
    assert kept == lines
    assert "more than asked" in note


# --- the empty-collection guard -----------------------------------------------------


@pytest.mark.parametrize("lines", [0, -1])
def test_a_non_positive_count_returns_nothing_rather_than_the_whole_file(lines: int) -> None:
    assert tail_records([HEADER, FRAME], lines) == ([], "")


def test_an_empty_log_returns_nothing() -> None:
    assert tail_records([], 40) == ([], "")


# --- the property, over every window size -------------------------------------------


def test_no_window_size_ever_opens_mid_record_without_saying_so() -> None:
    lines = (
        [f"2026-08-23 23:00:0{i},000 INFO yazses: m{i}" for i in range(5)]
        + [HEADER, FRAME, FRAME2, FINAL]
        + ["2026-08-23 23:59:00,000 INFO yazses: after", FRAME, FINAL]
    )
    for n in range(1, len(lines) + 4):
        kept, note = tail_records(lines, n)
        if not kept:
            continue
        assert starts_record(kept[0]) or note, f"n={n} opened mid-record silently: {kept[0]!r}"


def test_the_command_calls_the_helper_rather_than_slicing_directly() -> None:
    src = (REPO / "src" / "yazses" / "cli.py").read_text(encoding="utf-8")
    body = src[src.index("def logs(") :]
    body = body[: body.index("\n@app.command")]
    assert "tail_records(" in body, "logs() no longer routes through tail_records"
    assert "content[-lines:]" not in body, "logs() went back to the blind slice"
