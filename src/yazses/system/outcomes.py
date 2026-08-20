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


#: Holding the command key is not an attempt to dictate, so those bursts are counted
#: apart from the dictation rate. Both directions of the conflation were real:
#:
#: * a command that matched **types nothing by design** and set no discard reason, so
#:   it scored as a success and *flattered* the rate;
#: * a command that matched nothing scored as a failure, and on the machine that found
#:   this (2026-08-20) four of six recent bursts were unrecognised commands, so
#:   `yazses status` read `typed: 0 of 6 recent bursts (0%)` while dictation was
#:   healthy — beside a microphone warning, which is the worst possible pairing.
#:
#: The documented promise is "how often **dictation** actually produced text", and it
#: enumerates what counts against it as "silence, an empty transcription, no text
#: target" — every one a dictation-path failure. The daemon already stamped
#: `event["command_mode"]`; the gauge one module away simply never asked.
COMMAND_UNRECOGNISED = {"command_unmatched", "command_no_text_target"}


class OutcomeWindow:
    """Recent per-burst outcomes. Not thread-safe; the daemon records under its lock."""

    def __init__(self, window: int = DEFAULT_WINDOW) -> None:
        self._outcomes: deque[str] = deque(maxlen=window)
        self._commands: deque[str] = deque(maxlen=window)

    def record(self, outcome: str, *, command: bool = False) -> None:
        """Note one finished burst. Any string is accepted and counted.

        A future discard reason must show up in the totals rather than being
        dropped for not being on a list — an outcome nobody counted is exactly how
        a failure mode stays invisible.

        ``command`` says the dedicated command key was held, which makes the burst an
        instruction rather than an attempt to dictate. It is counted either way; the
        two are just never averaged together.
        """
        value = str(outcome or "unknown")
        (self._commands if command else self._outcomes).append(value)

    def as_dict(self) -> dict:
        counts = Counter(self._outcomes) + Counter(self._commands)
        commands = Counter(self._commands)
        return {
            # `total`/`typed`/`counts` keep their old meaning — every burst, however
            # it was started. A status bar reading them must not change behaviour
            # because a field was added beside them.
            "total": len(self._outcomes) + len(self._commands),
            "typed": counts.get(TYPED, 0),
            "counts": dict(counts),
            "dictation_total": len(self._outcomes),
            "dictation_typed": Counter(self._outcomes).get(TYPED, 0),
            "command_total": len(self._commands),
            "command_unrecognised": sum(
                n for reason, n in commands.items() if reason in COMMAND_UNRECOGNISED
            ),
        }


def describe_outcomes(data: dict | None) -> list[str]:
    """Lines for `yazses status`; empty when there is not enough to say. Pure.

    Returns a list because a machine that both dictates and uses the command key has
    two independent things to report, and averaging them produces a number that
    describes neither.
    """
    if not data:
        return []

    lines: list[str] = []
    if "dictation_total" in data:
        total = int(data.get("dictation_total") or 0)
        typed = int(data.get("dictation_typed") or 0)
        label = "recent dictation bursts"
    else:
        # An older daemon sends only the combined totals. It cannot tell the two kinds
        # apart, so neither can this: report what it sent, and do not call the result
        # a dictation rate, which would be a claim the payload cannot support.
        total = int(data.get("total") or 0)
        typed = int(data.get("typed") or 0)
        label = "recent bursts"

    if total >= MIN_SAMPLES:
        pct = round(100 * typed / total)
        lines.append(f"  typed:    {typed} of {total} {label} ({pct}%)")

    commands = int(data.get("command_total") or 0)
    if commands:
        # Reported whatever the dictation count is: below MIN_SAMPLES the rate above
        # is withheld, and that is exactly when a run of unrecognised commands would
        # otherwise leave no trace on the surface at all.
        unrecognised = int(data.get("command_unrecognised") or 0)
        lines.append(
            f"  commands: {commands} recent command burst(s), {unrecognised} unrecognised"
        )
    return lines


def classify_outcome(discard_reason: str | None, *, pipeline_failed: bool) -> str:
    """What became of one burst: a discard reason, ``error``, or ``typed``. Pure.

    ``discard_reason`` is set on every path that *decides* not to type. It is not
    set when something raises -- an injection that fails, a backend that went away
    -- because that lands in the pipeline's ``except`` handler, which records
    ``last_error`` instead. Counting those as ``typed`` made the gauge report
    failures as successes, which is worse than having no gauge: it is consulted
    exactly when something is wrong.

    ``event["injected"]`` cannot stand in for this. It is set *before* dispatch, so
    it records the intention to type rather than the result.

    A real discard reason wins over ``error``, because "the transcript was empty" is
    more useful than "something raised afterwards".
    """
    if discard_reason:
        return str(discard_reason)
    return "error" if pipeline_failed else TYPED
