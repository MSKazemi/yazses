"""A self-correction trigger inside ordinary prose must not eat the sentence.

`_apply_self_corrections` discards everything before a trigger, which is right when the
speaker is correcting themselves and catastrophic when the words are simply part of what
they said. The filter's own comment names this the worst thing it can produce: it "does
not garble the meaning, it inverts it", because the surviving half reads as fluent text
the user never dictated.

Issue #302 fixed the case where a *verb* governs the trigger ("you should never mind the
warning"). Two phrase types it could not see were still losing their first half:

    "the no wait policy applies to walk-ins"   ->  "policy applies to walk-ins"
    "she said no wait for the second batch"    ->  "for the second batch"

An article or possessive needs a noun head, and a reporting verb quotes the trigger
instead of performing it. Both are decisive on the single preceding word, which is the
window this module already chose -- a wider one starts suppressing real corrections.

## Both directions are asserted here, deliberately

A file that only checked prose survives would pass if self-correction were deleted
outright, so `PROSE` and `CORRECTIONS` are tested together: the fix is only a fix if it
costs no genuine rollback. Measured when it landed: prose destroyed 15/15 -> 2/15, real
corrections missed 0/10 -> 0/10.

The two survivors are recorded rather than hidden, in `test_the_known_residue_is_exactly_this`.
"""

from __future__ import annotations

import pytest

from yazses.config import DisfluencyConfig
from yazses.stt.filters.disfluency import filter_transcript

#: Ordinary English containing the trigger words. Every one must survive intact.
PROSE = [
    "the no wait policy applies to walk-ins",
    "there is no wait time at this branch",
    "she said no wait for the second batch",
    "he said scratch that from the notes",
    "the delete that button is confusing",
    "a never mind attitude will not help here",
    "our forget that clause was struck by legal",
    "the strike that motion carried unanimously",
    "my never mind reflex kicked in",
    "there was no wait at the counter",
    "the sign says no wait for members",
    "it is a no wait guarantee",
    "your delete that habit worries me",
]

#: Genuine self-corrections. Every one must still roll back, or the fix cost more than
#: it bought.
CORRECTIONS = [
    "meet me at four no wait five",
    "book the flight to Berlin scratch that Munich",
    "send it to Ana delete that send it to Bo",
    "the release is Tuesday never mind it is Wednesday",
    "add the header forget that add the footer",
    "call him at noon strike that at one",
    "deploy to staging no wait deploy to prod",
    "the file is config.toml scratch that it is config.yaml",
    "invite twelve people never mind invite twenty",
    "set the timeout to thirty forget that set it to sixty",
]


def _filtered(text: str) -> str:
    return filter_transcript(text, DisfluencyConfig()).text.strip()


@pytest.mark.parametrize("sentence", PROSE)
def test_ordinary_prose_survives_a_trigger_phrase(sentence: str) -> None:
    assert _filtered(sentence) == sentence, (
        "a trigger inside ordinary prose rolled the sentence back and left a fluent "
        "fragment the user never said, which is the failure mode this guard exists for"
    )


@pytest.mark.parametrize("sentence", CORRECTIONS)
def test_a_real_correction_still_rolls_back(sentence: str) -> None:
    out = _filtered(sentence)
    assert out != sentence, (
        "a genuine self-correction stopped rolling back. Suppressing prose must not be "
        "paid for by ignoring real corrections -- that would trade a visible defect for "
        "an invisible one in the other direction"
    )
    assert out, "a correction rolled back to nothing"


def test_the_known_residue_is_exactly_this() -> None:
    """The cases a one-word window cannot reach, pinned so they cannot quietly grow.

    Both put a word between the governing term and the trigger -- "told *me* scratch
    that", "*this* delete that shortcut" -- so seeing them needs the clause, which is
    the same boundary #302 declined to guess at.
    """
    residue = [
        "they told me scratch that plan entirely",
        "this delete that shortcut needs a confirm step",
    ]
    still_broken = [s for s in residue if _filtered(s) != s]
    assert still_broken == residue, (
        f"the residue changed: {still_broken}. If a case here now survives, delete it "
        "from this list so the boundary stays honest."
    )


def test_the_guard_does_not_simply_disable_self_correction() -> None:
    """The mutation that would make every prose case above pass for the wrong reason."""
    assert _filtered("scratch that send it to Alice") == "scratch that send it to Alice"
    assert _filtered("meet at three. no wait meet at four") == "meet at three. meet at four"
