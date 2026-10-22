"""Voice Pilot "check X" / "uncheck X" are idempotent (ADR-v2-007, ADR-021).

Both verbs run the same backend action as "toggle" -- AT-SPI has no "set checked" -- so
before this fix "uncheck X" on an already-unchecked box clicked it and *checked* it, and
"check X" on a checked box unchecked it. Now the box's checked state is read with the
snapshot and decides:

* already in the asked state: nothing is done, and the user is told so;
* the other state: acted on exactly as before (an exact match at once);
* unreadable: never acted on at once -- held for a spoken "confirm", because a toggle on
  a guess can do the opposite of what was said.

Pinned end to end, offline: the pure decision, the service's messages, the treewalk copy,
the contract's validation, and the AT-SPI adapter over a fake ``pyatspi``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yazses.grounding.contracts import SemanticCandidate, SemanticSourceKind
from yazses.grounding.treewalk import NodeFacts, TreeLimits, walk
from yazses.pilot.plan import (
    ACT,
    ALREADY,
    CONFIRM,
    Element,
    decide,
    parse_command,
)
from yazses.pilot.service import PilotService, elements_from_candidates
from yazses.platform.linux.atspi_tree import AtspiAccessibility


def box(label: str, checked: bool | None, *, eid: str = "", role: str = "check box",
        actions: tuple[str, ...] = ("click",)) -> Element:
    return Element(label=label, role=role, actions=actions, checked=checked,
                   entity_id=eid or label)


# ---- parse: the asked state is kept --------------------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "action", "want"),
    [("check dark mode", "toggle", True), ("uncheck dark mode", "toggle", False),
     ("toggle dark mode", "toggle", None), ("click dark mode", "activate", None)],
)
def test_the_asked_state_is_parsed(phrase, action, want):
    cmd = parse_command(phrase)
    assert cmd is not None
    assert (cmd.action, cmd.target) == (action, "dark mode")
    assert cmd.want_checked is want


# ---- decide: idempotent --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("phrase", "state", "reason"),
    [("uncheck dark mode", False, "already_unchecked"),
     ("check dark mode", True, "already_checked")],
)
def test_a_box_already_in_the_asked_state_is_left_alone(phrase, state, reason):
    d = decide(phrase, [box("Dark mode", state)])
    assert (d.verdict, d.reason) == (ALREADY, reason)
    assert d.action_name is None, "nothing may be run on a box that is already right"


@pytest.mark.parametrize(
    ("phrase", "state"),
    [("uncheck dark mode", True), ("check dark mode", False)],
)
def test_a_box_in_the_other_state_is_toggled_at_once(phrase, state):
    d = decide(phrase, [box("Dark mode", state)])
    assert (d.verdict, d.reason) == (ACT, "exact")
    assert d.action_name == "click"


@pytest.mark.parametrize("phrase", ["check dark mode", "uncheck dark mode"])
def test_an_unreadable_state_is_held_for_confirm_never_acted_on(phrase):
    d = decide(phrase, [box("Dark mode", None)])
    assert (d.verdict, d.reason) == (CONFIRM, "state_unknown")
    assert d.action_name == "click"


def test_toggle_still_flips_whatever_the_state():
    for state in (True, False, None):
        d = decide("toggle dark mode", [box("Dark mode", state)])
        assert (d.verdict, d.reason) == (ACT, "exact")


def test_a_weak_match_already_in_the_asked_state_is_not_offered_for_confirm():
    """Confirming it would flip the box the wrong way, so nothing is held."""
    d = decide("uncheck dark mode please", [box("Dark mode", False)])
    assert d.verdict == ALREADY


def test_a_weak_match_in_the_other_state_is_still_held_as_weak():
    d = decide("check dark mode please", [box("Dark mode", False)])
    assert (d.verdict, d.reason) == (CONFIRM, "weak")


def test_an_ordinal_picks_the_box_whose_state_is_then_read():
    els = [box("Notify", True, eid="first"), box("Notify", False, eid="second")]
    assert decide("check the first notify", els).verdict == ALREADY
    d = decide("check the second notify", els)
    assert (d.verdict, d.reason) == (ACT, "ordinal")
    assert d.element.entity_id == "second"


# ---- the service: messages and what is performed --------------------------------------------


def cand(label: str, eid: str, checked: bool | None) -> SemanticCandidate:
    return SemanticCandidate(source=SemanticSourceKind.ACCESSIBILITY, entity_id=eid,
                             role="check box", captured_at_s=0.0, confidence=1.0,
                             label=label, actions=("click",), checked=checked)


class FakeReader:
    def __init__(self, cands) -> None:
        self.cands = cands
        self.performed: list[tuple[str, str]] = []

    def read(self):
        return self.cands

    def perform(self, entity_id: str, action: str) -> bool:
        self.performed.append((entity_id, action))
        return True


def test_uncheck_on_an_unchecked_box_clicks_nothing_and_says_so():
    reader = FakeReader((cand("Dark mode", "n0", False),))
    out = PilotService(reader).command("uncheck dark mode")
    assert out.verdict == "already" and out.consumed
    assert reader.performed == []
    assert out.message == "'Dark mode' is already unchecked; nothing was changed."


def test_check_on_a_checked_box_clicks_nothing():
    reader = FakeReader((cand("Dark mode", "n0", True),))
    s = PilotService(reader)
    out = s.command("check dark mode")
    assert out.verdict == "already" and "already checked" in out.message
    assert reader.performed == [] and not s.pending


def test_uncheck_on_a_checked_box_clicks_it_and_says_unchecked():
    reader = FakeReader((cand("Dark mode", "n0", True),))
    out = PilotService(reader).command("uncheck dark mode")
    assert out.verdict == "act"
    assert reader.performed == [("n0", "click")]
    assert out.message == "Unchecked 'Dark mode'."


def test_an_unreadable_state_is_held_and_confirm_toggles_it():
    reader = FakeReader((cand("Dark mode", "n0", None),))
    s = PilotService(reader)
    out = s.command("check dark mode")
    assert out.verdict == "confirm"
    assert reader.performed == [], "a check on an unread state ran without a confirm"
    assert "Could not read whether 'Dark mode' is checked" in out.message
    assert "toggle 'Dark mode'" in out.message
    assert s.answer("confirm").verdict == "confirmed"
    assert reader.performed == [("n0", "click")]


def test_elements_carry_the_checked_state_and_refuse_a_non_bool():
    els = elements_from_candidates([
        cand("A", "n0", True), cand("B", "n1", None),
        SimpleNamespace(label="C", role="check box", actions=("click",), entity_id="n2",
                        checked=1),
    ])
    assert [e.checked for e in els] == [True, None, None]


# ---- the contract and the walk --------------------------------------------------------------


@pytest.mark.parametrize("bad", [1, 0, "yes", "false"])
def test_the_contract_refuses_a_checked_that_is_not_a_bool(bad):
    with pytest.raises(ValueError, match="checked"):
        cand("A", "n0", bad)  # type: ignore[arg-type]


def test_the_contract_defaults_checked_to_unknown():
    c = SemanticCandidate(source=SemanticSourceKind.ACCESSIBILITY, entity_id="n0",
                          role="push button", captured_at_s=0.0, confidence=1.0, label="Save")
    assert c.checked is None


class _CheckedOps:
    """A two-node tree whose facts carry a checked state (and one junk value)."""

    def __init__(self, states) -> None:
        self._states = states

    def facts(self, node, limits):
        return NodeFacts(name=node, role="check box", actions=("click",),
                         checked=self._states[node])

    def children(self, node):
        return ["A", "B", "C"] if node == "root" else []


def test_the_walk_copies_the_checked_state_and_drops_a_non_bool():
    ops = _CheckedOps({"root": None, "A": True, "B": False, "C": "yes"})
    result = walk("root", ops, TreeLimits(), clock=lambda: 0.0, captured_at_s=1.0)
    by_label = {c.label: c.checked for c in result.candidates}
    assert by_label == {"root": None, "A": True, "B": False, "C": None}


# ---- the AT-SPI adapter, over a fake pyatspi -------------------------------------------------

SHOWING, ACTIVE = "showing", "active"
CHECKED, CHECKABLE, INDETERMINATE = "checked", "checkable", "indeterminate"


class _States:
    def __init__(self, flags) -> None:
        self._flags = set(flags)

    def contains(self, flag) -> bool:
        return flag in self._flags


class _Node:
    def __init__(self, name, role="check box", states=(SHOWING,), kids=()) -> None:
        self.name = name
        self._role = role
        self._states = states
        self._kids = list(kids)

    def getRoleName(self):
        return self._role

    def getState(self):
        return _States(self._states)

    @property
    def childCount(self):
        return len(self._kids)

    def getChildAtIndex(self, i):
        return self._kids[i]

    def queryAction(self):
        class Action:
            nActions = 1

            def getName(self, _i):
                return "click"

            def doAction(self, _i):
                return True

        return Action()


def _snapshot(kids, *, with_checked_flag: bool = True):
    window = _Node("Settings", role="frame", states=(SHOWING, ACTIVE), kids=kids)
    desktop = _Node("desktop", role="desktop frame",
                    kids=[_Node("app", role="application", kids=[window])])
    mod = SimpleNamespace(
        STATE_SHOWING=SHOWING, STATE_ACTIVE=ACTIVE, STATE_CHECKABLE=CHECKABLE,
        STATE_INDETERMINATE=INDETERMINATE,
        Registry=SimpleNamespace(getDesktop=lambda _i: desktop),
    )
    if with_checked_flag:
        mod.STATE_CHECKED = CHECKED
    backend = AtspiAccessibility(atspi=mod, clock=lambda: 1.0)
    return {c.label: c.checked for c in backend.snapshot()}


def test_atspi_reads_checked_and_unchecked_boxes():
    got = _snapshot([
        _Node("Dark mode", states=(SHOWING, CHECKED)),
        _Node("Autosave", states=(SHOWING,)),
        _Node("Bold", role="check menu item", states=(SHOWING,)),
        _Node("Large", role="radio button", states=(SHOWING, CHECKED)),
    ])
    assert got["Dark mode"] is True
    assert got["Autosave"] is False
    assert got["Bold"] is False
    assert got["Large"] is True


def test_atspi_says_unknown_for_a_non_checkable_or_half_checked_control():
    got = _snapshot([
        _Node("Save", role="push button"),
        _Node("Wrap", role="toggle button"),          # might report PRESSED instead
        _Node("Select all", states=(SHOWING, INDETERMINATE)),
    ])
    assert got["Save"] is None
    assert got["Wrap"] is None, "a toggle button not reported checked may still be on"
    assert got["Select all"] is None
    assert got["Settings"] is None


def test_atspi_trusts_checkable_on_any_role():
    got = _snapshot([_Node("Wrap", role="toggle button", states=(SHOWING, CHECKABLE))])
    assert got["Wrap"] is False


def test_a_binding_without_the_checked_flag_reads_unknown_never_unchecked():
    got = _snapshot([_Node("Autosave", states=(SHOWING,))], with_checked_flag=False)
    assert got["Autosave"] is None
