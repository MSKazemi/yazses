"""Voice Pilot "uncheck X" on a radio button is refused, not clicked (ADR-v2-007, ADR-021).

A radio button cannot be unchecked by clicking it: clicking selects it, and it is turned
off by choosing another option. Before this fix "uncheck X" on a selected radio button
clicked it -- which changes nothing in most toolkits -- and reported "Unchecked 'X'", a
false report. On a radio whose state could not be read, the confirmed click would even
have *selected* it, the opposite of what was said.

Now "uncheck" on a radio button or radio menu item is refused with the reason, whatever
its state, and "check" on a selected one says it is already checked.
"""

from __future__ import annotations

import pytest

from yazses.grounding.contracts import SemanticCandidate, SemanticSourceKind
from yazses.pilot.plan import (
    ACT,
    ALREADY,
    REFUSED,
    Element,
    HeldTarget,
    decide,
    is_radio_role,
    parse_command,
    redecide_held,
)
from yazses.pilot.service import PilotService

RADIO_ROLES = ["radio button", "radio menu item"]


def radio(label: str, checked: bool | None, *, role: str = "radio button",
          eid: str = "") -> Element:
    return Element(label=label, role=role, actions=("click",), checked=checked,
                   entity_id=eid or label)


# ---- the pure decision ---------------------------------------------------------------------


@pytest.mark.parametrize("role", RADIO_ROLES)
@pytest.mark.parametrize("state", [True, False, None])
def test_uncheck_on_a_radio_is_refused_whatever_its_state(role, state):
    d = decide("uncheck large", [radio("Large", state, role=role)])
    assert (d.verdict, d.reason) == (REFUSED, "radio_uncheck")
    assert d.action_name is None, "nothing may be run for an uncheck on a radio button"
    assert d.element.label == "Large"


def test_a_weak_uncheck_match_on_a_radio_is_refused_not_offered_for_confirm():
    d = decide("uncheck large size", [radio("Large", True)])
    assert d.verdict == REFUSED


@pytest.mark.parametrize("role", RADIO_ROLES)
def test_check_on_a_selected_radio_is_already_checked(role):
    d = decide("check large", [radio("Large", True, role=role)])
    assert (d.verdict, d.reason) == (ALREADY, "already_checked")
    assert d.action_name is None


def test_check_on_an_unselected_radio_selects_it():
    d = decide("check large", [radio("Large", False)])
    assert (d.verdict, d.reason) == (ACT, "exact")
    assert d.action_name == "click"


def test_uncheck_on_a_check_box_is_unaffected():
    d = decide("uncheck large", [radio("Large", True, role="check box")])
    assert (d.verdict, d.reason) == (ACT, "exact")


@pytest.mark.parametrize(
    ("role", "expected"),
    [("radio button", True), ("Radio Button", True), ("radio_menu_item", True),
     (" radio  menu item ", True), ("check box", False), ("toggle button", False),
     ("", False), ("radio", False)],
)
def test_is_radio_role(role, expected):
    assert is_radio_role(role) is expected


def test_a_hand_built_held_uncheck_on_a_radio_is_refused_at_confirm_too():
    held = HeldTarget(command=parse_command("uncheck large"), label="Large",
                      role="radio button", checked=None)
    d = redecide_held(held, [radio("Large", None, eid="s2n0")])
    assert (d.verdict, d.reason) == (REFUSED, "radio_uncheck")
    assert d.action_name is None


# ---- the service: what is clicked and what is said ------------------------------------------


def cand(label: str, eid: str, checked: bool | None,
         role: str = "radio button") -> SemanticCandidate:
    return SemanticCandidate(source=SemanticSourceKind.ACCESSIBILITY, entity_id=eid,
                             role=role, captured_at_s=0.0, confidence=1.0,
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


@pytest.mark.parametrize("state", [True, False, None])
def test_service_uncheck_on_a_radio_clicks_nothing_and_explains(state):
    reader = FakeReader((cand("Large", "n0", state), cand("Small", "n1", not state)))
    s = PilotService(reader)
    out = s.command("uncheck large")
    assert out.verdict == "refused" and out.consumed
    assert reader.performed == [], "an uncheck on a radio button clicked it"
    assert not s.pending, "a refused uncheck must not be held for confirm"
    assert out.message == ("Cannot uncheck 'Large': a radio button is turned off by "
                           "choosing another option. Nothing was changed.")
    assert "Unchecked" not in out.message


def test_service_uncheck_on_a_radio_menu_item_is_refused():
    reader = FakeReader((cand("Large", "n0", True, role="radio menu item"),))
    out = PilotService(reader).command("uncheck large")
    assert out.verdict == "refused" and reader.performed == []


def test_service_check_on_a_selected_radio_says_already_checked():
    reader = FakeReader((cand("Large", "n0", True),))
    out = PilotService(reader).command("check large")
    assert out.verdict == "already" and reader.performed == []
    assert out.message == "'Large' is already checked; nothing was changed."


def test_service_check_on_an_unselected_radio_selects_it():
    reader = FakeReader((cand("Large", "n0", False),))
    out = PilotService(reader).command("check large")
    assert out.verdict == "act"
    assert reader.performed == [("n0", "click")]
    assert out.message == "Checked 'Large'."
