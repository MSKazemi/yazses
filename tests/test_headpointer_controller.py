"""The Head-Pointer state machine, on fabricated head-pose traces (ADR-v2-052, #404/#405).

Every test drives numbers, never a camera: a ``HeadPoseSignal`` is a handful of floats and
time is an assignment (``Rig.t``), so "the camera went quiet for 600 ms" or "the head sat dead
still for twenty frames" costs nothing to say and nothing to reproduce. The pointer is
``tests/pointer_fake.py``'s recording sink, so the assertions are on the *exact* calls a real
backend would have received. Nothing here moves a real pointer or opens a device.

What is being protected is one failure: **a pointer that moves or clicks when the user did not
ask it to** -- a click on startup, a click after the camera dropped out, a pointer that keeps
gliding on the last delta it saw, a motion that survives a pause. Each such rule has at least
one test that goes red when the rule is removed (the mutation checks are recorded in the
commit that introduced them), and the cases are the risk register's, not invented ones:
R-05 the user cannot stop continuous camera control, R-06 a stale pose keeps moving the
cursor, R-24 recovery itself fires an action.

**No number here is a product recommendation.** The traces are synthetic; they establish that
the state machine does what it says, not that any gain, dead zone or hold length suits a human
neck. That is hardware evidence, collected separately (``design/eye-control/GOVERNANCE.md``).
"""
from __future__ import annotations

import math

from tests.pointer_fake import FakePointerSink, PointerAction, PointerActionKind
from yazses.handsfree.safety import HandsFreeSafety
from yazses.headpointer.controller import (
    HeadPointerController,
    HeadPointerSettings,
    State,
)
from yazses.headpointer.pointer import PointerCalib, pose_to_cursor
from yazses.perception.signals import HeadPoseSignal
from yazses.pointer.base import PointerBackendError, PointerButton

FRAME = 1.0 / 30.0


class Rig:
    """A controller, a recording sink and a clock the test moves by hand."""

    def __init__(
        self,
        *,
        dwell: bool = False,
        hold: int = 5,
        calib: PointerCalib | None = None,
        safety: HandsFreeSafety | None = None,
        sink: FakePointerSink | None = None,
        feedback=None,
        freshness_s: float = 0.5,
    ) -> None:
        self.t = 100.0
        self.sink = sink or FakePointerSink()
        self.settings = HeadPointerSettings(
            calib=calib or PointerCalib(),
            freshness_s=freshness_s,
            dwell_enabled=dwell,
            dwell_hold_frames=hold,
        )
        self.ctl = HeadPointerController(
            self.sink, self.settings, safety=safety, feedback=feedback
        )

    def feed(self, yaw: float = 0.0, pitch: float = 0.0, *, dt: float = FRAME, conf: float = 1.0):
        """One new observation, taken ``dt`` seconds after the previous one."""
        self.t += dt
        sample = HeadPoseSignal(self.t, yaw, pitch, 0.0, conf)
        return self.ctl.update(sample, self.t)

    def idle(self, dt: float):
        """Time passes with no new observation; the runner still ticks."""
        self.t += dt
        return self.ctl.update(None, self.t)

    def reread(self, sample: HeadPoseSignal, dt: float = 0.001):
        """The runner polls again before the camera has produced anything new."""
        self.t += dt
        return self.ctl.update(sample, self.t)

    def centre(self):
        """The first sample: it is only observed, and becomes the neutral pose."""
        return self.feed(0.0, 0.0)

    @property
    def moves(self) -> list[PointerAction]:
        return [a for a in self.sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE]

    @property
    def clicks(self) -> int:
        return sum(1 for a in self.sink.actions if a.kind is PointerActionKind.BUTTON_PRESS)

    def total(self) -> tuple[float, float]:
        return (sum(a.x for a in self.moves), sum(a.y for a in self.moves))


# --------------------------------------------------------------------------- #
# The mapping itself
# --------------------------------------------------------------------------- #


def test_the_first_sample_is_only_observed_and_becomes_the_neutral_pose():
    rig = Rig()
    step = rig.feed(0.4, -0.2)  # a user who starts the feature looking off to one side
    assert step.state is State.TRACKING
    assert rig.sink.actions == []  # not one move, however far from "zero" it was
    # ...and that pose is now straight ahead.
    rig.feed(0.4, -0.2)
    assert rig.sink.actions == []


def test_deviation_from_neutral_moves_by_the_existing_pure_mapping():
    rig = Rig()
    rig.centre()
    rig.feed(0.05, 0.03)
    expected = pose_to_cursor(0.05, 0.03)
    assert rig.moves == [PointerAction.move_relative(round(expected[0]), round(expected[1]))]


def test_the_mapping_is_relative_to_the_neutral_not_to_zero():
    rig = Rig()
    rig.feed(0.3, 0.3)  # neutral is (0.3, 0.3)
    rig.feed(0.35, 0.3)
    expected_dx = round(pose_to_cursor(0.05, 0.0)[0])
    assert rig.moves == [PointerAction.move_relative(expected_dx, 0)]


def test_a_pose_inside_the_deadzone_never_moves_the_pointer():
    rig = Rig()
    rig.centre()
    for i in range(300):
        jitter = 0.019 * math.sin(i)  # strictly inside the 0.02 dead zone
        rig.feed(jitter, -jitter)
    assert rig.sink.actions == []


def test_the_sink_only_ever_receives_whole_units():
    rig = Rig(calib=PointerCalib(x_gain=10.0, y_gain=10.0, deadzone=0.02))
    rig.centre()
    for _ in range(40):
        rig.feed(0.033, 0.027)
    assert rig.moves
    assert all(float(a.x).is_integer() and float(a.y).is_integer() for a in rig.moves)


# --------------------------------------------------------------------------- #
# Sub-unit motion: the consumer accumulates, because the backends disagree
# --------------------------------------------------------------------------- #


class RoundingSink(FakePointerSink):
    """Models the X11 backend: round each call half away from zero, carry nothing."""

    def move_relative(self, dx: float, dy: float) -> None:
        def r(v: float) -> float:
            return math.copysign(math.floor(abs(v) + 0.5), v)

        super().move_relative(r(dx), r(dy))


def test_slow_motion_under_half_a_unit_per_frame_still_moves_a_rounding_backend():
    """0.3 units per frame is *nothing* to X11 unless the consumer carries the remainder."""
    calib = PointerCalib(x_gain=10.0, y_gain=10.0, deadzone=0.02)
    per_frame = pose_to_cursor(0.03, 0.0, calib)[0]
    assert 0.0 < per_frame < 0.5  # the premise: each frame alone would round to zero

    rig = Rig(calib=calib, sink=RoundingSink())
    rig.centre()
    for _ in range(100):
        rig.feed(0.03, 0.0)

    # 100 frames * 0.3 = 30 units of intended motion. An unaccumulated rounding sink
    # would have received 100 calls of 0.3 and moved 0; the consumer's remainder delivers it.
    assert rig.total()[0] == 30.0
    assert rig.total()[1] == 0.0


def test_the_same_slow_head_motion_gives_the_same_total_on_every_backend():
    calib = PointerCalib(x_gain=10.0, y_gain=10.0, deadzone=0.02)
    exact, rounding = Rig(calib=calib), Rig(calib=calib, sink=RoundingSink())
    for rig in (exact, rounding):
        rig.centre()
        for _ in range(60):
            rig.feed(0.03, -0.0234)
    assert exact.total() == rounding.total()


def test_a_remainder_does_not_survive_an_interruption():
    """A fraction of the last session's motion must not leak into the next burst."""
    calib = PointerCalib(x_gain=10.0, y_gain=10.0, deadzone=0.02)
    rig = Rig(calib=calib)
    rig.centre()
    rig.feed(0.03, 0.0)  # 0.3 owed, nothing emitted
    rig.feed(0.03, 0.0)  # 0.6 -> 1 emitted, residual -0.4
    emitted_before = rig.total()[0]
    rig.ctl.pause()
    rig.ctl.resume()
    rig.feed(0.0, 0.0)  # settling frame
    rig.feed(0.03, 0.0)  # starts from a clean 0.3, not from -0.4 + 0.3
    assert rig.total()[0] == emitted_before  # 0.3 alone rounds to nothing


# --------------------------------------------------------------------------- #
# Signal loss freezes motion; it never repeats the last delta
# --------------------------------------------------------------------------- #


def test_no_sample_at_all_produces_no_motion():
    rig = Rig()
    rig.centre()
    rig.feed(0.05)
    sent = len(rig.sink.actions)
    for _ in range(30):
        step = rig.idle(FRAME)
        assert step.state is State.LOST
    assert len(rig.sink.actions) == sent


def test_a_stale_sample_never_moves_the_pointer_again():
    """The runner polls faster than the camera: the same observation must act exactly once."""
    rig = Rig()
    rig.centre()
    sample = HeadPoseSignal(rig.t + FRAME, 0.05, 0.0, 0.0, 1.0)
    rig.t += FRAME
    rig.ctl.update(sample, rig.t)
    assert len(rig.moves) == 1
    for _ in range(10):  # polled again and again while the camera produces nothing new
        rig.reread(sample)
    assert len(rig.moves) == 1  # not 11: re-reading is not re-moving


def test_a_sample_older_than_the_freshness_window_is_no_signal():
    rig = Rig(freshness_s=0.5)
    rig.centre()
    sample = HeadPoseSignal(rig.t + FRAME, 0.05, 0.0, 0.0, 1.0)
    # The runner reads it 0.6 s after it was observed: the camera went blind meanwhile.
    step = rig.ctl.update(sample, rig.t + 0.6)
    assert step.state is State.LOST
    assert rig.sink.actions == []


def test_a_low_confidence_sample_is_no_signal():
    rig = Rig()
    rig.centre()
    step = rig.feed(0.05, conf=0.2)
    assert step.state is State.LOST
    assert rig.sink.actions == []


def test_a_sample_from_the_future_is_a_clock_fault_not_a_pose():
    rig = Rig()
    rig.centre()
    rig.t += FRAME
    future = HeadPoseSignal(rig.t + 5.0, 0.3, 0.0, 0.0, 1.0)
    assert rig.ctl.update(future, rig.t).state is State.LOST
    assert rig.sink.actions == []


def test_recovery_after_loss_does_not_replay_the_last_delta():
    rig = Rig()
    rig.centre()
    rig.feed(0.05)  # the pointer was moving...
    moves_before = len(rig.moves)
    rig.idle(1.0)  # ...and the camera went away for a second
    # It returns, with the head still turned: the first frame back is only observed.
    step = rig.feed(0.05)
    assert step.state is State.TRACKING and step.reason == "settling"
    assert len(rig.moves) == moves_before
    rig.feed(0.05)  # now it is following again, from the same neutral pose
    assert len(rig.moves) == moves_before + 1


def test_loss_resets_a_dwell_that_was_one_frame_from_firing():
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    rig.feed(0.05)  # travel past the radius: armed, first dwell frame
    for _ in range(3):
        rig.feed(0.0)  # 2, 3, 4 of 5 -- the next still frame would have clicked
    assert rig.clicks == 0
    rig.idle(1.0)
    for _ in range(3):
        rig.feed(0.0)  # back, and holding still
    assert rig.clicks == 0  # it must not complete on the first frames after recovery


# --------------------------------------------------------------------------- #
# Dwell-click: exactly one click, never a phantom one
# --------------------------------------------------------------------------- #


def _move_out_and_hold_still(rig: Rig, frames: int) -> None:
    rig.feed(0.05)  # travel well past the 15 px radius
    for _ in range(frames):
        rig.feed(0.0)


def test_dwell_clicks_exactly_once_after_a_stable_hold():
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    _move_out_and_hold_still(rig, 4)
    assert rig.clicks == 1
    assert rig.sink.actions[-2:] == [
        PointerAction.press(PointerButton.LEFT),
        PointerAction.release(PointerButton.LEFT),
    ]


def test_resting_after_a_click_does_not_click_again():
    """Hold still for a hundred frames: one click, not one every five."""
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    _move_out_and_hold_still(rig, 100)
    assert rig.clicks == 1


def test_moving_again_re_arms_it_for_exactly_one_more():
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    _move_out_and_hold_still(rig, 20)
    _move_out_and_hold_still(rig, 20)
    assert rig.clicks == 2


def test_dwell_progress_is_visible_before_the_click_fires():
    shown: list[float] = []
    hidden: list[int] = []

    class Feedback:
        def show(self, progress: float) -> None:
            shown.append(progress)

        def hide(self) -> None:
            hidden.append(1)

    rig = Rig(dwell=True, hold=5, feedback=Feedback())
    rig.centre()
    rig.feed(0.05)
    for _ in range(3):
        rig.feed(0.0)
        assert rig.clicks == 0
    assert shown and shown == sorted(shown)  # it climbed, on screen, ahead of the click
    assert 0.0 < shown[-1] < 1.0
    assert rig.ctl.status().dwell_progress == shown[-1]
    assert not hidden
    rig.feed(0.0)  # the frame that fires
    assert rig.clicks == 1
    assert hidden  # and the indicator is withdrawn when it does


def test_dwell_feedback_that_raises_cannot_break_the_pointer():
    class Broken:
        def show(self, progress: float) -> None:
            raise RuntimeError("overlay is gone")

        def hide(self) -> None:
            raise RuntimeError("overlay is gone")

    rig = Rig(dwell=True, hold=5, feedback=Broken())
    rig.centre()
    _move_out_and_hold_still(rig, 4)
    assert rig.clicks == 1


def test_dwell_disabled_never_clicks_however_long_the_pointer_rests():
    rig = Rig(dwell=False, hold=2)
    rig.centre()
    _move_out_and_hold_still(rig, 200)
    assert rig.clicks == 0
    assert rig.moves  # motion still works: dwell is an independent switch
    assert rig.ctl.status().dwell_progress == 0.0


def test_dwell_can_be_switched_off_and_on_while_running():
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    rig.feed(0.05)
    rig.ctl.set_dwell_enabled(False)
    for _ in range(50):
        rig.feed(0.0)
    assert rig.clicks == 0
    rig.ctl.set_dwell_enabled(True)
    _move_out_and_hold_still(rig, 20)  # needs fresh travel to arm again
    assert rig.clicks == 1


# --- the phantom-click cases the Phase 4 exit gate names ----------------------------------


def test_no_click_on_startup_however_still_the_user_sits():
    """The dwell detector counts frames of stillness; a pointer that has not moved is still."""
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    for _ in range(500):
        rig.feed(0.0, 0.0)
    assert rig.clicks == 0


def test_no_click_from_jitter_inside_the_deadzone():
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    for i in range(1000):
        rig.feed(0.015 * math.sin(i * 0.7), 0.015 * math.cos(i * 1.3))
    assert rig.clicks == 0


def test_no_click_from_jitter_that_keeps_the_pointer_moving():
    """Noise past the dead zone moves the pointer beyond the radius every frame: not a dwell."""
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    for i in range(1000):
        rig.feed(0.05 if i % 2 else -0.05, 0.0)
    assert rig.moves  # it really was moving
    assert rig.clicks == 0


def test_no_click_when_recovering_from_signal_loss_into_a_still_head():
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    rig.feed(0.05)
    rig.idle(2.0)
    for _ in range(100):
        rig.feed(0.0)
    assert rig.clicks == 0  # the user never moved again after coming back


def test_no_click_when_a_fresh_start_follows_a_long_still_period():
    rig = Rig(dwell=True, hold=5)
    for _ in range(100):
        rig.feed(0.0)
    assert rig.clicks == 0


# --------------------------------------------------------------------------- #
# Pause, clutch, recenter
# --------------------------------------------------------------------------- #


def test_pause_stops_motion_and_clicks_and_clears_the_dwell():
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    rig.feed(0.05)
    rig.feed(0.0)
    rig.ctl.pause()
    sent = len(rig.sink.actions)
    for _ in range(100):
        step = rig.feed(0.3, 0.3)  # a vigorous head, and a dwell that would have fired
        assert step.state is State.PAUSED
    assert len(rig.sink.actions) == sent
    assert rig.ctl.status().dwell_progress == 0.0 and rig.ctl.status().paused


def test_resume_never_moves_or_clicks_on_its_own_first_frame():
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    rig.ctl.pause()
    rig.feed(0.3)
    assert rig.ctl.resume().ok
    sent = len(rig.sink.actions)
    step = rig.feed(0.3)  # head still turned, as it was when paused
    assert step.reason == "settling"
    assert len(rig.sink.actions) == sent
    for _ in range(50):  # the head comes back and rests; nothing travelled, so nothing dwells
        rig.feed(0.0)
    assert rig.clicks == 0


def test_pause_is_idempotent_and_resume_without_pause_is_harmless():
    rig = Rig()
    rig.centre()
    rig.ctl.pause()
    rig.ctl.pause()
    assert rig.ctl.resume().ok
    assert rig.ctl.resume().ok


def test_a_held_clutch_freezes_motion_and_dwell_without_pausing_the_feature():
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    rig.feed(0.05)
    rig.ctl.set_clutch("face-gesture", True)
    sent = len(rig.sink.actions)
    for _ in range(100):
        step = rig.feed(0.3, -0.3)
        assert step.state is State.CLUTCHED
    assert len(rig.sink.actions) == sent
    assert rig.ctl.status().paused is False
    assert rig.ctl.status().clutched is True


def test_the_pointer_stays_frozen_until_every_clutch_has_been_released():
    rig = Rig()
    rig.centre()
    rig.ctl.set_clutch("key", True)
    rig.ctl.set_clutch("face", True)
    rig.ctl.set_clutch("key", False)
    assert rig.feed(0.3).state is State.CLUTCHED
    rig.ctl.set_clutch("face", False)
    assert rig.feed(0.3).reason == "settling"  # released: observed first, never a jump
    assert rig.sink.actions == []
    rig.feed(0.3)
    assert len(rig.moves) == 1


def test_releasing_a_clutch_nobody_held_is_harmless():
    rig = Rig()
    rig.centre()
    rig.ctl.set_clutch("ghost", False)
    assert rig.ctl.status().clutched is False


def test_recenter_makes_the_current_pose_zero_with_no_motion_and_no_click():
    rig = Rig(dwell=True, hold=5)
    rig.centre()
    rig.feed(0.05)
    rig.feed(0.0)
    rig.feed(0.0)  # a dwell is building
    sent = len(rig.sink.actions)
    rig.ctl.recenter()
    assert rig.ctl.status().dwell_progress == 0.0  # the candidate is dropped at once
    step = rig.feed(0.4, 0.3)  # the user has shifted in their chair
    assert step.reason == "centred"
    assert len(rig.sink.actions) == sent  # capturing the pose moved nothing
    for _ in range(50):
        rig.feed(0.4, 0.3)  # holding the new pose is the new "straight ahead"
    assert len(rig.sink.actions) == sent
    assert rig.clicks == 0
    rig.feed(0.45, 0.3)  # and motion is now measured from it
    assert rig.moves[-1] == PointerAction.move_relative(round(pose_to_cursor(0.05, 0.0)[0]), 0)


def test_recenter_with_no_signal_waits_for_the_next_valid_pose():
    rig = Rig()
    rig.centre()
    rig.ctl.recenter()
    rig.idle(1.0)
    rig.idle(1.0)
    assert rig.ctl.status().calibrated is False
    rig.feed(0.2)
    assert rig.ctl.status().calibrated is True
    assert rig.sink.actions == []


def test_recenter_while_paused_is_deferred_not_lost_and_never_acts():
    rig = Rig()
    rig.centre()
    rig.ctl.pause()
    rig.ctl.recenter()
    rig.feed(0.5)
    assert rig.ctl.resume().ok
    # The capture frame doubles as the settling frame: observed, never acted on.
    assert rig.feed(0.5).reason == "centred"
    rig.feed(0.5)
    assert rig.sink.actions == []


# --------------------------------------------------------------------------- #
# The global hands-free gate always wins
# --------------------------------------------------------------------------- #


class GateRig(Rig):
    """A rig whose controller consults a real ``HandsFreeSafety`` on the rig's clock."""

    def __init__(self, **kw) -> None:
        self.gate = HandsFreeSafety(("headpointer",), clock=lambda: self.t * 1000.0)
        super().__init__(safety=self.gate, **kw)

    def arm(self) -> None:
        """Deliver a sample, then arm explicitly -- the order the gate's contract requires."""
        self.feed(0.0)
        assert self.ctl.resume().ok, self.gate.status()


def test_with_the_gate_on_nothing_acts_until_the_user_arms_it():
    rig = GateRig(dwell=True, hold=5)
    for _ in range(30):
        step = rig.feed(0.3)
        assert step.state is State.SUPPRESSED
    assert rig.sink.actions == []


def test_once_armed_the_pointer_follows_the_head():
    rig = GateRig()
    rig.arm()
    rig.feed(0.0)  # settle
    rig.feed(0.0)  # neutral captured
    rig.feed(0.05)
    assert len(rig.moves) == 1


def test_a_global_pause_stops_all_motion_and_clicks():
    rig = GateRig(dwell=True, hold=5)
    rig.arm()
    rig.feed(0.0)
    rig.feed(0.0)
    rig.feed(0.05)
    rig.feed(0.0)  # a dwell is building
    rig.gate.pause("panic stop")
    sent = len(rig.sink.actions)
    for _ in range(100):
        step = rig.feed(0.3, 0.3)
        assert step.state is State.SUPPRESSED
        assert "panic stop" in step.reason
    assert len(rig.sink.actions) == sent


def test_a_global_shutdown_is_terminal_and_stops_everything():
    rig = GateRig(dwell=True, hold=5)
    rig.arm()
    rig.feed(0.0)
    rig.feed(0.0)
    rig.gate.shutdown()
    sent = len(rig.sink.actions)
    for _ in range(20):
        rig.feed(0.3)
    assert len(rig.sink.actions) == sent
    assert rig.ctl.resume().ok is False  # a stopped daemon cannot be re-armed


def test_a_gate_that_goes_stale_disarms_and_recovery_needs_an_explicit_resume():
    rig = GateRig(dwell=True, hold=5)
    rig.arm()
    rig.feed(0.0)
    rig.feed(0.0)
    rig.feed(0.05)
    moves = len(rig.moves)
    rig.idle(0.8)  # past the gate's 500 ms window
    rig.idle(0.1)
    # The camera flickers back with the head turned. Nothing moves: it was disarmed.
    for _ in range(30):
        step = rig.feed(0.3)
        assert step.state is State.SUPPRESSED
    assert len(rig.moves) == moves
    assert rig.ctl.resume().ok
    rig.feed(0.3)  # settling
    rig.feed(0.3)
    assert len(rig.moves) == moves + 1


def test_resume_is_refused_with_a_reason_while_there_is_no_fresh_signal():
    rig = GateRig()
    result = rig.ctl.resume()
    assert result.ok is False and "headpointer" in result.reason


def test_the_gate_clear_pending_latch_drops_a_half_built_dwell():
    rig = GateRig(dwell=True, hold=5)
    rig.arm()
    rig.feed(0.0)
    rig.feed(0.0)
    rig.feed(0.05)
    rig.feed(0.0)
    rig.feed(0.0)
    assert rig.ctl.status().dwell_progress > 0.0
    rig.gate.pause()
    rig.feed(0.0)
    assert rig.ctl.status().dwell_progress == 0.0


# --------------------------------------------------------------------------- #
# A failing pointer backend stops the feature, not the daemon
# --------------------------------------------------------------------------- #


def test_a_failing_sink_faults_the_controller_and_nothing_is_retried_or_replayed():
    rig = Rig()
    rig.centre()
    rig.sink.fail_with(PointerBackendError("compositor went away"))
    step = rig.feed(0.05)
    assert step.state is State.FAULTED and "compositor went away" in step.reason
    rig.sink.clear_failure()  # the backend comes back by itself...
    for _ in range(30):
        rig.feed(0.05)
    assert rig.sink.actions == []  # ...and still nothing moves: only resume() clears a fault


def test_resume_clears_a_fault_and_the_pointer_works_again():
    rig = Rig()
    rig.centre()
    rig.sink.fail_with()
    rig.feed(0.05)
    rig.sink.clear_failure()
    assert rig.ctl.resume().ok
    rig.feed(0.05)  # settling
    rig.feed(0.05)
    assert len(rig.moves) == 1


def test_a_failed_click_is_not_retried_and_faults_the_feature():
    rig = Rig(dwell=True, hold=3)
    rig.centre()
    rig.feed(0.05)
    rig.feed(0.0)
    original = rig.sink.click

    def broken(button=PointerButton.LEFT):
        raise PointerBackendError("button refused")

    rig.sink.click = broken  # type: ignore[method-assign]
    step = rig.feed(0.0)
    assert step.state is State.FAULTED
    rig.sink.click = original  # type: ignore[method-assign]
    for _ in range(30):
        rig.feed(0.0)
    assert rig.clicks == 0


def test_a_sink_failure_is_reported_to_the_global_gate():
    rig = GateRig()
    rig.arm()
    rig.feed(0.0)
    rig.feed(0.0)
    rig.sink.fail_with()
    rig.feed(0.05)
    health = rig.gate.status().source("headpointer")
    assert health is not None and health.faulted


def test_a_non_finite_gain_cannot_poison_the_controller():
    calib = PointerCalib(x_gain=float("nan"), y_gain=float("inf"), deadzone=float("nan"))
    rig = Rig(calib=calib)
    rig.centre()
    rig.feed(0.05, 0.05)
    assert all(math.isfinite(a.x) and math.isfinite(a.y) for a in rig.moves)


# --------------------------------------------------------------------------- #
# Lifecycle and observability
# --------------------------------------------------------------------------- #


def test_close_releases_the_sink_once_and_stops_acting():
    rig = Rig()
    rig.centre()
    rig.ctl.close()
    rig.ctl.close()
    assert rig.sink.closed
    assert rig.sink.actions.count(PointerAction.close()) == 1
    assert rig.feed(0.5).state is State.CLOSED


def test_status_reports_states_and_flags_but_no_pose_or_position():
    rig = Rig(dwell=True)
    rig.centre()
    rig.feed(0.3, 0.2)
    status = rig.ctl.status()
    assert status.state is State.TRACKING and status.calibrated
    assert status.backend == "fake"
    # A privacy guard: nothing on the snapshot can carry an angle or a screen position.
    fields = set(status.__dataclass_fields__)
    assert fields.isdisjoint({"yaw", "pitch", "roll", "x", "y", "position", "neutral", "pose"})
    assert not any("0.3" in str(v) for v in vars(status).values())
