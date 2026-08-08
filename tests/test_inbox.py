"""The maintainer inbox must not lose a thread, and must not invent one.

`scripts/inbox.py` answers "what have I not replied to?". Its network half is a thin
`gh` wrapper; its decisions are pure and live here. The case worth pinning hardest is
the one that caused this script to exist: a thread with **zero comments**, opened by
somebody else, is waiting on you — and every "find threads with comments" filter,
including the ad-hoc one that first found the gap, silently misses it.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("inbox", ROOT / "scripts" / "inbox.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # Registered before exec: @dataclass resolves annotations via sys.modules, and a
    # module loaded straight from a path is not there unless we put it there.
    sys.modules["inbox"] = mod
    spec.loader.exec_module(mod)
    return mod


inbox = _load()
ME = "MSKazemi"


def test_zero_comment_thread_from_a_stranger_is_waiting():
    """The regression this script exists for: no comments does not mean no obligation."""
    assert inbox.waiting(thread_author="YossiMH", last_speaker=None, me=ME)


def test_my_own_thread_with_no_replies_is_not_waiting():
    """An announcement nobody answered is not a task — it would drown the real ones."""
    assert not inbox.waiting(thread_author=ME, last_speaker=None, me=ME)


@pytest.mark.parametrize(
    "last_speaker,expected",
    [("YossiMH", True), (ME, False), ("waterlemonnn", True)],
)
def test_last_word_decides(last_speaker, expected):
    assert inbox.waiting("someone", last_speaker, ME) is expected


def test_my_reply_after_theirs_clears_the_thread():
    assert not inbox.waiting("YossiMH", ME, ME)


@pytest.mark.parametrize(
    "login,expected",
    [
        ("dependabot[bot]", True),
        ("github-actions[bot]", True),
        ("Dependabot", True),
        ("YossiMH", False),
        ("waterlemonnn", False),
    ],
)
def test_bot_detection(login, expected):
    assert inbox.is_bot(login) is expected


def test_age_days_handles_the_rest_api_z_suffix():
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    assert inbox.age_days("2026-08-07T12:00:00Z", now=now) == pytest.approx(2.0)


def test_age_days_handles_graphql_offset_form():
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    assert inbox.age_days("2026-08-08T12:00:00+00:00", now=now) == pytest.approx(1.0)


def test_oldest_silence_ranks_first():
    """A thread rots by how long it has been ignored, not by issue number."""
    old = inbox.Thread("issue", 1, "old", "a", "2026-08-01T00:00:00Z")
    new = inbox.Thread("issue", 999, "new", "b", "2026-08-08T00:00:00Z")
    assert [t.number for t in inbox.rank([new, old])] == [1, 999]


def test_render_says_so_plainly_when_nothing_is_waiting():
    out = inbox.render([], "MSKazemi/yazses")
    assert "Nothing is waiting on you" in out


def test_render_links_each_kind_to_the_right_url():
    now = datetime.now(timezone.utc)
    stamp = (now - timedelta(days=1)).isoformat()
    threads = [
        inbox.Thread("issue", 103, "EMG", "YossiMH", stamp),
        inbox.Thread("pr", 143, "vectors", "waterlemonnn", stamp),
        inbox.Thread("review", 144, "inline", "waterlemonnn", stamp),
        inbox.Thread("discussion", 129, "thanks", "slegarraga", stamp),
    ]
    out = inbox.render(threads, "MSKazemi/yazses")
    assert "/issues/103" in out
    assert "/pull/143" in out
    assert "/pull/144" in out       # a review thread lives on the PR, not on /issues
    assert "/discussions/129" in out


def test_render_flags_a_thread_left_for_days():
    now = datetime.now(timezone.utc)
    stale = inbox.Thread("issue", 98, "design review", "YossiMH",
                         (now - timedelta(days=5)).isoformat())
    fresh = inbox.Thread("issue", 99, "just now", "YossiMH",
                         (now - timedelta(hours=2)).isoformat())
    assert "🔴" in inbox.render([stale], "r/r")
    assert "🔴" not in inbox.render([fresh], "r/r")
