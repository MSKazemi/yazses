"""`yazses tune` offered to delete the word "this" from every future dictation.

`_propose_disfluency` counts words that appeared in a wrong transcript and *not* in the
user's correction, and proposes the frequent ones as filler words. It had no notion of
what can plausibly BE a filler, and correcting a dictation removes ordinary words all the
time — "send **this** to Bob" corrected to "send **that** to Bob" makes "this" a removed
word. Twice, and it is proposed.

Applying that writes `this` into `[filters.disfluency] filler_words`, and from then on the
disfluency filter strips the word "this" from everything the user says. On a real corpus
the proposal was:

    okay, this, one

That is the most destructive thing `tune --apply` can write, so it is the one proposal
that must not be reachable by frequency alone.

## The rule, and why it is not an allow-list

An ordinary function word is refused **unless** it is one a filler is plausibly drawn from.
"well" is both — a stopword and a genuine filler — and blocking it outright would stop a
real one being discovered.

A strict allow-list would be worse than the bug: the point of this proposal is to find a
*personal* verbal tic, and the shipped list already contains the obvious ones. The
stopword rule blocks the dangerous class (grammatical words that occur everywhere) while
leaving discovery possible.

`PLAUSIBLE_FILLERS` lives in `stt/filters/disfluency.py` — the filter's own module — and
answers exactly one question: *could this word be a filler at all?* It is deliberately not
merged with `reflow/outline.py`'s leading fillers, which are *phrases* matched at the start
of a sentence ("so basically", "okay so"); the two overlap but have different shapes, and
merging them would hand one caller a list that does not fit its job.
"""

from __future__ import annotations

import pytest

from yazses.learning.analysis import _VOCAB_STOPWORDS, _could_be_a_filler
from yazses.stt.filters.disfluency import PLAUSIBLE_FILLERS

#: Verbatim from the proposal a real corpus produced.
OBSERVED = ["okay", "this", "one"]


@pytest.mark.parametrize("word", ["this", "one", "the", "that", "these", "your", "them"])
def test_an_ordinary_word_is_never_proposed_as_a_filler(word: str) -> None:
    assert not _could_be_a_filler(word), (
        f"tune would offer to delete {word!r} from every future dictation"
    )


@pytest.mark.parametrize("word", ["um", "uh", "okay", "right", "basically", "anyway"])
def test_a_genuine_filler_is_still_proposable(word: str) -> None:
    """A guard that refused everything would make the proposal useless."""
    assert _could_be_a_filler(word)


def test_well_is_both_and_must_survive() -> None:
    """The case that rules out reusing the stopword list on its own.

    "well" is an ordinary word *and* one of the commonest fillers in English. A plain
    stopword block would have silently stopped it ever being discovered.
    """
    assert "well" in _VOCAB_STOPWORDS, "premise gone — revisit the exception"
    assert "well" in PLAUSIBLE_FILLERS
    assert _could_be_a_filler("well")


def test_the_real_proposal_keeps_only_the_filler() -> None:
    kept = [w for w in OBSERVED if _could_be_a_filler(w)]
    assert kept == ["okay"], f"kept {kept}"


def test_a_personal_tic_is_still_discoverable() -> None:
    """Not an allow-list: the whole point is finding a filler we did not ship.

    A strict list of known fillers would refuse these, and they are exactly what this
    proposal exists to surface.
    """
    for tic in ("yeah", "innit", "gotcha", "cool", "whatever"):
        assert _could_be_a_filler(tic), tic


def test_the_list_is_words_not_phrases() -> None:
    """It answers "could this WORD be a filler", so a phrase in it would never match.

    `_could_be_a_filler` is handed single tokens by the proposal, so a multi-word entry
    would sit there matching nothing and reading like coverage.
    """
    assert PLAUSIBLE_FILLERS, "the list is empty — this guard proves nothing"
    multiword = sorted(w for w in PLAUSIBLE_FILLERS if " " in w)
    assert not multiword, f"phrases cannot match a single token: {multiword}"


def _event(raw: str, corrected: str, eid: int):
    """A wrong-flagged event whose correction removed some words."""
    from yazses.learning.store import EventRecord

    return EventRecord(
        id=eid, ts="2026-08-19T00:00:00", audio_secs=1.0, decode_ms=100,
        model="base.en", level=0.02, sample_rate=16000, intent_type="dictate",
        intent_action="inject", injected=True, discard_reason="", wrong_flag=True,
        edit_signal=0.0, retx_distance=None, has_audio=False,
        raw_text=raw, cleaned_text=raw, filtered_text=raw, final_text=raw,
        correction_text=corrected, retx_text="",
    )


def test_the_proposal_itself_applies_the_rule() -> None:
    """The wiring, not just the predicate.

    Every test above calls `_could_be_a_filler` directly, which proves the rule is right
    and NOT that anything consults it — removing the call from `_propose_disfluency` left
    all of them green. This drives the real proposal.
    """
    from yazses.config import Config
    from yazses.learning.analysis import _propose_disfluency

    # "this" removed by the correction twice over, alongside a genuine filler.
    events = [
        _event("okay send this to Bob", "send that to Bob", 1),
        _event("okay send this to Sara", "send that to Sara", 2),
    ]
    proposal = _propose_disfluency(events, Config())
    assert proposal is not None, "no proposal at all — the fixture no longer triggers it"

    added = [w for w in proposal.value if w not in Config().filters.disfluency.filler_words]
    assert "this" not in added, (
        f"tune still offers to delete the word 'this' from every dictation: {added}"
    )
    assert "okay" in added, f"the genuine filler was lost too: {added}"
