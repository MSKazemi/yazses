"""What the Meetings page shows about stored and running meetings. Pure beside the disk.

Reads and writes only through ``meeting/store.py``, so a rename here and
``yazses meeting relabel`` are the same operation. Nothing in this module loads a model.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from yazses.recimport.render import VALID_FORMATS, render_transcript

#: The daemon's ids are ``%Y%m%d-%H%M%S``; a dashed date is accepted too.
_STAMP = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})[_T-](\d{2})-?(\d{2})")

#: A running meeting that has heard nothing for this long is worth saying out loud.
_STALL_WARNING_S = 10.0

NO_TRANSCRIPT = "No finished transcript for this meeting."
BUSY = (
    "The names were not saved: this meeting is still being processed, or a "
    "`yazses meeting` command is working on it. Try again when it has finished."
)


@dataclass(frozen=True)
class MeetingRow:
    id: str
    title: str
    detail: str
    dir: str
    finished: bool


@dataclass(frozen=True)
class LiveView:
    running: bool = False        # the daemon answered
    busy: bool = False           # alive, but did not answer in time
    enabled: bool = False
    active: bool = False
    finalizing: bool = False
    clock: str = "00:00:00"
    lines: tuple[str, ...] = ()
    warning: str = ""


def _title(meeting_id: str) -> str:
    match = _STAMP.match(meeting_id)
    if not match:
        return meeting_id
    year, month, day, hour, minute = match.groups()
    return f"{year}-{month}-{day} {hour}:{minute}"


def meeting_rows(listing: Sequence[Mapping[str, Any]]) -> list[MeetingRow]:
    """One row per ``store.list_meetings`` entry, in its order (newest first)."""
    from yazses.meeting.store import duration_summary

    rows = []
    for meta in listing:
        meeting_id = str(meta.get("id") or "")
        finished = meta.get("status") == "done"
        parts = [duration_summary(dict(meta))]
        if not finished:
            # A meeting someone holds is running, not failed (as `meeting list` says).
            parts.append("in progress" if meta.get("busy") else "unfinished")
        elif meta.get("quality_suspect"):
            parts.append("check the quality")
        rows.append(MeetingRow(
            meeting_id, _title(meeting_id), " · ".join(p for p in parts if p),
            str(meta.get("dir") or ""), finished,
        ))
    return rows


def _view(meeting_dir: str | Path) -> Any:
    """The canonical transcript, or ``None`` when it is missing or unreadable."""
    from yazses.meeting.store import load_result_view

    try:
        return load_result_view(meeting_dir)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def transcript_text(meeting_dir: str | Path) -> str:
    """The speaker-labelled transcript; else the live draft; else a sentence saying why."""
    view = _view(meeting_dir)
    if view is not None:
        return render_transcript(view, "txt") or NO_TRANSCRIPT
    from yazses.meeting.store import live_text

    try:
        draft = live_text(meeting_dir)
    except (OSError, ValueError):
        draft = ""
    if draft:
        return f"{NO_TRANSCRIPT} This is the live draft:\n\n{draft}"
    return (
        f"{NO_TRANSCRIPT} If it did not finish, `yazses meeting recover` can retry it "
        "while the recording is still there."
    )


def speakers(meeting_dir: str | Path) -> dict[str, str]:
    """``{cluster id: current display name}`` in order of first appearance."""
    view = _view(meeting_dir)
    if view is None or not view.diarized:
        return {}
    found: dict[str, str] = {}
    for utterance in view.utterances:
        key = utterance.speaker
        if key and key not in found:
            found[key] = view.speaker_names.get(key) or key
    return found


def rename(meeting_dir: str | Path, names: Mapping[str, str], fmt: str) -> None:
    """Apply the non-empty *names* and re-render, as ``yazses meeting relabel`` does.

    Holds the meeting's lock, and raises ``MeetingBusyError``, changing nothing, while
    the daemon or a ``yazses meeting`` command holds it.
    """
    from yazses.meeting.lock import MeetingLock
    from yazses.meeting.store import relabel

    renames = {k: v.strip() for k, v in names.items() if v.strip()}
    if renames:
        with MeetingLock(meeting_dir):
            relabel(meeting_dir, renames=renames, fmt=fmt)


def export(meeting_dir: str | Path, fmt: str, dest: str | Path) -> Path:
    """Write the transcript as *fmt* to *dest*, never inside the meeting folder."""
    if fmt not in VALID_FORMATS:
        raise ValueError(f"Unknown format {fmt!r}.")
    dest = Path(dest)
    folder = Path(meeting_dir).resolve()
    if dest.resolve().is_relative_to(folder):
        raise ValueError("Choose a place outside the meeting's own folder.")
    view = _view(meeting_dir)
    if view is None:
        raise ValueError(NO_TRANSCRIPT)
    from yazses.system.private_files import write_private_text

    # The folder is one the user picked (their home, a shared folder): not ours to restrict.
    write_private_text(dest, render_transcript(view, fmt), tighten_parent=False)
    return dest


def clock(seconds: object) -> str:
    try:
        total = max(0, int(float(seconds)))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        total = 0
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def live_view(reply: Mapping[str, Any] | None) -> LiveView:
    """A ``meeting_status`` reply, or nothing, as the page shows it."""
    if reply is None:
        return LiveView()
    if reply.get("unresponsive"):
        return LiveView(busy=True)
    try:
        stalled = float(reply.get("stalled_s") or 0.0)
    except (TypeError, ValueError):
        stalled = 0.0
    active = bool(reply.get("active"))
    warning = ""
    if active and stalled >= _STALL_WARNING_S:
        warning = f"No audio for {int(stalled)} seconds. Check the microphone."
    lines = reply.get("live_lines")
    return LiveView(
        running=True,
        enabled=bool(reply.get("enabled")),
        active=active,
        finalizing=bool(reply.get("finalizing")),
        clock=clock(reply.get("elapsed_s")),
        lines=tuple(str(line) for line in lines) if isinstance(lines, list) else (),
        warning=warning,
    )
