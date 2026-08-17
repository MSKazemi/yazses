"""What recently happened to your dictation, summarised (companion to #296).

`stt/latency.py` exists because decode time "has always been measured and logged
but was never summarised, so the one number that predicts whether dictation feels
usable was only available by reading a log by eye". The same was true of the more
basic number — whether a burst produced any text at all — and a fast decode that
types nothing is not usable at all.

Written after reading a real machine's log by hand to answer *is dictation working
here?*: it had gone from 21 typed of 30 bursts to 6 of 14 over about six hours, a
doubling of the failure rate that nothing in YazSes reported while its owner was
actively trying to dictate. The per-burst outcome was in the log the whole time.

## Why a bounded window, and not a lifetime rate

A lifetime average is dominated by history and moves too slowly to show a change
that started this morning — which is precisely the case worth catching. The window
is short enough that a degradation shows up within a working session.

## Why it reports on a healthy run too

It is a number, not a warning. Something that only appears when things are bad is
something you have no baseline for, so you cannot tell 70% from 100% when it
matters. Guards that only fire on trouble are elsewhere; this is a gauge.
"""
from __future__ import annotations

from collections import Counter, deque

#: Bursts kept. Long enough to be more than noise, short enough that a change
#: within one working session is visible rather than averaged away.
DEFAULT_WINDOW = 50

#: Below this, say nothing. A single failed burst is not a trend, and printing
#: "0% of 1" would be believed — the same restraint `latency.py` applies to p95.
MIN_SAMPLES = 5

#: The outcome that means text reached the window.
TYPED = "typed"


class OutcomeWindow:
    """Recent per-burst outcomes. Not thread-safe; the daemon records under its lock."""

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        self._outcomes: deque[str] = deque(maxlen=window)

    def record(self, outcome: str) -> None:
        """Note one finished burst. Any string is accepted and counted.

        A future discard reason must show up in the totals rather than being
        dropped for not being on a list — an outcome nobody counted is exactly how
        a failure mode stays invisible.
        """
        self._outcomes.append(str(outcome or "unknown"))

    def as_dict(self) -> dict:
        counts = Counter(self._outcomes)
        return {
            "total": len(self._outcomes),
            "typed": counts.get(TYPED, 0),
            "counts": dict(counts),
        }


def describe_outcomes(data: dict | None) -> str | None:
    """One line for `yazses status`, or None when there is not enough to say. Pure."""
    if not data:
        return None
    total = int(data.get("total") or 0)
    if total < MIN_SAMPLES:
        return None
    typed = int(data.get("typed") or 0)
    pct = round(100 * typed / total)
    return f"  typed:    {typed} of {total} recent bursts ({pct}%)"
