"""The pure decisions behind a face switch's ``select`` / ``confirm`` / ``cancel``.

No pointer, no daemon, no notification: a recording click, a fake confirmation holder and a clock
the test moves by hand. What is protected is that a gesture which is *bound* is never silent
(done / refused-with-a-reason / nothing-to-do), that a select cannot click when the pointer is
stopped, and that one held or flickering gesture cannot click repeatedly.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from yazses.facegesture.actions import (
    DONE,
    NOOP,
    REFUSED,
    SELECT_MIN_INTERVAL_S,
    ActionOutcome,
    SelectLimiter,
    SwitchOutcomeLog,
    line_from_row,
    perform_select,
    resolve_confirmation,
    select_refusal,
)


@dataclass
class View:
    state: str = "tracking"
    paused: bool = False
    clutched: bool = False
    faulted: bool = False
    closed: bool = False
    gate_allowed: bool | None = None


@dataclass
class Result:
    ok: bool
    reason: str = ""


class Clock:
    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class RecordingPointer:
    """Stands in for the Head-Pointer's atomic commit_click: judge, then click once."""

    def __init__(self, view: View | None = None) -> None:
        self.view = view or View()
        self.clicks = 0

    def __call__(self, policy):
        reason = policy(self.view)
        if reason:
            return Result(False, reason)
        self.clicks += 1
        return Result(True)


# ------------------------------------------------------------------ select_refusal


def test_a_healthy_tracking_pointer_may_click():
    assert select_refusal(View()) == ""


@pytest.mark.parametrize(
    ("view", "words"),
    [
        (View(closed=True), "shut down"),
        (View(faulted=True), "faulted"),
        (View(paused=True), "paused"),
        (View(clutched=True), "clutched"),
        (View(gate_allowed=False), "safety gate"),
        (View(state="waiting"), "signal"),
        (View(state="lost"), "signal"),
        (View(state="suppressed"), "signal"),
    ],
)
def test_each_stopped_state_refuses_with_its_own_reason(view, words):
    assert words in select_refusal(view)


def test_no_gate_at_all_is_not_a_closed_gate():
    # None means "nothing to consult" -- the same rule the face switch itself follows.
    assert select_refusal(View(gate_allowed=None)) == ""


def test_own_clutch_state_word_does_not_refuse_a_select():
    # The controller's last state word may be 'clutched' because of the face switch's own
    # freeze; `clutched` (which already excludes it) is what decides, not the word.
    assert select_refusal(View(state="clutched", clutched=False)) == ""


# ------------------------------------------------------------------ the limiter


def test_the_default_interval_is_the_provisional_constant():
    assert SelectLimiter().min_interval_s == SELECT_MIN_INTERVAL_S


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
def test_a_nonsense_interval_falls_back_instead_of_meaning_no_limit(bad):
    assert SelectLimiter(bad).min_interval_s == SELECT_MIN_INTERVAL_S


def test_a_second_click_inside_the_interval_is_refused_and_one_after_it_is_not():
    clock = Clock()
    limiter = SelectLimiter(1.0, clock)
    assert limiter.refusal() == ""
    limiter.mark()
    clock.t += 0.4
    assert "less than 1 s" in limiter.refusal()
    clock.t += 0.7
    assert limiter.refusal() == ""


def test_asking_does_not_consume_the_slot():
    limiter = SelectLimiter(1.0, Clock())
    for _ in range(5):
        assert limiter.refusal() == ""


# ------------------------------------------------------------------ perform_select


def test_select_clicks_once_and_says_done():
    pointer, clock = RecordingPointer(), Clock()
    outcome = perform_select(pointer, SelectLimiter(1.0, clock), clock=clock)
    assert (outcome.action, outcome.result) == ("select", DONE)
    assert pointer.clicks == 1


def test_select_while_paused_clicks_nothing_and_says_why():
    pointer = RecordingPointer(View(paused=True))
    outcome = perform_select(pointer, SelectLimiter(1.0, Clock()))
    assert outcome.result == REFUSED
    assert "paused" in outcome.reason
    assert pointer.clicks == 0


def test_a_held_gesture_that_presses_again_inside_the_interval_cannot_click_twice():
    pointer, clock = RecordingPointer(), Clock()
    limiter = SelectLimiter(1.0, clock)
    first = perform_select(pointer, limiter, clock=clock)
    clock.t += 0.2  # flicker across the threshold: release, press again
    second = perform_select(pointer, limiter, clock=clock)
    assert first.result == DONE
    assert second.result == REFUSED
    assert "less than" in second.reason
    assert pointer.clicks == 1


def test_a_refused_select_does_not_start_the_rate_limit_clock():
    pointer, clock = RecordingPointer(View(paused=True)), Clock()
    limiter = SelectLimiter(1.0, clock)
    perform_select(pointer, limiter, clock=clock)
    pointer.view = View()
    clock.t += 0.1
    assert perform_select(pointer, limiter, clock=clock).result == DONE


def test_a_commit_click_that_raises_is_a_refusal_not_an_exception():
    def boom(_policy):
        raise RuntimeError("sink gone")

    outcome = perform_select(boom, SelectLimiter())
    assert outcome.result == REFUSED
    assert "RuntimeError" in outcome.reason


# ------------------------------------------------------------------ confirm / cancel


class Holder:
    """A fake pending-confirmation slot with ConfirmGate's surface."""

    def __init__(self, pending: object | None = None) -> None:
        self._pending = pending
        self.confirms = 0
        self.cancels = 0

    @property
    def pending(self):
        return self._pending

    def confirm(self):
        self.confirms += 1
        held, self._pending = self._pending, None
        return held

    def cancel(self):
        self.cancels += 1
        self._pending = None


@pytest.mark.parametrize("action", ["confirm", "cancel"])
def test_nothing_pending_is_a_harmless_noop_that_touches_nothing(action):
    holder, released, dropped = Holder(), [], []
    outcome = resolve_confirmation(
        action, holder, released.append, on_cancel=lambda: dropped.append(1)
    )
    assert outcome.result == NOOP
    assert "nothing is waiting" in outcome.reason
    assert (holder.confirms, holder.cancels, released, dropped) == (0, 0, [], [])


def test_confirm_releases_the_held_item_exactly_once():
    holder, released = Holder("rm -rf build"), []
    outcome = resolve_confirmation("confirm", holder, released.append)
    assert outcome.result == DONE
    assert released == ["rm -rf build"]
    # a second answer (say a spoken "confirm" racing the gesture) finds nothing and releases nothing
    again = resolve_confirmation("confirm", holder, released.append)
    assert again.result == NOOP
    assert released == ["rm -rf build"]


def test_cancel_drops_the_held_item_and_releases_nothing():
    holder, released, dropped = Holder("rm -rf build"), [], []
    outcome = resolve_confirmation(
        "cancel", holder, released.append, on_cancel=lambda: dropped.append(1)
    )
    assert outcome.result == DONE
    assert released == []
    assert dropped == [1]
    assert holder.pending is None


def test_the_outcome_never_carries_the_held_text():
    secret = "rm -rf /home/someone/precious"
    outcome = resolve_confirmation("confirm", Holder(secret), lambda _h: None)
    assert secret not in outcome.line
    assert secret not in outcome.reason


def test_a_release_that_raises_is_reported_and_does_not_propagate():
    def boom(_held):
        raise OSError("no injector")

    outcome = resolve_confirmation("confirm", Holder("x"), boom)
    assert outcome.result == REFUSED
    assert "OSError" in outcome.reason


def test_a_holder_that_raises_is_reported_and_does_not_propagate():
    class Broken(Holder):
        @property
        def pending(self):
            raise RuntimeError("x")

    assert resolve_confirmation("cancel", Broken(), lambda _h: None).result == REFUSED


def test_only_confirm_and_cancel_are_answers():
    assert resolve_confirmation("select", Holder("x"), lambda _h: None).result == REFUSED


# ------------------------------------------------------------------ the log


def test_a_bound_action_that_never_fired_says_so_and_an_unbound_one_is_absent():
    log = SwitchOutcomeLog(Clock())
    rows = log.snapshot({"select", "hold_to_talk"})
    assert [r["action"] for r in rows] == ["select"]
    assert rows[0]["result"] == "unused"
    assert log.lines({"select"}) == ("select: bound, not used yet",)


def test_the_log_keeps_the_newest_outcome_and_counts_each_kind():
    clock = Clock()
    log = SwitchOutcomeLog(clock)
    log.record(ActionOutcome("select", REFUSED, "the Head-Pointer is paused", clock()))
    log.record(ActionOutcome("select", DONE, "", clock()))
    clock.t += 5.0
    log.record(ActionOutcome("confirm", NOOP, "nothing is waiting for confirmation", clock()))
    clock.t += 2.0
    select, confirm = log.snapshot({"select", "confirm", "cancel"})[:2]
    assert (select["result"], select["done"], select["refused"], select["age_s"]) == (
        DONE, 1, 1, 7.0,
    )
    assert (confirm["result"], confirm["noop"], confirm["age_s"]) == (NOOP, 1, 2.0)
    assert log.lines({"select"}) == ("select: last done",)


def test_a_refusal_line_carries_its_reason():
    clock = Clock()
    log = SwitchOutcomeLog(clock)
    log.record(ActionOutcome("select", REFUSED, "the Head-Pointer is paused", clock()))
    assert log.lines({"select"}) == ("select: last refused (the Head-Pointer is paused)",)


def test_line_from_row_survives_a_malformed_row():
    assert line_from_row({}) == "?: bound, not used yet"
    assert "x" in line_from_row({"action": "x", "result": None, "reason": None})
