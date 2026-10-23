"""Every Voice Pilot click held for "confirm" is decided again at confirm time (ADR-021).

A destructive label ("Delete", "Send", "Log out"), a partial match and a tie on a plain
button are held for a spoken "confirm", for up to 30 s. Before this fix the confirm then
clicked the node first matched, by its hold-time snapshot id: if the dialog had changed,
that id named a different control or none, and if a second identical "Delete" row had
appeared there was no telling which one the prompt meant.

Now the confirm re-reads the window and finds the held control again by its exact label
(case and whitespace folded), its role, an action able to carry out the verb, and its
position among identical controls -- the same pure ``plan.redecide_held`` that a held
"check"/"uncheck" uses (`test_pilot_confirm_recheck.py`). Pinned here, for a destructive
click and a tied plain-button click: unchanged acts once on the *new* id; vanished,
relabelled, a different role, no longer clickable, or one identical control more or less
is refused and clicks nothing. Pure, then the service over a reader whose snapshots
change during the hold, then end to end through a real :class:`OnScreenReader` over a
backend that refuses an id from an older snapshot.
"""

from __future__ import annotations

import pytest

from yazses.grounding.contracts import SemanticCandidate, SemanticSourceKind
from yazses.grounding.onscreen import OnScreenReader
from yazses.pilot.plan import (
    ACT,
    CONFIRM,
    HELD_AMBIGUOUS,
    HELD_GONE,
    NO_MATCH,
    Element,
    HeldTarget,
    decide,
    held_target,
    redecide_held,
)
from yazses.pilot.service import PilotService


def btn(label: str, eid: str, *, role: str = "push button",
        actions: tuple[str, ...] = ("click",), checked: bool | None = None) -> Element:
    return Element(label=label, role=role, actions=actions, checked=checked, entity_id=eid)


def held_for(phrase: str, elements: list[Element], reason: str) -> HeldTarget:
    d = decide(phrase, elements)
    assert d is not None and (d.verdict, d.reason) == (CONFIRM, reason), d
    target = held_target(d, elements)
    assert target is not None
    return target


def destructive_hold() -> HeldTarget:
    return held_for("click delete", [btn("Delete", "s1n0"), btn("Cancel", "s1n1")],
                    "destructive")


def tied_hold() -> HeldTarget:
    t = held_for("click save", [btn("Save", "s1n0"), btn("Save", "s1n1")], "ambiguous")
    assert (t.occurrence, t.occurrences) == (0, 2), "the first of the tie is offered"
    return t


# ---- the pure re-decision: a destructive held click -------------------------------------


def test_destructive_unchanged_acts_on_the_new_snapshot_id():
    d = redecide_held(destructive_hold(), [btn("Delete", "s2n0"), btn("Cancel", "s2n1")])
    assert (d.verdict, d.reason) == (ACT, "confirmed")
    assert d.element.entity_id == "s2n0", "the hold-time id must never be acted on"
    assert d.action_name == "click"


def test_destructive_vanished_is_refused():
    d = redecide_held(destructive_hold(), [btn("Cancel", "s2n0")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_GONE)
    assert d.element is None and d.action_name is None


@pytest.mark.parametrize("new_label", ["Delete all", "Delete account", "Deleted", "Remove"])
def test_destructive_relabelled_is_refused_never_matched_fuzzily(new_label):
    """A confirmed "Delete" must not land on "Delete all", however well it would score."""
    d = redecide_held(destructive_hold(), [btn(new_label, "s2n0"), btn("Cancel", "s2n1")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_GONE)
    assert d.action_name is None


def test_destructive_with_an_extra_identical_control_is_refused():
    d = redecide_held(destructive_hold(),
                      [btn("Delete", "s2n0"), btn("Delete", "s2n1"), btn("Cancel", "s2n2")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_AMBIGUOUS)
    assert d.action_name is None


def test_destructive_whose_role_changed_is_refused():
    d = redecide_held(destructive_hold(), [btn("Delete", "s2n0", role="menu item")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_GONE)


def test_destructive_that_can_no_longer_be_clicked_is_refused():
    d = redecide_held(destructive_hold(), [btn("Delete", "s2n0", actions=())])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_GONE)


def test_destructive_label_is_compared_up_to_case_and_whitespace_only():
    d = redecide_held(destructive_hold(), [btn("  DELETE ", "s2n0")])
    assert (d.verdict, d.element.entity_id) == (ACT, "s2n0")


@pytest.mark.parametrize("label", ["Send", "Log out", "Don't Save"])
def test_every_destructive_label_is_re_checked_the_same_way(label):
    t = held_for("click " + label.lower(), [btn(label, "s1n0")], "destructive")
    assert redecide_held(t, [btn(label, "s2n0")]).element.entity_id == "s2n0"
    assert redecide_held(t, []).reason == HELD_GONE
    assert redecide_held(t, [btn(label, "a"), btn(label, "b")]).reason == HELD_AMBIGUOUS


# ---- the pure re-decision: a tied plain-button click ------------------------------------


def test_tie_unchanged_acts_on_the_new_id_of_the_offered_control():
    d = redecide_held(tied_hold(), [btn("Save", "s2n0"), btn("Save", "s2n1")])
    assert (d.verdict, d.reason) == (ACT, "confirmed")
    assert d.element.entity_id == "s2n0"


def test_tie_vanished_is_refused():
    d = redecide_held(tied_hold(), [btn("Cancel", "s2n0")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_GONE)


def test_tie_relabelled_is_refused():
    d = redecide_held(tied_hold(), [btn("Save draft", "s2n0"), btn("Save draft", "s2n1")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_GONE)


def test_tie_with_one_of_the_pair_relabelled_is_refused_as_ambiguous():
    d = redecide_held(tied_hold(), [btn("Save draft", "s2n0"), btn("Save", "s2n1")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_AMBIGUOUS)
    assert d.action_name is None


def test_tie_with_an_extra_identical_control_is_refused():
    d = redecide_held(tied_hold(),
                      [btn("Save", "s2n0"), btn("Save", "s2n1"), btn("Save", "s2n2")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_AMBIGUOUS)


def test_tie_identity_is_per_role():
    """A "Save" menu item appearing does not make the pair of "Save" buttons ambiguous."""
    d = redecide_held(tied_hold(), [btn("Save", "m0", role="menu item"),
                                    btn("Save", "s2n0"), btn("Save", "s2n1")])
    assert (d.verdict, d.element.entity_id) == (ACT, "s2n0")


# ---- the pure re-decision: other held clicks ---------------------------------------------


def test_a_partial_match_is_found_again_by_the_held_label_not_the_spoken_words():
    """Held on "Save"; at confirm it reads "Save copy" -- which matches what was *said*
    better. It is a different control from the one the prompt named, so: refused."""
    t = held_for("click save copy", [btn("Save", "s1n0")], "weak")
    assert t.label == "Save"
    d = redecide_held(t, [btn("Save copy", "s2n0")])
    assert (d.verdict, d.reason) == (NO_MATCH, HELD_GONE)
    assert redecide_held(t, [btn("Save", "s2n0")]).element.entity_id == "s2n0"


def test_a_held_plain_click_ignores_the_checked_state():
    """Only "check"/"uncheck" ask for a state; a held "click" on a toggle button whose
    state became unreadable is still the same control and still acts."""
    t = held_for("click dark mode please",
                 [btn("Dark mode", "s1n0", role="toggle button", checked=True)], "weak")
    d = redecide_held(t, [btn("Dark mode", "s2n0", role="toggle button", checked=None)])
    assert (d.verdict, d.element.entity_id) == (ACT, "s2n0")


# ---- the service, over a reader whose snapshot changes during the hold ------------------


def cand(label: str, eid: str, role: str = "push button") -> SemanticCandidate:
    return SemanticCandidate(source=SemanticSourceKind.ACCESSIBILITY, entity_id=eid,
                             role=role, captured_at_s=0.0, confidence=1.0,
                             label=label, actions=("click",))


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


DELETE_SCREEN = (cand("Delete", "s1n0"), cand("Cancel", "s1n1"))
SAVE_SCREEN = (cand("Save", "s1n0"), cand("Save", "s1n1"))


@pytest.mark.parametrize(
    ("phrase", "first", "second", "acted_on"),
    [("click delete", DELETE_SCREEN, (cand("Delete", "s2n0"), cand("Cancel", "s2n1")),
      "'Delete'"),
     ("click save", SAVE_SCREEN, (cand("Save", "s2n0"), cand("Save", "s2n1")), "'Save'")],
    ids=["destructive", "tie"],
)
def test_service_unchanged_acts_once_on_the_new_id(phrase, first, second, acted_on):
    reader = ChangingReader(first, second)
    s = PilotService(reader)
    assert s.command(phrase).verdict == "confirm"
    assert reader.performed == []
    out = s.answer("confirm")
    assert reader.reads == 2, "confirm must re-read the window"
    assert reader.performed == [("s2n0", "click")], "the hold-time id was acted on"
    assert out.verdict == "confirmed" and out.consumed
    assert out.message == f"Done: {acted_on}."
    assert s.answer("confirm").consumed is False, "a second confirm must not act again"
    assert reader.performed == [("s2n0", "click")]


@pytest.mark.parametrize(
    ("phrase", "first", "second", "why"),
    [
        # vanished
        ("click delete", DELETE_SCREEN, (cand("Cancel", "s2n0"),),
         "no longer in the window"),
        ("click save", SAVE_SCREEN, (cand("Cancel", "s2n0"),), "no longer in the window"),
        # label changed
        ("click delete", DELETE_SCREEN, (cand("Delete all", "s2n0"), cand("Cancel", "s2n1")),
         "no longer in the window"),
        ("click save", SAVE_SCREEN, (cand("Save draft", "s2n0"), cand("Save draft", "s2n1")),
         "no longer in the window"),
        # role changed
        ("click delete", DELETE_SCREEN, (cand("Delete", "s2n0", role="menu item"),),
         "no longer in the window"),
        # an extra identical control appeared
        ("click delete", DELETE_SCREEN,
         (cand("Delete", "s2n0"), cand("Delete", "s2n1"), cand("Cancel", "s2n2")),
         "no longer clear which"),
        ("click save", SAVE_SCREEN,
         (cand("Save", "s2n0"), cand("Save", "s2n1"), cand("Save", "s2n2")),
         "no longer clear which"),
    ],
    ids=["destructive-vanished", "tie-vanished", "destructive-relabelled",
         "tie-relabelled", "destructive-role", "destructive-extra", "tie-extra"],
)
def test_service_changed_target_is_refused_and_clicks_nothing(phrase, first, second, why):
    reader = ChangingReader(first, second)
    s = PilotService(reader)
    assert s.command(phrase).verdict == "confirm"
    out = s.answer("confirm")
    assert reader.performed == [], "a confirm clicked a control the prompt never named"
    assert out.verdict == "refused" and out.consumed
    assert why in out.message and "Nothing was changed" in out.message
    assert not s.pending


def test_service_unreadable_window_at_confirm_refuses_a_held_destructive_click():
    reader = ChangingReader(DELETE_SCREEN, None)
    s = PilotService(reader)
    s.command("click delete")
    out = s.answer("confirm")
    assert reader.performed == [] and out.verdict == "refused"
    assert "Could not re-read the window" in out.message


def test_service_a_confirmed_click_that_does_not_respond_is_failed():
    class Deaf(ChangingReader):
        def perform(self, entity_id: str, action: str) -> bool:
            super().perform(entity_id, action)
            return False

    reader = Deaf(DELETE_SCREEN, (cand("Delete", "s2n0"),))
    s = PilotService(reader)
    s.command("click delete")
    out = s.answer("confirm")
    assert out.verdict == "failed" and reader.performed == [("s2n0", "click")]


# ---- end to end through OnScreenReader, over a backend with per-snapshot ids -----------


class SnapshotBackend:
    """Like AT-SPI's adapter: ids are per snapshot, and an id from an older one is refused."""

    def __init__(self, labels: list[str]) -> None:
        self.labels = labels
        self.generation = 0
        self.clicked: list[str] = []

    def snapshot(self, *, window_id=None, region=None):
        self.generation += 1
        return tuple(cand(lab, f"s{self.generation}n{i}") for i, lab in enumerate(self.labels))

    def perform(self, entity_id: str, action: str) -> bool:
        if not entity_id.startswith(f"s{self.generation}n"):
            return False                               # a stale id: refused, not guessed
        self.clicked.append(entity_id)
        return True


def test_end_to_end_unchanged_destructive_click_uses_the_fresh_id():
    backend = SnapshotBackend(["Delete", "Cancel"])
    s = PilotService(OnScreenReader(lambda: backend))
    assert s.command("click delete").verdict == "confirm"
    out = s.answer("confirm")
    assert out.verdict == "confirmed", "the stale hold-time id would have been refused"
    assert backend.clicked == ["s2n0"]


def test_end_to_end_a_second_delete_row_during_the_hold_clicks_nothing():
    backend = SnapshotBackend(["Delete", "Cancel"])
    s = PilotService(OnScreenReader(lambda: backend))
    assert s.command("click delete").verdict == "confirm"
    backend.labels[:] = ["Delete", "Delete", "Cancel"]   # another row appeared
    out = s.answer("confirm")
    assert out.verdict == "refused" and backend.clicked == []


def test_end_to_end_a_tie_whose_window_changed_clicks_nothing():
    backend = SnapshotBackend(["Save", "Save"])
    s = PilotService(OnScreenReader(lambda: backend))
    assert s.command("click save").verdict == "confirm"
    backend.labels[:] = ["Save as", "Save"]
    out = s.answer("confirm")
    assert out.verdict == "refused" and backend.clicked == []
