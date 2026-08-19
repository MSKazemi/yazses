"""The summariser reliably picked the least informative sentence in the paragraph.

`condense` scores each sentence as its mean content-word frequency and keeps the top N. The
mean divided by the sentence's *own* length, so a one-word interjection scored the full
frequency of that word over a single word and beat every real sentence:

    "We should ship the release today. Ship it. The release needs the changelog
     updated and the tags pushed before anyone can install it."
        ->  "We should ship the release today. Ship it."

    "The migration touches the database schema and the API layer. Right. We need
     to coordinate the deploy with the frontend team carefully."
        ->  "The migration touches the database schema and the API layer. Right."

Ramble — which is the entire input this feature exists for — is full of "Right.", "Okay.",
"Sure.", "Ship it." They are the *least* informative sentences there are, so a summariser
that prefers them is inverted rather than merely noisy.

## Why the floor is 2 and not higher

Sweeping the divisor floor over five realistic paragraphs and three adversarial ones showed
there is no value that is simply better:

    floor   "Right." / "Ship it."   two-word echo   "Fix the wheel." (legitimate)
    1       kept  (wrong)           kept  (wrong)   kept  (right)
    2       dropped                 kept  (wrong)   kept  (right)
    3       dropped                 kept  (wrong)   DROPPED  (wrong)
    4-5     dropped                 dropped         DROPPED  (wrong)

Above 2 the floor stops removing noise and starts removing content, and the crossover sits
in the middle of the useful range. 2 is the largest value that removes a failure with no
legitimate counterpart: a sentence carrying one content word has no summary value by
construction, whereas "Fix the wheel." plainly does.

Both ends are pinned below, so raising the floor to "do better" fails a test instead of
quietly discarding short real sentences.

`condense` is in `features._UNWIRED` — nothing calls it yet, so this reaches whoever wires
it rather than a user today.
"""

from __future__ import annotations

import pytest

from yazses.condense.extract import _MIN_CONTENT_WORDS, condense

RAMBLE = (
    "We should ship the release today. Ship it. The release needs the changelog "
    "updated and the tags pushed before anyone can install it."
)
AGREEMENT = (
    "The migration touches the database schema and the API layer. Right. We need to "
    "coordinate the deploy with the frontend team carefully."
)
TWO_FILLERS = (
    "Okay. Sure. The deployment pipeline needs a rollback step before we can call it "
    "production ready. We also need alerting on the queue depth."
)


@pytest.mark.parametrize(
    "text,unwanted",
    [
        (RAMBLE, "Ship it."),
        (AGREEMENT, "Right."),
        (TWO_FILLERS, "Okay."),
        (TWO_FILLERS, "Sure."),
    ],
)
def test_a_one_word_interjection_is_not_the_summary(text: str, unwanted: str) -> None:
    assert unwanted not in condense(text, max_sentences=2)


def test_the_sentences_that_said_something_are_kept() -> None:
    """A scorer that just refused short sentences would pass the tests above."""
    out = condense(RAMBLE, max_sentences=2)
    assert "We should ship the release today." in out
    assert "The release needs the changelog" in out

    out = condense(AGREEMENT, max_sentences=2)
    assert "The migration touches the database schema" in out
    assert "coordinate the deploy" in out


def test_a_legitimate_short_sentence_is_still_selectable() -> None:
    """The other end of the trade-off, and the reason the floor stops at 2.

    Raising `_MIN_CONTENT_WORDS` to 3 to out-rank a two-word echo drops this instead.
    """
    text = (
        "The build is broken. The CI logs show a missing wheel for the arm64 leg of "
        "the matrix build. Fix the wheel."
    )
    assert "Fix the wheel." in condense(text, max_sentences=2)


def test_the_floor_is_recorded_as_a_measurement_not_a_preference() -> None:
    """Fails the day someone raises it, which is when the docstring above must be re-read."""
    assert _MIN_CONTENT_WORDS == 2


def test_original_order_is_preserved() -> None:
    out = condense(RAMBLE, max_sentences=2)
    assert out.index("We should ship") < out.index("The release needs")


def test_short_input_and_edges_are_unchanged() -> None:
    assert condense("Just one sentence.", max_sentences=2) == "Just one sentence."
    assert condense("", max_sentences=2) == ""
    assert condense("   ", max_sentences=2) == ""


def test_a_sentence_of_pure_stopwords_scores_nothing() -> None:
    """It has no content words at all, so the floor must not hand it a score."""
    text = "It is what it is. The scheduler drops a job when the queue is saturated. So."
    assert "It is what it is." not in condense(text, max_sentences=1)
