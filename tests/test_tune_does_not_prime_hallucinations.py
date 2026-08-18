"""`yazses tune` must not propose priming Whisper with its own hallucinations.

Found by running the command against a real 1,617-event corpus. The top vocabulary
proposal — the one `--apply` offers to write into `[stt] initial_prompt` — was:

    for you thanks watching these cube assess within aspects can needed yasas grom
    two both and referees finished one etc why

Two separate defects in twenty-one terms.

**Stopwords.** Eleven are function words. `initial_prompt` is a bounded budget (the
decoder sees only the last ~224 tokens), and Whisper's language model already knows
"for" and "and" perfectly, so each one displaces a term that would have helped. The
miner's rule — *in the correction, absent from the live transcript* — catches them
because ordinary rephrasing changes which function words appear, not because the model
cannot hear them.

**Hallucination feedback, which is the serious one.** `for`, `you`, `thanks` and
`watching` are the words of *"Thank you for watching"* — the silence hallucination that
`postprocess/hallucination.py` exists to delete. The path is a loop: a clip decodes to
the ghost phrase, the user re-dictates, the re-dictation does not contain those words,
the miner reads them as vocabulary the model keeps missing, and priming them biases the
decoder **toward** the phrase. The product would have been tuning itself into the
failure it ships a guard against.

The exclusion list is taken from `_GHOST_PHRASES` itself, via the new `ghost_words()`,
rather than copied here — a copy drifts, and the two disagreeing silently is the whole
bug one layer up.

## What this deliberately does not fix

`yasas` and `grom` survive, and they are mis-hearings of "YazSes" and "from". They come
through `_better_text`, i.e. the corrected/re-transcribed text, so the *ground truth
itself* is wrong. That is a real limitation of re-transcription as an oracle and is not
something a word list can settle.
"""

from __future__ import annotations

import pytest

from yazses.learning.analysis import _VOCAB_STOPWORDS, _worth_priming
from yazses.postprocess.hallucination import ghost_words, is_ghost_phrase

#: The exact proposal a real corpus produced, in order.
OBSERVED = [
    "for", "you", "thanks", "watching", "these", "cube", "assess", "within",
    "aspects", "can", "needed", "yasas", "grom", "two", "both", "and",
    "referees", "finished", "one", "etc", "why",
]
#: The content words in it — terms a user might genuinely need spelled right.
CONTENT = {"cube", "assess", "aspects", "yasas", "grom", "referees", "finished"}


def test_the_ghost_phrase_guard_still_knows_these_words() -> None:
    """The premise. If the phrase list changes, this file must follow it, not lead."""
    assert is_ghost_phrase("Thank you for watching")
    assert {"thanks", "watching", "for", "you"} <= ghost_words()
    assert "subscribe" in ghost_words()


def test_no_hallucination_word_is_ever_proposed() -> None:
    """The serious half: priming these makes the ghost phrase *more* likely."""
    offenders = sorted(w for w in ghost_words() if _worth_priming(w))
    assert not offenders, (
        f"tune would prime Whisper with its own silence hallucination: {offenders}. "
        "postprocess/hallucination.py exists to delete that phrase."
    )


def test_the_real_proposal_keeps_only_its_content_words() -> None:
    kept = {w for w in OBSERVED if _worth_priming(w)}
    assert kept == CONTENT, (
        f"kept {sorted(kept)}, expected {sorted(CONTENT)}. Dropping a content word "
        "silently defeats the feature; keeping a function word wastes prompt budget."
    )


@pytest.mark.parametrize("word", sorted(CONTENT))
def test_content_words_survive(word: str) -> None:
    """A filter that ate real vocabulary would be worse than the bug it fixes."""
    assert _worth_priming(word)


def test_the_stopword_list_holds_no_content_word() -> None:
    """Cheap standing check that the list has not grown teeth.

    These are terms a user plausibly dictates and needs spelled correctly; none should
    ever be filtered out as a function word.
    """
    plausible = {
        "kubernetes", "postgres", "yazses", "whisper", "seyedkazemi", "grafana",
        "referees", "cube", "aspects", "assess", "finished", "python", "numpy",
    }
    assert not (plausible & _VOCAB_STOPWORDS)
    assert not (plausible & ghost_words())


def test_short_tokens_are_still_the_callers_job() -> None:
    """`len(tok) > 2` lives in the miner; this predicate must not duplicate it.

    Two checks in two places that must agree is how they come to disagree — the list
    documents that it only carries words longer than two characters.
    """
    assert all(len(w) > 2 for w in _VOCAB_STOPWORDS)
