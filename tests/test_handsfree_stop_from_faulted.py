"""The independent stop path of ADR-v2-148 works from the FAULTED state (Phase 6 exit gate).

The state in which a hands-free user most needs to stop things is the one in which the machinery
is least trustworthy: a camera has gone quiet, a backend reported a fault, and the pointer may be
doing anything. A stop that is itself refused, or that needs a healthy sensor, is no stop. So every
path the preset documents is driven *from FAULTED* and must (a) work, (b) leave the system
suppressed, and (c) not re-arm by itself afterwards.

All fabricated clocks and fake sinks; no camera, no pointer, no socket.
"""
from __future__ import annotations

import types

from tests.pointer_fake import FakePointerSink
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.facegesture.switches import PRESS, SwitchAction, SwitchIntent, SwitchMapper
from yazses.gesture.engine import ChordEngine
from yazses.handsfree.safety import HandsFreeSafety, SafetyState
from yazses.headpointer.controller import SOURCE_NAME, HeadPointerController, HeadPointerSettings
from yazses.ipc.protocol import Request


def _faulted_by_silence():
    """An armed gate whose camera then went quiet for five seconds."""
    clock = [1000.0]
    gate = HandsFreeSafety((SOURCE_NAME, "facegesture"), clock=lambda: clock[0])
    gate.sample(SOURCE_NAME)
    gate.sample("facegesture")
    assert gate.resume().ok
    clock[0] += 5000.0
    assert gate.status().state is SafetyState.FAULTED
    return gate, clock


def _faulted_by_backend():
    clock = [1000.0]
    gate = HandsFreeSafety((SOURCE_NAME,), clock=lambda: clock[0])
    gate.sample(SOURCE_NAME)
    assert gate.resume().ok
    gate.fault(SOURCE_NAME, "pointer backend closed")
    assert gate.status().state is SafetyState.FAULTED
    return gate, clock


def _daemon(gate, runtime=None):
    return types.SimpleNamespace(
        _handsfree_safety=gate, _headpointer=runtime, _config=Config(),
        _gaze_targeter=None, _extra_activations=[],
    )


def _pause(daemon):
    return Daemon._handle_handsfree(daemon, Request("handsfree", {"action": "pause"}))


def _resume(daemon):
    return Daemon._handle_handsfree(daemon, Request("handsfree", {"action": "resume"}))


# --------------------------------------------------------------------------- the global stop


def test_pause_from_a_silent_camera_fault_is_accepted_and_ends_in_paused():
    gate, _ = _faulted_by_silence()
    reply = _pause(_daemon(gate))
    assert reply == {"ok": True, "scope": ["all hands-free input"]}
    status = gate.status()
    assert status.state is SafetyState.PAUSED and status.user_paused


def test_pause_from_a_backend_fault_is_accepted_and_ends_in_paused():
    gate, _ = _faulted_by_backend()
    assert _pause(_daemon(gate))["ok"] is True
    assert gate.status().state is SafetyState.PAUSED


def test_pause_from_faulted_needs_no_pointer_and_no_running_head_pointer():
    gate, _ = _faulted_by_silence()
    reply = _pause(_daemon(gate, runtime=None))
    assert reply["ok"] is True, "the stop must not depend on the thing being stopped"


def test_every_source_is_denied_after_a_stop_from_faulted_even_with_fresh_signals():
    gate, clock = _faulted_by_silence()
    _pause(_daemon(gate))
    gate.sample(SOURCE_NAME)
    gate.sample("facegesture")  # the camera is suddenly healthy again
    assert gate.gate(SOURCE_NAME).allowed is False
    assert gate.gate("facegesture").allowed is False


def test_a_stop_from_faulted_is_never_undone_by_the_fault_clearing():
    gate, _ = _faulted_by_backend()
    _pause(_daemon(gate))
    gate.clear_fault(SOURCE_NAME)
    gate.sample(SOURCE_NAME)
    assert gate.gate(SOURCE_NAME).allowed is False
    assert gate.status().state is SafetyState.PAUSED


def test_recovery_after_the_stop_is_explicit_and_refused_while_the_fault_stands():
    gate, clock = _faulted_by_silence()
    daemon = _daemon(gate)
    _pause(daemon)
    refused = _resume(daemon)
    assert refused["ok"] is False and "not ready to re-arm" in refused["reason"]
    assert gate.status().state is not SafetyState.ACTIVE
    gate.sample(SOURCE_NAME)
    gate.sample("facegesture")
    reply = _resume(daemon)
    assert reply["ok"] is True
    decision = gate.gate(SOURCE_NAME)
    assert decision.allowed and decision.clear_pending, "the first decision after re-arm drops stale state"


def test_pausing_twice_from_faulted_is_idempotent():
    gate, _ = _faulted_by_silence()
    daemon = _daemon(gate)
    assert _pause(daemon)["ok"] and _pause(daemon)["ok"]
    assert gate.status().state is SafetyState.PAUSED


def test_shutdown_from_faulted_is_terminal():
    gate, _ = _faulted_by_silence()
    gate.shutdown("disabled")
    gate.sample(SOURCE_NAME)
    assert gate.resume().ok is False
    assert gate.gate(SOURCE_NAME).allowed is False


# --------------------------------------------------------------------------- the camera-side stops


def test_the_face_switch_pause_action_runs_while_the_gate_is_faulted():
    gate, _ = _faulted_by_silence()
    mapper = SwitchMapper(
        {"brow_raise": "pause_pointer", "jaw_open": "hold_to_talk"},
        {
            "pause_pointer": SwitchAction(press=lambda: gate.pause("face switch")),
            "hold_to_talk": SwitchAction(press=lambda: (_ for _ in ()).throw(AssertionError("must not talk"))),
        },
        gate=gate,
    )
    assert mapper.handle(SwitchIntent("jaw_open", PRESS, 1.0)) is False, "a non-stop action stays suppressed"
    assert mapper.handle(SwitchIntent("brow_raise", PRESS, 2.0)) is True
    assert gate.status().state is SafetyState.PAUSED


def test_the_stop_chord_fires_while_the_gate_is_faulted_but_recenter_does_not():
    gate, _ = _faulted_by_silence()
    fired: list[str] = []
    engine = ChordEngine(
        {"brow_raise+shake": "pause_pointer", "brow_raise+nod": "recenter"},
        {"pause_pointer": lambda: (fired.append("pause"), gate.pause("chord")),
         "recenter": lambda: fired.append("recenter")},
        window_s=0.4, refractory_s=0.0, freeze_tail_s=0.0, gate=gate,
    )
    engine.press("brow_raise", 10.0)
    engine.pulse("nod", 10.1)
    engine.tick(10.6)
    engine.release("brow_raise", 10.7)
    assert fired == [], "recenter is not a stop and must stay suppressed"
    engine.press("brow_raise", 20.0)
    engine.pulse("shake", 20.1)
    engine.tick(20.6)
    assert fired == ["pause"]
    assert gate.status().state is SafetyState.PAUSED


# --------------------------------------------------------------------------- the pointer itself


def test_a_faulted_pointer_moves_nothing_and_the_stop_keeps_it_that_way():
    gate, clock = _faulted_by_silence()
    sink = FakePointerSink()
    controller = HeadPointerController(sink, HeadPointerSettings(), safety=gate, backend="fake")
    from yazses.perception.signals import HeadPoseSignal

    now = clock[0] / 1000.0
    step = controller.update(HeadPoseSignal(now, 0.4, 0.4, 0.0, 1.0), now)
    assert (step.dx, step.dy, step.clicked) == (0, 0, False)
    _pause(_daemon(gate))
    now += 0.1
    step = controller.update(HeadPoseSignal(now, 0.4, 0.4, 0.0, 1.0), now)
    assert (step.dx, step.dy, step.clicked) == (0, 0, False)
    assert [a for a in sink.actions if a.kind.value != "close"] == []
