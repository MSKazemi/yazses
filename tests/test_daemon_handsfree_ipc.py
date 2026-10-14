"""The daemon's global hands-free stop, and the live state it publishes (#420).

Two things were missing before the settings panel could exist. `headpointer pause` was a
*feature-level* pause — it never told the global gate, so the face switch kept running and
`status` kept saying the state was unknown. And the hands-free `status` payload had a slot for
the gate's live ACTIVE/PAUSED/FAULTED snapshot that nothing in the daemon ever filled.

These tests drive the real handler and the real gate against a fabricated clock. No camera,
no socket, no thread.
"""
from __future__ import annotations

import types

from tests.pointer_fake import FakePointerSink
from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.handsfree.observability import facts_from_payload
from yazses.handsfree.safety import HandsFreeSafety, SafetyState
from yazses.headpointer.controller import SOURCE_NAME, HeadPointerController, HeadPointerSettings
from yazses.headpointer.runtime import HeadPointerRunner, HeadPointerRuntime
from yazses.ipc.protocol import Request


class _Lease:
    def start(self):
        pass

    def stop(self):
        pass

    def latest(self):
        return None


def _daemon(*, gate=None, runtime=None, cfg=None):
    return types.SimpleNamespace(
        _handsfree_safety=gate, _headpointer=runtime, _config=cfg or Config(),
        _gaze_targeter=None, _extra_activations=[],
    )


def _runtime(gate, clock):
    controller = HeadPointerController(
        FakePointerSink(), HeadPointerSettings(), safety=gate, backend="fake"
    )
    runner = HeadPointerRunner(
        controller, _Lease(), clock=lambda: clock[0] / 1000.0, thread=False
    )
    return HeadPointerRuntime(runner=runner), controller


def _call(daemon, action):
    return Daemon._handle_handsfree(daemon, Request("handsfree", {"action": action}))


def test_the_method_is_registered_with_the_ipc_server():
    import inspect

    assert 'server.register("handsfree", self._handle_handsfree)' in inspect.getsource(
        Daemon._start_ipc_server
    )


def test_pause_stops_every_source_at_once_not_only_the_head_pointer():
    clock = [1000.0]
    gate = HandsFreeSafety((SOURCE_NAME, "facegesture"), clock=lambda: clock[0])
    gate.sample(SOURCE_NAME)
    gate.sample("facegesture")
    assert gate.resume().ok
    runtime, _ = _runtime(gate, clock)
    reply = _call(_daemon(gate=gate, runtime=runtime), "pause")
    assert reply["ok"] is True and reply["scope"] == ["all hands-free input"]
    assert gate.gate("facegesture").allowed is False, "the face switch must stop too"
    assert gate.gate(SOURCE_NAME).allowed is False
    assert gate.status().state is SafetyState.PAUSED


def test_pause_with_the_global_stop_off_still_stops_the_pointer_and_says_it_was_only_that():
    clock = [1000.0]
    runtime, controller = _runtime(None, clock)
    reply = _call(_daemon(gate=None, runtime=runtime), "pause")
    assert reply == {"ok": True, "scope": ["Head-Pointer only"]}
    assert controller.status().paused is True


def test_pause_with_nothing_running_is_a_refusal_with_the_reason_not_a_silent_ok():
    reply = _call(_daemon(), "pause")
    assert reply["ok"] is False and "global stop is off" in reply["reason"]


def test_resume_rearms_after_a_user_pause():
    clock = [1000.0]
    gate = HandsFreeSafety((SOURCE_NAME,), clock=lambda: clock[0])
    gate.sample(SOURCE_NAME)
    gate.resume()
    runtime, _ = _runtime(gate, clock)
    daemon = _daemon(gate=gate, runtime=runtime)
    _call(daemon, "pause")
    gate.sample(SOURCE_NAME)  # the camera is still delivering
    reply = _call(daemon, "resume")
    assert reply["ok"] is True, reply
    assert gate.status().state is SafetyState.ACTIVE


def test_resume_after_a_fault_is_refused_until_the_signal_is_back_and_says_so():
    clock = [1000.0]
    gate = HandsFreeSafety((SOURCE_NAME,), clock=lambda: clock[0])
    gate.sample(SOURCE_NAME)
    gate.resume()
    runtime, _ = _runtime(gate, clock)
    daemon = _daemon(gate=gate, runtime=runtime)
    clock[0] += 5000.0  # the camera went quiet for five seconds
    assert gate.status().state is SafetyState.FAULTED
    refused = _call(daemon, "resume")
    assert refused["ok"] is False and "headpointer" in refused["reason"]
    assert gate.status().state is SafetyState.FAULTED, "a refused recovery must not half-arm"
    gate.sample(SOURCE_NAME)  # a fresh frame arrives
    assert _call(daemon, "resume")["ok"] is True
    assert gate.status().state is SafetyState.ACTIVE


def test_a_pointer_fault_is_cleared_by_resume_and_never_by_itself():
    clock = [1000.0]
    gate = HandsFreeSafety((SOURCE_NAME,), clock=lambda: clock[0])
    gate.sample(SOURCE_NAME)
    gate.resume()
    runtime, controller = _runtime(gate, clock)
    controller.fail("pointer backend failed")
    assert gate.status().state is SafetyState.FAULTED
    gate.sample(SOURCE_NAME)
    assert gate.status().state is SafetyState.FAULTED, "fresh data alone must not recover"
    assert _call(_daemon(gate=gate, runtime=runtime), "resume")["ok"] is True
    assert gate.status().state is SafetyState.ACTIVE


def test_unknown_actions_and_missing_params_are_refused_not_guessed():
    daemon = _daemon()
    assert _call(daemon, "launch")["ok"] is False
    assert Daemon._handle_handsfree(daemon, Request("handsfree", {}))["ok"] is False


def test_neither_action_accepts_a_position():
    """The handler reads one parameter, `action`. A pointer position sent along is ignored."""
    clock = [1000.0]
    gate = HandsFreeSafety((SOURCE_NAME,), clock=lambda: clock[0])
    gate.sample(SOURCE_NAME)
    gate.resume()
    reply = Daemon._handle_handsfree(
        _daemon(gate=gate), Request("handsfree", {"action": "pause", "x": 10, "y": 20})
    )
    assert reply["ok"] is True


# ------------------------------------------------------------------ the live state in status


def test_status_now_carries_the_live_gate_state():
    clock = [1000.0]
    gate = HandsFreeSafety((SOURCE_NAME,), clock=lambda: clock[0])
    gate.sample(SOURCE_NAME)
    gate.resume()
    cfg = Config()
    cfg.headpointer.enabled = True
    cfg.handsfree_safety.enabled = True
    payload = Daemon._handsfree_payload(_daemon(gate=gate, cfg=cfg))
    assert payload is not None
    facts = facts_from_payload(payload)
    assert facts is not None and facts.safety is not None
    assert facts.safety.state is SafetyState.ACTIVE
    gate.pause("user")
    again = facts_from_payload(Daemon._handsfree_payload(_daemon(gate=gate, cfg=cfg)))
    assert again.safety.state is SafetyState.PAUSED


def test_status_has_no_gate_state_when_the_global_stop_is_off():
    cfg = Config()
    cfg.headpointer.enabled = True
    payload = Daemon._handsfree_payload(_daemon(gate=None, cfg=cfg))
    assert payload is not None and payload["safety"] is None


def test_a_gate_that_cannot_answer_does_not_break_status():
    class Broken:
        def status(self):
            raise RuntimeError("boom")

    cfg = Config()
    cfg.headpointer.enabled = True
    cfg.handsfree_safety.enabled = True
    payload = Daemon._handsfree_payload(_daemon(gate=Broken(), cfg=cfg))
    assert payload is not None and payload["safety"] is None
