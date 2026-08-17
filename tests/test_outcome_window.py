"""Recent dictation outcomes, summarised — the companion to decode latency.

`stt/latency.py` exists because decode time "has always been measured and logged
but was never summarised, so the one number that predicts whether dictation feels
usable was only available by reading a log by eye". Exactly the same is true of
whether a burst produced any text at all, and that number is the more basic one:
a fast decode that types nothing is not usable at all.

This was written after reading a real machine's log by hand to answer "is
dictation working here?", and finding that it had degraded from 21 typed of 30
bursts to 6 of 14 — a doubling of the failure rate that nothing in YazSes
reported, on a machine whose owner was actively trying to dictate.
"""
from __future__ import annotations

from yazses.system.outcomes import DEFAULT_WINDOW, OutcomeWindow, describe_outcomes


def test_counts_what_happened_to_recent_bursts():
    w = OutcomeWindow()
    for _ in range(6):
        w.record("typed")
    for _ in range(7):
        w.record("empty")
    w.record("silent")

    d = w.as_dict()
    assert d["total"] == 14
    assert d["typed"] == 6
    assert d["counts"]["empty"] == 7
    assert d["counts"]["silent"] == 1


def test_the_window_is_bounded_and_recent():
    """A lifetime average hides a degradation; the recent window is the point."""
    w = OutcomeWindow(window=10)
    for _ in range(50):
        w.record("typed")
    for _ in range(10):
        w.record("empty")
    d = w.as_dict()
    assert d["total"] == 10, "the window must forget older bursts"
    assert d["typed"] == 0, f"ten failures in a row must read as zero success: {d}"


def test_nothing_to_say_before_there_is_evidence():
    """One failed burst is not a trend, and reporting 0% after it would be alarming.

    The same restraint `latency.py` applies to p95: a number the data cannot yet
    support is worse than no number, because it will be believed.
    """
    w = OutcomeWindow()
    assert describe_outcomes(w.as_dict()) is None
    w.record("empty")
    assert describe_outcomes(w.as_dict()) is None


def test_it_reports_once_there_is_enough_to_mean_something():
    w = OutcomeWindow()
    for _ in range(6):
        w.record("typed")
    for _ in range(7):
        w.record("empty")
    line = describe_outcomes(w.as_dict())
    assert line is not None
    assert "6" in line and "13" in line, line
    assert "46%" in line, f"expected the rate, got {line!r}"


def test_a_healthy_run_still_reports():
    """Not a warning — a number. It is how you notice a change from 100% to 70%."""
    w = OutcomeWindow()
    for _ in range(20):
        w.record("typed")
    line = describe_outcomes(w.as_dict())
    assert line is not None and "100%" in line, line


def test_the_default_window_covers_a_working_session_not_a_lifetime():
    assert 20 <= DEFAULT_WINDOW <= 200, DEFAULT_WINDOW


def test_an_unknown_outcome_is_counted_rather_than_dropped():
    """A new discard reason must not silently vanish from the totals."""
    w = OutcomeWindow()
    w.record("typed")
    w.record("some_future_reason")
    d = w.as_dict()
    assert d["total"] == 2
    assert d["counts"]["some_future_reason"] == 1
