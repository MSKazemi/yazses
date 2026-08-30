"""The measured residue of the self-correction rollback, so it cannot grow in silence.

`_trigger_is_negated` consults the single word before a trigger and asks whether it
makes the trigger part of a phrase rather than an interjection. Three closed classes
answer that today: negations and modals, determiners/reporting verbs/copulas, and
nominative pronouns.

What is left is an **open** class. A plural common noun as the subject reads exactly
like the pronoun case and cannot be enumerated::

    "children never mind the cold at all"       ->  "the cold at all"
    "students forget that lesson by the summer" ->  "lesson by the summer"

and the filter's own docstring names that output as the worst it can produce: it does
not garble the meaning, it inverts it.

**Why this is a ledger and not a fix.** The word before a *genuine* correction is the
object being replaced, and it is a bare noun -- "send it to bob scratch that send it
to alice" turns on `bob`, "open the config file delete that ..." on `file`. So a rule
that suppressed rollback after any noun would break real corrections, and the module
states its policy for exactly this situation: the residual ambiguity is "tracked as a
known gap rather than guessed at". A guess here is not neutral -- every entry in
those lists trades a missed rollback, which the user can see and fix, against a wrong
one, which silently destroys meaning.

So this file records the cases that are known to be wrong, the same shape as
`test_orphan_modules.py` and `test_config_keys_are_read.py`: the suite passes today
and fails the moment the list is wrong in either direction -- a seventh case
appearing, or one of these six finally being fixed and its entry going stale.

Both halves matter. The second parametrization is what stops the file becoming a
monument to a bug that was fixed years ago and never delisted.
"""

from __future__ import annotations

import pytest

from yazses.config import DisfluencyConfig
from yazses.stt.filters.disfluency import filter_transcript

#: input -> what the filter produces today. Every one of these is *wrong*: the input
#: is ordinary prose and should survive whole. Measured, not predicted.
KNOWN_GAP = {
    "children never mind the cold at all": "the cold at all",
    "students forget that lesson by the summer": "lesson by the summer",
    "customers forget that discount every single year": "discount every single year",
    "passengers no wait policy is posted at the door": "policy is posted at the door",
    "some people never mind the noise": "the noise",
    "most travellers no wait at this counter": "at this counter",
}

#: Prose the guard *does* cover. Here so a change that widens the gap fails loudly
#: rather than quietly moving a case from this set into the one above.
COVERED = (
    "they never mind the noise from the street",
    "we never mind waiting for the next train",
    "he said never mind the cost and left",
    "the no wait policy applies to walk-ins",
    "you should never mind the warning",
    "please do not delete that branch",
)

#: Genuine corrections. The gap must never be closed by suppressing these.
REAL_CORRECTIONS = {
    "send it to bob scratch that send it to alice": "send it to alice",
    "the meeting is on tuesday no wait wednesday": "wednesday",
    "open the config file delete that open the log file": "open the log file",
    "i think we should ship it never mind lets wait": "lets wait",
}


def _filtered(text: str) -> str:
    result = filter_transcript(text, DisfluencyConfig())
    return result[0] if isinstance(result, tuple) else getattr(result, "text", result)


def test_the_ledger_is_not_empty() -> None:
    """A guard that iterates is green on an empty collection."""
    assert KNOWN_GAP and COVERED and REAL_CORRECTIONS


@pytest.mark.parametrize("text", sorted(COVERED))
def test_prose_the_guard_covers_survives_whole(text: str) -> None:
    assert _filtered(text) == text, (
        f"{text!r} used to be handled and now loses its first half. The guard has "
        "narrowed, and this is the failure mode the module cares most about: the "
        "result reads as fluent text the user never said."
    )


@pytest.mark.parametrize("text", sorted(KNOWN_GAP))
def test_the_known_gap_has_not_changed(text: str) -> None:
    """Fails in both directions on purpose.

    If this now returns the input unchanged, the gap was fixed -- delete the entry
    and move it to `COVERED`. If it returns something else again, the behaviour moved
    without anyone deciding it should.
    """
    actual = _filtered(text)
    assert actual == KNOWN_GAP[text], (
        f"{text!r} now yields {actual!r}, not the recorded {KNOWN_GAP[text]!r}.\n"
        "If it is now returned unchanged, the open-class subject case has been "
        "fixed: move this entry into COVERED. Otherwise the rollback moved without "
        "a decision behind it."
    )


@pytest.mark.parametrize("text", sorted(REAL_CORRECTIONS))
def test_a_real_correction_still_rolls_back(text: str) -> None:
    """The cost side of the trade. Closing the gap above by suppressing rollback
    after any noun would take these with it -- the word before each trigger here is
    a bare noun (`bob`, `tuesday`, `file`) or the object pronoun `it`."""
    assert _filtered(text) == REAL_CORRECTIONS[text], (
        f"{text!r} no longer rolls back to {REAL_CORRECTIONS[text]!r}. A widened "
        "prose guard has started suppressing genuine self-corrections."
    )
