"""When a spoken answer to `ask_human` is over (#640). Pure: frames and a clock, no mic.

Before this, the listener recorded for the caller's whole timeout, up to 120 s, so a
two-word answer held the microphone (and blocked dictation) for the agent's entire wait.
"""
from __future__ import annotations

import pytest

from yazses.endpoint import answer, autostop
from yazses.endpoint.answer import ANSWERED, NO_SPEECH, TIMEOUT, AnswerEndpoint


def _run(frames, *, timeout_s=60.0, end_silence_s=1.2, no_speech_s=8.0, step=0.05):
    """Feed ``frames`` (a function of elapsed seconds -> speech?) until the endpoint ends.

    Returns ``(outcome, elapsed_s)``.
    """
    judge = AnswerEndpoint(started_at=100.0, timeout_s=timeout_s,
                           end_silence_s=end_silence_s, no_speech_s=no_speech_s)
    t = 0.0
    while True:
        t = round(t + step, 6)
        outcome = judge.observe(100.0 + t, frames(t))
        if outcome is not None:
            return outcome, t
        assert t < 1000, "the endpoint never ended"


def test_a_short_answer_ends_soon_after_the_speaker_stops():
    outcome, ended = _run(lambda t: 0.5 <= t < 1.5)  # "yes, go ahead"
    assert outcome == ANSWERED
    assert ended == pytest.approx(1.5 + 1.2, abs=0.06), "it held the mic past the trailing silence"


def test_a_pause_between_words_does_not_end_the_answer():
    def speech(t):  # two phrases with a 0.8 s gap, under the 1.2 s end-of-answer silence
        return 0.5 <= t < 1.5 or 2.3 <= t < 3.0

    outcome, ended = _run(speech)
    assert outcome == ANSWERED
    assert ended == pytest.approx(3.0 + 1.2, abs=0.06)


def test_thinking_before_answering_is_not_an_empty_answer():
    """Silence counts only after speech: a 5 s pause before the first word is thinking."""
    outcome, ended = _run(lambda t: 5.0 <= t < 6.0)
    assert outcome == ANSWERED and ended == pytest.approx(7.2, abs=0.06)


def test_nothing_said_ends_with_no_answer_after_the_grace():
    outcome, ended = _run(lambda t: False)
    assert outcome == NO_SPEECH and ended == pytest.approx(8.0, abs=0.06)


def test_a_zero_grace_waits_for_the_callers_timeout():
    outcome, ended = _run(lambda t: False, timeout_s=20, no_speech_s=0)
    assert outcome == NO_SPEECH and ended == pytest.approx(20.0, abs=0.06)


def test_the_callers_timeout_ends_an_answer_that_never_stops():
    outcome, ended = _run(lambda t: True, timeout_s=5)
    assert outcome == TIMEOUT and ended == pytest.approx(5.0, abs=0.06)


def test_a_grace_longer_than_the_timeout_cannot_outlast_it():
    outcome, ended = _run(lambda t: False, timeout_s=3, no_speech_s=8)
    assert outcome == NO_SPEECH and ended == pytest.approx(3.0, abs=0.06)


def test_the_end_silence_has_the_hands_free_floor():
    """A mistyped 0 must not cut every answer after its first word."""
    outcome, ended = _run(lambda t: 0.5 <= t < 1.0, end_silence_s=0)
    assert outcome == ANSWERED
    assert ended == pytest.approx(1.0 + autostop.MIN_SILENCE_TIMEOUT_MS / 1000, abs=0.06)


def test_a_sub_second_timeout_still_records_a_second():
    """The listener never recorded less than a second; that floor is kept."""
    outcome, ended = _run(lambda t: True, timeout_s=0.1)
    assert outcome == TIMEOUT and ended == pytest.approx(answer.MIN_TIMEOUT_S, abs=0.06)


def test_it_reuses_the_hands_free_decision_rather_than_copying_it():
    assert answer.should_stop is autostop.should_stop
    assert answer.MIN_SILENCE_TIMEOUT_MS == autostop.MIN_SILENCE_TIMEOUT_MS
