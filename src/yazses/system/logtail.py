"""Slice the tail of the daemon log without opening in the middle of a record.

`yazses logs` used to be `content[-lines:]` — a blind line slice. A log record is not
one line: the daemon logs exceptions, and a Python traceback is thirty lines under a
single header. Whenever the slice boundary landed inside one, the first thing a user
saw was an orphaned stack fragment with no timestamp, no level, and no exception line
above it — decapitated, and therefore *misattributed*: it looks like the newest failure
when it is the oldest thing in the window. Observed on a real log, where 14 of the 40
default lines were the tail of a `PortAudioError` whose header sat just outside.

So the boundary is moved to a record edge. Extending **backwards** is preferred over
dropping, because the point of the command is diagnosis and the header is the half that
says what the daemon was doing; a traceback is tens of lines, so the cost is bounded.
Dropping is the fallback for the two cases where extending cannot work — the file itself
begins mid-record (rotation cut it) or the header is absurdly far back.

Either way the adjustment is **stated**, never silent: the user asked for N lines and is
getting a different number, and a diagnostic tool that quietly changes what it was asked
for is the wrong tool to be holding during a failure.
"""

from __future__ import annotations

import re

#: A record begins with `logging`'s default `asctime` — `%(asctime)s %(levelname)s …`,
#: the format string every YazSes entry point installs. Continuation lines (traceback
#: frames, wrapped messages) never carry it, which is exactly what makes them findable.
#: `tests/test_logtail_never_opens_mid_record.py` formats a real `LogRecord` with the
#: format literal read out of `core/daemon.py` and asserts this matches it, so the
#: pattern cannot drift away from the format it is meant to track.
_RECORD_START = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} ")

#: How far back the window may be extended to recover a record's header. A traceback is
#: tens of lines; beyond this the "record" is more likely a log with no header at all
#: (a rotated file, or a subprocess writing raw text), and extending would show the user
#: hundreds of lines they did not ask for.
_MAX_REJOIN = 200


def starts_record(line: str) -> bool:
    """True when `line` begins a log record rather than continuing one."""
    return _RECORD_START.match(line) is not None


def tail_records(all_lines: list[str], lines: int) -> tuple[list[str], str]:
    """Return the last `lines` lines, moved to a record boundary, plus a note.

    The note is empty when the plain slice already began at a record — the common case,
    which must stay byte-identical to the old behaviour. Otherwise it names the
    adjustment, because the caller printed a different number of lines than was asked.
    """
    if lines <= 0 or not all_lines:
        return [], ""
    start = max(0, len(all_lines) - lines)
    if start == 0 or starts_record(all_lines[start]):
        return all_lines[start:], ""

    back = start
    while back > 0 and not starts_record(all_lines[back]):
        back -= 1
    if starts_record(all_lines[back]) and start - back <= _MAX_REJOIN:
        extra = start - back
        return all_lines[back:], (
            f"(showing {extra} line(s) more than asked: the window opened inside a log "
            f"record, so it was extended back to where that record starts.)"
        )

    forward = start
    while forward < len(all_lines) and not starts_record(all_lines[forward]):
        forward += 1
    if forward >= len(all_lines):
        return all_lines[start:], (
            "(no line in this window begins a log record -- it is all continuation "
            "text. Raise --lines to reach the record it belongs to.)"
        )
    hidden = forward - start
    return all_lines[forward:], (
        f"({hidden} leading line(s) hidden: they continue a log record that begins "
        f"before this window. Raise --lines to include it.)"
    )
