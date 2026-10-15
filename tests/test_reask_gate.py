"""Confidence-Gated Re-Ask, wired into the dictation path (ADR-v2-077).

`confidence.py` (span finder, confusion sets) is covered in `test_reask_verbatim.py`. What
is tested here is the judgement on top of it -- **when the gate may interrupt, and what a
reply may mean** -- because ADR-021's rule applies: a guard is judged on how *rarely* it
fires, and one that swallows the user's next sentence is worse than no guard. So most of
these tests assert silence, or that no text is ever lost.
"""
from __future__ import annotations

import math
from dataclasses import replace

import pytest

from yazses.config import Config, ReaskConfig
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.postprocess.prosody import Word
from yazses.reask.gate import (
    HOLD_SECONDS,
    ReaskGate,
    find_uncertain_word,
    locate,
    patch,
    reply_choice,
)

THEIR = ["their", "there", "they're"]
THRESHOLD = -1.0
SURE = 0.95
UNSURE = math.exp(-2.0)  # logprob -2.0, below the -1.0 default


class FakeTimer:
    """Stands in for threading.Timer: records the callback, fires only when told to."""

    made: list[FakeTimer] = []

    def __init__(self, interval, fn):
        self.interval, self.fn = interval, fn
        self.daemon = False
        self.started = False
        self.cancelled = False
        FakeTimer.made.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.fn()


@pytest.fixture(autouse=True)
def _reset_timers():
    FakeTimer.made = []


def _gate(expired=None):
    return ReaskGate(
        (expired if expired is not None else (lambda _t: None)),
        timer_factory=FakeTimer,
    )


# ---- the reply grammar is anchored at both ends -----------------------------


@pytest.mark.parametrize("reply, want", [
    ("second", "there"),
    ("the second one", "there"),
    ("The third one.", "they're"),
    ("first option", "their"),
    ("option 2", "there"),
    ("number three", "they're"),
    ("there", "there"),
    ("They're", "they're"),
    ("They’re", "they're"),
])
def test_a_reply_that_is_a_pick(reply, want):
    assert reply_choice(reply, THEIR) == want


@pytest.mark.parametrize("reply", [
    "I want one coffee",          # contains "one" -- parse_choice would take it
    "the second time was there",  # contains an ordinal AND an option
    "please pick the second one now",
    "there is a cat",
    "one",                        # a bare number word is not an ordinal here
    "fourth",
    "option 4",
    "",
    "second second",
])
def test_a_sentence_is_never_a_pick(reply):
    assert reply_choice(reply, THEIR) is None


def test_two_is_itself_an_option_not_the_second_ordinal():
    assert reply_choice("two", ["to", "too", "two"]) == "two"
    assert reply_choice("second", ["to", "too", "two"]) == "too"


# ---- when it must stay silent ------------------------------------------------


def test_nothing_uncertain_is_silent():
    words = [("it", SURE), ("is", SURE), ("there", SURE)]
    assert find_uncertain_word(words, THRESHOLD) is None


def test_an_uncertain_word_outside_the_table_is_silent():
    assert find_uncertain_word([("elephant", UNSURE)], THRESHOLD) is None


def test_two_uncertain_confusable_words_is_a_noisy_burst_not_a_question():
    words = [("their", UNSURE), ("is", SURE), ("to", UNSURE)]
    assert find_uncertain_word(words, THRESHOLD) is None


def test_an_unreported_probability_never_triggers():
    """`Word.probability` defaults to 0.0; an engine with no probabilities must not make
    every confusable word look uncertain."""
    assert find_uncertain_word([("there", 0.0)], THRESHOLD) is None


def test_a_repeated_word_is_not_held_because_the_patch_would_be_ambiguous():
    g = _gate()
    v = g.handle("there is there", [("there", UNSURE)], THRESHOLD)
    assert v.text == "there is there" and v.action == "" and not g.pending
    assert FakeTimer.made == []


def test_a_burst_with_no_confusable_word_passes_through_untouched():
    g = _gate()
    v = g.handle("hello world", [("hello", SURE), ("world", UNSURE)], THRESHOLD)
    assert (v.text, v.prompt, v.action) == ("hello world", "", "")


# ---- the hold / pick / release cycle -----------------------------------------


def _hold(g, text="Put it over there please."):
    words = [("Put", SURE), (" there", UNSURE), (" please.", SURE)]
    return g.handle(text, words, THRESHOLD)


def test_an_uncertain_word_holds_the_burst_and_asks():
    g = _gate()
    v = _hold(g)
    assert v.text is None and v.action == "held"
    assert "their / there / they're" in v.prompt
    assert g.pending
    (timer,) = FakeTimer.made
    assert timer.started and timer.daemon and timer.interval == HOLD_SECONDS


def test_a_pick_patches_only_that_word_and_types_the_burst():
    g = _gate()
    _hold(g)
    v = g.handle("the first one", [], THRESHOLD)
    assert v.text == "Put it over their please." and v.action == "picked"
    assert not g.pending and FakeTimer.made[0].cancelled


def test_a_pick_keeps_a_leading_capital():
    g = _gate()
    g.handle("There it is.", [("There", UNSURE)], THRESHOLD)
    assert g.handle("first", [], THRESHOLD).text == "Their it is."


def test_picking_the_word_already_there_changes_nothing():
    g = _gate()
    _hold(g)
    assert g.handle("there", [], THRESHOLD).text == "Put it over there please."


def test_a_reply_that_is_not_a_pick_releases_the_text_and_keeps_the_reply():
    g = _gate()
    _hold(g)
    v = g.handle("and then we left", [], THRESHOLD)
    assert v.text == "Put it over there please. and then we left"
    assert v.action == "released" and not g.pending


def test_a_reply_with_its_own_leading_space_is_not_double_spaced():
    g = _gate()
    _hold(g)
    assert g.handle(" next", [], THRESHOLD).text == "Put it over there please. next"


def test_a_reply_is_not_itself_held_again():
    """Resolving a hold must not chain into a second hold on the same utterance."""
    g = _gate()
    _hold(g)
    v = g.handle("over there", [("there", UNSURE)], THRESHOLD)
    assert v.action == "released" and not g.pending


def test_an_unanswered_hold_is_handed_to_on_expire_exactly_once():
    got: list[str] = []
    g = _gate(got.append)
    _hold(g)
    FakeTimer.made[0].fire()
    FakeTimer.made[0].fire()
    assert got == ["Put it over there please."] and not g.pending


def test_a_reply_that_beats_the_timer_wins_and_the_timer_then_does_nothing():
    got: list[str] = []
    g = _gate(got.append)
    _hold(g)
    g.handle("second", [], THRESHOLD)
    FakeTimer.made[0].fire()
    assert got == []


def test_cancel_returns_the_held_text_for_shutdown():
    g = _gate()
    _hold(g)
    assert g.cancel() == "Put it over there please."
    assert g.cancel() is None


def test_locate_and_patch_handle_the_apostrophe():
    m = locate("They’re late.", "they're")
    assert m is not None
    assert patch("They’re late.", m, "there") == "There late."


# ---- wired into the daemon -----------------------------------------------------


def _daemon(mocker):
    cfg = replace(Config(), reask=ReaskConfig(enabled=True))
    d = Daemon(config=cfg, platform=get_platform())
    mocker.patch("yazses.system.notify.notify")
    return d


def _w(*pairs):
    return [Word(t, 0.0, 0.0, p) for t, p in pairs]


def test_off_by_default_and_constructs_nothing():
    assert Config().reask.enabled is False
    d = Daemon(config=Config(), platform=get_platform())
    assert d._reask is None


def test_the_daemon_holds_then_patches(mocker):
    d = _daemon(mocker)
    event: dict = {}
    assert d._reask_gate("Over there.", _w(("there", UNSURE)), event) is None
    assert event["reask_action"] == "held"
    out = d._reask_gate("second", [], event)
    assert out == "Over there." and event["reask_action"] == "picked"


def test_the_prompt_is_sent_as_a_notification(mocker):
    d = _daemon(mocker)
    notify = mocker.patch("yazses.system.notify.notify")
    d._reask_gate("Over there.", _w(("there", UNSURE)), {})
    assert notify.call_count == 1 and "there" in notify.call_args.args[1]


def test_the_event_carries_the_action_and_never_the_words(mocker):
    d = _daemon(mocker)
    event: dict = {}
    d._reask_gate("Take it to Gdansk.", _w(("to", UNSURE)), event)
    assert event == {"reask_action": "held"}


def test_a_pending_command_safety_hold_keeps_first_claim(mocker):
    d = _daemon(mocker)
    d._cmdsafety.hold("rm -rf /tmp/x")
    assert d._reask_gate("Over there.", _w(("there", UNSURE)), {}) == "Over there."
    assert d._reask is None


def test_a_gate_that_raises_types_the_text_as_heard(mocker):
    d = _daemon(mocker)
    d._reask_gate("warm up", [], {})
    mocker.patch.object(d._reask, "handle", side_effect=RuntimeError("boom"))
    assert d._reask_gate("Over there.", _w(("there", UNSURE)), {}) == "Over there."


def test_expiry_copies_to_the_clipboard_and_never_types(mocker):
    d = _daemon(mocker)
    clip = mocker.patch("yazses.system.clipboard.set_clipboard", return_value=True)
    inject = mocker.patch.object(d, "_active_injector")
    d._reask_expired("Over there.")
    clip.assert_called_once_with("Over there.")
    inject.assert_not_called()


def test_the_gate_runs_on_the_dictation_path():
    """A correct pure module nothing calls would pass every test above."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(Daemon._on_hold_end)))
    called = {
        n.func.attr for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "_reask_gate" in called, "the gate is never reached from _on_hold_end"


def test_reask_is_wired_and_enableable():
    from yazses.system.features import unwired_slugs

    assert "reask" not in unwired_slugs()
