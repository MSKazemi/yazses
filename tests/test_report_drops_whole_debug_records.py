"""A DEBUG record's body must not survive its own header being dropped.

`system/report.py` builds a bundle meant to be attached to a public issue, and its own
docstring calls it safe **by construction**. It dropped lines containing ` DEBUG `. But a
log record is not one line -- every `exc_info=True` call writes a header plus a traceback
-- and the header is the only line carrying the level. So the filter removed the header
and kept the body: the frames, and the exception message, of a record it had just judged
unsafe to share. Reproduced before the fix: two DEBUG headers removed, five of their own
lines emitted, and the bundle stating "2 DEBUG line(s) omitted".
"""

from __future__ import annotations

import pathlib

from yazses.system.report import _CONTENT_LEVEL, _log_tail

INFO = "2026-08-24 10:00:00,000 INFO yazses.core.daemon: Recording started"
DEBUG = "2026-08-24 10:00:01,000 DEBUG yazses.core.daemon: Injecting text: 'my bank PIN'"
DONE = "2026-08-24 10:00:03,000 INFO yazses.core.daemon: done"
BODY = [
    "Traceback (most recent call last):",
    '  File "x.py", line 1, in <module>',
    "ValueError: while correcting 'my private sentence'",
]


def _tail(tmp_path: pathlib.Path, lines: list[str], n: int = 40) -> list[str]:
    log = tmp_path / "daemon.log"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _log_tail(log, n)


def test_the_level_this_guards_is_the_one_the_module_declares() -> None:
    assert _CONTENT_LEVEL == "DEBUG"


def test_a_debug_records_traceback_does_not_survive_its_header(tmp_path) -> None:
    out = _tail(tmp_path, [INFO, DEBUG, *BODY, DONE])
    joined = "\n".join(out)
    assert "my private sentence" not in joined, "a dropped record's body was emitted"
    assert "Traceback" not in joined
    assert "my bank PIN" not in joined
    # ...and the records that were safe are still there.
    assert any("Recording started" in line for line in out)
    assert any("done" in line for line in out)


def test_the_count_matches_what_was_actually_removed(tmp_path) -> None:
    out = _tail(tmp_path, [INFO, DEBUG, *BODY, DONE])
    note = next(line for line in out if "omitted" in line)
    assert "4 line(s)" in note, f"count does not match the 4 removed lines: {note}"
    assert "DEBUG" in note


def test_a_multi_line_info_record_is_kept_whole(tmp_path) -> None:
    # The filter drops records by level, not multi-line records in general.
    lines = [INFO, "  a continuation of the INFO record", DONE]
    out = _tail(tmp_path, lines)
    assert any("a continuation of the INFO record" in line for line in out)
    assert not any("omitted" in line for line in out)


def test_a_window_opening_inside_a_debug_record_drops_the_orphan(tmp_path) -> None:
    # Rotation cut the header away: the body's level cannot be seen, so it cannot be
    # shown to be safe. Something in the window does start a record, so the format holds.
    out = _tail(tmp_path, [*BODY, DONE], n=len(BODY) + 1)
    joined = "\n".join(out)
    assert "my private sentence" not in joined
    assert any("done" in line for line in out)


def test_a_log_with_no_record_headers_at_all_is_still_reported(tmp_path) -> None:
    # Not this format -- there are no level-tagged records to protect against, and
    # emptying the bundle would not protect anyone. `redact_text` remains the guard.
    plain = [f"plain line {i}" for i in range(6)]
    out = _tail(tmp_path, plain)
    assert len(out) == len(plain), out
    assert not any("omitted" in line for line in out)


def test_the_scrubber_still_runs_on_what_is_kept(tmp_path) -> None:
    home = str(pathlib.Path.home())
    out = _tail(tmp_path, [f"2026-08-24 10:00:00,000 INFO yazses: at {home}/secret"])
    assert home not in "\n".join(out)


def test_nothing_is_said_when_nothing_was_removed(tmp_path) -> None:
    out = _tail(tmp_path, [INFO, DONE])
    assert not any("omitted" in line for line in out)


def test_the_fixture_reproduces_the_pre_fix_leak(tmp_path) -> None:
    """The old filter, applied to this fixture, really did emit the body.

    Without this the tests above could pass against a fixture that never exercised the
    defect -- a green mutation usually means the fixture is not the case under test.
    """
    lines = [INFO, DEBUG, *BODY, DONE]
    old_kept = [line for line in lines if f" {_CONTENT_LEVEL} " not in line]
    assert "ValueError: while correcting 'my private sentence'" in old_kept
    assert len(lines) - len(old_kept) == 1, "the old filter removed only the header"
