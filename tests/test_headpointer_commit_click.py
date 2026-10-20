"""``HeadPointerController.commit_click`` -- the one entry point a face switch's select uses.

A real controller over ``tests/pointer_fake.py``'s recording sink: the assertions are on the exact
calls a backend would have received, and nothing here can move a real pointer. What is protected:
the policy is asked *before* anything is sent, a refusal sends nothing, the switch's own clutch
does not refuse itself while someone else's does, a failing sink faults the controller instead of
being retried, and a commit click disarms dwell so the two paths cannot both fire.
"""
from __future__ import annotations

from tests.pointer_fake import FakePointerSink, PointerActionKind
from tests.test_headpointer_controller import GateRig, Rig
from yazses.headpointer.controller import State
from yazses.pointer.base import PointerButton


def _clicks(rig: Rig) -> int:
    return sum(1 for a in rig.sink.actions if a.kind is PointerActionKind.BUTTON_PRESS)


def _tracking_rig(**kw) -> Rig:
    rig = Rig(**kw)
    rig.centre()
    rig.feed(0.0, 0.0)
    assert rig.ctl.status().state is State.TRACKING
    return rig


def _allow(_ctx) -> str:
    return ""


def test_an_allowed_commit_sends_exactly_one_left_click():
    rig = _tracking_rig()
    result = rig.ctl.commit_click(_allow)
    assert result.ok
    presses = [a for a in rig.sink.actions if a.kind is PointerActionKind.BUTTON_PRESS]
    assert [p.button for p in presses] == [PointerButton.LEFT]
    assert _clicks(rig) == 1


def test_a_refusing_policy_sends_nothing_and_its_reason_comes_back():
    rig = _tracking_rig()
    result = rig.ctl.commit_click(lambda ctx: "not now")
    assert (result.ok, result.reason) == (False, "not now")
    assert _clicks(rig) == 0


def test_a_policy_that_raises_refuses_and_sends_nothing():
    rig = _tracking_rig()

    def policy(_ctx):
        raise ValueError("bad")

    result = rig.ctl.commit_click(policy)
    assert not result.ok
    assert _clicks(rig) == 0


def test_the_context_reports_pause_and_a_foreign_clutch():
    rig = _tracking_rig()
    seen = []
    rig.ctl.pause()
    rig.ctl.commit_click(lambda ctx: seen.append(ctx) or "x")
    assert seen[-1].paused is True
    rig.ctl.resume()
    rig.ctl.set_clutch("cli", True)
    rig.ctl.commit_click(lambda ctx: seen.append(ctx) or "x")
    assert seen[-1].clutched is True


def test_the_callers_own_clutch_is_not_counted_but_anyone_elses_is():
    rig = _tracking_rig()
    rig.ctl.set_clutch("faceswitch", True)
    seen = []
    rig.ctl.commit_click(lambda ctx: seen.append(ctx) or "", own_clutches=("faceswitch",))
    assert seen[-1].clutched is False
    rig.ctl.set_clutch("cli", True)
    rig.ctl.commit_click(lambda ctx: seen.append(ctx) or "x", own_clutches=("faceswitch",))
    assert seen[-1].clutched is True


def test_a_failing_sink_faults_the_controller_and_the_click_is_not_retried():
    rig = _tracking_rig()
    rig.sink.fail_with()
    result = rig.ctl.commit_click(_allow)
    assert not result.ok
    status = rig.ctl.status()
    assert status.state is State.FAULTED and status.fault
    rig.sink.clear_failure()
    # still refused: only an explicit resume clears a fault, and nothing was replayed
    seen = []
    rig.ctl.commit_click(lambda ctx: seen.append(ctx) or "x")
    assert seen[-1].faulted is True
    assert _clicks(rig) == 0


def test_a_closed_controller_says_closed_and_sends_nothing():
    rig = _tracking_rig()
    rig.ctl.close()
    seen = []
    result = rig.ctl.commit_click(lambda ctx: seen.append(ctx) or "closed")
    assert seen[-1].closed is True
    assert not result.ok


def test_a_commit_click_disarms_dwell_so_one_pause_of_the_head_cannot_click_twice():
    rig = _tracking_rig(dwell=True, hold=3)
    rig.ctl.commit_click(_allow)
    assert rig.ctl.status().dwell_armed is False
    clicks_after_commit = _clicks(rig)
    for _ in range(10):  # head perfectly still: dwell may not click without travel
        rig.feed(0.0, 0.0)
    assert _clicks(rig) == clicks_after_commit == 1


def test_the_global_gate_closed_is_reported_as_not_allowed():
    rig = GateRig()
    rig.arm()
    rig.feed(0.0)
    seen = []
    rig.ctl.commit_click(lambda ctx: seen.append(ctx) or "")
    assert seen[-1].gate_allowed is True
    rig.gate.pause("test")
    result = rig.ctl.commit_click(lambda ctx: seen.append(ctx) or ("gate" if not ctx.gate_allowed else ""))
    assert seen[-1].gate_allowed is False
    assert not result.ok
    assert _clicks(rig) == 1  # only the first, allowed, one


def test_no_gate_means_gate_allowed_is_none_not_false():
    rig = _tracking_rig()
    seen = []
    rig.ctl.commit_click(lambda ctx: seen.append(ctx) or "")
    assert seen[-1].gate_allowed is None


def test_the_sink_used_is_the_one_the_controller_was_built_with():
    sink = FakePointerSink()
    rig = Rig(sink=sink)
    rig.centre()
    rig.feed(0.0, 0.0)
    rig.ctl.commit_click(_allow)
    assert [a.kind for a in sink.actions] == [
        PointerActionKind.BUTTON_PRESS, PointerActionKind.BUTTON_RELEASE,
    ]
