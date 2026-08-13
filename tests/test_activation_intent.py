"""Tests for the intent-carrying activation seam (#137) and its gate (#138).

Pure: no decoder, no desktop, no injector. Every case names the failure it locks
out, because the whole point of this layer is refusing things safely.
"""

from __future__ import annotations

import math

import pytest

from yazses.activation.confirm import (
    DEFAULT_CONFIRM_THRESHOLD,
    DEFAULT_REJECT_FLOOR,
    Consequence,
    Decision,
    classify_consequence,
    decide,
)
from yazses.activation.intent import ActivationIntent, Rejection, validate
from yazses.activation.pipeline import handle_intent

VOCAB = ("undo", "save", "new line", "delete line")


# ---- vocabulary validation ------------------------------------------------


def test_label_inside_the_declared_vocabulary_is_accepted():
    assert validate(ActivationIntent("undo", 0.99), VOCAB) is None


def test_label_outside_the_vocabulary_is_refused():
    """A source must not be able to ask for something it never advertised."""
    assert validate(ActivationIntent("format disk", 0.99), VOCAB) is Rejection.OUT_OF_VOCABULARY


def test_source_with_no_vocabulary_may_not_emit_intents():
    """EMGBackend declares none; it triggers, it does not decide."""
    assert validate(ActivationIntent("undo", 0.99), ()) is Rejection.NO_VOCABULARY


@pytest.mark.parametrize("label", ["", "   "])
def test_empty_label_is_refused(label):
    assert validate(ActivationIntent(label, 0.99), VOCAB) is Rejection.EMPTY_LABEL


@pytest.mark.parametrize("confidence", [-0.01, 1.01, math.nan, math.inf, -math.inf])
def test_confidence_outside_zero_to_one_is_refused(confidence):
    """NaN fails every comparison, so it must be tested for explicitly."""
    assert validate(ActivationIntent("undo", confidence), VOCAB) is Rejection.BAD_CONFIDENCE


def test_boolean_confidence_is_refused():
    """bool is an int in Python; True must not sail through as 1.0."""
    assert validate(ActivationIntent("undo", True), VOCAB) is Rejection.BAD_CONFIDENCE


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_confidence_bounds_are_inclusive(confidence):
    assert validate(ActivationIntent("undo", confidence), VOCAB) is None


# ---- consequence classification -------------------------------------------


@pytest.mark.parametrize("action", [
    "close", "quit", "send", "save", "delete_lines", "delete_words",
    "run_command", "run_tests", "commit", "push",
])
def test_actions_that_leave_the_undo_stack_are_irreversible(action):
    assert classify_consequence(action) is Consequence.IRREVERSIBLE


@pytest.mark.parametrize("action", ["press_enter", "arrow_left", "select_all", "copy"])
def test_ordinary_editing_actions_are_reversible(action):
    assert classify_consequence(action) is Consequence.REVERSIBLE


def test_unknown_action_defaults_to_irreversible():
    """Safe direction: an unclassified new command confirms rather than fires."""
    assert classify_consequence("launch_missiles") is Consequence.IRREVERSIBLE


def test_classification_ignores_case_and_padding():
    assert classify_consequence("  CLOSE  ") is Consequence.IRREVERSIBLE


def test_every_dispatcher_action_has_a_deliberate_consequence():
    """Contract: adding a command must be a decision, not a default.

    Walks the real dispatch tables. An action nobody classified is treated as
    irreversible and will confirm, which is safe — but it should be a choice, so
    this fails until someone makes it.
    """
    import re
    from pathlib import Path

    from yazses.activation.confirm import _IRREVERSIBLE_ACTIONS, _REVERSIBLE_ACTIONS

    src = Path(__file__).resolve().parent.parent / "src/yazses/commands/dispatch.py"
    actions = set(re.findall(r'^\s*"([a-z_0-9]+)":\s*\[', src.read_text(), re.M))
    assert actions, "found no actions in commands/dispatch.py -- test is looking at nothing"

    unclassified = sorted(actions - _REVERSIBLE_ACTIONS - _IRREVERSIBLE_ACTIONS)
    assert not unclassified, (
        "these dispatcher actions have no consequence classification in "
        f"activation/confirm.py: {unclassified}"
    )


# ---- the confidence x consequence policy ----------------------------------


def test_confident_reversible_action_just_happens():
    assert decide(0.99, Consequence.REVERSIBLE) is Decision.ACT


def test_unsure_reversible_action_asks_first():
    assert decide(0.70, Consequence.REVERSIBLE) is Decision.CONFIRM


def test_irreversible_action_confirms_even_at_full_confidence():
    """The core of #138: a threshold cannot make a destructive miss acceptable.

    At the literature's 96-97% in-session accuracy there is no confidence value
    that makes silent execution of an unrecoverable action defensible.
    """
    assert decide(1.0, Consequence.IRREVERSIBLE) is Decision.CONFIRM


def test_sub_chance_confidence_is_dropped_not_prompted():
    """Prompting on a coin flip trains users to dismiss prompts."""
    assert decide(0.20, Consequence.REVERSIBLE) is Decision.REJECT
    assert decide(0.20, Consequence.IRREVERSIBLE) is Decision.REJECT


def test_threshold_and_floor_are_boundary_inclusive():
    assert decide(DEFAULT_CONFIRM_THRESHOLD, Consequence.REVERSIBLE) is Decision.ACT
    assert decide(DEFAULT_REJECT_FLOOR, Consequence.REVERSIBLE) is Decision.CONFIRM


def test_thresholds_are_configurable():
    assert decide(0.75, Consequence.REVERSIBLE, threshold=0.7) is Decision.ACT
    assert decide(0.75, Consequence.REVERSIBLE, threshold=0.8) is Decision.CONFIRM


def test_defaults_are_the_documented_values():
    """These are cited in the docs and the PR rationale; pin them."""
    assert (DEFAULT_CONFIRM_THRESHOLD, DEFAULT_REJECT_FLOOR) == (0.90, 0.50)


# ---- end-to-end routing ----------------------------------------------------


class _Cmd:
    """Stand-in for CommandIntent; only `action` and `intent.name` are read."""

    def __init__(self, action, name="EDIT"):
        self.action = action
        self.intent = type("T", (), {"name": name})()


def _route(label, confidence, action, *, name="EDIT", confirm=None, vocab=VOCAB):
    dispatched = []
    outcome = handle_intent(
        ActivationIntent(label, confidence, source="test"),
        vocab,
        classify=lambda _: _Cmd(action, name),
        dispatch=dispatched.append,
        confirm=confirm,
    )
    return outcome, dispatched


def test_confident_reversible_intent_is_dispatched():
    outcome, dispatched = _route("undo", 0.99, "undo")
    assert outcome.executed and len(dispatched) == 1


def test_irreversible_intent_is_dispatched_only_after_a_yes():
    outcome, dispatched = _route("save", 0.99, "save", confirm=lambda a, i: True)
    assert outcome.decision is Decision.CONFIRM
    assert outcome.confirmed is True and len(dispatched) == 1


def test_declining_the_confirmation_dispatches_nothing():
    outcome, dispatched = _route("save", 0.99, "save", confirm=lambda a, i: False)
    assert not outcome.executed and dispatched == []


def test_confirmation_needed_but_impossible_fails_closed():
    """No prompt available must mean 'do not act', never 'assume yes'."""
    outcome, dispatched = _route("save", 0.99, "save", confirm=None)
    assert not outcome.executed and dispatched == []


def test_out_of_vocabulary_intent_never_reaches_the_grammar():
    called = []
    outcome = handle_intent(
        ActivationIntent("format disk", 0.99),
        VOCAB,
        classify=lambda t: called.append(t) or _Cmd("close"),
        dispatch=lambda c: pytest.fail("must not dispatch"),
    )
    assert outcome.rejection is Rejection.OUT_OF_VOCABULARY
    assert called == [], "classify must not run on a refused label"


def test_label_the_grammar_reads_as_plain_text_is_not_typed():
    """A decoder is not a keyboard; ~68% WER prose must not be injected."""
    outcome, dispatched = _route("undo", 0.99, "", name="DICTATE")
    assert not outcome.executed and dispatched == []


def test_low_confidence_intent_is_rejected_before_any_prompt():
    prompted = []
    outcome, dispatched = _route(
        "undo", 0.1, "undo", confirm=lambda a, i: prompted.append(a) or True
    )
    assert outcome.decision is Decision.REJECT
    assert dispatched == [] and prompted == []
