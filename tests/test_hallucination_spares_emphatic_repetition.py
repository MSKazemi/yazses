"""Emphatic repetition is speech, not a decoder fault.

`is_repetition_loop` flagged any unit repeated three times, including a ONE-word unit.
At three, a single-word repeat stops describing Whisper's degenerate loop and starts
describing English: "no no no", "okay okay okay", "wait wait wait", "yeah yeah yeah",
"what what what" were all deleted before injection.

Measured on a real machine (v2.39.0, engine `parakeet`, `[hallucination] enabled = true`):
five of seven consecutive dictations ended in

    INFO yazses.core.daemon: Hallucination guard -- discarding fabricated transcript.

at input levels up to 0.1786 -- roughly 20x that machine's `vad_threshold` of 0.0036, so
loud, deliberate speech, not silence. Nothing was typed and nothing said why.

Two things make this the wrong default:

* ADR-v2-025's own Consequences promise the guard "avoids dropping legitimate short
  utterances". The ghost-phrase rule earned that by matching whole transcripts only; the
  loop rule never got the same conservatism.
* The same ADR cites atypical/aphasic speech (arXiv 2502.12414) as worst affected by
  hallucination -- and repeating a word IS the dysfluency. The guard runs BEFORE
  `filters.disfluency`, so on a `dysfluency_friendly` install it deleted the stutter
  before the filter built to tidy it ever saw it.

ADR-021 sets the trade: a ghost phrase that reaches the editor is visible and one
keystroke to delete; a silently deleted sentence is unrecoverable and unexplained.
"""
import pytest

from yazses.config import HallucinationConfig
from yazses.postprocess.hallucination import (
    drop_reason,
    is_repetition_loop,
    should_drop,
)


def _cfg(**kw) -> HallucinationConfig:
    kw.setdefault("enabled", True)
    return HallucinationConfig(**kw)


# --- the regression: ordinary speech survives -------------------------------

@pytest.mark.parametrize("text", [
    "No no no.",
    "Okay okay okay.",
    "Wait, wait, wait.",
    "Yeah yeah yeah.",
    "What what what?",
    "So so so.",
    "Hmm hmm hmm.",
    "Please please please.",
])
def test_threefold_single_word_emphasis_is_not_a_loop(text):
    assert not is_repetition_loop(text), f"deleted real speech: {text!r}"
    assert should_drop(text, _cfg()) is False


@pytest.mark.parametrize("text", [
    "That is very very very good.",
    "I I I think we should go.",
    "The the the quick brown fox.",
    "Can you can you can you hear me?",
    "Let me check the log file for errors.",
    "The meeting is at three pm tomorrow.",
])
def test_repetition_inside_a_sentence_is_never_a_loop(text):
    assert not is_repetition_loop(text), f"deleted real speech: {text!r}"


# --- the permissive direction: real loops still die -------------------------

@pytest.mark.parametrize("text", [
    "the the the the",                      # pinned by tests/test_hallucination.py
    "no no no no",                          # pinned by tests/test_hallucination.py
    "the the the the the the the the",
    "i love it i love it i love it",        # 3x a 3-word unit -- unchanged
    "each machete de shiramasun each machete de shiramasun "
    "each machete de shiramasun each",      # the live-corpus partial-tail loop
])
def test_degenerate_loops_are_still_caught(text):
    assert is_repetition_loop(text), f"missed a degenerate loop: {text!r}"
    assert should_drop(text, _cfg()) is True


def test_multiword_units_keep_the_three_repeat_rule():
    """Only the ONE-word unit was loosened; a repeated phrase still goes at three."""
    assert is_repetition_loop("go home go home go home")
    assert is_repetition_loop("okay then okay then okay then")


# --- the discard can now explain itself -------------------------------------

def test_drop_reason_names_the_rule():
    assert drop_reason("thanks for watching", _cfg()) == "ghost_phrase"
    assert drop_reason("the the the the", _cfg()) == "repetition_loop"
    assert drop_reason("the meeting is at three pm", _cfg()) is None


def test_drop_reason_honours_the_config_gates():
    assert drop_reason("thanks for watching", _cfg(enabled=False)) is None
    assert drop_reason("thanks for watching", _cfg(drop_ghost_phrases=False)) is None
    assert drop_reason("the the the the", _cfg(drop_loops=False)) is None


def test_should_drop_still_agrees_with_drop_reason():
    for text in ("thanks for watching", "the the the the", "hello there", ""):
        assert should_drop(text, _cfg()) == (drop_reason(text, _cfg()) is not None)
