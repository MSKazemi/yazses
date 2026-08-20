"""Four meetings listed as four bare timestamps, and the length was on disk all along.

Measured on a real machine, 2026-08-20 — `yazses meeting list`:

    20260819-033515  not diarized  …/20260819-033515
    20260814-065156  not diarized  …/20260814-065156
    20260803-095635  not diarized  …/20260803-095635
    20260710-212029  not diarized  …/20260710-212029

The four `meeting.json` files beside them held `duration_s` of **11.6, 26.6, 56.7 and
8081.4** — one real two-hour meeting and three accidental starts. Finding the real one is
what a person opens this list to do, and it took opening four files.

Why it stayed missing is the more useful half: the row was **three copies of one
f-string** (`meeting status` has two branches, `meeting list` has one), so adding a column
meant remembering three places. `_speaker_summary`'s own docstring even cites the 8081-second
meeting — that fix touched the speaker column and left the duration beside it. These tests
pin the fact *and* the single renderer, because the duplication is the actual defect.
"""
from __future__ import annotations

import ast
import inspect

import pytest

from yazses.cli import _format_uptime, _meeting_row
from yazses.meeting.store import duration_summary


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0.0, "0s"),
        (11.6, "11s"),
        (56.7, "56s"),
        (59.9, "59s"),
        (60.0, "1m 0s"),
        (3599, "59m 59s"),
        (3600, "1h 0m"),
        (8081.4, "2h 14m"),
    ],
)
def test_a_length_reads_at_a_glance(seconds, expected):
    assert duration_summary({"duration_s": seconds}) == expected


@pytest.mark.parametrize("meta", [{}, {"duration_s": None}, {"duration_s": "soon"}, {"duration_s": -5}])
def test_an_unrecorded_length_says_nothing_rather_than_guessing(meta):
    """A meeting that never finalized has no `meeting.json`; its row already says why."""
    assert duration_summary(meta) == ""


def test_a_meeting_that_recorded_nothing_still_shows_its_zero():
    """Not the same as unrecorded — a zero-length meeting is worth seeing."""
    assert duration_summary({"duration_s": 0}) == "0s"


@pytest.mark.parametrize("seconds", [0, 1, 59, 60, 61, 3599, 3600, 8081, 100000])
def test_the_two_formatters_agree(seconds):
    """Two formatters for one idea is how surfaces drift; they differ only on 'missing'."""
    assert duration_summary({"duration_s": seconds}) == _format_uptime(seconds)


# --- the row -------------------------------------------------------------------


def test_the_row_carries_every_column():
    row = _meeting_row(
        {"id": "20260803-095635", "duration_s": 8081.4, "diarized": True,
         "num_speakers": 3, "has_notes": True, "dir": "/m/20260803-095635"}
    )
    assert "20260803-095635" in row
    assert "2h 14m" in row
    assert "3 speaker(s)" in row
    assert "+notes" in row
    assert "/m/20260803-095635" in row


def test_the_real_meeting_is_distinguishable_from_the_accidental_ones():
    """The measured case, as the list a person actually reads."""
    metas = [
        {"id": "a", "duration_s": 11.6, "diarized": False, "dir": "/a"},
        {"id": "b", "duration_s": 26.6, "diarized": False, "dir": "/b"},
        {"id": "c", "duration_s": 8081.4, "diarized": False, "dir": "/c"},
        {"id": "d", "duration_s": 56.7, "diarized": False, "dir": "/d"},
    ]
    rows = [_meeting_row(m) for m in metas]
    assert len({r.split("  ")[1] for r in rows}) == 4, (
        f"the rows do not tell the meetings apart: {rows}"
    )
    assert "2h 14m" in rows[2]


def test_an_unfinished_meeting_gains_no_second_word_for_the_same_fact():
    row = _meeting_row({"id": "x", "recoverable": True, "dir": "/x"})
    assert "unfinished" in row
    assert "unknown" not in row


def test_a_meeting_without_notes_says_nothing_about_notes():
    assert "+notes" not in _meeting_row({"id": "x", "duration_s": 5, "dir": "/x"})


def test_there_is_exactly_one_place_that_renders_a_meeting_row():
    """The guard on the defect itself, not just its symptom.

    Three copies is why a recorded fact went unprinted for as long as it did. If a
    fourth listing appears and builds its own line, this fails before the next column
    can go missing from it.
    """
    from yazses import cli

    tree = ast.parse(inspect.getsource(cli))
    callers = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_speaker_summary"
    }
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_speaker_summary"
    ]
    assert callers and len(calls) == 1, (
        f"`_speaker_summary` is called {len(calls)} times in cli.py; every meeting "
        f"listing must go through `_meeting_row` so a column cannot be added to one "
        f"list and forgotten in the others."
    )
