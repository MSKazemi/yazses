"""The Head-Pointer motion model is in real time: camera frame rate must not change the speed.

Before this, ``x_gain``/``y_gain`` meant "pointer units per *sample* per radian", so a 30 fps
camera moved the pointer twice as far per second as a 15 fps one from the identical head pose,
and with the old magnitudes a held 0.3 rad turn ran away at thousands of units per second.
The model now is rate control: the head's offset sets a *velocity* (units per second per
radian), the velocity is capped per axis and overall (units per second), and a sample moves the
pointer by velocity x the real time since the previous accepted sample, clamped to a maximum so
a stall becomes one bounded step.

Every test drives numbers (a ``HeadPoseSignal`` and a clock the test advances by hand) into the
real controller with ``tests/pointer_fake.py``'s recording sink: no camera, no real pointer.

**No number here is a recommendation.** The default gains and caps are provisional
first-principles safety limits (the tests pin their *properties* -- positive, finite, the
config and the pure core agree, a held comfortable turn is nowhere near the old runaway -- not
their values), and the traces are synthetic. What these tests prove is the arithmetic of the
model and that every guarantee the state machine already made still holds under it.
"""
from __future__ import annotations

import logging
import math

import pytest

from tests.pointer_fake import FakePointerSink, PointerActionKind
from yazses.config import HeadpointerConfig
from yazses.handsfree.safety import HandsFreeSafety
from yazses.headpointer.controller import (
    DEFAULT_MAX_DT_S,
    HeadPointerController,
    HeadPointerSettings,
    State,
)
from yazses.headpointer.pointer import PointerCalib, elapsed_s, limit_velocity, pose_to_cursor
from yazses.headpointer.runtime import settings_from_config
from yazses.perception.signals import HeadPoseSignal

# A calibration with round numbers so the expected displacement is exact arithmetic.
CALIB = PointerCalib(
    x_gain=-1000.0, y_gain=500.0, deadzone=0.02,
    max_speed_x=400.0, max_speed_y=300.0, max_speed_overall=450.0,
)
# Same gains, caps out of the way: for the tests that are about time, not about the caps.
UNCAPPED = PointerCalib(
    x_gain=-1000.0, y_gain=500.0, deadzone=0.02,
    max_speed_x=1e9, max_speed_y=1e9, max_speed_overall=1e9,
)


class Rig:
    """A controller, a recording sink and a clock the test moves by hand."""

    def __init__(self, calib: PointerCalib = UNCAPPED, *, safety=None, **settings) -> None:
        self.t = 100.0
        self.sink = FakePointerSink()
        self.ctl = HeadPointerController(
            self.sink, HeadPointerSettings(calib=calib, **settings), safety=safety
        )

    def feed(self, yaw: float = 0.0, pitch: float = 0.0, *, dt: float):
        """One observation ``dt`` seconds after the previous one."""
        self.t += dt
        return self.ctl.update(HeadPoseSignal(self.t, yaw, pitch, 0.0, 1.0), self.t)

    def idle(self, dt: float):
        self.t += dt
        return self.ctl.update(None, self.t)

    @property
    def moves(self):
        return [a for a in self.sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE]

    def total(self) -> tuple[float, float]:
        return (sum(a.x for a in self.moves), sum(a.y for a in self.moves))


def hold(rig: Rig, fps: int, seconds: float, yaw: float, pitch: float = 0.0) -> None:
    """Centre, then hold one pose for ``seconds`` of camera time at ``fps``."""
    dt = 1.0 / fps
    rig.feed(0.0, 0.0, dt=dt)  # the first sample: observed, becomes the neutral pose
    for _ in range(round(seconds * fps)):
        rig.feed(yaw, pitch, dt=dt)


# --------------------------------------------------------------------------- #
# Frame-rate independence: the point of the whole change
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_a_held_pose_moves_the_pointer_velocity_times_time_at_any_frame_rate(fps):
    rig = Rig()
    hold(rig, fps, seconds=4.0, yaw=0.1, pitch=-0.1)
    # velocity = gain x angle: x -1000 * 0.1 = -100 u/s, y 500 * -0.1 = -50 u/s
    dx, dy = rig.total()
    assert dx == pytest.approx(-100.0 * 4.0, abs=1.0)  # remainder is carried: within a unit
    assert dy == pytest.approx(-50.0 * 4.0, abs=1.0)


def test_the_same_head_motion_gives_the_same_displacement_at_15_30_and_60_fps():
    totals = {}
    for fps in (15, 30, 60):
        rig = Rig()
        hold(rig, fps, seconds=2.0, yaw=0.05, pitch=0.2)
        totals[fps] = rig.total()
    for fps in (30, 60):
        assert totals[fps][0] == pytest.approx(totals[15][0], abs=1.0)
        assert totals[fps][1] == pytest.approx(totals[15][1], abs=1.0)
    assert totals[15][0] != 0 and totals[15][1] != 0  # the comparison is not vacuous


def test_a_ramping_head_gives_a_frame_rate_independent_displacement_too():
    """A moving head, not just a held one. Integration error is O(dt), so allow a few units."""
    def run(fps: int) -> float:
        rig = Rig()
        dt = 1.0 / fps
        rig.feed(0.0, 0.0, dt=dt)
        for k in range(1, round(3.0 * fps) + 1):
            rig.feed(0.1 * (k * dt) / 3.0, 0.0, dt=dt)  # 0 -> 0.1 rad over 3 s
        return rig.total()[0]

    ref = run(120)
    for fps in (15, 30, 60):
        assert run(fps) == pytest.approx(ref, abs=0.1 * abs(ref))
    assert ref < -100  # it did move, and in the geometry-correct direction (negative x gain)


def test_the_displacement_is_not_proportional_to_the_number_of_samples():
    """The old per-sample model failed exactly this: 4x the frames gave 4x the distance."""
    slow, fast = Rig(), Rig()
    hold(slow, 15, seconds=2.0, yaw=0.1)
    hold(fast, 60, seconds=2.0, yaw=0.1)
    assert len(fast.moves) > 3 * len(slow.moves)  # 4x the samples...
    assert fast.total()[0] == pytest.approx(slow.total()[0], abs=1.0)  # ...the same distance


def test_the_runner_polling_faster_than_the_camera_does_not_change_the_distance():
    """Re-reading the same observation is not a new sample, so it adds no time and no motion."""
    once, rereads = Rig(), Rig()
    dt = 1.0 / 15
    for rig, extra in ((once, 0), (rereads, 3)):
        camera = rig.t  # the camera's own clock; the poll clock runs a little ahead of it
        rig.feed(0.0, 0.0, dt=dt)
        camera = rig.t
        for _ in range(30):
            camera += dt
            sample = HeadPoseSignal(camera, 0.1, 0.0, 0.0, 1.0)
            rig.ctl.update(sample, camera)
            for k in range(1, extra + 1):
                rig.ctl.update(sample, camera + 0.001 * k)
    assert rereads.total() == once.total()


# --------------------------------------------------------------------------- #
# dt is the real gap between accepted samples, clamped
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("stall_s", [0.4, 1.0, 10.0, 3600.0])
def test_a_stall_yields_at_most_one_clamped_step(stall_s):
    """The runner thread blocked, or the camera hiccuped: the next sample is stall_s later."""
    rig = Rig(freshness_s=1e9)  # the sample is fresh by its own clock; only dt is on trial
    dt = 1.0 / 30
    rig.feed(0.0, 0.0, dt=dt)
    rig.feed(0.1, 0.0, dt=dt)
    before = len(rig.moves)
    step = rig.feed(0.1, 0.0, dt=stall_s)
    assert step.state is State.TRACKING
    assert len(rig.moves) - before <= 1
    # velocity -100 u/s for at most max_dt_s: never stall_s' worth.
    assert abs(rig.moves[-1].x) <= 100.0 * DEFAULT_MAX_DT_S + 1.0


def test_the_clamp_is_exactly_max_dt_times_velocity():
    rig = Rig(max_dt_s=0.2, freshness_s=1e9)
    rig.feed(0.0, 0.0, dt=1 / 30)
    rig.feed(0.1, 0.0, dt=1 / 30)
    n = len(rig.moves)
    rig.feed(0.1, 0.0, dt=5.0)
    assert [a.x for a in rig.moves[n:]] == [-20.0]  # -100 u/s x 0.2 s


def test_dt_is_measured_from_the_last_accepted_sample_not_from_before_a_gap():
    """After a signal loss the settling frame absorbs the gap; the next step is one frame."""
    rig = Rig()
    dt = 1 / 30
    rig.feed(0.0, 0.0, dt=dt)
    rig.feed(0.1, 0.0, dt=dt)
    for _ in range(40):
        assert rig.idle(dt).state is State.LOST  # >1 s of nothing
    sent = len(rig.moves)
    step = rig.feed(0.1, 0.0, dt=dt)  # the camera is back
    assert step.state is State.TRACKING and step.reason == "settling"
    assert len(rig.moves) == sent  # the first sample after the loss moves nothing
    rig.feed(0.1, 0.0, dt=dt)
    assert rig.moves[sent:] and rig.moves[sent].x == pytest.approx(-100.0 * dt, abs=1.0)
    assert abs(rig.total()[0] - sum(a.x for a in rig.moves[:sent])) <= 5.0


def test_a_repeated_or_backwards_timestamp_moves_nothing():
    rig = Rig()
    dt = 1 / 30
    rig.feed(0.0, 0.0, dt=dt)
    rig.feed(0.1, 0.0, dt=dt)
    sent = len(rig.moves)
    same = HeadPoseSignal(rig.t, 0.1, 0.0, 0.0, 1.0)
    earlier = HeadPoseSignal(rig.t - 0.01, 0.3, 0.0, 0.0, 1.0)
    for sample in (same, earlier):
        rig.t += 0.001
        rig.ctl.update(sample, rig.t)
    assert len(rig.moves) == sent


@pytest.mark.parametrize(
    "prev,now",
    [
        (5.0, 5.0),  # zero
        (5.0, 4.0),  # negative
        (5.0, math.nan),
        (math.nan, 5.0),
        (-math.inf, 5.0),  # "no previous sample"
        (5.0, math.inf),
        (math.inf, math.inf),
    ],
)
def test_elapsed_time_is_zero_when_it_is_not_a_real_positive_gap(prev, now):
    assert elapsed_s(prev, now) == 0.0


def test_elapsed_time_is_the_real_gap_up_to_the_clamp():
    assert elapsed_s(10.0, 10.04) == pytest.approx(0.04)
    assert elapsed_s(10.0, 99.0) == DEFAULT_MAX_DT_S
    assert elapsed_s(10.0, 99.0, 1.5) == 1.5
    assert elapsed_s(10.0, 10.5, 1.5) == pytest.approx(0.5)
    for bad in (0.0, -1.0, math.nan, math.inf):
        assert elapsed_s(10.0, 10.1, bad) == 0.0  # an unusable clamp moves nothing


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_an_unusable_max_dt_setting_falls_back_to_the_default_clamp(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="yazses.headpointer.controller"):
        rig = Rig(max_dt_s=bad, freshness_s=1e9)
    rig.feed(0.0, 0.0, dt=1 / 30)
    rig.feed(0.1, 0.0, dt=1 / 30)
    n = len(rig.moves)
    rig.feed(0.1, 0.0, dt=60.0)
    assert [a.x for a in rig.moves[n:]] == [-100.0 * DEFAULT_MAX_DT_S]
    assert any("max_dt_s" in r.getMessage() for r in caplog.records)


# --------------------------------------------------------------------------- #
# Speed caps
# --------------------------------------------------------------------------- #


def test_limit_velocity_is_the_identity_below_every_cap():
    assert limit_velocity(100.0, -50.0, CALIB) == (100.0, -50.0)
    assert limit_velocity(0.0, 0.0, CALIB) == (0.0, 0.0)


def test_each_axis_is_capped_on_its_own_and_the_sign_survives():
    assert limit_velocity(-9000.0, 0.0, CALIB) == (-400.0, 0.0)
    assert limit_velocity(9000.0, 0.0, CALIB) == (400.0, 0.0)
    assert limit_velocity(0.0, 9000.0, CALIB) == (0.0, 300.0)
    assert limit_velocity(0.0, -9000.0, CALIB) == (0.0, -300.0)


def test_the_overall_cap_scales_the_vector_and_keeps_its_direction():
    vx, vy = limit_velocity(400.0, 300.0, CALIB)  # inside both axis caps, speed 500 > 450
    assert math.hypot(vx, vy) == pytest.approx(450.0)
    assert vx / vy == pytest.approx(400.0 / 300.0)  # the same heading, not bent to an axis
    vx, vy = limit_velocity(-9000.0, 9000.0, CALIB)  # both axes clipped, then scaled
    assert math.hypot(vx, vy) == pytest.approx(450.0)
    assert vx < 0 < vy


def test_a_non_finite_velocity_is_passed_through_for_the_finiteness_guard():
    vx, _ = limit_velocity(math.nan, 1.0, CALIB)
    assert math.isnan(vx)


@pytest.mark.parametrize("fps", [15, 30, 60])
def test_an_extreme_pose_never_exceeds_the_speed_caps(fps):
    rig = Rig(CALIB)
    hold(rig, fps, seconds=2.0, yaw=-3.0, pitch=3.0)  # a pose that asks for ~1500 u/s
    dx, dy = rig.total()
    # Axes clip to (400, 300) u/s (speed 500), then the overall cap scales that to 450 u/s
    # along the same heading: (360, 270) u/s. Over 2 s, at every frame rate:
    assert dx == pytest.approx(360.0 * 2.0, abs=2.0)  # +x: yaw -3 against a negative gain
    assert dy == pytest.approx(270.0 * 2.0, abs=2.0)
    assert math.hypot(dx, dy) <= 450.0 * 2.0 + 1.0


def test_a_single_step_is_never_longer_than_cap_times_the_frame_gap():
    rig = Rig(CALIB)
    dt = 1 / 30
    rig.feed(0.0, 0.0, dt=dt)
    for _ in range(60):
        rig.feed(-3.0, 3.0, dt=dt)
    assert max(math.hypot(a.x, a.y) for a in rig.moves) <= 450.0 * dt + 1.0


def test_the_cap_is_the_bound_even_when_a_stall_meets_an_extreme_pose():
    rig = Rig(CALIB, freshness_s=1e9)
    rig.feed(0.0, 0.0, dt=1 / 30)
    rig.feed(-3.0, 3.0, dt=1 / 30)
    n = len(rig.moves)
    rig.feed(-3.0, 3.0, dt=3600.0)
    step = rig.moves[n]
    assert math.hypot(step.x, step.y) <= 450.0 * DEFAULT_MAX_DT_S + 1.0


@pytest.mark.parametrize("bad", [0.0, -5.0, math.nan, math.inf])
def test_a_cap_cannot_be_switched_off_by_a_bad_value(bad, caplog):
    """Zero, negative or non-finite is 'use the shipped cap', never 'unlimited'."""
    calib = PointerCalib(
        x_gain=-1000.0, y_gain=500.0, max_speed_x=bad, max_speed_y=bad, max_speed_overall=bad
    )
    with caplog.at_level(logging.WARNING, logger="yazses.headpointer.controller"):
        rig = Rig(calib)
    hold(rig, 30, seconds=2.0, yaw=-3.0, pitch=3.0)
    dx, dy = rig.total()
    shipped = PointerCalib()
    assert abs(dx) <= shipped.max_speed_x * 2.0 + 1.0
    assert abs(dy) <= shipped.max_speed_y * 2.0 + 1.0
    assert math.hypot(dx, dy) <= shipped.max_speed_overall * 2.0 + 1.0
    assert any("max_speed_overall" in r.getMessage() for r in caplog.records)


def test_non_finite_gains_still_fall_back_and_do_not_poison_the_remainder():
    calib = PointerCalib(x_gain=math.nan, y_gain=math.inf, deadzone=math.nan)
    rig = Rig(calib)
    hold(rig, 30, seconds=1.0, yaw=0.1, pitch=0.1)
    assert all(math.isfinite(a.x) and math.isfinite(a.y) for a in rig.moves)
    assert rig.ctl.status().state is State.TRACKING


# --------------------------------------------------------------------------- #
# The sign semantics and the dead zone are unchanged
# --------------------------------------------------------------------------- #


def test_the_shipped_defaults_keep_the_geometry_of_a_real_webcam():
    calib = settings_from_config(HeadpointerConfig()).calib
    vx_left, _ = pose_to_cursor(+0.3, 0.0, calib)  # head to the user's left: +yaw
    _, vy_up = pose_to_cursor(0.0, -0.3, calib)  # chin up: -pitch
    assert vx_left < 0  # pointer goes left
    assert vy_up < 0  # y grows downward: chin up is pointer up


def test_motion_through_the_controller_follows_the_head_with_the_shipped_defaults():
    rig = Rig(settings_from_config(HeadpointerConfig()).calib)
    hold(rig, 30, seconds=1.0, yaw=+0.15, pitch=-0.1)  # turn left, chin up
    dx, dy = rig.total()
    assert dx < 0 and dy < 0


def test_a_pose_inside_the_deadzone_still_moves_nothing_at_any_frame_rate():
    for fps in (15, 60):
        rig = Rig()
        dt = 1.0 / fps
        rig.feed(0.0, 0.0, dt=dt)
        for i in range(fps * 5):
            jitter = 0.019 * math.sin(i)
            rig.feed(jitter, -jitter, dt=dt)
        assert rig.moves == []


# --------------------------------------------------------------------------- #
# The shipped defaults are safe by construction (properties, not tuned values)
# --------------------------------------------------------------------------- #


def test_the_config_and_the_pure_core_agree_on_the_caps():
    cfg, core = HeadpointerConfig(), PointerCalib()
    assert (cfg.max_speed_x, cfg.max_speed_y, cfg.max_speed_overall) == (
        core.max_speed_x, core.max_speed_y, core.max_speed_overall
    )
    assert (abs(cfg.x_gain), cfg.y_gain) == (core.x_gain, core.y_gain)


def test_the_default_caps_are_finite_positive_and_cross_a_screen_in_a_few_seconds():
    """A safety property, not a tuned value: slow enough to stop, fast enough to be usable."""
    core = PointerCalib()
    for cap in (core.max_speed_x, core.max_speed_y, core.max_speed_overall):
        assert math.isfinite(cap) and cap > 0
    seconds_to_cross = 1920.0 / min(core.max_speed_x, core.max_speed_overall)
    assert 1.0 <= seconds_to_cross <= 10.0


def test_a_held_comfortable_turn_with_the_defaults_is_nowhere_near_the_old_runaway():
    """Observed live: 0.3 rad held moved ~3,700 units per second with the per-sample 800."""
    for fps in (15, 30, 60):
        rig = Rig(settings_from_config(HeadpointerConfig()).calib)
        hold(rig, fps, seconds=4.0, yaw=0.3, pitch=0.3)
        dx, dy = rig.total()
        assert math.hypot(dx, dy) / 4.0 <= PointerCalib().max_speed_overall + 1.0
        assert math.hypot(dx, dy) / 4.0 < 1000.0  # the old number was ~3,700


def test_the_new_config_keys_reach_the_settings_and_junk_falls_back():
    cfg = HeadpointerConfig()
    cfg.max_speed_x, cfg.max_speed_y, cfg.max_speed_overall = 111.0, 222.0, 333.0
    calib = settings_from_config(cfg).calib
    assert (calib.max_speed_x, calib.max_speed_y, calib.max_speed_overall) == (111.0, 222.0, 333.0)
    cfg.max_speed_x = "banana"  # type: ignore[assignment]
    cfg.max_speed_overall = float("nan")  # type: ignore[assignment]
    fallback = settings_from_config(cfg).calib
    assert fallback.max_speed_x == PointerCalib().max_speed_x
    assert fallback.max_speed_overall == PointerCalib().max_speed_overall


# --------------------------------------------------------------------------- #
# The guarantees the state machine already made, under the time-based model
# --------------------------------------------------------------------------- #


def test_the_first_sample_and_the_settling_sample_move_nothing_whatever_the_gap():
    rig = Rig(freshness_s=1e9)
    rig.feed(0.4, -0.2, dt=1.0)  # first sample: the neutral pose
    rig.ctl.pause()
    rig.ctl.resume()
    rig.feed(0.4, -0.2, dt=500.0)  # settling frame, a huge gap before it
    assert rig.sink.actions == []


def test_a_pause_a_clutch_and_signal_loss_each_freeze_the_pointer():
    rig = Rig()
    dt = 1 / 30
    rig.feed(0.0, 0.0, dt=dt)
    rig.feed(0.1, 0.0, dt=dt)
    base = len(rig.moves)
    assert base == 1

    rig.ctl.pause()
    for _ in range(30):
        assert rig.feed(0.3, 0.3, dt=dt).state is State.PAUSED
    rig.ctl.resume()
    rig.ctl.set_clutch("test", True)
    for _ in range(30):
        assert rig.feed(0.3, 0.3, dt=dt).state is State.CLUTCHED
    rig.ctl.set_clutch("test", False)
    for _ in range(30):
        assert rig.idle(dt).state is State.LOST
    assert len(rig.moves) == base  # no motion, and nothing replayed on the way back
    assert rig.feed(0.1, 0.0, dt=dt).reason == "settling"
    assert len(rig.moves) == base


def test_releasing_a_clutch_does_not_integrate_the_time_it_was_held():
    rig = Rig()
    dt = 1 / 30
    rig.feed(0.0, 0.0, dt=dt)
    rig.ctl.set_clutch("switch", True)
    for _ in range(90):  # three seconds held, samples still arriving
        rig.feed(0.2, 0.0, dt=dt)
    rig.ctl.set_clutch("switch", False)
    assert rig.feed(0.2, 0.0, dt=dt).reason == "settling"
    assert rig.moves == []
    rig.feed(0.2, 0.0, dt=dt)
    assert len(rig.moves) <= 1  # one frame's worth, not three seconds'
    assert abs(rig.total()[0]) <= 200.0 * dt + 1.0


def test_a_global_pause_stops_all_motion_under_the_time_based_model():
    gate = HandsFreeSafety(("headpointer",), clock=lambda: rig.t * 1000.0)
    rig = Rig(safety=gate)
    dt = 1 / 30
    rig.feed(0.0, dt=dt)
    assert rig.ctl.resume().ok, gate.status()
    rig.feed(0.0, dt=dt)
    rig.feed(0.0, dt=dt)
    rig.feed(0.1, dt=dt)
    assert rig.moves
    gate.pause("panic stop")
    sent = len(rig.sink.actions)
    for _ in range(100):
        assert rig.feed(0.3, 0.3, dt=dt).state is State.SUPPRESSED
    assert len(rig.sink.actions) == sent


def test_no_click_on_startup_or_after_signal_loss_with_dwell_on():
    rig = Rig(dwell_enabled=True, dwell_hold_frames=3)
    dt = 1 / 30
    for _ in range(40):  # sitting perfectly still after enabling
        rig.feed(0.0, 0.0, dt=dt)
    for _ in range(40):
        rig.idle(dt)
    for _ in range(40):
        rig.feed(0.0, 0.0, dt=dt)
    assert not any(a.kind is PointerActionKind.BUTTON_PRESS for a in rig.sink.actions)
