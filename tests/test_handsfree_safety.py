"""The hands-free stop state and stale-signal watchdog, on fabricated timelines (ADR-v2-148).

Every test here drives a fake clock, so "the camera went quiet for 600 ms" is an assignment
rather than a `sleep`. No camera, no thread, no hardware — which is the point of putting the
decision in a pure module: the failure being prevented (a runaway pointer for someone who cannot
reach a keyboard) is the one nobody wants to reproduce by hand.

The cases are the risk register's, not invented ones: R-05 the user cannot stop continuous camera
control, R-06 a stale last pose keeps moving the cursor, R-24 recovery itself fires an action.
"""
from __future__ import annotations

import threading

from yazses.config import Config
from yazses.handsfree.safety import (
    DEFAULT_STALE_AFTER_MS,
    HandsFreeSafety,
    SafetyLimits,
    SafetyState,
    gate_from_config,
)
from yazses.headpointer.pointer import DwellClicker

POINTER = "headpointer"
SWITCH = "facegesture"


class Clock:
    """A monotonic millisecond clock the test moves by hand."""

    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms


def armed(clock: Clock, sources: tuple[str, ...] = (POINTER,), **kw) -> HandsFreeSafety:
    """A gate with every source sampled and explicitly armed — the steady state."""
    gate = HandsFreeSafety(sources, clock=clock, **kw)
    for name in sources:
        gate.sample(name)
    result = gate.resume()
    assert result.ok, result
    return gate


# --------------------------------------------------------------- starting safe


def test_a_fresh_gate_suppresses_everything():
    gate = HandsFreeSafety((POINTER, SWITCH), clock=Clock())
    assert gate.state is SafetyState.PAUSED
    assert gate.gate(POINTER).allowed is False
    assert gate.gate(SWITCH).allowed is False


def test_arming_is_refused_for_a_source_that_has_no_signal_yet():
    """A camera still warming up cannot be armed, and the refusal names it."""
    gate = HandsFreeSafety((POINTER, SWITCH), clock=Clock())
    gate.sample(POINTER)

    result = gate.resume()

    assert result.armed == (POINTER,)
    assert result.refused == (SWITCH,)
    assert result.ok is False
    assert gate.gate(POINTER).allowed is True
    assert gate.gate(SWITCH).allowed is False


def test_an_armed_source_with_a_fresh_signal_may_act():
    gate = armed(Clock())
    decision = gate.gate(POINTER)
    assert decision.allowed is True
    assert decision.state is SafetyState.ACTIVE
    assert gate.status().suppressed is False


def test_a_source_the_gate_has_never_heard_of_is_denied():
    """Deny by default: a typo in a source name must not open a hole."""
    gate = armed(Clock())
    assert gate.gate("mystery").allowed is False


# --------------------------------------------------------------- the stop path


def test_pause_suppresses_pointer_and_switch_alike():
    """R-05: one stop, and nothing continuous acts — whichever path called it."""
    clock = Clock()
    gate = armed(clock, (POINTER, SWITCH))

    gate.pause("voice command: stop")

    assert gate.state is SafetyState.PAUSED
    assert gate.gate(POINTER).allowed is False
    assert gate.gate(SWITCH).allowed is False
    assert "stop" in gate.status().reason


def test_entering_pause_asks_each_consumer_to_clear_pending_state_once():
    clock = Clock()
    gate = armed(clock, (POINTER, SWITCH))
    gate.gate(POINTER)  # consume the initial arm latch
    gate.gate(SWITCH)

    gate.pause()

    assert gate.gate(POINTER).clear_pending is True
    assert gate.gate(POINTER).clear_pending is False
    assert gate.gate(SWITCH).clear_pending is True


def test_pause_is_idempotent():
    """A second stop must not re-ask for a clear: a guard that repeats gets ignored."""
    clock = Clock()
    gate = armed(clock, (POINTER,))
    gate.gate(POINTER)
    gate.pause()
    gate.gate(POINTER)  # consumes the clear-pending latch

    gate.pause("again")
    gate.pause("and again")

    assert gate.gate(POINTER).clear_pending is False
    assert gate.state is SafetyState.PAUSED


def test_pause_is_safe_from_any_thread():
    """The stop path arrives on a tray callback, a hotkey thread or the command dispatcher."""
    clock = Clock()
    gate = armed(clock, (POINTER, SWITCH))
    errors: list[BaseException] = []

    def hammer() -> None:
        try:
            for _ in range(200):
                gate.pause("stop")
                gate.gate(POINTER)
                gate.status()
        except BaseException as exc:  # pragma: no cover - a raise here is the failure
            errors.append(exc)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert gate.state is SafetyState.PAUSED
    assert gate.gate(POINTER).allowed is False


# --------------------------------------------------------------- the watchdog


def test_a_stale_signal_stops_the_source_instead_of_reusing_the_last_value():
    """R-06: the last pose is not a pose. It is the absence of one."""
    clock = Clock()
    gate = armed(clock)
    assert gate.gate(POINTER).allowed is True

    clock.advance(DEFAULT_STALE_AFTER_MS + 1)

    decision = gate.gate(POINTER)
    assert decision.allowed is False
    assert decision.state is SafetyState.FAULTED
    assert "stale" in decision.reason


def test_the_freshness_window_is_an_age_not_a_guess():
    """Exactly at the window is still fresh; one millisecond past it is not."""
    clock = Clock()
    gate = armed(clock, limits=SafetyLimits(stale_after_ms=200.0))

    clock.advance(200.0)
    assert gate.gate(POINTER).allowed is True

    clock.advance(0.5)
    assert gate.gate(POINTER).allowed is False


def test_a_returning_signal_does_not_silently_resume_the_pointer():
    """R-24: a camera that flickers back must not put a cursor back in motion by itself."""
    clock = Clock()
    gate = armed(clock)
    clock.advance(DEFAULT_STALE_AFTER_MS + 1)
    gate.gate(POINTER)

    gate.sample(POINTER)  # tracking is back

    decision = gate.gate(POINTER)
    assert decision.allowed is False
    assert decision.state is SafetyState.PAUSED
    assert "re-arm" in decision.reason


def test_recovery_needs_an_explicit_rearm_and_then_starts_clean():
    clock = Clock()
    gate = armed(clock)
    clock.advance(DEFAULT_STALE_AFTER_MS + 1)
    gate.gate(POINTER)
    gate.sample(POINTER)

    assert gate.resume().ok is True

    decision = gate.gate(POINTER)
    assert decision.allowed is True
    assert decision.clear_pending is True, "recovery must not resume a half-finished activation"


def test_rearming_a_source_whose_signal_is_still_missing_is_refused():
    clock = Clock()
    gate = armed(clock)
    clock.advance(DEFAULT_STALE_AFTER_MS + 1)

    result = gate.resume()

    assert result.refused == (POINTER,)
    assert gate.gate(POINTER).allowed is False


def test_a_stale_switch_does_not_stop_the_pointer():
    """ADR-v2-148's recovery hierarchy: losing one modality must not disable the others."""
    clock = Clock()
    gate = armed(clock, (POINTER, SWITCH))

    for _ in range(4):
        clock.advance(DEFAULT_STALE_AFTER_MS / 2)
        gate.sample(POINTER)  # the pointer keeps delivering; the switch does not

    assert gate.gate(POINTER).allowed is True
    assert gate.gate(SWITCH).allowed is False
    assert gate.state is SafetyState.FAULTED  # the summary still tells the user something is off


# --------------------------------------------------------------- reported faults


def test_a_reported_fault_suppresses_until_it_is_cleared_and_rearmed():
    clock = Clock()
    gate = armed(clock, (POINTER, SWITCH))

    gate.fault(POINTER, "pointer backend denied")

    assert gate.gate(POINTER).allowed is False
    assert gate.state is SafetyState.FAULTED
    assert "denied" in gate.status().reason
    assert gate.gate(SWITCH).allowed is True  # contained

    gate.clear_fault(POINTER)
    assert gate.gate(POINTER).allowed is False, "clearing a fault is not a re-arm"

    gate.sample(POINTER)
    assert gate.resume((POINTER,)).ok is True
    assert gate.gate(POINTER).allowed is True


def test_shutdown_suppresses_first_and_cannot_be_rearmed():
    clock = Clock()
    gate = armed(clock, (POINTER, SWITCH))

    gate.shutdown()

    status = gate.status()
    assert status.state is SafetyState.PAUSED
    assert status.terminal is True
    assert gate.gate(POINTER).allowed is False
    assert gate.gate(SWITCH).allowed is False

    gate.sample(POINTER)
    result = gate.resume()
    assert result.ok is False
    assert result.armed == ()
    assert gate.gate(POINTER).allowed is False


# --------------------------------------------------------------- observability


def test_status_reports_per_source_health_and_nothing_a_camera_saw():
    """#416 consumes this. It must be printable without leaking anything biometric."""
    clock = Clock()
    gate = armed(clock, (POINTER, SWITCH))
    clock.advance(120.0)

    status = gate.status()
    pointer = status.source(POINTER)

    assert pointer is not None
    assert pointer.armed is True
    assert pointer.stale is False
    assert pointer.age_ms == 120.0
    assert status.source("mystery") is None
    assert [s.name for s in status.sources] == [SWITCH, POINTER]
    fields = set(vars(pointer))
    assert fields == {"name", "armed", "stale", "faulted", "reason", "age_ms", "epoch"}


def test_polling_runs_the_watchdog_even_when_no_consumer_asks():
    """A consumer whose own loop has stalled is exactly when nobody would notice."""
    clock = Clock()
    gate = armed(clock)

    clock.advance(DEFAULT_STALE_AFTER_MS + 1)
    status = gate.poll()

    assert status.state is SafetyState.FAULTED
    assert status.source(POINTER).stale is True  # type: ignore[union-attr]


# --------------------------------------------------------------- config seam


def test_the_section_ships_off_and_an_existing_install_is_unchanged():
    cfg = Config()
    assert cfg.handsfree_safety.enabled is False
    assert cfg.handsfree_safety.stale_after_ms == int(DEFAULT_STALE_AFTER_MS)
    assert gate_from_config(cfg, (POINTER,)) is None


def test_opting_in_builds_a_gate_on_the_configured_window():
    cfg = Config()
    cfg.handsfree_safety.enabled = True
    cfg.handsfree_safety.stale_after_ms = 120
    clock = Clock()

    gate = gate_from_config(cfg, (POINTER,), clock=clock)

    assert gate is not None
    gate.sample(POINTER)
    assert gate.resume().ok is True
    clock.advance(121.0)
    assert gate.gate(POINTER).allowed is False


def test_a_window_that_cannot_mean_anything_falls_back_to_the_shipped_default():
    """Zero would make every sample stale forever — a guard that always fires catches nothing."""
    assert SafetyLimits(stale_after_ms=0.0).window_ms() == DEFAULT_STALE_AFTER_MS
    assert SafetyLimits(stale_after_ms=-5.0).window_ms() == DEFAULT_STALE_AFTER_MS
    assert SafetyLimits(stale_after_ms=42.0).window_ms() == 42.0


# --------------------------------------------------------------- the consumer contract


def test_a_dwell_in_progress_does_not_complete_across_a_pause():
    """The acceptance criterion, made concrete against the real dwell clicker.

    Without the clear-pending latch, a dwell two frames from firing when the user hit stop would
    complete on the first frame after recovery — a click nobody asked for, in whatever the cursor
    happened to be sitting on.
    """
    clock = Clock()
    gate = armed(clock)
    dwell = DwellClicker(radius=5.0, hold_frames=3)
    clicks = 0

    def frame(x: float, y: float) -> None:
        nonlocal clicks
        decision = gate.gate(POINTER)
        if decision.clear_pending:
            dwell.reset()
        if decision.allowed and dwell.update(x, y):
            clicks += 1

    frame(10.0, 10.0)
    frame(10.0, 10.0)  # two of the three frames a click needs
    gate.pause("stop")
    frame(10.0, 10.0)  # suppressed, and the pending dwell is dropped
    gate.sample(POINTER)
    assert gate.resume().ok is True

    frame(10.0, 10.0)
    frame(10.0, 10.0)
    assert clicks == 0, "the dwell resumed where it left off"

    frame(10.0, 10.0)
    assert clicks == 1
