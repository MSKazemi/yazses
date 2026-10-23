"""A held Voice Pilot "check X" / "uncheck X" is decided again at confirm time (ADR-021).

A "check" is held for a spoken "confirm" when its state could not be read, or the match
was partial or tied. The hold lasts up to 30 s, and before this fix "confirm" then ran
the toggle on the reading taken at hold time. If the user had clicked the box in the
meantime, "confirm" flipped it back -- the opposite of what they said. If the window had
changed, it acted on a snapshot id that no longer meant the same control.

Now "confirm" re-reads the window, finds the same control again by label and role, and
re-runs the decision on the fresh reading. Pinned here: the pure re-decision, the service
over a fake reader whose snapshots change between the prompt and the answer, and the
whole path through a real :class:`OnScreenReader` over a fake backend that, like AT-SPI,
refuses an id from an older snapshot.

The same re-decision now covers every held click (a destructive label, a partial match,
a tie); `test_pilot_confirm_recheck_all_clicks.py` pins those.
"""

from __future__ import annotations

import pytest

from yazses.grounding.contracts import SemanticCandidate, SemanticSourceKind
from yazses.grounding.onscreen import OnScreenReader
from yazses.pilot.plan import (
    ACT,
    ALREADY,
    CONFIRM,
    HELD_AMBIGUOUS,
    HELD_GONE,
    HELD_STATE_LOST,
    NO_MATCH,
    Element,
    HeldTarget,
    decide,
    held_target,
    parse_command,
    redecide_held,
)
from yazses.pilot.service import PilotService


def box(label: str, checked: bool | None, *, eid: str = "", role: str = "check box",
        actions: tuple[str, ...] = ("click",)) -> Element:
    return Element(label=label, role=role, actions=actions, checked=checked,
                   entity_id=eid or label)


def held_for(phrase: str, elements: list[Element]) -> HeldTarget:
    d = decide(phrase, elements)
    assert d is not None and d.verdict == CONFIRM, d
    target = held_target(d, elements)
    assert target is not None
    return target


# ---- the pure re-decision ------------------------------------------------------------------


def test_every_held_verb_gets_a_held_target_and_only_a_held_one():
    els = [box("Delete", None, role="push button")]
    d = decide("click delete", els)
    assert d.verdict == CONFIRM
    t = held_target(d, els)
    assert t is not None, "a held click must be found again at confirm, not acted on blind"
    assert (t.label, t.role, t.occurrence, t.occurrences) == ("Delete", "push button", 0, 1)
    # Not among the elements it is described over: nothing to find again.
    assert held_target(decide("check delete", [box("Delete", False)]), []) is None
    # Not held at all (an exact, safe match acts at once): no target.
    save = [box("Save", None, role="push button")]
    assert held_target(decide("click save", save), save) is None


def test_held_target_records_label_role_state_and_position():
    els = [box("Notify", None, eid="a"), box("Notify", None, eid="b"),
           box("Notify", None, eid="c", role="push button")]
    t = held_for("check notify", els)          # a tie: the first is offered
    assert (t.label, t.role, t.checked) == ("Notify", "check box", None)
    assert (t.occurrence, t.occurrences) == (0, 2), "a push button is not the same control"
    assert t.command.want_checked is True


def test_state_changed_during_the_hold_is_already_and_acts_on_nothing():
    t = held_for("check dark mode", [box("Dark mode", None)])
    d = redecide_held(t, [box("Dark mode", True, eid="s2n0")])
    assert (d.verdict, d.reason) == (ALREADY, "already_checked")
    assert d.action_name is None


def test_a_box_unchecked_by_hand_during_an_uncheck_hold_is_left_alone():
    t = held_for("uncheck dark mode please", [box("Dark mode", True)])   # weak match
    assert t.checked is True
    d = redecide_held(t, [box("Dark mode", False, eid="s2n0")])
    assert (d.verdict, d.reason) == (ALREADY, "already_unchecked")


def test_a_vanished_target_is_refused():
    t = held_for("check dark mode", [box("Dark mode", None)])
    d = redecide_held(t, [box("Light mode", False, eid="s2n0")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_GONE)
    assert d.element is None and d.action_name is None


def test_a_target_whose_role_changed_is_gone_not_matched_by_label_alone():
    t = held_for("check dark mode", [box("Dark mode", None)])
    d = redecide_held(t, [box("Dark mode", None, role="push button")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_GONE)


def test_a_target_that_lost_its_action_is_gone():
    t = held_for("check dark mode", [box("Dark mode", None)])
    d = redecide_held(t, [box("Dark mode", False, actions=())])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_GONE)


def test_a_changed_number_of_identical_controls_is_ambiguous_and_refused():
    t = held_for("check notify", [box("Notify", False, eid="a"), box("Notify", False, eid="b")])
    d = redecide_held(t, [box("Notify", False, eid="x"), box("Notify", False, eid="y"),
                          box("Notify", False, eid="z")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_AMBIGUOUS)
    assert d.action_name is None


def test_the_same_position_among_identical_controls_is_found_again():
    els = [box("Notify", False, eid="a"), box("Notify", False, eid="b")]
    t = held_for("check the second notify please", els)   # ordinal over weak matches
    assert t.occurrence == 1
    d = redecide_held(t, [box("Notify", True, eid="s2a"), box("Notify", False, eid="s2b")])
    assert (d.verdict, d.element.entity_id) == (ACT, "s2b")


def test_a_state_read_at_hold_time_and_unreadable_now_is_refused():
    t = held_for("check dark mode please", [box("Dark mode", False)])
    d = redecide_held(t, [box("Dark mode", None)])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_STATE_LOST)


@pytest.mark.parametrize(
    ("phrase", "hold_state", "now_state"),
    [("check dark mode", None, None),          # confirmed a toggle on an unread state
     ("check dark mode", None, False),         # unread then, still the other state now
     ("check dark mode please", False, False),  # weak match, unchanged
     ("uncheck dark mode please", True, True)],
)
def test_an_unchanged_target_acts_on_the_new_snapshot_id(phrase, hold_state, now_state):
    t = held_for(phrase, [box("Dark mode", hold_state, eid="s1n0")])
    d = redecide_held(t, [box("Dark mode", now_state, eid="s2n0")])
    assert (d.verdict, d.reason) == (ACT, "confirmed")
    assert d.element.entity_id == "s2n0", "the old snapshot's id must never be acted on"
    assert d.action_name == "click"


def test_the_label_is_matched_by_whitespace_and_case_insensitive_identity():
    t = held_for("check dark mode", [box("Dark mode", None)])
    d = redecide_held(t, [box("  dark   MODE ", False, eid="s2n0")])
    assert d.verdict == ACT


def test_redecide_held_is_total_on_an_empty_read():
    t = HeldTarget(command=parse_command("check dark mode"), label="Dark mode",
                   role="check box")
    assert redecide_held(t, []).verdict == NO_MATCH


# ---- the service, over a reader whose snapshot changes during the hold ----------------------


def cand(label: str, eid: str, checked: bool | None,
         role: str = "check box") -> SemanticCandidate:
    return SemanticCandidate(source=SemanticSourceKind.ACCESSIBILITY, entity_id=eid,
                             role=role, captured_at_s=0.0, confidence=1.0,
                             label=label, actions=("click",), checked=checked)


class ChangingReader:
    """Duck-types `OnScreenReader`; each `read()` returns the next snapshot in turn."""

    def __init__(self, *snapshots) -> None:
        self.snapshots = list(snapshots)
        self.reads = 0
        self.performed: list[tuple[str, str]] = []

    def read(self):
        snap = self.snapshots[min(self.reads, len(self.snapshots) - 1)]
        self.reads += 1
        return snap

    def perform(self, entity_id: str, action: str) -> bool:
        self.performed.append((entity_id, action))
        return True


def test_service_state_changed_during_hold_clicks_nothing():
    reader = ChangingReader((cand("Dark mode", "s1n0", None),),
                            (cand("Dark mode", "s2n0", True),))
    s = PilotService(reader)
    assert s.command("check dark mode").verdict == "confirm"
    out = s.answer("confirm")
    assert reader.reads == 2, "confirm must re-read the window"
    assert reader.performed == [], "confirm toggled a box the user had already checked"
    assert out.verdict == "already" and out.consumed
    assert out.message == "'Dark mode' is already checked now; nothing was changed."
    assert not s.pending


def test_service_vanished_target_is_refused_with_a_reason():
    reader = ChangingReader((cand("Dark mode", "s1n0", None),),
                            (cand("Font size", "s2n0", None, role="spin button"),))
    s = PilotService(reader)
    s.command("check dark mode")
    out = s.answer("confirm")
    assert reader.performed == []
    assert out.verdict == "refused" and out.consumed
    assert "no longer in the window" in out.message and "Nothing was changed" in out.message


def test_service_ambiguous_after_the_hold_is_refused():
    reader = ChangingReader(
        (cand("Notify", "s1n0", False), cand("Notify", "s1n1", False)),
        (cand("Notify", "s2n0", False),),
    )
    s = PilotService(reader)
    assert s.command("check notify").verdict == "confirm"     # a tie
    out = s.answer("confirm")
    assert reader.performed == []
    assert out.verdict == "refused" and "no longer clear which" in out.message


def test_service_lost_state_is_refused():
    reader = ChangingReader((cand("Dark mode", "s1n0", False),),
                            (cand("Dark mode", "s2n0", None),))
    s = PilotService(reader)
    assert s.command("check dark mode please").verdict == "confirm"
    out = s.answer("confirm")
    assert reader.performed == [] and out.verdict == "refused"
    assert "can no longer be read" in out.message


def test_service_unchanged_target_acts_once_on_the_new_id():
    reader = ChangingReader((cand("Dark mode", "s1n0", False),),
                            (cand("Dark mode", "s2n0", False),))
    s = PilotService(reader)
    assert s.command("check dark mode please").verdict == "confirm"
    out = s.answer("confirm")
    assert reader.performed == [("s2n0", "click")]
    assert out.verdict == "confirmed" and out.message == "Done: checked 'Dark mode'."
    assert s.answer("confirm").consumed is False, "a second confirm must not act again"
    assert reader.performed == [("s2n0", "click")]


def test_service_unread_state_confirmed_says_toggled():
    reader = ChangingReader((cand("Dark mode", "s1n0", None),),
                            (cand("Dark mode", "s2n0", None),))
    s = PilotService(reader)
    s.command("uncheck dark mode")
    out = s.answer("confirm")
    assert reader.performed == [("s2n0", "click")]
    assert out.message == "Done: toggled 'Dark mode'."


def test_service_an_unreadable_window_at_confirm_is_refused():
    reader = ChangingReader((cand("Dark mode", "s1n0", None),), None)
    s = PilotService(reader)
    s.command("check dark mode")
    out = s.answer("confirm")
    assert reader.performed == [] and out.verdict == "refused"
    assert "Could not re-read the window" in out.message


def test_a_held_plain_click_is_re_read_and_acts_on_the_new_id():
    reader = ChangingReader((cand("Delete", "s1n0", None, role="push button"),),
                            (cand("Delete", "s2n0", None, role="push button"),))
    s = PilotService(reader)
    assert s.command("click delete").verdict == "confirm"
    assert s.answer("confirm").verdict == "confirmed"
    assert reader.reads == 2, "confirm must re-read the window for every held click"
    assert reader.performed == [("s2n0", "click")]


def test_cancel_on_a_held_check_reads_nothing_and_clicks_nothing():
    reader = ChangingReader((cand("Dark mode", "s1n0", None),))
    s = PilotService(reader)
    s.command("check dark mode")
    assert s.answer("cancel").verdict == "cancelled"
    assert reader.reads == 1 and reader.performed == []


# ---- end to end through OnScreenReader, over a backend with per-snapshot ids ---------------


class SnapshotBackend:
    """Like AT-SPI's adapter: ids are per snapshot, and an id from an older one is refused."""

    def __init__(self, states: list[bool | None]) -> None:
        self.states = states
        self.generation = 0
        self.clicked: list[str] = []

    def snapshot(self, *, window_id=None, region=None):
        self.generation += 1
        return (cand("Dark mode", f"s{self.generation}n0", self.states[0]),)

    def perform(self, entity_id: str, action: str) -> bool:
        if not entity_id.startswith(f"s{self.generation}n"):
            return False                               # a stale id: refused, not guessed
        self.clicked.append(entity_id)
        self.states[0] = None if self.states[0] is None else not self.states[0]
        return True


def test_end_to_end_box_checked_by_hand_during_hold_stays_checked():
    backend = SnapshotBackend([None])
    s = PilotService(OnScreenReader(lambda: backend))
    assert s.command("check dark mode").verdict == "confirm"
    backend.states[0] = True                           # the user ticked it themselves
    out = s.answer("confirm")
    assert out.verdict == "already"
    assert backend.clicked == [] and backend.states == [True]


def test_end_to_end_unchanged_box_is_clicked_once_with_the_fresh_id():
    backend = SnapshotBackend([False])
    s = PilotService(OnScreenReader(lambda: backend))
    assert s.command("check dark mode please").verdict == "confirm"
    out = s.answer("confirm")
    assert out.verdict == "confirmed"
    assert backend.clicked == ["s2n0"] and backend.states == [True]
