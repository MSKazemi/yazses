"""Predictive Completion's pending-suggestion lifecycle (ADR-v2-016) — the pure half.

`predict/session.py` decides everything about an offer: what the model is shown, which
generator result is still wanted, what the next utterance does to the offer and when
it expires. No thread, no model, no clock — so each rule is pinned here directly.

The properties that matter most, because each one is a way to type something the user
did not ask for:

* nothing is typed without a whole-utterance accept ("take it" or "accept suggestion");
* a result for an older burst is never offered;
* an offer expires, and an accept after expiry types nothing (and is not typed as the
  literal word either, for a short grace period);
* an offer is answered at most once.
"""
from __future__ import annotations

import pytest

from yazses.predict.session import (
    ACCEPT,
    DECLINE,
    DROPPED,
    EXPIRED,
    LATE,
    LATE_GRACE_S,
    MAX_SUGGESTION_CHARS,
    NONE,
    SUGGESTION_TTL_S,
    PredictSession,
    clean_suggestion,
    continues_word,
    typed_tail,
)

CONTEXT = "the meeting is moved to"


def _offered(raw: str = " three pm on Friday", *, now: float = 100.0):
    s = PredictSession()
    req = s.note_injected(CONTEXT)
    assert req is not None
    epoch, _ctx = req
    sug = s.offer(epoch, raw, now)
    assert sug is not None
    return s, sug


# ---- clean_suggestion ------------------------------------------------------

def test_clean_keeps_only_the_first_line():
    assert clean_suggestion(" three pm\nand then a second line") == "three pm"


def test_clean_cuts_at_the_first_sentence_end():
    assert clean_suggestion(" three pm. Then lunch.") == "three pm."


def test_clean_strips_wrapping_quotes_and_collapses_whitespace():
    assert clean_suggestion('  "three   pm\ton Friday"  ') == "three pm on Friday"


def test_clean_removes_control_and_bidi_characters():
    # A right-to-left override or a zero-width joiner must never be typed into a
    # document or a terminal on the model's say-so.
    assert clean_suggestion("three‮ pm‍ now\x07") == "three pm now"


def test_clean_caps_length_on_a_word_boundary():
    raw = " " + " ".join(["word"] * 100)
    out = clean_suggestion(raw)
    assert len(out) <= MAX_SUGGESTION_CHARS
    assert out.endswith("word")


@pytest.mark.parametrize("raw", [None, "", "   ", "\nsecond line only", '""'])
def test_clean_returns_empty_for_nothing_usable(raw):
    assert clean_suggestion(raw) == ""


# ---- continues_word / typed_tail --------------------------------------------

def test_a_leading_space_starts_a_new_word():
    assert continues_word("the meet", " at noon") is False


def test_no_leading_space_after_a_letter_continues_the_word():
    assert continues_word("the meet", "ing at noon") is True


def test_tail_adds_one_separating_space():
    assert typed_tail(CONTEXT, "three pm") == " three pm"


def test_tail_skips_words_already_on_screen():
    # merge_completion's overlap de-duplication, reused: only the new words are typed.
    assert typed_tail("send the report to", "to the team") == " the team"


def test_tail_is_empty_when_the_suggestion_adds_nothing():
    assert typed_tail("send the report to", "report to") == ""


def test_tail_glues_a_word_continuation_and_closing_punctuation():
    assert typed_tail("the meet", "ing at noon", glue=True) == "ing at noon"
    assert typed_tail("yes", ", of course") == ", of course"


def test_tail_does_not_double_a_space_already_on_screen():
    assert typed_tail("the meeting is ", "at noon") == "at noon"


def test_tail_with_no_context_is_the_suggestion():
    assert typed_tail("", "at noon") == "at noon"


# ---- context ----------------------------------------------------------------

def test_too_little_context_requests_nothing():
    s = PredictSession()
    assert s.note_injected("hello") is None
    assert s.note_injected(" there") is None
    assert s.note_injected(" friend") is not None  # three words now


def test_context_accumulates_and_is_capped_without_a_half_word():
    s = PredictSession(max_context_chars=20)
    s.note_injected("alpha bravo charlie")
    s.note_injected(" delta echo foxtrot")
    ctx = s.context
    assert len(ctx) <= 20
    assert ctx.endswith("foxtrot")
    # The cut never leaves a fragment like "rlie" at the start.
    assert ctx.split()[0] in {"alpha", "bravo", "charlie", "delta", "echo", "foxtrot"}


def test_bursts_typed_without_a_separator_stay_separate_words_for_the_model():
    s = PredictSession()
    s.note_injected("one two")
    s.note_injected("three four")
    assert s.context == "one two three four"


def test_switching_application_resets_the_context():
    s = PredictSession()
    s.note_injected("dear team the report is", app="thunderbird")
    req = s.note_injected("git commit", app="kitty")
    assert s.context == "git commit"
    assert req is None  # two words: not enough to predict from


# ---- staleness ----------------------------------------------------------------

def test_a_result_for_an_older_request_is_never_offered():
    s = PredictSession()
    epoch, _ = s.note_injected(CONTEXT)
    s.begin_burst()  # the user started speaking again while the model was busy
    assert s.offer(epoch, " three pm on Friday", 1.0) is None
    assert s.pending is None


def test_new_typed_text_withdraws_the_previous_offer():
    s, _ = _offered()
    s.note_injected(" and the room changed")
    assert s.pending is None


def test_begin_burst_keeps_an_offer_already_shown():
    # The burst that begins may be the very "take it" that claims it.
    s, sug = _offered()
    s.begin_burst()
    assert s.pending == sug


def test_an_offer_needs_enough_new_words():
    s = PredictSession()
    epoch, _ = s.note_injected(CONTEXT)
    assert s.offer(epoch, " noon", 1.0) is None  # one word is not worth an interruption
    assert s.offer(epoch, " noon tomorrow", 1.0) is not None


def test_an_offer_that_only_repeats_the_screen_is_dropped():
    s = PredictSession()
    epoch, _ = s.note_injected(CONTEXT)
    assert s.offer(epoch, " moved to", 1.0) is None


# ---- resolve ---------------------------------------------------------------------

@pytest.mark.parametrize("phrase", ["Accept suggestion.", "take it", "Take it."])
def test_accept_types_the_suggestion_not_the_words(phrase):
    s, sug = _offered()
    res = s.resolve(phrase, 105.0)
    assert res.action == ACCEPT and res.consumed
    assert res.typed == " three pm on Friday" == sug.completion
    assert "accept" not in res.typed.lower() and "take it" not in res.typed.lower()


def test_accept_extends_the_context_with_what_was_typed():
    s, _ = _offered()
    s.resolve("take it", 105.0)
    assert s.context == CONTEXT + " three pm on Friday"


def test_decline_is_consumed_and_types_nothing():
    s, _ = _offered()
    res = s.resolve("discard", 105.0)
    assert res.action == DECLINE and res.consumed and res.typed == ""
    assert s.pending is None


@pytest.mark.parametrize("phrase", ["discard", "Discard.", "DISCARD!"])
def test_discard_is_the_decline_phrase(phrase):
    s, _ = _offered()
    res = s.resolve(phrase, 105.0)
    assert res.action == DECLINE and res.consumed and res.typed == ""


# Narrowed 2026-10-23 (owner decision): each was a control phrase and is consumed no
# longer. A one-word "Decline." or "Keep it." replying to a message is now typed.
@pytest.mark.parametrize("phrase", [
    "accept", "Accept.", "accept that", "yes take it", "Keep it.", "use that",
    "Decline.", "reject", "cancel that",
])
def test_a_removed_control_phrase_is_dictation_and_dismisses_the_offer(phrase):
    s, _ = _offered()
    res = s.resolve(phrase, 105.0)
    assert res.action == DROPPED
    assert res.consumed is False and res.typed == ""
    assert s.pending is None


@pytest.mark.parametrize("phrase", ["take it easy", "Take it easy.", "accept suggestion now"])
def test_a_control_phrase_inside_a_longer_utterance_is_dictation(phrase):
    s, _ = _offered()
    res = s.resolve(phrase, 105.0)
    assert res.action == DROPPED and res.consumed is False


@pytest.mark.parametrize("reply", ["No.", "no", "Never mind."])
def test_a_one_word_no_is_dictation_not_a_decline(reply):
    # "No." is an ordinary reply. It dismisses the offer like any other speech, and is
    # not consumed, so the daemon types it.
    s, _ = _offered()
    res = s.resolve(reply, 105.0)
    assert res.action == DROPPED
    assert res.consumed is False and res.typed == ""
    assert s.pending is None


@pytest.mark.parametrize("reply", ["No.", "Decline.", "Keep it."])
def test_a_reply_after_expiry_is_dictated_not_swallowed_by_the_grace_period(reply):
    # The late-grace window consumes only control phrases; these are not.
    s, _ = _offered(now=100.0)
    res = s.resolve(reply, 100.0 + SUGGESTION_TTL_S + 1.0)
    assert res.action == EXPIRED and res.consumed is False


def test_a_discard_after_expiry_is_still_consumed_in_the_grace_period():
    s, _ = _offered(now=100.0)
    res = s.resolve("discard", 100.0 + SUGGESTION_TTL_S + 1.0)
    assert res.action == LATE and res.consumed is True and res.typed == ""


def test_any_other_utterance_drops_the_offer_and_is_dictated():
    s, _ = _offered()
    res = s.resolve("and bring the slides", 105.0)
    assert res.action == DROPPED
    assert res.consumed is False and res.typed == ""
    assert s.pending is None


def test_accept_inside_a_sentence_is_ordinary_dictation():
    # Anchored: only the whole utterance is a control phrase (ADR-021).
    s, _ = _offered()
    assert s.resolve("I take it you agree", 105.0).action == DROPPED


def test_an_offer_is_answered_at_most_once():
    s, _ = _offered()
    assert s.resolve("take it", 105.0).action == ACCEPT
    second = s.resolve("take it", 106.0)
    assert second.action == NONE and second.consumed is False


def test_nothing_pending_means_nothing_is_consumed():
    s = PredictSession()
    res = s.resolve("take it", 1.0)
    assert res.action == NONE and res.consumed is False and res.typed == ""


def test_an_accept_after_expiry_types_nothing_but_is_still_consumed():
    s, _ = _offered(now=100.0)
    res = s.resolve("take it", 100.0 + SUGGESTION_TTL_S + 1.0)
    assert res.action == LATE
    assert res.consumed is True and res.typed == ""


def test_long_after_expiry_an_accept_is_just_a_word():
    s, _ = _offered(now=100.0)
    res = s.resolve("take it", 100.0 + SUGGESTION_TTL_S + LATE_GRACE_S + 1.0)
    assert res.action == EXPIRED and res.consumed is False


def test_ordinary_speech_after_expiry_is_dictated():
    s, _ = _offered(now=100.0)
    res = s.resolve("and bring the slides", 100.0 + SUGGESTION_TTL_S + 1.0)
    assert res.action == EXPIRED and res.consumed is False


def test_interrupt_forgets_offer_context_and_in_flight_request():
    s = PredictSession()
    epoch, _ = s.note_injected(CONTEXT)
    s.interrupt()
    assert s.pending is None and s.context == ""
    assert s.offer(epoch, " three pm on Friday", 1.0) is None


def test_drop_reports_whether_anything_was_withdrawn():
    s, _ = _offered()
    assert s.drop() is True
    assert s.drop() is False


def test_display_has_no_leading_separator():
    _, sug = _offered()
    assert sug.display == "three pm on Friday"
    assert sug.words == 4
