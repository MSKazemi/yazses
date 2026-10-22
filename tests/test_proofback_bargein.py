"""Barge-in decisions for Interruptible Proofreading (ADR-v2-108), pure and clock-injected.

The contract the daemon relies on:

* a hold is a barge-in only while a read-back of a dictated burst is playing and a word
  of it has started — anything else arms nothing;
* the word playing at the press is located in the *typed* text, and the span from it to
  the end of the burst is what the next burst replaces;
* a word that cannot be located (a truncated read-back) is reported, never guessed;
* an armed target is applied only to the burst it was armed for, with an editable
  target, without streaming, and with something to type in its place.

Every timeline here uses 1 sample == 1 ms so the times stay readable.
"""
from __future__ import annotations

import pytest

from yazses.proofback.bargein import (
    REPLACE_FROM,
    ProofbackController,
    ProofTarget,
    plan_replacement,
    resolve_barge_in,
    word_spans,
)
from yazses.timeline.history import InjectionTimeline

SR = 1000


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# ---- word_spans ---------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "hello world",
    "  leading and trailing  ",
    "tabs\tand\nnewlines",
    "no break　ideographic space",
    "",
    "   ",
    "one",
    "سلام دنیا",
])
def test_word_spans_agree_with_str_split(text):
    assert [text[s:e] for s, e in word_spans(text)] == text.split()


def test_word_spans_offsets():
    assert word_spans(" ab  cd") == [(1, 3), (5, 7)]


# ---- resolve_barge_in -----------------------------------------------------------

def test_target_covers_from_the_word_to_the_end_of_the_burst():
    t = resolve_barge_in("I sent the wrong file.", "I sent the wrong file.", 3, stamp=5.0)
    assert t is not None
    assert t.word == "wrong"
    assert t.kept == "I sent the "
    assert t.erase_count == len("wrong file.")
    assert t.char_offset + t.erase_count == len("I sent the wrong file.")
    assert t.stamp == 5.0
    assert t.intent == REPLACE_FROM


def test_first_word_keeps_a_leading_continuation_space():
    t = resolve_barge_in(" hello there", " hello there", 0)
    assert t is not None
    assert t.kept == " "
    assert t.erase_count == len("hello there")


@pytest.mark.parametrize("index", [-1, 2, 99])
def test_out_of_range_index_resolves_to_nothing(index):
    assert resolve_barge_in("one two", "one two", index) is None


def test_the_truncated_word_of_a_capped_readback_is_never_guessed():
    injected = "alpha beta gamma delta"
    spoken = "alpha beta ga…"  # [tts] max_readback_chars cut "gamma"
    assert resolve_barge_in(injected, spoken, 2) is None
    # The words before the cut still map exactly.
    t = resolve_barge_in(injected, spoken, 1)
    assert t is not None and t.word == "beta"


def test_texts_that_disagree_before_the_word_resolve_to_nothing():
    assert resolve_barge_in("one two three", "one too three", 2) is None


# ---- ProofbackController.barge_in --------------------------------------------------

def _playing(clock, injected="aa bb cc", spoken=None, stamp=1.0):
    pb = ProofbackController(clock=clock)
    session = pb.start_readback(injected, spoken if spoken is not None else injected, stamp)
    pb.playback_started(session)
    return pb, session


def test_a_press_while_a_word_is_playing_arms_that_word():
    clock = _Clock()
    pb, session = _playing(clock)
    session.on_chunk("aa bb cc", 600, SR, 10.0)  # 200 ms per word
    clock.t = 10.25  # inside "bb"
    result = pb.barge_in()
    assert result.reason == "armed"
    assert result.word_index == 1 and result.word == "bb"
    assert pb.armed == result.target
    assert result.target is not None and result.target.kept == "aa "


def test_a_press_before_the_first_word_starts_arms_nothing():
    """Kokoro synthesizes the first sentence before it plays: READBACK, no word yet."""
    clock = _Clock(5.0)
    pb, _session = _playing(clock)
    result = pb.barge_in()
    assert result.reason == "nothing_heard"
    assert result.target is None and pb.armed is None


def test_a_press_when_nothing_is_playing_arms_nothing():
    clock = _Clock(1.0)
    pb = ProofbackController(clock=clock)
    assert pb.barge_in().reason == "not_playing"
    session = pb.start_readback("aa bb", "aa bb", 1.0)
    pb.playback_started(session)
    session.on_chunk("aa bb", 400, SR, 0.0)
    pb.playback_finished(session)
    assert pb.barge_in().reason == "not_playing"
    assert pb.armed is None


def test_an_utterance_that_is_not_a_dictation_cannot_be_edited():
    """`yazses say` plays through the same path with no session."""
    clock = _Clock(1.0)
    pb, session = _playing(clock)
    session.on_chunk("aa bb cc", 600, SR, 0.0)
    pb.playback_started(None)  # the next utterance is a `say`
    assert pb.barge_in().reason == "not_playing"


def test_a_truncated_word_is_reported_but_not_armed():
    clock = _Clock()
    pb, session = _playing(clock, injected="aa bb cccc dd", spoken="aa bb cc…")
    session.on_chunk("aa bb cc…", 600, SR, 0.0)
    clock.t = 0.59  # the cut word
    result = pb.barge_in()
    assert result.reason == "unmapped"
    assert result.word_index == 2 and result.word == "cc…"
    assert result.target is None and pb.armed is None


def test_silence_after_a_chunk_maps_to_the_last_word_heard():
    clock = _Clock()
    pb, session = _playing(clock, injected="aa bb. cc dd.")
    session.on_chunk("aa bb.", 400, SR, 0.0)
    clock.t = 0.9  # next sentence still being synthesized
    result = pb.barge_in()
    assert result.word == "bb."


def test_one_barge_in_consumes_the_session_and_a_second_arms_nothing():
    clock = _Clock()
    pb, session = _playing(clock)
    session.on_chunk("aa bb cc", 600, SR, 0.0)
    clock.t = 0.1
    assert pb.barge_in().reason == "armed"
    assert pb.barge_in().reason == "not_playing"
    assert pb.armed is None, "a later press must never leave an older target armed"


def test_take_armed_pops_once_and_disarm_forgets():
    clock = _Clock()
    pb, session = _playing(clock)
    session.on_chunk("aa bb cc", 600, SR, 0.0)
    clock.t = 0.1
    target = pb.barge_in().target
    assert pb.take_armed() == target
    assert pb.take_armed() is None
    pb2, s2 = _playing(clock)
    s2.on_chunk("aa bb cc", 600, SR, 0.0)
    pb2.barge_in()
    pb2.disarm()
    assert pb2.take_armed() is None


def test_the_clock_is_read_by_the_controller_not_the_caller():
    calls = []

    def clock():
        calls.append(1)
        return 0.0

    pb, session = _playing(clock)
    session.on_chunk("aa", 100, SR, 0.0)
    pb.barge_in()
    assert calls == [1]


# ---- plan_replacement --------------------------------------------------------------

def _target(stamp=7.0) -> ProofTarget:
    t = resolve_barge_in("send the wrong file", "send the wrong file", 2, stamp=stamp)
    assert t is not None
    return t


def test_applied_plan_erases_the_tail_and_types_the_burst_without_its_lead_space():
    plan = plan_replacement(_target(), " right file", current_stamp=7.0,
                            streaming=False, target_ok=True)
    assert plan.apply and plan.reason == "applied"
    assert plan.erase_count == len("wrong file")
    assert plan.text == "right file"
    # What the screen holds afterwards.
    assert "send the wrong file"[: -plan.erase_count] + plan.text == "send the right file"


def test_unknown_target_state_still_applies():
    """target_ok is None when the detector could not decide; only False refuses."""
    assert plan_replacement(_target(), "x", current_stamp=7.0, streaming=False,
                            target_ok=None).apply


@pytest.mark.parametrize("kwargs,reason", [
    ({"streaming": True}, "streaming"),
    ({"target_ok": False}, "no_text_target"),
    ({"current_stamp": 8.0}, "burst_changed"),
    ({"current_stamp": None}, "burst_changed"),
])
def test_refusals_type_the_burst_unchanged(kwargs, reason):
    args = {"current_stamp": 7.0, "streaming": False, "target_ok": True, **kwargs}
    plan = plan_replacement(_target(), " right file", **args)
    assert not plan.apply and plan.reason == reason
    assert plan.erase_count == 0 and plan.text == " right file"


def test_a_blank_burst_erases_nothing():
    plan = plan_replacement(_target(), "   ", current_stamp=7.0, streaming=False, target_ok=True)
    assert not plan.apply and plan.reason == "empty" and plan.erase_count == 0


def test_no_target_is_a_no_op():
    plan = plan_replacement(None, "hello", current_stamp=1.0, streaming=False, target_ok=True)
    assert not plan.apply and plan.text == "hello" and plan.reason == "none"


# ---- InjectionTimeline.replace_last (keeps "undo burst" honest after an erase) -------

def test_timeline_replace_last_rewrites_only_a_matching_newest_event():
    tl = InjectionTimeline()
    tl.record("first ")
    tl.record("send the wrong file")
    assert tl.replace_last("send the wrong file", "send the ") is True
    assert tl.text() == "first send the "
    op = tl.peek_undo("burst")
    assert op is not None and op.backspaces == len("send the ")
    assert tl.replace_last("not the newest", "x") is False
    assert tl.text() == "first send the "


def test_timeline_replace_last_with_empty_text_removes_the_event():
    tl = InjectionTimeline()
    tl.record("a ")
    tl.record("b")
    assert tl.replace_last("b", "") is True
    assert tl.text() == "a "
    assert InjectionTimeline().replace_last("x", "y") is False
