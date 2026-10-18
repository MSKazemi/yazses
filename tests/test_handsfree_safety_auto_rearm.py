"""A hold-only face switch re-arms itself when the face comes back -- and nothing else does.

Live, 2026-10-18: with the global stop on, the face switch went stale every time its user looked
at the keyboard or phone for more than 0.5 s (eight times in three minutes) and stayed disarmed
until Resume, so eyes-closed dictation stopped working within minutes. The amendment to
ADR-v2-148 lets a source that opted in (`allow_auto_rearm`) recover from a *staleness* disarm
after an unbroken run of fresh samples. These pin both halves: the recovery, and every case
that must still wait for an explicit Resume. Times are synthetic; nothing here is a measurement.
"""
from __future__ import annotations

from yazses.facegesture.switches import REARM_AFTER_MS, rearms_on_face_return
from yazses.handsfree.safety import HandsFreeSafety, SafetyState

SRC = "facegesture"
FRAME = 1000.0 / 15


class Clock:
    def __init__(self) -> None:
        self.now = 10_000.0

    def __call__(self) -> float:
        return self.now


def _armed(opt_in: bool = True) -> tuple[HandsFreeSafety, Clock]:
    clock = Clock()
    gate = HandsFreeSafety((SRC,), clock=clock)
    if opt_in:
        gate.allow_auto_rearm(SRC, REARM_AFTER_MS)
    gate.sample(SRC)
    assert gate.resume().ok
    return gate, clock


def _frames(gate: HandsFreeSafety, clock: Clock, ms: float) -> None:
    end = clock.now + ms
    while clock.now < end:
        clock.now += FRAME
        gate.sample(SRC)


def _look_away(clock: Clock, ms: float = 1000.0) -> None:
    clock.now += ms  # no face, so no sample


def test_the_face_coming_back_rearms_after_an_unbroken_second():
    gate, clock = _armed()
    _look_away(clock)
    _frames(gate, clock, FRAME)
    assert not gate.gate(SRC).allowed, "the gap must still disarm, as before"
    _frames(gate, clock, REARM_AFTER_MS - 2 * FRAME)
    assert not gate.gate(SRC).allowed, "re-armed before the face had been back for long enough"
    _frames(gate, clock, 3 * FRAME)
    decision = gate.gate(SRC)
    assert decision.allowed and decision.clear_pending, "re-arm must also clear any half-gesture"
    assert gate.status().state is SafetyState.ACTIVE


def test_a_face_that_flickers_in_and_out_does_not_rearm():
    gate, clock = _armed()
    for _ in range(5):
        _look_away(clock, 700)
        _frames(gate, clock, REARM_AFTER_MS / 2)
    assert not gate.gate(SRC).allowed


def test_a_source_that_did_not_opt_in_still_waits_for_resume():
    gate, clock = _armed(opt_in=False)
    _look_away(clock)
    _frames(gate, clock, 5 * REARM_AFTER_MS)
    assert not gate.gate(SRC).allowed
    assert gate.resume().ok and gate.gate(SRC).allowed


def test_a_user_pause_is_never_undone_by_the_face_returning():
    gate, clock = _armed()
    gate.pause("user")
    _frames(gate, clock, 5 * REARM_AFTER_MS)
    assert not gate.gate(SRC).allowed
    # ... including a pause that arrives while the source was already stale-disarmed.
    gate, clock = _armed()
    _look_away(clock)
    _frames(gate, clock, FRAME)
    gate.pause("user")
    _frames(gate, clock, 5 * REARM_AFTER_MS)
    assert not gate.gate(SRC).allowed
    assert gate.status().state is SafetyState.PAUSED


def test_a_reported_fault_is_never_undone_by_the_face_returning():
    gate, clock = _armed()
    _look_away(clock)
    _frames(gate, clock, FRAME)
    gate.fault(SRC, "camera closed")
    gate.clear_fault(SRC)
    _frames(gate, clock, 5 * REARM_AFTER_MS)
    assert not gate.gate(SRC).allowed


def test_shutdown_is_never_undone():
    gate, clock = _armed()
    _look_away(clock)
    gate.shutdown()
    _frames(gate, clock, 5 * REARM_AFTER_MS)
    assert not gate.gate(SRC).allowed


def test_only_hold_bindings_may_rearm_on_face_return():
    assert rearms_on_face_return(frozenset({"hold_to_talk"}))
    assert rearms_on_face_return(frozenset({"hold_to_talk", "hold_to_command"}))
    assert not rearms_on_face_return(frozenset({"hold_to_talk", "select"}))
    assert not rearms_on_face_return(frozenset({"pause_pointer"}))
    assert not rearms_on_face_return(frozenset())


def test_look_away_look_back_then_dictate_through_the_real_backend():
    """The live failure, end to end: dictate, look at the keyboard for a second, look back,
    close the eyes again. Before the amendment the second closure was refused and only its
    release arrived; now it starts a second dictation. Scores are a synthetic fixture."""
    from yazses.config import FacegestureConfig
    from yazses.facegesture.backend import FaceGestureBackend
    from yazses.perception import FaceSignal, PerceptionSample

    cfg = FacegestureConfig(enabled=True, min_hold_frames=12,
                            switches=[{"gesture": "jaw_open", "intent": "none"},
                                      {"gesture": "eyes_closed", "intent": "hold_to_talk"}])

    class Lease:
        name = "scripted"
        sample = None

        def start(self): ...

        def stop(self): ...

        def latest(self):
            return self.sample

    def run(opt_in: bool):
        clock = [100.0]
        events: list[str] = []
        gate = HandsFreeSafety((SRC,), clock=lambda: clock[0] * 1000.0)
        lease = Lease()
        backend = FaceGestureBackend(cfg, lambda n: events.append("start"),
                                     lambda: events.append("end"),
                                     safety=gate, perception=lease, clock=lambda: clock[0])
        if opt_in and rearms_on_face_return(backend.bound_actions):
            gate.allow_auto_rearm(SRC, REARM_AFTER_MS)
        for i in range(int(10 * 15)):
            t = i / 15
            clock[0] = 100.0 + t
            if 3.5 <= t < 4.5:
                lease.sample = None  # looking at the keyboard: no face
            else:
                s = 0.85 if (1 <= t < 3) or (7 <= t < 9) else 0.08
                lease.sample = PerceptionSample(clock[0], face=FaceSignal(
                    clock[0], 0.95, {"eyeBlinkLeft": s, "eyeBlinkRight": s}))
            if i == 1:
                assert gate.resume().ok
            backend._shared_step()
        return events

    assert run(opt_in=False) == ["start", "end", "end"], "the old behaviour this replaces"
    assert run(opt_in=True) == ["start", "end", "start", "end"]
