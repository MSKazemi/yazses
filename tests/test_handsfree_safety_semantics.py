"""What the hands-free stop state does at the edges a tidy fake never reaches (#417, EYE-SAFETY-001).

``test_handsfree_safety.py`` proves the state machine on a clock that only moves when the test
moves it and a camera that calls the gate on every tick. A real machine does neither. This file
holds the orderings, timings and device states that a fake hides, each as a test that fails when
the guard it names is removed:

* **kill versus pause.** Nothing but an explicit re-arm clears a pause, and nothing at all
  clears a shutdown -- not a returning signal, not a cleared fault, not the passage of time. The
  set of code that *can* re-arm is itself pinned, so an automatic re-arm cannot be added
  without a test being edited on purpose.
* **stale versus absent.** A source nobody has heard from yet is "no signal yet" (PAUSED); one
  that was delivering and went quiet is FAULTED. And the lapse is judged when the next sample
  arrives, not only when somebody happens to ask: the face switch asks the gate only on a press,
  and a laptop that was asleep asks nothing.
* **clock jumps.** A suspend or a stepped clock gives one enormous (or negative, or not-a-number)
  age. That must disarm once, never fire, and never re-arm by itself.
* **who arms what.** The characterisation of the OPEN OWNER DECISION: with ``[handsfree_safety]``
  on, nothing but ``yazses handsfree resume`` arms the face-switch and chord sources, and a
  face-only user cannot do that for themselves. These tests pin what happens *now*; they are not
  a recommendation to keep it.

Everything is a fabricated clock and a fake sink. No camera, no pointer, no socket, no thread
that outlives its test.
"""
from __future__ import annotations

import ast
import inspect
import math
import random
import re
import threading
import types
from pathlib import Path

import pytest

import yazses
from tests.pointer_fake import FakePointerSink
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.facegesture.detector import GESTURES
from yazses.facegesture.switches import ACTIONS as SWITCH_ACTIONS
from yazses.facegesture.switches import PRESS, RELEASE, SwitchAction, SwitchIntent, SwitchMapper
from yazses.gesture.engine import ACTIONS as CHORD_ACTIONS
from yazses.handsfree.safety import (
    DEFAULT_STALE_AFTER_MS,
    HandsFreeSafety,
    SafetyLimits,
    SafetyState,
)
from yazses.headpointer.controller import (
    SOURCE_NAME as POINTER,
)
from yazses.headpointer.controller import (
    HeadPointerController,
    HeadPointerSettings,
)
from yazses.ipc.protocol import Request
from yazses.perception.signals import HeadPoseSignal

SRC = Path(yazses.__file__).resolve().parent
SWITCH = "facegesture"
CHORD = "gesture"
WINDOW = DEFAULT_STALE_AFTER_MS
GESTURE = next(iter(GESTURES))


class Clock:
    def __init__(self, now: float = 10_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms


def armed(clock: Clock, names: tuple[str, ...] = (POINTER, SWITCH), **kw) -> HandsFreeSafety:
    gate = HandsFreeSafety(names, clock=clock, **kw)
    for name in names:
        gate.sample(name)
    assert gate.resume().ok
    return gate


# ============================================================ kill versus pause


def _random_walk(seed: int, steps: int = 400) -> None:
    """Drive a two-source gate with arbitrary events and check the latch invariants as it goes.

    The model is deliberately dumber than the gate: it only knows "a pause was requested and no
    re-arm has armed anything since", and "a fault was reported and was not cleared *and*
    re-armed". If the gate ever says ``allowed`` while the model says it must not, a path other
    than an explicit re-arm cleared a stop.
    """
    rng = random.Random(seed)
    clock = Clock()
    names = (POINTER, SWITCH)
    gate = HandsFreeSafety(names, clock=clock)
    paused = False
    shut = False
    fault_latched = {name: False for name in names}
    fault_cleared = {name: False for name in names}
    for step in range(steps):
        op = rng.choice(
            ["sample", "sample", "advance", "advance_far", "gate", "poll", "pause", "resume",
             "fault", "clear_fault", "resume_one", "shutdown_rare"]
        )
        name = rng.choice(names)
        if op == "sample":
            gate.sample(name)
        elif op == "advance":
            clock.advance(rng.choice([1.0, 50.0, 200.0, WINDOW, WINDOW + 1.0]))
        elif op == "advance_far":
            clock.advance(rng.choice([10_000.0, 3_600_000.0, 8 * 3_600_000.0]))
        elif op == "gate":
            gate.gate(name)
        elif op == "poll":
            gate.poll()
        elif op == "pause":
            gate.pause("test")
            paused = True
        elif op == "fault":
            gate.fault(name, "backend closed")
            fault_latched[name] = True
            fault_cleared[name] = False
        elif op == "clear_fault":
            gate.clear_fault(name)
            fault_cleared[name] = True
        elif op in ("resume", "resume_one"):
            result = gate.resume(None if op == "resume" else [name])
            if shut:
                assert result.ok is False and result.armed == ()
            for armed_name in result.armed:
                assert not fault_latched[armed_name] or fault_cleared[armed_name], (
                    f"seed {seed} step {step}: {armed_name} re-armed while its fault stood"
                )
                fault_latched[armed_name] = False
            if result.armed:
                paused = False
        elif op == "shutdown_rare" and rng.random() < 0.02:
            gate.shutdown()
            shut = True
        # The invariants, after every event.
        for each in names:
            decision = gate.gate(each)
            if shut or paused or fault_latched[each]:
                assert decision.allowed is False, (
                    f"seed {seed} step {step} after {op}: {each} allowed while "
                    f"shut={shut} paused={paused} fault={fault_latched[each]}"
                )


@pytest.mark.parametrize("seed", range(25))
def test_nothing_but_an_explicit_rearm_clears_a_pause_a_fault_or_a_shutdown(seed):
    _random_walk(seed)


def test_a_pause_survives_everything_a_healthy_camera_can_do():
    clock = Clock()
    gate = armed(clock)
    gate.pause("voice stop")
    for _ in range(50):
        clock.advance(100.0)
        gate.sample(POINTER)
        gate.sample(SWITCH)
        gate.clear_fault(POINTER)
        assert gate.gate(POINTER).allowed is False
        assert gate.gate(SWITCH).allowed is False
        assert gate.status().state is SafetyState.PAUSED


def test_re_arming_one_source_after_a_pause_does_not_wake_the_others():
    """``resume(["headpointer"])`` lifts the global pause flag, so each source's *own* disarm is
    the only thing still holding the others back. ``yazses headpointer resume`` must not start
    the face switch."""
    clock = Clock()
    gate = armed(clock)
    gate.pause("stop")
    assert gate.resume([POINTER]).ok is True
    assert gate.gate(POINTER).allowed is True
    assert gate.gate(SWITCH).allowed is False
    assert "awaiting re-arm" in gate.gate(SWITCH).reason


def test_a_shutdown_cannot_be_undone_by_any_call_the_gate_offers():
    clock = Clock()
    gate = armed(clock)
    gate.shutdown()
    gate.clear_fault(POINTER)
    gate.sample(POINTER)
    assert gate.resume().ok is False
    assert gate.resume([POINTER]).ok is False
    gate.pause("again")  # pausing a shut-down gate is harmless
    assert gate.gate(POINTER).allowed is False
    assert gate.status().terminal is True


def _calls_on_a_gate(method: str) -> set[tuple[str, str]]:
    """``(file, enclosing function)`` for every ``<something safety/gate>.<method>(...)`` in src."""
    found: set[tuple[str, str]] = set()
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel == "handsfree/safety.py":
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)

        def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
            for child in ast.iter_child_nodes(node):
                inner = scope
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    inner = (*scope, child.name)
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == method
                ):
                    receiver = ast.get_source_segment(text, child.func.value) or ""
                    if re.search(r"safety|gate", receiver):
                        found.add((rel, ".".join(scope)))
                visit(child, inner)

        visit(tree, ())
    return found


def test_only_the_human_initiated_entry_points_can_rearm_or_clear_a_fault():
    """The inventory behind "nothing but a human-initiated action can clear a kill".

    Each entry is a command a person gives: ``yazses handsfree resume`` / the controls window /
    the tray (``Daemon._handle_handsfree``), ``yazses headpointer resume`` (the controller's own
    ``resume``), and ``yazses gesture resume``. A new caller -- a watchdog thread, a reconnect
    hook, a timer -- would be an automatic re-arm, which ADR-v2-148 forbids (R-24). If you are
    adding one on purpose, this test is the place the decision is recorded.
    """
    assert _calls_on_a_gate("resume") == {
        ("core/daemon.py", "Daemon._handle_handsfree"),
        ("gesture/runtime.py", "GestureRuntime.command"),
        ("headpointer/controller.py", "HeadPointerController.resume"),
    }
    assert _calls_on_a_gate("clear_fault") == {
        ("headpointer/controller.py", "HeadPointerController.resume"),
    }
    assert _calls_on_a_gate("shutdown") == {("core/daemon.py", "Daemon._shutdown")}


def test_no_face_or_chord_action_can_resume_so_a_stop_is_never_undone_by_the_camera():
    """The vocabularies a camera can speak contain a way to stop and no way to start."""
    assert "pause_pointer" in SWITCH_ACTIONS
    assert not [a for a in SWITCH_ACTIONS if "resume" in a or "start" in a or "arm" in a]
    assert not [a for a in CHORD_ACTIONS if "resume" in a or "arm" in a]


# ============================================================ stale versus absent


def test_absent_is_paused_and_stale_is_faulted_and_the_words_differ():
    clock = Clock()
    gate = HandsFreeSafety((POINTER,), clock=clock)
    absent = gate.status()
    assert absent.state is SafetyState.PAUSED and "no signal yet" in absent.reason

    gate.sample(POINTER)
    assert gate.resume().ok
    clock.advance(WINDOW + 1.0)
    stale = gate.status()
    assert stale.state is SafetyState.FAULTED and "stale" in stale.reason
    assert stale.reason != absent.reason


def test_a_gap_is_judged_when_the_next_sample_arrives_even_if_nobody_asked_during_it():
    """The face switch asks the gate only on a press; a suspended laptop asks nothing.

    Before the fix the returning camera refreshed the sample *first*, so the gate never saw the
    silence and the source went on acting as if it had been delivering throughout.
    """
    clock = Clock()
    gate = armed(clock)
    clock.advance(30_000.0)  # thirty seconds of nothing; no gate() or poll() call in between
    gate.sample(SWITCH)  # the camera is back

    decision = gate.gate(SWITCH)

    assert decision.allowed is False
    assert "awaiting re-arm" in decision.reason
    assert decision.clear_pending is True


def test_a_gap_exactly_at_the_window_does_not_disarm_but_one_ms_over_does():
    clock = Clock()
    gate = armed(clock)
    gate.gate(POINTER)
    clock.advance(WINDOW)
    gate.sample(POINTER)
    assert gate.gate(POINTER).allowed is True
    clock.advance(WINDOW + 1.0)
    gate.sample(POINTER)
    assert gate.gate(POINTER).allowed is False


def test_a_source_that_never_armed_is_not_disarmed_by_a_late_first_sample():
    """The watchdog acts on armed sources only: a camera warming up is not a fault."""
    clock = Clock()
    gate = HandsFreeSafety((POINTER,), clock=clock)
    gate.sample(POINTER)
    clock.advance(5_000.0)
    gate.sample(POINTER)
    assert gate.status().source(POINTER).epoch == 0  # type: ignore[union-attr]


# ============================================================ clock jumps


def test_a_suspend_sized_gap_disarms_once_never_fires_and_never_rearms_by_itself():
    clock = Clock()
    gate = armed(clock)
    gate.gate(POINTER)
    gate.gate(SWITCH)  # consume the arm latches
    epoch_before = gate.status().epoch

    clock.advance(8 * 3_600_000.0)  # eight hours asleep

    cleared = {POINTER: 0, SWITCH: 0}
    for _ in range(500):
        for name in (POINTER, SWITCH):
            decision = gate.gate(name)
            assert decision.allowed is False
            cleared[name] += decision.clear_pending
    assert cleared == {POINTER: 1, SWITCH: 1}, "one suppression is one clear request, not 500"
    assert gate.status().epoch == epoch_before + 2

    gate.sample(POINTER)
    gate.sample(SWITCH)  # the camera comes back
    for _ in range(100):
        assert gate.gate(POINTER).allowed is False
        assert gate.gate(SWITCH).allowed is False
    assert gate.status().state is SafetyState.PAUSED  # not FAULTED any more, still not ACTIVE

    assert gate.resume().ok is True
    assert gate.gate(POINTER).allowed is True


def test_rearming_straight_after_a_jump_is_refused_until_a_fresh_sample_exists():
    clock = Clock()
    gate = armed(clock)
    clock.advance(3_600_000.0)
    result = gate.resume()
    assert result.armed == () and set(result.refused) == {POINTER, SWITCH}
    assert gate.gate(POINTER).allowed is False


@pytest.mark.parametrize(
    "back_ms",
    [pytest.param(3_600_000.0, id="one-hour"), pytest.param(WINDOW * 4, id="four-windows")],
)
def test_a_clock_that_steps_backwards_cannot_make_a_dead_camera_look_alive(back_ms):
    """A negative age used to compare as "not older than the window", so a camera that died
    just before the step looked fresh until the clock climbed back past it."""
    clock = Clock()
    gate = armed(clock)
    clock.advance(-back_ms)

    decision = gate.gate(POINTER)

    assert decision.allowed is False
    assert gate.status().state is SafetyState.FAULTED
    assert "clock" in gate.status().reason
    assert gate.status().source(POINTER).age_ms is not None  # type: ignore[union-attr]


def test_a_small_backwards_step_is_scheduling_noise_and_stays_fresh():
    """A frame stamped a few ms after the thread read the clock must not trip the guard."""
    clock = Clock()
    gate = armed(clock)
    gate.sample(POINTER, at_ms=clock.now + WINDOW / 2.0)
    assert gate.gate(POINTER).allowed is True


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(math.nan, id="nan"),
        pytest.param(math.inf, id="inf"),
        pytest.param(-math.inf, id="minus-inf"),
    ],
)
def test_a_timestamp_that_is_not_a_number_is_never_evidence_of_life(bad):
    clock = Clock()
    gate = armed(clock)
    gate.sample(POINTER, at_ms=bad)  # ignored: the previous sample stands and ages out
    clock.advance(WINDOW + 1.0)
    assert gate.gate(POINTER).allowed is False
    assert gate.status().source(POINTER).age_ms is not None  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "bad",
    [pytest.param(math.nan, id="nan"), pytest.param(math.inf, id="inf")],
)
def test_a_clock_that_reads_not_a_number_denies_and_reports_a_finite_status(bad):
    clock = Clock()
    gate = armed(clock)
    decision = gate.gate(POINTER, at_ms=bad)
    status = gate.status(at_ms=bad)
    assert decision.allowed is False
    assert status.state is not SafetyState.ACTIVE
    for health in status.sources:
        assert health.age_ms is None or math.isfinite(health.age_ms)


@pytest.mark.parametrize(
    "window",
    [pytest.param(math.nan, id="nan"), pytest.param(math.inf, id="inf"),
     pytest.param(-1.0, id="negative"), pytest.param(0.0, id="zero")],
)
def test_a_window_that_cannot_express_freshness_falls_back_to_the_default(window):
    assert SafetyLimits(stale_after_ms=window).window_ms() == DEFAULT_STALE_AFTER_MS


def test_a_head_pointer_driven_across_a_jump_moves_nothing_and_clicks_nothing():
    """The real controller on the real gate, with the clock the runner would hand it."""
    clock = Clock(now=100_000.0)
    gate = HandsFreeSafety((POINTER,), clock=clock)
    sink = FakePointerSink()
    ctl = HeadPointerController(sink, HeadPointerSettings(dwell_enabled=True), safety=gate)

    def feed(yaw: float, pitch: float = 0.0) -> None:
        clock.advance(33.0)
        ctl.update(HeadPoseSignal(clock.now / 1000.0, yaw, pitch, 0.0, 1.0), clock.now / 1000.0)

    feed(0.0)
    assert gate.resume().ok
    feed(0.0)  # the capture frame
    feed(0.0)  # the settling frame
    for _ in range(10):
        feed(0.3)
    before = len(sink.actions)
    assert before > 0, "the rig never moved the pointer, so the assertion below proves nothing"
    clock.advance(8 * 3_600_000.0)  # the laptop slept
    for _ in range(30):
        feed(0.3)  # and wakes to a camera that is already delivering again
    assert len(sink.actions) == before, "the pointer acted on a signal that had been dead for hours"
    assert gate.status().state is not SafetyState.ACTIVE


# ============================================================ two sources, racing


def test_one_source_going_quiet_does_not_stop_the_other_or_change_its_epoch():
    clock = Clock()
    gate = armed(clock)
    gate.gate(POINTER)
    pointer_epoch = gate.status().source(POINTER).epoch  # type: ignore[union-attr]
    for _ in range(6):
        clock.advance(WINDOW / 2.0)
        gate.sample(POINTER)
    assert gate.gate(POINTER).allowed is True
    assert gate.gate(SWITCH).allowed is False
    assert gate.status().source(POINTER).epoch == pointer_epoch  # type: ignore[union-attr]


def test_a_partial_rearm_arms_what_it_can_names_what_it_cannot_and_clears_the_user_pause():
    """Characterised, not endorsed: ``resume`` with one source refused returns ``ok=False`` yet
    has armed the others and lifted the global pause. Every surface that prints the refusal
    must therefore also say what *was* armed (the daemon's reply carries ``scope``)."""
    clock = Clock()
    gate = armed(clock)
    gate.pause("stop")
    clock.advance(WINDOW + 1.0)
    gate.sample(POINTER)  # only the pointer's camera is delivering

    result = gate.resume()

    assert result.ok is False
    assert result.armed == (POINTER,) and result.refused == (SWITCH,)
    assert gate.gate(POINTER).allowed is True
    assert gate.gate(SWITCH).allowed is False
    assert gate.status().user_paused is False


def test_pausing_while_a_source_goes_stale_asks_for_one_clear_not_two():
    clock = Clock()
    gate = armed(clock)
    gate.gate(POINTER)
    gate.gate(SWITCH)
    clock.advance(WINDOW + 1.0)
    gate.pause("stop")  # races the watchdog: both want to suppress the same source
    first = gate.gate(POINTER)
    assert first.clear_pending is True
    assert gate.gate(POINTER).clear_pending is False


def test_a_pause_and_a_rearm_racing_on_two_threads_never_tear_the_state():
    """Every snapshot the gate hands out is internally consistent while two threads fight."""
    clock = Clock()
    gate = armed(clock)
    stop = threading.Event()
    bad: list[str] = []

    def stopper() -> None:
        while not stop.is_set():
            gate.pause("stop")

    def starter() -> None:
        while not stop.is_set():
            gate.sample(POINTER)
            gate.sample(SWITCH)
            gate.resume()

    def observer() -> None:
        for _ in range(3000):
            status = gate.status()
            if status.state is SafetyState.ACTIVE and (
                status.user_paused or not all(s.armed for s in status.sources)
            ):
                bad.append(f"ACTIVE with {status}")
            decision = gate.gate(POINTER)
            if decision.allowed and gate.status().terminal:
                bad.append("allowed after shutdown")

    threads = [threading.Thread(target=stopper), threading.Thread(target=starter)]
    for thread in threads:
        thread.start()
    try:
        observer()
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=10)
    assert bad == []
    gate.pause("final")
    assert gate.gate(POINTER).allowed is False


# ============================================================ who arms what (OPEN OWNER DECISION)


def _daemon_stub(gate, runtime=None):
    return types.SimpleNamespace(
        _handsfree_safety=gate, _headpointer=runtime, _config=Config(),
        _gaze_targeter=None, _extra_activations=[],
    )


def _resume(stub):
    return Daemon._handle_handsfree(stub, Request("handsfree", {"action": "resume"}))


def _built_gate(clock: Clock, *, headpointer: bool = True, chords: bool = True):
    cfg = Config()
    cfg.handsfree_safety.enabled = True
    cfg.headpointer.enabled = headpointer
    cfg.gesture.enabled = chords
    cfg.gesture.chords = {"brow_raise+nod": "recenter"} if chords else {}
    gate = Daemon._build_handsfree_safety(types.SimpleNamespace(), cfg)
    assert gate is not None
    # The daemon builds it on the real clock; the test needs the same object on a fake one.
    return HandsFreeSafety(
        [s.name for s in gate.status().sources], limits=SafetyLimits(), clock=clock
    )


def _switch(gate, log: list[str]) -> SwitchMapper:
    bindings = {GESTURE: "hold_to_talk"}
    handlers = {"hold_to_talk": SwitchAction(press=lambda: log.append("press"),
                                             release=lambda: log.append("release"))}
    return SwitchMapper(bindings, handlers, gate=gate)


def test_with_the_gate_on_the_daemon_registers_only_the_pointer_and_the_chords():
    """Current behaviour: the face switch is NOT a registered source at build time."""
    clock = Clock()
    gate = _built_gate(clock)
    names = [s.name for s in gate.status().sources]
    assert names == sorted([POINTER, CHORD])
    assert SWITCH not in names
    status = gate.status()
    assert status.state is SafetyState.PAUSED and "no signal yet" in status.reason
    assert not any(s.armed for s in status.sources)


def test_nothing_arms_a_source_except_an_explicit_resume_however_healthy_the_camera_is():
    clock = Clock()
    gate = _built_gate(clock)
    log: list[str] = []
    mapper = _switch(gate, log)
    for _ in range(100):  # ten seconds of a perfectly healthy face
        clock.advance(100.0)
        mapper.frame(True)
        gate.sample(POINTER)
        gate.sample(CHORD)
        mapper.handle(SwitchIntent(GESTURE, PRESS, 0.0))
        mapper.handle(SwitchIntent(GESTURE, RELEASE, 0.0))
    # A release with no press is still delivered, by design (closing a closed mic is harmless
    # and dropping the one release that matters is the failure); a *press* is the action.
    assert "press" not in log, "the dictation key was opened with no arm"
    assert gate.status().state is SafetyState.PAUSED
    assert not any(s.armed for s in gate.status().sources)


def test_a_resume_after_the_first_face_frame_arms_the_face_switch_and_the_next_press_works():
    clock = Clock()
    gate = _built_gate(clock)
    log: list[str] = []
    mapper = _switch(gate, log)
    gate.sample(POINTER)
    gate.sample(CHORD)
    mapper.frame(True)  # the face switch registers itself with its first frame

    reply = _resume(_daemon_stub(gate))

    assert reply["ok"] is True
    assert set(reply["scope"]) == {POINTER, CHORD, SWITCH}  # type: ignore[arg-type]
    assert mapper.handle(SwitchIntent(GESTURE, PRESS, 0.0)) is True
    assert log == ["press"]


def test_a_resume_before_the_face_switch_has_seen_a_face_leaves_it_unarmed_and_unreported():
    """The ordering hazard: ``resume`` arms what is *registered*. Run it while the camera is
    still warming up and the face switch is not there to arm; it registers a moment later,
    disarmed, and the user must run ``resume`` a second time. The first reply said
    ``ok: True`` and never mentioned the face switch."""
    clock = Clock()
    gate = _built_gate(clock)
    log: list[str] = []
    mapper = _switch(gate, log)
    gate.sample(POINTER)
    gate.sample(CHORD)

    reply = _resume(_daemon_stub(gate))
    assert reply["ok"] is True and SWITCH not in reply["scope"]  # type: ignore[operator]

    mapper.frame(True)  # now it registers
    assert gate.status().source(SWITCH).armed is False  # type: ignore[union-attr]
    assert mapper.handle(SwitchIntent(GESTURE, PRESS, 0.0)) is False
    assert log == []

    assert _resume(_daemon_stub(gate))["ok"] is True  # the second resume does it
    assert mapper.handle(SwitchIntent(GESTURE, PRESS, 0.0)) is True


def test_a_face_that_leaves_the_frame_for_longer_than_the_window_strands_a_face_only_user():
    """Characterised, not endorsed. Everything below is something a face-only user can do; none
    of it gets the face switch back."""
    clock = Clock()
    gate = _built_gate(clock, headpointer=False, chords=False)  # a face-only configuration
    assert [s.name for s in gate.status().sources] == []
    log: list[str] = []
    mapper = _switch(gate, log)
    mapper.frame(True)
    assert _resume(_daemon_stub(gate))["ok"] is True
    assert mapper.handle(SwitchIntent(GESTURE, PRESS, 0.0)) is True
    mapper.handle(SwitchIntent(GESTURE, RELEASE, 0.0))

    for _ in range(8):  # the head turns away for 0.8 s: no face, no samples
        clock.advance(100.0)
        mapper.frame(False)
    assert gate.status().state is SafetyState.FAULTED

    for _ in range(600):  # the face is back, and stays perfectly in view for a minute
        clock.advance(100.0)
        mapper.frame(True)
        mapper.handle(SwitchIntent(GESTURE, PRESS, 0.0))
        mapper.handle(SwitchIntent(GESTURE, RELEASE, 0.0))
    status = gate.status()
    assert status.state is SafetyState.PAUSED
    assert "awaiting re-arm" in status.reason
    assert log.count("press") == 1, "the switch acted again with no re-arm"

    # The only camera-borne input left is the stop, which is already in force.
    pauser = SwitchMapper(
        {GESTURE: "pause_pointer"}, {"pause_pointer": SwitchAction(press=lambda: gate.pause("face"))},
        gate=gate,
    )
    assert pauser.handle(SwitchIntent(GESTURE, PRESS, 0.0)) is True
    assert gate.status().user_paused is True  # a stop works; nothing a face can say undoes it


# ============================================================ speech stays usable


def test_speech_only_dictation_does_not_consult_the_hands_free_gate():
    """The gate belongs to camera-driven input. The dictation entry points never mention it."""
    text = (SRC / "core" / "daemon.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    daemon_cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Daemon")
    mentioning = {
        fn.name
        for fn in daemon_cls.body
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            (isinstance(n, ast.Attribute) and n.attr == "_handsfree_safety")
            or (isinstance(n, ast.Constant) and n.value == "_handsfree_safety")
            for n in ast.walk(fn)
        )
    }
    assert mentioning == {
        "_build_pipeline", "_build_face_gesture_source", "_build_headpointer", "_build_gesture",
        "_handsfree_payload", "_handle_handsfree", "_shutdown",
    }
    for dictation in ("_on_hold_start", "_on_hold_end", "_on_command_hold_start",
                      "_on_command_hold_end"):
        assert dictation not in mentioning


def test_a_paused_gate_still_lets_the_stop_words_and_the_status_through():
    """Pausing suppresses actions, not the ability to ask what happened or to stop again."""
    clock = Clock()
    gate = armed(clock)
    stub = _daemon_stub(gate)
    assert Daemon._handle_handsfree(stub, Request("handsfree", {"action": "pause"}))["ok"] is True
    assert Daemon._handle_handsfree(stub, Request("handsfree", {"action": "pause"}))["ok"] is True
    assert gate.status().state is SafetyState.PAUSED


# ============================================================ shutdown order, behaviourally


def _shutdown_rig(gate, order: list[tuple[str, bool]]):
    """A Daemon with every optional attribute ``_shutdown`` reads set to None, then the three
    that matter replaced by recorders that note whether the gate was already closed."""
    daemon = Daemon.__new__(Daemon)
    for name in set(re.findall(r"self\.(_\w+)", inspect.getsource(Daemon._shutdown))):
        if not hasattr(daemon, name):
            setattr(daemon, name, None)
    daemon._platform = types.SimpleNamespace(lifecycle=types.SimpleNamespace(clear_pid=lambda: None))
    daemon._handsfree_safety = gate

    def recorder(label: str):
        def note() -> None:
            closed = (not gate.gate(POINTER).allowed) and gate.status().terminal
            order.append((label, closed))

        return types.SimpleNamespace(stop=note, close=note)

    daemon._gesture = recorder("gesture")
    daemon._headpointer = recorder("headpointer")
    daemon._perception = recorder("camera")
    return daemon


def test_shutdown_closes_the_gate_before_any_backend_is_stopped_or_the_camera_released():
    clock = Clock()
    gate = armed(clock)
    order: list[tuple[str, bool]] = []
    daemon = _shutdown_rig(gate, order)

    Daemon._shutdown(daemon)

    assert [label for label, _ in order] == ["gesture", "headpointer", "camera"]
    assert all(closed for _, closed in order), f"a backend stopped while actions were allowed: {order}"


def test_shutdown_still_closes_the_backends_when_one_of_them_raises():
    clock = Clock()
    gate = armed(clock)
    order: list[tuple[str, bool]] = []
    daemon = _shutdown_rig(gate, order)

    def boom() -> None:
        raise RuntimeError("backend would not stop")

    daemon._gesture = types.SimpleNamespace(stop=boom)
    Daemon._shutdown(daemon)

    assert [label for label, _ in order] == ["headpointer", "camera"]
    assert gate.status().terminal is True


def test_nothing_reaches_a_pointer_sink_between_the_gate_closing_and_the_sink_closing():
    clock = Clock(now=1_000.0)
    gate = HandsFreeSafety((POINTER,), clock=clock)
    sink = FakePointerSink()
    ctl = HeadPointerController(sink, HeadPointerSettings(dwell_enabled=True), safety=gate)

    def feed(yaw: float) -> None:
        clock.advance(33.0)
        ctl.update(HeadPoseSignal(clock.now / 1000.0, yaw, 0.0, 0.0, 1.0), clock.now / 1000.0)

    feed(0.0)
    assert gate.resume().ok
    feed(0.0)  # the capture frame
    feed(0.0)  # the settling frame
    for _ in range(5):
        feed(0.4)
    moved = len(sink.actions)
    assert moved > 0, "the rig never moved the pointer, so the assertion below proves nothing"

    gate.shutdown("daemon shutting down")
    for _ in range(40):  # the runner thread is still ticking while the daemon tears down
        feed(0.4)
    assert len(sink.actions) == moved
    ctl.close()
