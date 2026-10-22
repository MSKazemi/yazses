"""`pilot.plan.decide`: act only on a specific, checkable match (ADR-v2-007, ADR-021).

Pure, so every case is a list of plain `Element` values. The direction that matters is
the negative one: a partial match, a tie and a destructive label must never come back
as ACT, and a static label that merely *reads* "Save" must never be picked over the
button that does.
"""

from __future__ import annotations

import pytest

from yazses.pilot.plan import (
    ACT,
    CONFIRM,
    NO_MATCH,
    Element,
    decide,
    is_destructive_label,
    resolve_action_name,
)


def btn(label: str, *actions: str, eid: str = "") -> Element:
    return Element(label=label, role="push button", actions=actions or ("click",),
                   entity_id=eid or label)


DIALOG = [btn("Save"), btn("Save As"), btn("Cancel"), btn("Delete"),
          Element("Save", role="label", actions=())]


# ---- ACT ---------------------------------------------------------------------------------


def test_one_exact_actionable_match_acts():
    d = decide("click the Save button", DIALOG)
    assert d is not None
    assert (d.verdict, d.reason) == (ACT, "exact")
    assert d.element.label == "Save" and d.element.role == "push button"
    assert d.action_name == "click"


def test_the_static_label_reading_save_is_never_the_target():
    d = decide("click save", [Element("Save", role="label"), btn("Save", eid="real")])
    assert d.verdict == ACT and d.element.entity_id == "real"


def test_an_ordinal_over_exact_matches_acts_on_the_nth_in_reading_order():
    els = [btn("Save", eid="first"), btn("Save", eid="second"), btn("Quit")]
    d = decide("click the second save", els)
    assert (d.verdict, d.reason) == (ACT, "ordinal")
    assert d.element.entity_id == "second"


def test_focus_never_needs_the_destructive_confirmation():
    els = [btn("Delete", "click", "focus")]
    d = decide("select delete", els)
    assert d.verdict == ACT and d.action_name == "focus"


def test_toggle_prefers_the_toggle_action():
    d = decide("toggle dark mode", [btn("Dark mode", "click", "toggle")])
    assert d.verdict == ACT and d.action_name == "toggle"


# ---- CONFIRM -----------------------------------------------------------------------------


@pytest.mark.parametrize("label", ["Delete", "Send", "Don't Save", "Log out", "Empty Trash",
                                   "Move to Trash", "Buy now", "Uninstall"])
def test_a_destructive_label_is_held_even_on_an_exact_match(label):
    d = decide(f"click {label}", [btn(label)])
    assert (d.verdict, d.reason) == (CONFIRM, "destructive")


def test_a_partial_match_is_held_as_weak():
    d = decide("click save", [btn("Save As"), btn("Cancel")])
    assert (d.verdict, d.reason) == (CONFIRM, "weak")
    assert d.element.label == "Save As"


def test_a_tie_is_held_and_offers_the_first_in_reading_order():
    els = [btn("Save", eid="a"), btn("Save", eid="b")]
    d = decide("click save", els)
    assert (d.verdict, d.reason) == (CONFIRM, "ambiguous")
    assert d.element.entity_id == "a" and d.matches == 2


def test_a_tie_between_partial_matches_is_also_ambiguous():
    d = decide("click report", [btn("Report bug"), btn("Report spam")])
    assert (d.verdict, d.reason) == (CONFIRM, "ambiguous")


def test_with_confirm_ambiguous_off_a_tie_does_nothing_rather_than_guess():
    els = [btn("Save"), btn("Save")]
    d = decide("click save", els, confirm_ambiguous=False)
    assert (d.verdict, d.reason) == (NO_MATCH, "ambiguous")
    assert d.element is None


def test_an_ordinal_over_only_partial_matches_is_still_held():
    d = decide("click the second save", [btn("Save As"), btn("Save Copy")])
    assert (d.verdict, d.reason) == (CONFIRM, "weak")


def test_an_ordinal_on_a_destructive_exact_match_is_still_held():
    d = decide("click the second delete", [btn("Delete"), btn("Delete")])
    assert (d.verdict, d.reason) == (CONFIRM, "destructive")


# ---- NO_MATCH / not a command ----------------------------------------------------------


def test_nothing_on_screen_matches():
    d = decide("click frobnicate", DIALOG)
    assert (d.verdict, d.reason) == (NO_MATCH, "no_match")


def test_a_match_that_cannot_be_clicked_is_no_match():
    d = decide("click save", [Element("Save", role="label")])
    assert d.verdict == NO_MATCH


def test_an_ordinal_past_the_end_is_no_match():
    d = decide("click the fifth save", [btn("Save")])
    assert (d.verdict, d.reason) == (NO_MATCH, "ordinal_out_of_range")


@pytest.mark.parametrize("phrase", ["", "hello world", "the save button", "click the"])
def test_a_phrase_that_is_not_a_command_is_none(phrase):
    assert decide(phrase, DIALOG) is None


def test_the_threshold_is_honoured():
    assert decide("click save", [btn("Save As")], threshold=0.9).verdict == NO_MATCH


# ---- the two small helpers ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("verb", "offered", "expected"),
    [
        ("activate", ("press",), "press"),
        ("activate", ("Click", "press"), "click"),
        ("activate", ("jump",), "jump"),
        ("toggle", ("click",), "click"),
        ("focus", ("click", "focus"), "focus"),
        ("focus", ("click",), None),
        ("activate", (), None),
        ("nonsense", ("click",), None),
    ],
)
def test_resolve_action_name(verb, offered, expected):
    assert resolve_action_name(verb, offered) == expected


@pytest.mark.parametrize("label", ["Save", "Open", "Format", "Replace", "Trash", "Cancel",
                                   "OK", "Close tab", "Deleted items", "Settings", "Postcode"])
def test_ordinary_labels_are_not_destructive(label):
    """A guard is judged on how rarely it fires (ADR-021): these must not prompt."""
    assert is_destructive_label(label) is False


@pytest.mark.parametrize("label", ["Delete", "Remove account", "Do not save", "Sign out",
                                   "Shut down", "Restart now", "Submit", "Send message"])
def test_destructive_labels(label):
    assert is_destructive_label(label) is True
