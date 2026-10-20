"""Every Head-Pointer state, every way in and out of it, on a fake clock (#405, ADR-v2-052).

``#405``'s last acceptance criterion is "all state transitions have fake-clock/unit coverage".
The neighbouring files test each rule on a hand-picked trace -- pause stops a dwell, a
recovered signal settles, a held clutch freezes -- which is the right way to *explain* a rule
but cannot show that a transition nobody thought to write a trace for is safe. This file closes
that gap two ways, and neither depends on a list of cases somebody typed and could forget to
extend:

* **The matrix** is derived from :class:`~yazses.headpointer.controller.State` itself. Each
  state the controller *holds* is a condition (a consent answer, a fault, a lost signal, a
  closed gate, a pause, a clutch); every ordered pair of them is entered, stacked, and unwound,
  and the state word, the absence of any pointer action while anything is held, and the
  settling frame on the way out are asserted at every tick. ``WAITING`` (what ``resume`` and
  start-up leave behind) and ``CLOSED`` (terminal) are covered from every held state too. A
  ``State`` added later without a row here fails :func:`test_every_state_is_in_the_matrix`.

* **The model** is a Hypothesis property: any sequence of samples (fresh, stale, repeated,
  low-confidence, from the future, missing) interleaved with any controls (pause, resume,
  clutch, recenter, dwell on/off, a gate closing, a permission dialog changing its answer, a
  backend that starts failing) is run against a small oracle of the rules, and after every step
  the oracle checks the invariants #405 is about -- nothing moves or clicks while anything
  forbids it, the first free sample after any interruption only settles, no click fires unless
  dwell is on, the pointer travelled past the radius since the last interruption or click, and
  the user was *shown* progress on an earlier step. :func:`test_the_model_is_not_vacuous`
  replays seeded sequences through the same checker and insists it saw clicks, motion and
  every state, so a green run cannot be a checker that never looked.

Nothing here moves a real pointer, opens a camera or reads the host. No number is a product
recommendation: the hold and radius are chosen so the synthetic traces click often, not to suit
a person (``design/eye-control/GOVERNANCE.md``).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from itertools import product
from types import SimpleNamespace

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.pointer_fake import FakePointerSink, PointerActionKind
from yazses.headpointer.controller import (
    HeadPointerController,
    HeadPointerSettings,
    State,
)
from yazses.perception.signals import HeadPoseSignal
from yazses.pointer.base import PointerBackendError, PointerButton
from yazses.pointer.consent import ConsentReport, PointerConsent

FRAME = 1.0 / 30.0
#: Short on purpose, so a 30 fps still head completes a dwell in a few samples and the model
#: meets clicks often. The controller's own floor is 0.05 s.
HOLD_S = 0.1
RADIUS = 15.0
FRESHNESS_S = 0.5
MIN_CONFIDENCE = 0.5

#: The consent answers that block the pointer, and the state word each one rests in.
BLOCKING_CONSENT = {
    PointerConsent.PENDING: State.PENDING_CONSENT,
    PointerConsent.DENIED: State.DENIED,
    PointerConsent.UNAVAILABLE: State.UNAVAILABLE,
}


# --------------------------------------------------------------------------- #
# Doubles
# --------------------------------------------------------------------------- #


class FakeGate:
    """The global hands-free gate as the controller sees it: allowed or not, plus the latch.

    Duck-typed against ``HandsFreeSafety``. It models the one-shot ``clear_pending`` the real
    gate raises on the first decision after a denial, and nothing else: here the gate is a
    condition the test opens and closes. (The real gate's own rules -- staleness, explicit
    re-arming -- are tested against the real object in ``test_headpointer_controller.py``.)
    """

    def __init__(self) -> None:
        self.allowed = True
        self._latch = False
        self.faults: list[str] = []

    def deny(self) -> None:
        if self.allowed:
            self._latch = True
        self.allowed = False

    def allow(self) -> None:
        self.allowed = True

    def sample(self, source: str, *, at_ms: float | None = None) -> None:
        return None

    def gate(self, source: str, *, at_ms: float | None = None) -> SimpleNamespace:
        clear, self._latch = self._latch, False
        return SimpleNamespace(
            allowed=self.allowed, clear_pending=clear,
            reason="" if self.allowed else "gate closed (test)",
        )

    def fault(self, source: str, reason: str) -> None:
        self.faults.append(reason)

    def clear_fault(self, source: str) -> None:
        return None

    def resume(self, sources: object = None) -> SimpleNamespace:
        return SimpleNamespace(ok=self.allowed, reason="" if self.allowed else "gate closed (test)")


class Feedback:
    """Records what the user was shown, and on which step it first became visible."""

    def __init__(self) -> None:
        self.tick = 0
        self.visible = False
        self.since = -1
        self.shows = 0
        #: Out-of-range values shown. Recorded, not asserted here: the controller swallows
        #: anything a feedback sink raises, so an ``assert`` in this method would be silent.
        self.bad: list[float] = []

    def show(self, progress: float) -> None:
        if not 0.0 < progress <= 1.0:
            self.bad.append(progress)
        self.shows += 1
        if not self.visible:
            self.visible, self.since = True, self.tick

    def hide(self) -> None:
        self.visible = False


class Sink(FakePointerSink):
    """A recording sink with a permission step, which snapshots the feedback at every click.

    Like the real portal sink, it *raises* when used without permission: a controller that
    tried to move through an unanswered dialog would fault, and the state check would see it.
    """

    def __init__(self, feedback: Feedback) -> None:
        super().__init__()
        self.consent = PointerConsent.GRANTED
        self._fb = feedback
        #: (step, was progress visible, step it became visible) for every click attempted.
        self.click_views: list[tuple[int, bool, int]] = []

    def pointer_consent(self) -> ConsentReport:
        return ConsentReport(self.consent, f"test consent is {self.consent.value}")

    def move_relative(self, dx: float, dy: float) -> None:
        self._permit()
        super().move_relative(dx, dy)

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        self.click_views.append((self._fb.tick, self._fb.visible, self._fb.since))
        self._permit()
        super().click(button)

    def _permit(self) -> None:
        if self.consent in BLOCKING_CONSENT:
            raise PointerBackendError(f"not allowed: {self.consent.value}")


class Rig:
    """Controller + gate + sink + feedback on a clock the test moves by hand."""

    def __init__(self, *, dwell: bool = True) -> None:
        self.t = 100.0
        self.fb = Feedback()
        self.sink = Sink(self.fb)
        self.gate = FakeGate()
        self.ctl = HeadPointerController(
            self.sink,
            HeadPointerSettings(
                freshness_s=FRESHNESS_S, min_confidence=MIN_CONFIDENCE, dwell_enabled=dwell,
                dwell_radius_px=RADIUS, dwell_hold_s=HOLD_S,
            ),
            safety=self.gate,  # type: ignore[arg-type]  # duck-typed gate
            feedback=self.fb,
        )

    @property
    def state(self) -> State:
        return self.ctl.status().state

    def actions(self) -> int:
        return len(self.sink.actions)

    def presses(self) -> int:
        return sum(1 for a in self.sink.actions if a.kind is PointerActionKind.BUTTON_PRESS)


# --------------------------------------------------------------------------- #
# Part 1 -- the matrix, derived from the State enum
# --------------------------------------------------------------------------- #

#: Each state the controller rests in while something forbids acting, as the condition that
#: puts it there. Order is the controller's precedence, highest first (``update``): permission
#: before signal, a fault's word over a lost signal's, then the gate, the pause, the clutch.
HELD: dict[State, str] = {
    State.PENDING_CONSENT: "consent:pending",
    State.DENIED: "consent:denied",
    State.UNAVAILABLE: "consent:unavailable",
    State.FAULTED: "fault",
    State.LOST: "lost",
    State.SUPPRESSED: "gate",
    State.PAUSED: "paused",
    State.CLUTCHED: "clutch",
}
#: States that are not a held condition, and why each is covered separately.
NOT_HELD = {
    State.TRACKING: "the absence of every condition; every matrix case ends in it",
    State.WAITING: "start-up, and what resume() leaves until the next sample",
    State.CLOSED: "terminal; entered from every other state below",
}
_CONSENT = {
    "consent:pending": PointerConsent.PENDING,
    "consent:denied": PointerConsent.DENIED,
    "consent:unavailable": PointerConsent.UNAVAILABLE,
}


def test_every_state_is_in_the_matrix() -> None:
    """A State added later must be given a condition or an explanation, or this fails."""
    assert set(HELD) | set(NOT_HELD) == set(State)
    assert not set(HELD) & set(NOT_HELD)


def expected(held: set[str]) -> State:
    for state, cond in HELD.items():  # precedence order
        if cond in held:
            return state
    return State.TRACKING


class Matrix:
    """Drives one matrix case and asserts the safety rules at every tick."""

    def __init__(self) -> None:
        self.rig = Rig(dwell=True)
        self.held: set[str] = set()
        self.lost = False
        r = self.rig
        r.t += FRAME
        assert r.ctl.update(HeadPoseSignal(r.t, 0.0, 0.0, 0.0, 1.0), r.t).state is State.TRACKING
        self.lean(2)
        assert r.actions() > 0, "the rig must move before the case starts"

    def lean(self, n: int = 1, yaw: float = 0.3, pitch: float = 0.2) -> list[State]:
        """``n`` ticks with the head turned well past the dead zone (or no sample, if lost)."""
        r = self.rig
        states = []
        for _ in range(n):
            r.t += FRAME
            r.fb.tick += 1
            sample = None if self.lost else HeadPoseSignal(r.t, yaw, pitch, 0.0, 1.0)
            states.append(r.ctl.update(sample, r.t).state)
        return states

    def apply(self, cond: str) -> None:
        r = self.rig
        if cond in _CONSENT:
            r.sink.consent = _CONSENT[cond]
            self.held -= set(_CONSENT)  # one dialog, one answer
        elif cond == "fault":
            r.ctl.fail("test fault")
            assert r.state is State.FAULTED
        elif cond == "lost":
            self.lost = True
        elif cond == "gate":
            r.gate.deny()
        elif cond == "paused":
            r.ctl.pause()
            assert r.state is State.PAUSED
        elif cond == "clutch":
            r.ctl.set_clutch("switch", True)
        else:  # pragma: no cover - a typo in this file
            raise AssertionError(cond)
        self.held.add(cond)

    def clear(self, cond: str) -> None:
        r = self.rig
        if cond not in self.held:
            return
        if cond in _CONSENT:
            r.sink.consent = PointerConsent.GRANTED
        elif cond == "lost":
            self.lost = False
        elif cond == "gate":
            r.gate.allow()
        elif cond == "clutch":
            r.ctl.set_clutch("switch", False)
        elif cond in ("fault", "paused"):
            # One command clears both, and leaves WAITING until the next sample arrives.
            r.ctl.resume()
            assert r.state is State.WAITING
            self.held -= {"fault", "paused"}
        self.held.discard(cond)

    def hold_still_and_check(self) -> None:
        """While anything is held: the predicted word on every tick, and no action at all."""
        before = self.rig.actions()
        for state in self.lean(3):
            assert state is expected(self.held), (state, sorted(self.held))
        assert self.rig.actions() == before, ("acted while held", sorted(self.held))

    def recover_and_check(self, *, then_yaw: float = 0.3) -> None:
        """Everything released: one settling frame with no action, then the pointer follows.

        ``then_yaw`` is the pose of the sample after the settling one; it must differ from
        the neutral pose for "the pointer follows" to be observable.
        """
        assert not self.held
        before = self.rig.actions()
        assert self.lean(1) == [State.TRACKING]
        assert self.rig.actions() == before, "the first free sample moved the pointer"
        assert self.lean(1, yaw=then_yaw) == [State.TRACKING]
        assert self.rig.actions() > before, "the pointer did not come back"


@pytest.mark.parametrize(
    ("first", "second"), list(product(HELD, HELD)), ids=lambda s: s.value
)
def test_every_pair_of_held_states_stacks_unwinds_and_never_acts(first: State, second: State):
    m = Matrix()
    clicks = m.rig.presses()
    m.apply(HELD[first])
    m.hold_still_and_check()
    m.apply(HELD[second])  # stacked: the higher-precedence word shows, nothing acts
    m.hold_still_and_check()
    m.clear(HELD[first])  # unwound: whatever is still held shows, nothing acts
    if m.held:
        m.hold_still_and_check()
    m.clear(HELD[second])
    m.recover_and_check()
    assert m.rig.presses() == clicks, "a transition clicked"


@pytest.mark.parametrize("target", list(HELD), ids=lambda s: s.value)
def test_from_start_up_waiting_into_each_held_state_and_out(target: State):
    """Start-up is WAITING; a condition held before the first sample wins, and nothing acts."""
    rig = Rig(dwell=True)
    assert rig.state is State.WAITING
    m = Matrix.__new__(Matrix)
    m.rig, m.held, m.lost = rig, set(), False
    m.apply(HELD[target])
    m.hold_still_and_check()
    m.clear(HELD[target])
    # The first free sample is the capture of the neutral pose (the leaned one), which is also
    # a no-action frame; turning back to straight ahead is then a deviation, so it moves.
    m.recover_and_check(then_yaw=0.0)
    assert rig.presses() == 0


@pytest.mark.parametrize(
    "source", [*HELD, State.TRACKING, State.WAITING], ids=lambda s: s.value
)
def test_close_is_terminal_from_every_state(source: State):
    m = Matrix()
    if source in HELD:
        m.apply(HELD[source])
        m.lean(1)
    elif source is State.WAITING:
        m.rig.ctl.resume()
    assert m.rig.state is source
    m.rig.ctl.close()
    assert m.rig.state is State.CLOSED
    m.rig.sink.consent = PointerConsent.GRANTED
    m.lost = False
    m.rig.gate.allow()
    assert m.rig.ctl.resume().ok is False
    m.rig.ctl.recenter()
    m.rig.ctl.set_clutch("switch", False)
    m.rig.ctl.set_dwell_enabled(True)
    before = [a for a in m.rig.sink.actions if a.kind is not PointerActionKind.CLOSE]
    assert m.lean(5) == [State.CLOSED] * 5
    after = [a for a in m.rig.sink.actions if a.kind is not PointerActionKind.CLOSE]
    assert after == before


@pytest.mark.parametrize("source", [*HELD, State.TRACKING], ids=lambda s: s.value)
def test_recenter_from_every_state_captures_on_the_first_free_sample_and_never_acts(source):
    m = Matrix()
    if source in HELD:
        m.apply(HELD[source])
        m.lean(1)
    m.rig.ctl.recenter()
    assert m.rig.ctl.status().calibrated is False
    if source in HELD:
        m.hold_still_and_check()
        m.clear(HELD[source])
    before = m.rig.actions()
    m.lean(1)  # the capture frame: the leaned pose becomes neutral
    assert m.rig.actions() == before and m.rig.ctl.status().calibrated
    m.lean(3)  # the same leaned pose is now straight ahead: still no motion
    assert m.rig.actions() == before


@pytest.mark.parametrize("source", [*HELD, State.TRACKING], ids=lambda s: s.value)
def test_toggling_dwell_in_every_state_changes_no_state_and_moves_nothing(source):
    """Dwell is its own switch: flipping it must not move, click, or change the state word."""
    m = Matrix()
    if source in HELD:
        m.apply(HELD[source])
        m.lean(1)
    word = m.rig.state
    before = m.rig.actions()
    for enabled in (False, True, False):
        m.rig.ctl.set_dwell_enabled(enabled)
        assert m.rig.state is word
        assert m.rig.ctl.status().dwell_enabled is enabled
    assert m.rig.actions() == before


# --------------------------------------------------------------------------- #
# Part 2 -- the model: any event sequence, checked against an oracle at every step
# --------------------------------------------------------------------------- #


@dataclass
class Oracle:
    """What the rules say the controller may do, tracked from the outside."""

    paused: bool = False
    clutches: set[str] = field(default_factory=set)
    fault: bool = False
    dwell: bool = True
    sink_failing: bool = False
    #: The next free sample must only settle (start-up, any quiesce).
    settle: bool = True
    #: The next free sample is a neutral-pose capture (start-up, recenter).
    capture: bool = True
    last_ts: float = -math.inf
    pos: tuple[int, int] = (0, 0)
    origin: tuple[int, int] = (0, 0)
    armed: bool = False

    def quiesce(self, *, settle: bool = True) -> None:
        self.origin, self.armed = self.pos, False
        if settle:
            self.settle = True


@dataclass
class Stats:
    moves: int = 0
    clicks: int = 0
    #: Clicks on a camera slower than the hold: each had to wait at the brink for one more
    #: frame, because the gap that completed it was also the first that could show it.
    slow_clicks: int = 0
    states: set[State] = field(default_factory=set)


def _check_update(rig: Rig, o: Oracle, sample: HeadPoseSignal | None) -> State:
    """One ``update`` against the oracle. Returns the state word it produced.

    Every update is its own numbered step (``Feedback.tick``), so "shown on an earlier step"
    means an earlier *sample*, never merely an earlier event of a multi-frame hold.
    """
    word_before = rig.ctl.status().state
    n = rig.actions()
    rig.fb.tick += 1
    step_no = rig.fb.tick
    step = rig.ctl.update(sample, rig.t)
    new_actions = rig.sink.actions[n:]
    now = rig.t
    valid = (
        sample is not None
        and sample.confidence >= MIN_CONFIDENCE
        and 0.0 <= now - sample.timestamp_s <= FRESHNESS_S
    )
    consent = rig.sink.consent

    def rests(state: State) -> State:
        assert step.state is state, (step, state, o)
        assert new_actions == [], ("acted while it must not", step, new_actions)
        o.quiesce()
        return state

    if consent in BLOCKING_CONSENT:
        return rests(BLOCKING_CONSENT[consent])
    if not valid:
        return rests(State.FAULTED if o.fault else State.LOST)
    assert sample is not None
    if sample.timestamp_s <= o.last_ts:
        # The same observation again (or an older one): nothing new, nothing done.
        assert step.state is word_before and new_actions == []
        return step.state
    o.last_ts = sample.timestamp_s
    if o.fault:
        return rests(State.FAULTED)
    if not rig.gate.allowed:
        return rests(State.SUPPRESSED)
    if o.paused:
        return rests(State.PAUSED)
    if o.clutches:
        return rests(State.CLUTCHED)
    if o.settle or o.capture:
        # The first free sample after any interruption -- or the neutral capture -- only settles.
        assert step.state is State.TRACKING and new_actions == [], (step, new_actions, o)
        o.settle = o.capture = False
        o.quiesce(settle=False)
        return State.TRACKING
    if step.state is State.FAULTED:
        assert o.sink_failing and new_actions == [], (step, new_actions)
        o.fault = True
        o.quiesce()
        return State.FAULTED
    assert step.state is State.TRACKING, (step, o)
    moves = [a for a in new_actions if a.kind is PointerActionKind.MOVE_RELATIVE]
    presses = [a for a in new_actions if a.kind is PointerActionKind.BUTTON_PRESS]
    assert len(moves) <= 1 and len(presses) <= 1, new_actions
    calib = rig.ctl._calib  # noqa: SLF001 - the caps actually applied
    max_dt = rig.ctl._max_dt  # noqa: SLF001
    for mv in moves:
        # Velocity is capped and dt is clamped, so one sample is one bounded step (+1 remainder).
        assert abs(mv.x) <= calib.max_speed_x * max_dt + 1.0, mv
        assert abs(mv.y) <= calib.max_speed_y * max_dt + 1.0, mv
        assert math.hypot(mv.x, mv.y) <= calib.max_speed_overall * max_dt + 2.0, mv
        o.pos = (o.pos[0] + int(mv.x), o.pos[1] + int(mv.y))
        if (o.pos[0] - o.origin[0]) ** 2 + (o.pos[1] - o.origin[1]) ** 2 > RADIUS**2:
            o.armed = True
    if presses:
        assert o.dwell, "clicked with dwell off"
        assert o.armed, "clicked without travelling past the radius since the last reset"
        tick, visible, since = rig.sink.click_views[-1]
        assert tick == step_no and visible and since < step_no, (
            "clicked without the user having been shown progress on an earlier step",
            rig.sink.click_views[-1],
        )
        o.origin, o.armed = o.pos, False
    status = rig.ctl.status()
    assert 0.0 <= status.dwell_progress <= 1.0
    if not o.dwell:
        assert status.dwell_progress == 0.0
    return State.TRACKING


def run_model(events: list[tuple], stats: Stats | None = None) -> Stats:
    """Drive one event sequence through a fresh controller and check every step."""
    stats = stats or Stats()
    rig = Rig(dwell=True)
    o = Oracle()
    last: HeadPoseSignal | None = None
    stats.states.add(rig.state)
    for ev in events:
        kind = ev[0]
        if kind == "feed":
            _, yaw, pitch, dt, age, conf = ev
            rig.t += dt
            last = HeadPoseSignal(rig.t - age, yaw, pitch, 0.0, conf)
            stats.states.add(_check_update(rig, o, last))
        elif kind == "hold":
            # A head that holds one pose for a while: fresh frames ``dt`` apart. This is what
            # lets a dwell build, so it is what makes the click rules testable at all. A ``dt``
            # longer than the hold is a camera slower than the dwell: the dwell then completes
            # in a single gap, which is the case the "shown before it fires" rule exists for.
            _, yaw, pitch, frames, dt = ev
            for _ in range(frames):
                rig.t += dt
                last = HeadPoseSignal(rig.t, yaw, pitch, 0.0, 1.0)
                pressed = rig.presses()
                stats.states.add(_check_update(rig, o, last))
                if dt >= HOLD_S and rig.presses() > pressed:
                    stats.slow_clicks += 1
        elif kind == "reread":
            rig.t += ev[1]
            stats.states.add(_check_update(rig, o, last))
        elif kind == "idle":
            rig.t += ev[1]
            stats.states.add(_check_update(rig, o, None))
        elif kind == "pause":
            rig.ctl.pause()
            o.paused = True
            o.quiesce()
            assert rig.state is State.PAUSED
        elif kind == "resume":
            rig.ctl.resume()
            o.paused = o.fault = False
            o.quiesce()
            assert rig.state is State.WAITING
        elif kind == "clutch":
            _, source, active = ev
            rig.ctl.set_clutch(source, active)
            if active:
                o.clutches.add(source)
                o.quiesce()
            elif source in o.clutches:
                o.clutches.discard(source)
                o.quiesce()
        elif kind == "recenter":
            rig.ctl.recenter()
            o.capture = True
            o.quiesce()
        elif kind == "dwell":
            rig.ctl.set_dwell_enabled(ev[1])
            o.dwell = ev[1]
            o.quiesce(settle=False)
        elif kind == "gate":
            if ev[1]:
                rig.gate.allow()
            else:
                if rig.gate.allowed:
                    o.quiesce()  # the latch quiesces on the very next update
                rig.gate.deny()
        elif kind == "consent":
            rig.sink.consent = ev[1]
        elif kind == "sinkfail":
            if ev[1]:
                rig.sink.fail_with(PointerBackendError("backend went away (test)"))
            else:
                rig.sink.clear_failure()
            o.sink_failing = ev[1]
        elif kind == "fail":
            rig.ctl.fail("runner broke (test)")
            o.fault = True
            o.quiesce()
            assert rig.state is State.FAULTED
        else:  # pragma: no cover - a typo in the strategy
            raise AssertionError(ev)
        stats.states.add(rig.state)
    assert rig.fb.bad == [], ("progress outside (0, 1] was shown", rig.fb.bad)
    stats.moves += sum(1 for a in rig.sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE)
    stats.clicks += rig.presses()
    rig.ctl.close()
    assert rig.state is State.CLOSED
    stats.states.add(State.CLOSED)
    return stats


_YAW = [0.0, 0.0, 0.0, 0.01, 0.05, -0.05, 0.3, -0.3]
_PITCH = [0.0, 0.0, 0.03, -0.2]
_DT = [FRAME, FRAME, FRAME, 1.0 / 60.0, 0.0, 0.1, 0.3, 0.7]
_AGE = [0.0, 0.0, 0.0, 0.02, 0.6, -0.01]
_CONF = [1.0, 1.0, 1.0, 0.9, 0.3]
_CONSENTS = [
    PointerConsent.GRANTED, PointerConsent.NOT_REQUIRED, PointerConsent.UNKNOWN,
    *BLOCKING_CONSENT,
]

_feed = st.tuples(
    st.just("feed"), st.sampled_from(_YAW), st.sampled_from(_PITCH), st.sampled_from(_DT),
    st.sampled_from(_AGE), st.sampled_from(_CONF),
)
_control = st.one_of(
    st.tuples(st.just("reread"), st.sampled_from([0.001, FRAME])),
    st.tuples(st.just("idle"), st.sampled_from([FRAME, 0.3, 0.8])),
    st.tuples(st.just("pause")),
    st.tuples(st.just("resume")),
    st.tuples(st.just("clutch"), st.sampled_from(["switch", "face"]), st.booleans()),
    st.tuples(st.just("recenter")),
    st.tuples(st.just("dwell"), st.booleans()),
    st.tuples(st.just("gate"), st.booleans()),
    st.tuples(st.just("consent"), st.sampled_from(_CONSENTS)),
    st.tuples(st.just("sinkfail"), st.booleans()),
    st.tuples(st.just("fail")),
)
#: Gaps between the frames of a held pose. ``SLOW_FRAME`` is longer than ``HOLD_S``.
SLOW_FRAME = 0.12
_HOLD_DT = [FRAME, FRAME, SLOW_FRAME]
_hold = st.tuples(
    st.just("hold"), st.sampled_from(_YAW), st.sampled_from(_PITCH), st.integers(1, 12),
    st.sampled_from(_HOLD_DT),
)
# Samples outnumber controls, so dwells get the chance to build and fire.
_event = st.one_of(_feed, _feed, _hold, _hold, _control)


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(_event, min_size=1, max_size=150))
def test_any_sequence_of_samples_and_controls_obeys_the_rules(events):
    run_model(events)


def _seeded_events(seed: int, n: int = 300) -> list[tuple]:
    """A seeded stream from the same vocabulary, for replay.

    Weighted towards recovery (resume, an open gate, a granted dialog, a released clutch) so a
    stream spends enough time free for dwells to build, fire and be interrupted; every
    condition is still entered many times across the seeds.
    """
    rnd = random.Random(seed)
    controls: list = [
        lambda: ("reread", rnd.choice([0.001, FRAME])),
        lambda: ("idle", rnd.choice([FRAME, 0.3, 0.8])),
        lambda: ("pause",),
        lambda: ("resume",),
        lambda: ("resume",),
        lambda: ("resume",),
        lambda: ("clutch", rnd.choice(["switch", "face"]), True),
        lambda: ("clutch", "switch", False),
        lambda: ("clutch", "face", False),
        lambda: ("recenter",),
        lambda: ("dwell", rnd.random() < 0.8),
        lambda: ("gate", False),
        lambda: ("gate", True),
        lambda: ("gate", True),
        lambda: ("consent", rnd.choice(_CONSENTS)),
        lambda: ("consent", PointerConsent.GRANTED),
        lambda: ("sinkfail", rnd.random() < 0.3),
        lambda: ("sinkfail", False),
        lambda: ("fail",),
    ]
    out: list[tuple] = []
    for _ in range(n):
        roll = rnd.random()
        if roll < 0.45:
            out.append((
                "hold", rnd.choice(_YAW), rnd.choice(_PITCH), rnd.randint(1, 12),
                rnd.choice(_HOLD_DT),
            ))
        elif roll < 0.8:
            out.append((
                "feed", rnd.choice(_YAW), rnd.choice(_PITCH), rnd.choice(_DT),
                rnd.choice(_AGE), rnd.choice(_CONF),
            ))
        else:
            out.append(rnd.choice(controls)())
    return out


def test_the_model_is_not_vacuous():
    """The checker must actually meet clicks, motion and every state, or it proves nothing."""
    stats = Stats()
    for seed in range(40):
        run_model(_seeded_events(seed), stats)
    # Floors well under what these 40 seeds produced when written (164 clicks, 5370 moves):
    # they are there to catch a checker or a stream that stopped reaching the case, not to
    # pin a count.
    assert stats.clicks >= 100, stats.clicks
    assert stats.slow_clicks >= 5, stats.slow_clicks
    assert stats.moves >= 2000, stats.moves
    assert stats.states == set(State), set(State) - stats.states
