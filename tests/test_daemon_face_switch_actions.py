"""The daemon's handlers for a face switch's ``select`` / ``confirm`` / ``cancel`` (ADR-v2-147).

Real pieces end to end -- the real ``Daemon`` glue, ``SwitchMapper``, ``HeadPointerController`` and
``ConfirmGate`` -- with only the edges faked: a recording ``FakePointerSink`` (nothing here can
click a real pointer), a recording injector (nothing is typed anywhere) and a stubbed
notification. The gestures are driven as :class:`SwitchIntent` values, so no camera and no
blendshape trace is involved.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.pointer_fake import FakePointerSink, PointerActionKind
from yazses.cmdsafety.classify import ConfirmGate
from yazses.config import Config, FacegestureConfig
from yazses.core.daemon import Daemon, _switch_action_lines
from yazses.facegesture.actions import SelectLimiter
from yazses.facegesture.switches import PRESS, RELEASE, SwitchIntent
from yazses.handsfree.observability import facts_from_payload, render_status_lines
from yazses.handsfree.safety import HandsFreeSafety
from yazses.headpointer.controller import HeadPointerController, HeadPointerSettings
from yazses.headpointer.runtime import HeadPointerRunner, HeadPointerRuntime
from yazses.ipc.protocol import Request
from yazses.perception.signals import HeadPoseSignal
from yazses.platform import get_platform


class _Lease:
    def start(self):
        pass

    def stop(self):
        pass

    def latest(self):
        return None


class _Injector:
    def __init__(self):
        self.typed: list[str] = []

    def inject(self, text):
        self.typed.append(text)


class Rig:
    """A daemon with select/confirm/cancel bound to three gestures, and a live Head-Pointer."""

    def __init__(self, monkeypatch, *, gate=None, extra=()):
        notices: list[str] = []
        monkeypatch.setattr("yazses.system.notify.notify", lambda title, body="", **kw: notices.append(body))
        self.notices = notices
        cfg = replace(
            Config(),
            facegesture=replace(
                FacegestureConfig(), enabled=True,
                switches=[
                    {"gesture": "smile", "intent": "select"},
                    {"gesture": "brow_raise", "intent": "confirm"},
                    {"gesture": "mouth_pucker", "intent": "cancel"},
                    *extra,
                ],
            ),
        )
        self.d = Daemon(config=cfg, platform=get_platform())
        self.d._handsfree_safety = gate
        self.sink = FakePointerSink()
        self.t = 100.0
        self.controller = HeadPointerController(
            self.sink, HeadPointerSettings(), safety=gate, backend="fake"
        )
        runner = HeadPointerRunner(
            self.controller, _Lease(), clock=lambda: self.t, thread=False
        )
        self.runtime = HeadPointerRuntime(runner=runner)
        self.d._headpointer = self.runtime
        # the rate limit runs on the rig's clock so "1.5 s later" costs nothing to say
        self.d._switch_select_limiter = SelectLimiter(clock=lambda: self.t)
        self.injector = _Injector()
        self.d._injector = self.injector
        self.source = self.d._build_face_gesture_source(self.d._config)[0]
        self.mapper = self.source._mapper

    def track(self):
        """Two fresh samples: centred, then tracking."""
        for _ in range(2):
            self.t += 0.033
            self.controller.update(HeadPoseSignal(self.t, 0.0, 0.0, 0.0, 1.0), self.t)

    def gesture(self, name, *, hold=0.0):
        self.mapper.handle(SwitchIntent(name, PRESS, self.t))
        self.t += hold
        self.mapper.handle(SwitchIntent(name, RELEASE, self.t))

    @property
    def clicks(self) -> int:
        return sum(1 for a in self.sink.actions if a.kind is PointerActionKind.BUTTON_PRESS)

    def last(self, action):
        return self.d._switch_outcomes.last(action)


@pytest.fixture
def rig(monkeypatch):
    return Rig(monkeypatch)


# ------------------------------------------------------------------ wiring


def test_all_three_actions_are_wired_so_nothing_is_reported_unwired(rig):
    assert rig.mapper.unwired() == []
    assert rig.source.bound_actions >= {"select", "confirm", "cancel"}
    assert rig.d._switch_bound >= {"select", "confirm", "cancel"}


def test_the_ipc_method_is_registered():
    import inspect

    assert 'server.register("facegesture", self._handle_facegesture)' in inspect.getsource(
        Daemon._start_ipc_server
    )


# ------------------------------------------------------------------ select


def test_select_clicks_the_left_button_once_through_the_pointer_sink(rig):
    rig.track()
    rig.gesture("smile")
    assert rig.clicks == 1
    presses = [a for a in rig.sink.actions if a.kind is PointerActionKind.BUTTON_PRESS]
    assert presses[0].button.value == "left"
    assert rig.last("select").result == "done"


def test_select_holds_the_pointer_still_for_the_gesture_and_then_lets_go(rig):
    rig.track()
    rig.mapper.handle(SwitchIntent("smile", PRESS, rig.t))
    assert rig.controller.status().clutched is True  # the face switch's own freeze
    assert rig.clicks == 1  # ...which did not refuse its own click
    rig.mapper.handle(SwitchIntent("smile", RELEASE, rig.t))
    assert rig.controller.status().clutched is False


def test_select_is_refused_with_a_reason_when_the_pointer_is_paused(rig):
    rig.track()
    rig.controller.pause()
    rig.gesture("smile")
    assert rig.clicks == 0
    outcome = rig.last("select")
    assert outcome.result == "refused" and "paused" in outcome.reason


def test_select_is_refused_when_someone_else_clutches_the_pointer(rig):
    rig.track()
    rig.controller.set_clutch("cli", True)
    rig.gesture("smile")
    assert rig.clicks == 0
    assert "clutched" in rig.last("select").reason


def test_select_is_refused_before_any_head_signal_has_arrived(rig):
    rig.gesture("smile")
    assert rig.clicks == 0
    assert "signal" in rig.last("select").reason


def test_select_is_refused_when_the_head_pointer_is_not_running(rig):
    rig.d._headpointer = HeadPointerRuntime(reason="Head-Pointer is off")
    rig.gesture("smile")
    assert rig.clicks == 0
    assert "off" in rig.last("select").reason


def test_select_is_refused_when_there_is_no_head_pointer_object_at_all(rig):
    rig.d._headpointer = None
    rig.gesture("smile")
    assert rig.last("select").result == "refused"


def test_a_flickering_gesture_clicks_once_not_repeatedly(rig):
    rig.track()
    for _ in range(6):
        rig.gesture("smile", hold=0.05)
    assert rig.clicks == 1
    assert rig.d._switch_outcomes.snapshot({"select"})[0]["refused"] == 5


def test_a_second_deliberate_select_after_the_interval_clicks_again(rig):
    rig.track()
    rig.gesture("smile")
    rig.t += 1.5
    rig.gesture("smile")
    assert rig.clicks == 2


def test_select_under_a_closed_global_gate_never_reaches_the_pointer(monkeypatch):
    gate = HandsFreeSafety(("headpointer", "facegesture"), clock=lambda: rig.t * 1000.0)
    rig = Rig(monkeypatch, gate=gate)
    rig.track()
    gate.sample("facegesture", at_ms=rig.t * 1000.0)
    # nothing has armed the gate: the mapper itself suppresses the press
    rig.gesture("smile")
    assert rig.clicks == 0


def test_select_with_an_armed_gate_that_then_pauses_is_refused(monkeypatch):
    gate = HandsFreeSafety(("headpointer", "facegesture"), clock=lambda: rig.t * 1000.0)
    rig = Rig(monkeypatch, gate=gate)
    rig.track()
    gate.sample("facegesture", at_ms=rig.t * 1000.0)
    assert gate.resume().ok
    rig.track()  # the runner ticks again once armed, so the controller leaves SUPPRESSED
    gate.sample("facegesture", at_ms=rig.t * 1000.0)
    rig.gesture("smile")
    assert rig.clicks == 1
    rig.t += 2.0
    rig.track()
    gate.sample("facegesture", at_ms=rig.t * 1000.0)
    gate.pause("test")
    rig.gesture("smile")
    assert rig.clicks == 1


def test_a_failing_pointer_backend_faults_and_select_reports_it(rig):
    rig.track()
    rig.sink.fail_with()
    rig.gesture("smile")
    assert rig.last("select").result == "refused"
    assert rig.controller.status().fault


# ------------------------------------------------------------------ confirm / cancel


def test_confirm_with_nothing_pending_is_a_noop_that_types_and_clicks_nothing(rig):
    rig.gesture("brow_raise")
    outcome = rig.last("confirm")
    assert outcome.result == "noop"
    assert rig.injector.typed == [] and rig.clicks == 0


def test_cancel_with_nothing_pending_is_a_noop(rig):
    rig.gesture("mouth_pucker")
    assert rig.last("cancel").result == "noop"
    assert rig.injector.typed == []


def test_confirm_releases_a_held_dictated_command_through_the_injector(rig):
    rig.d._cmdsafety = ConfirmGate()
    rig.d._cmdsafety.submit("rm -rf build")
    assert rig.d._cmdsafety.pending == "rm -rf build"
    rig.gesture("brow_raise")
    assert rig.injector.typed == ["rm -rf build"]
    assert rig.d._cmdsafety.pending is None
    assert rig.last("confirm").result == "done"
    assert "rm -rf" not in rig.last("confirm").line
    assert any("Confirmed" in n for n in rig.notices)


def test_confirm_re_dispatches_a_held_command_instead_of_typing_its_text(rig, monkeypatch):
    dispatched = []
    rig.d._cmdsafety.submit("rm -rf build")
    rig.d._cmdsafety_intent = SimpleNamespace(action="run_command")
    monkeypatch.setattr(rig.d, "_cmdsafety_dispatch_held", lambda: dispatched.append(1) or True)
    rig.gesture("brow_raise")
    assert dispatched == [1]
    assert rig.injector.typed == []


def test_cancel_drops_the_held_command_and_types_nothing(rig):
    rig.d._cmdsafety.submit("rm -rf build")
    rig.d._cmdsafety_intent = SimpleNamespace(action="run_command")
    rig.gesture("mouth_pucker")
    assert rig.d._cmdsafety.pending is None
    assert rig.d._cmdsafety_intent is None
    assert rig.injector.typed == []
    assert rig.last("cancel").result == "done"


def test_a_second_confirm_after_the_first_does_nothing_more(rig):
    rig.d._cmdsafety.submit("rm -rf build")
    rig.gesture("brow_raise")
    rig.gesture("brow_raise")
    assert rig.injector.typed == ["rm -rf build"]
    assert rig.last("confirm").result == "noop"


def test_confirm_into_a_window_with_no_text_target_does_not_type(rig, monkeypatch):
    rig.d._state.target_ok = False
    handled = []
    monkeypatch.setattr(rig.d, "_handle_no_target", lambda text: handled.append(text) or True)
    rig.d._cmdsafety.submit("rm -rf build")
    rig.gesture("brow_raise")
    assert handled == ["rm -rf build"]
    assert rig.injector.typed == []


# ------------------------------------------------------------------ surfaces


def test_ipc_status_lists_bound_actions_with_their_last_outcome(rig):
    rig.track()
    rig.gesture("smile")
    rig.gesture("brow_raise")
    reply = rig.d._handle_facegesture(Request("facegesture", {"action": "status"}))
    assert reply["ok"] is True and reply["active"] is True
    by_action = {r["action"]: r for r in reply["actions"]}
    assert by_action["select"]["result"] == "done"
    assert by_action["confirm"]["result"] == "noop"
    assert by_action["cancel"]["result"] == "unused"


def test_ipc_status_when_the_face_switch_was_never_built(monkeypatch):
    d = Daemon(config=Config(), platform=get_platform())
    reply = d._handle_facegesture(Request("facegesture", {}))
    assert reply["ok"] is True and reply["active"] is False and reply["reason"]


def test_ipc_rejects_an_unknown_action(rig):
    assert rig.d._handle_facegesture(Request("facegesture", {"action": "click"}))["ok"] is False


def test_the_handsfree_state_carries_each_actions_last_outcome(rig):
    rig.track()
    rig.controller.pause()
    rig.gesture("smile")
    lines = _switch_action_lines(rig.d)
    assert "select: last refused (the Head-Pointer is paused)" in lines
    assert "confirm: bound, not used yet" in lines
    payload = {"features_requested": ["facegesture"], "switch_actions": list(lines)}
    facts = facts_from_payload(payload)
    assert facts is not None and facts.switch_actions == lines
    text = "\n".join(render_status_lines(payload))
    assert "face switch actions" in text and "last refused" in text


def test_no_outcomes_before_a_face_switch_exists():
    d = Daemon(config=Config(), platform=get_platform())
    assert _switch_action_lines(d) == ()


# ------------------------------------------------------------------ pause_pointer, no global stop
#
# `handsfree pause`, the panel's Pause and a chord's `pause_pointer` all still pause a running
# Head-Pointer when `[handsfree_safety]` is off. A face switch bound to `pause_pointer` used to
# be the one input that did nothing in that configuration (EYE-FACE-002: "supported actions
# can include ... pause pointer").

_PAUSE = ({"gesture": "eyes_closed", "intent": "pause_pointer"},)


def test_pause_pointer_pauses_a_running_head_pointer_when_the_global_stop_is_off(monkeypatch):
    rig = Rig(monkeypatch, extra=_PAUSE)
    assert rig.d._handsfree_safety is None
    assert rig.mapper.unwired() == []
    rig.track()
    assert rig.controller.status().paused is False
    rig.gesture("eyes_closed")
    assert rig.controller.status().paused is True


def test_after_a_face_pause_a_select_is_refused_and_clicks_nothing(monkeypatch):
    rig = Rig(monkeypatch, extra=_PAUSE)
    rig.track()
    rig.gesture("eyes_closed")
    rig.gesture("smile")
    assert rig.clicks == 0
    assert "paused" in rig.last("select").reason


def test_a_face_pause_is_undone_by_the_ordinary_resume(monkeypatch):
    rig = Rig(monkeypatch, extra=_PAUSE)
    rig.track()
    rig.gesture("eyes_closed")
    assert rig.controller.status().paused is True
    assert rig.runtime.command("resume")["ok"] is True
    assert rig.controller.status().paused is False


def test_with_the_global_stop_on_pause_pointer_pauses_the_gate(monkeypatch):
    gate = HandsFreeSafety(("headpointer", "facegesture"), clock=lambda: rig.t * 1000.0)
    rig = Rig(monkeypatch, gate=gate, extra=_PAUSE)
    rig.track()
    gate.sample("facegesture", at_ms=rig.t * 1000.0)
    assert gate.resume().ok
    rig.gesture("eyes_closed")
    assert gate.status().user_paused is True


def test_pause_pointer_with_nothing_to_pause_stays_unwired_and_names_the_remedy(
    monkeypatch, caplog
):
    rig = Rig(monkeypatch, extra=_PAUSE)
    rig.d._headpointer = HeadPointerRuntime(reason="Head-Pointer is off")
    with caplog.at_level(logging.WARNING):
        source = rig.d._build_face_gesture_source(rig.d._config)[0]
    assert source._mapper.unwired() == ["pause_pointer"]
    assert "[handsfree_safety]" in caplog.text and "[headpointer]" in caplog.text


def test_a_pause_the_pointer_refuses_is_logged_and_never_raises(caplog):
    class _Refusing:
        active = True

        def command(self, action, params=None):
            return {"ok": False, "reason": "busy"}

    with caplog.at_level(logging.INFO):
        Daemon._switch_pause_pointer(_Refusing())
    assert "did not pause (busy)" in caplog.text


# ------------------------------------------------------------------ holds take the hotkey's path
#
# The confirmation policy (cmdsafety) sits behind the daemon's own hold entry points. A face
# hold must enter through exactly those -- not a parallel path that could skip the check -- so a
# destructive spoken command made with a face switch is held for confirmation just as one made
# with the hotkey is.


def test_face_holds_enter_the_same_daemon_entry_points_as_the_hotkey(monkeypatch):
    rig = Rig(monkeypatch, extra=({"gesture": "eyes_closed", "intent": "hold_to_command"},))
    calls: list[tuple] = []
    monkeypatch.setattr(rig.d, "_on_hold_start", lambda leaked: calls.append(("talk", leaked)))
    monkeypatch.setattr(rig.d, "_on_hold_end", lambda: calls.append(("talk_end",)))
    monkeypatch.setattr(
        rig.d, "_on_command_hold_start", lambda leaked: calls.append(("command", leaked))
    )
    monkeypatch.setattr(rig.d, "_on_command_hold_end", lambda: calls.append(("command_end",)))
    # Rebuilt after patching: the legacy primary binding captures the bound method at build.
    rig.mapper = rig.d._build_face_gesture_source(rig.d._config)[0]._mapper
    rig.gesture("jaw_open")      # the legacy primary binding: hold_to_talk
    rig.gesture("eyes_closed")   # hold_to_command
    assert calls == [("talk", 0), ("talk_end",), ("command", 0), ("command_end",)]
