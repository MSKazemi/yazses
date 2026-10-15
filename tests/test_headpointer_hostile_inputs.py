"""Head-Pointer against the inputs and orderings a tidy fake never produces (#404, ADR-v2-052).

``tests/test_headpointer_controller.py`` and ``test_headpointer_motion.py`` drive well-formed
traces through an instant, always-working fake sink. That proves the state machine. It cannot
show what the real world does to it, and this file is about exactly that gap:

* **A pose that is not a number.** ``HeadPoseSignal`` refuses non-finite fields, so a real
  camera cannot produce one -- but a duck-typed double, a second perception source or a mutated
  object can, and what the controller did with it was not "skip the frame". As the capture frame
  it became the neutral pose and turned every later *good* sample into a fault; mid-stream it
  faulted the feature until an explicit resume.
* **Samples out of order.** Two producers, a retry, a queue that reorders: an older pose arriving
  after a newer one must move nothing *and* must not drag the clock back, or the next step is
  integrated over a gap that never happened.
* **A sink that breaks half way through a gesture**, and one that is slow rather than broken.
  The recording fake is instantaneous; the Wayland portal is a D-Bus round trip. "Shutdown while
  a move is in flight" has an answer only against a sink that is actually in flight.
* **An unreadable ``x_gain``.** On a real webcam (2026-10-13) the X axis was inverted because a
  left turn is *positive* yaw. The shipped config negates the gain, but every *fallback* for a
  bad value used the pure core's own positive number -- a typo mirrored the horizontal axis, and
  no synthetic pose test could notice, because the sign is geometry, not arithmetic.

Everything here is a number in a list. No camera is opened and no real pointer moves; every
magnitude is a provisional first-principles value, not a measurement (``GOVERNANCE.md``).
"""

from __future__ import annotations

import json
import math
import threading
import types

import pytest

from tests.pointer_fake import FakePointerSink, PointerAction, PointerActionKind
from yazses.config import HeadpointerConfig
from yazses.handsfree.safety import HandsFreeSafety
from yazses.headpointer.controller import (
    HeadPointerController,
    HeadPointerSettings,
    State,
)
from yazses.headpointer.pointer import WEBCAM_X_GAIN, PointerCalib
from yazses.headpointer.runtime import settings_from_config, status_dict
from yazses.perception.signals import HeadPoseSignal
from yazses.pointer.base import PointerBackendError, PointerButton

FRAME = 1.0 / 30.0
# Round numbers, caps out of the way: these tests are about ordering and validity, not speed.
CALIB = PointerCalib(
    x_gain=-1000.0, y_gain=500.0, deadzone=0.02,
    max_speed_x=1e9, max_speed_y=1e9, max_speed_overall=1e9,
)


def raw(ts: float, yaw: float, pitch: float = 0.0, conf: float = 1.0):  # type: ignore[no-untyped-def]
    """A pose that bypassed ``HeadPoseSignal``'s validation, as a duck-typed source could."""
    return types.SimpleNamespace(timestamp_s=ts, yaw=yaw, pitch=pitch, roll=0.0, confidence=conf)


class Rig:
    def __init__(self, sink: FakePointerSink | None = None, *, safety=None, calib=CALIB) -> None:  # type: ignore[no-untyped-def]
        self.t = 100.0
        self.sink = sink or FakePointerSink()
        self.ctl = HeadPointerController(
            self.sink, HeadPointerSettings(calib=calib), safety=safety, backend="fake"
        )

    def feed(self, yaw: float = 0.0, pitch: float = 0.0, *, dt: float = FRAME):  # type: ignore[no-untyped-def]
        self.t += dt
        return self.ctl.update(HeadPoseSignal(self.t, yaw, pitch, 0.0, 1.0), self.t)

    def feed_raw(self, yaw: float, *, ts: float | None = None, conf: float = 1.0):  # type: ignore[no-untyped-def]
        self.t += FRAME
        sample = raw(self.t if ts is None else ts, yaw, 0.0, conf)
        return self.ctl.update(sample, self.t)  # type: ignore[arg-type]

    @property
    def moves(self) -> list[PointerAction]:
        return [a for a in self.sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE]


BAD_POSES = [
    pytest.param(dict(yaw=math.nan), id="nan-yaw"),
    pytest.param(dict(yaw=math.inf), id="inf-yaw"),
    pytest.param(dict(yaw=0.1, ts=math.nan), id="nan-timestamp"),
    pytest.param(dict(yaw=0.1, ts=math.inf), id="inf-timestamp"),
    pytest.param(dict(yaw=0.1, conf=math.nan), id="nan-confidence"),
]


# --------------------------------------------------------------------------- #
# A pose that is not a number is no signal -- not a neutral pose, not a fault
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", BAD_POSES)
def test_a_garbled_pose_as_the_first_frame_does_not_become_the_neutral_pose(bad) -> None:  # type: ignore[no-untyped-def]
    rig = Rig()
    step = rig.feed_raw(**bad)
    assert step.state is State.LOST, "a garbled frame is a missing frame"
    assert rig.ctl.status().calibrated is False, "it must not have been captured as neutral"
    # The real camera then comes up. Nothing may have been poisoned: the first good frame is
    # the capture frame (it is also the settling frame), and the head then moves the pointer.
    assert rig.feed(0.0).reason == "centred"
    rig.feed(0.2)
    assert rig.ctl.status().fault == ""
    assert rig.moves, "the pointer must follow a good head after a garbled first frame"
    assert all(math.isfinite(a.x) and math.isfinite(a.y) for a in rig.moves)


@pytest.mark.parametrize("bad", BAD_POSES)
def test_a_garbled_pose_mid_stream_freezes_the_pointer_and_recovers_by_itself(bad) -> None:  # type: ignore[no-untyped-def]
    rig = Rig()
    for _ in range(4):
        rig.feed(0.0)
    rig.feed(0.2)
    sent = len(rig.moves)
    assert sent >= 1

    step = rig.feed_raw(**bad)
    assert step.state is State.LOST and (step.dx, step.dy) == (0, 0)
    assert rig.ctl.status().fault == "", "a bad frame must not latch a fault that needs a resume"
    assert len(rig.moves) == sent

    # Recovery is automatic and goes through a settling frame: no catch-up, no replayed delta.
    assert rig.feed(0.2).reason == "settling"
    assert len(rig.moves) == sent
    rig.feed(0.2)
    assert len(rig.moves) == sent + 1


def test_a_nan_timestamp_cannot_leave_the_state_reading_tracking() -> None:
    """NaN compares false against everything: it used to slip past every freshness check."""
    rig = Rig()
    for _ in range(4):
        rig.feed(0.0)
    assert rig.ctl.status().state is State.TRACKING
    rig.feed_raw(0.3, ts=math.nan)
    assert rig.ctl.status().state is State.LOST


def test_the_status_stays_strict_json_even_for_a_garbled_sample() -> None:
    rig = Rig()
    rig.feed(0.0)
    rig.feed_raw(0.3, ts=math.nan)
    json.dumps(status_dict(rig.ctl.status()), allow_nan=False)  # raises on NaN/Infinity


# --------------------------------------------------------------------------- #
# Samples out of order
# --------------------------------------------------------------------------- #
def _trace(extra_late_sample: bool) -> list[PointerAction]:
    rig = Rig()
    for _ in range(3):
        rig.feed(0.0)
    rig.feed(0.15)
    rig.feed(0.15)
    newest_t = rig.t
    if extra_late_sample:
        # An older observation, different yaw, delivered after a newer one. Still "fresh" by
        # age, so only the ordering rule stands between it and the pointer.
        rig.ctl.update(HeadPoseSignal(newest_t - 2 * FRAME, -0.3, 0.0, 0.0, 1.0), newest_t + 0.001)
    rig.t = newest_t
    rig.feed(0.15)
    rig.feed(0.15)
    return rig.moves


def test_a_late_older_pose_moves_nothing_and_does_not_drag_the_clock_back() -> None:
    """If it rewound the clock the next step would integrate over three frames, not one."""
    clean = _trace(extra_late_sample=False)
    with_late = _trace(extra_late_sample=True)
    assert with_late == clean


def test_the_same_pose_delivered_twice_moves_the_pointer_once() -> None:
    rig = Rig()
    for _ in range(3):
        rig.feed(0.0)
    sample = HeadPoseSignal(rig.t + FRAME, 0.15, 0.0, 0.0, 1.0)
    rig.ctl.update(sample, rig.t + FRAME)
    once = list(rig.moves)
    for i in range(1, 6):
        rig.ctl.update(sample, rig.t + FRAME + 0.001 * i)
    assert rig.moves == once


# --------------------------------------------------------------------------- #
# A sink that breaks half way through a gesture
# --------------------------------------------------------------------------- #
class FailsOnNthMove(FakePointerSink):
    """Works for ``n - 1`` moves, then raises on every call like a compositor that went away."""

    def __init__(self, n: int) -> None:
        super().__init__()
        self._n = n
        self.calls = 0

    def move_relative(self, dx: float, dy: float) -> None:
        self.calls += 1
        if self.calls >= self._n:
            raise PointerBackendError("the compositor went away mid-gesture")
        super().move_relative(dx, dy)


def test_a_sink_that_dies_mid_gesture_faults_tells_the_gate_and_is_never_called_again() -> None:
    gate_clock = [0.0]
    gate = HandsFreeSafety(("headpointer",), clock=lambda: gate_clock[0] * 1000.0)
    sink = FailsOnNthMove(3)
    rig = Rig(sink, safety=gate)
    gate_clock[0] = rig.t
    rig.feed(0.0)
    gate_clock[0] = rig.t
    assert rig.ctl.resume().ok
    gate_clock[0] = rig.t + FRAME
    rig.feed(0.0)  # the capture frame: the gate was shut for the first one

    states: list[State] = []
    for _ in range(25):
        gate_clock[0] = rig.t + FRAME
        states.append(rig.feed(0.25).state)

    assert State.FAULTED in states
    health = gate.status().source("headpointer")
    assert health is not None and health.faulted, "the global stop must be told"
    assert sink.calls == 3, "after the failure the sink is not tried again, retried or probed"
    assert len(sink.actions) == 2, "the failed step's motion is spent, not replayed"


def test_after_a_mid_gesture_failure_resume_does_not_replay_the_failed_step() -> None:
    sink = FailsOnNthMove(2)
    rig = Rig(sink)
    rig.feed(0.0)
    rig.feed(0.0)
    rig.feed(0.25)
    rig.feed(0.25)  # the failing move
    assert rig.ctl.status().state is State.FAULTED
    sink._n = 10**9  # the backend comes back
    assert rig.ctl.resume().ok
    before = len(sink.actions)
    rig.feed(0.25)  # settling frame after the resume
    assert len(sink.actions) == before
    rig.feed(0.25)
    new = sink.actions[before:]
    assert len(new) == 1, "exactly one fresh step, not the lost one on top of it"


class PressThenFailRelease(FakePointerSink):
    """A click whose release the platform refuses: the button is left down."""

    def __init__(self) -> None:
        super().__init__()
        self.click_calls = 0

    def click(self, button: PointerButton = PointerButton.LEFT) -> None:
        self.click_calls += 1
        self._actions.append(PointerAction.press(button))
        raise PointerBackendError("the release was refused")


def test_a_click_that_fails_after_its_press_is_not_retried_and_faults_the_feature() -> None:
    """Retrying would press again on a button that is already down; the controller must not.

    It also cannot release the button itself -- the sink is write-only and has no release
    method -- so what it *can* promise is: one call, a fault, and a gate that knows.
    """
    sink = PressThenFailRelease()
    rig = Rig(sink)
    rig.feed(0.0)
    rig.feed(0.0)
    result = rig.ctl.commit_click(lambda _ctx: "")
    assert result.ok is False
    assert sink.click_calls == 1
    assert rig.ctl.status().state is State.FAULTED
    for _ in range(20):
        rig.feed(0.2)
    assert sink.click_calls == 1


# --------------------------------------------------------------------------- #
# Shutdown while a move is in flight
# --------------------------------------------------------------------------- #
class BlocksInsideMove(FakePointerSink):
    """A sink that is in the middle of a platform call until the test lets it return."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.order: list[str] = []

    def move_relative(self, dx: float, dy: float) -> None:
        self.order.append("move-start")
        self.entered.set()
        assert self.release.wait(timeout=10.0), "the test never released the move"
        super().move_relative(dx, dy)
        self.order.append("move-end")

    def close(self) -> None:
        self.order.append("close")
        super().close()


def test_closing_during_an_in_flight_move_waits_for_it_then_closes_and_never_moves_again() -> None:
    sink = BlocksInsideMove()
    rig = Rig(sink)
    rig.feed(0.0)
    rig.feed(0.0)
    sink.release.clear()

    runner = threading.Thread(target=lambda: rig.feed(0.25), daemon=True)
    runner.start()
    assert sink.entered.wait(timeout=10.0), "the move never started"

    closer = threading.Thread(target=rig.ctl.close, daemon=True)
    closer.start()
    closer.join(timeout=0.3)
    assert closer.is_alive(), "close() returned while a move was still inside the platform call"
    assert "close" not in sink.order, "the sink was closed underneath its own in-flight move"

    sink.release.set()
    runner.join(timeout=10.0)
    closer.join(timeout=10.0)
    assert not runner.is_alive() and not closer.is_alive()
    assert sink.order == ["move-start", "move-end", "close"]

    sink.order.clear()
    for _ in range(5):
        assert rig.feed(0.25).state is State.CLOSED
    assert sink.order == [], "nothing reaches a sink after shutdown"
    assert rig.ctl.status().state is State.CLOSED


def test_pause_during_an_in_flight_move_lands_after_it_and_stops_the_next_one() -> None:
    sink = BlocksInsideMove()
    rig = Rig(sink)
    rig.feed(0.0)
    rig.feed(0.0)
    sink.release.clear()
    runner = threading.Thread(target=lambda: rig.feed(0.25), daemon=True)
    runner.start()
    assert sink.entered.wait(timeout=10.0)

    pauser = threading.Thread(target=rig.ctl.pause, daemon=True)
    pauser.start()
    pauser.join(timeout=0.3)
    assert pauser.is_alive(), "pause() is serialised with the in-flight move"

    sink.release.set()
    runner.join(timeout=10.0)
    pauser.join(timeout=10.0)
    moved = len(sink.actions)
    for _ in range(10):
        rig.feed(0.25)
    assert len(sink.actions) == moved, "once pause has landed the pointer does not move"


# --------------------------------------------------------------------------- #
# The sign of x is geometry: no fallback may flip it
# --------------------------------------------------------------------------- #
def test_the_shipped_x_gain_is_the_one_the_fallbacks_use() -> None:
    assert HeadpointerConfig().x_gain == WEBCAM_X_GAIN < 0.0


@pytest.mark.parametrize("junk", [None, "banana", math.nan, math.inf, -math.inf, [1]])
def test_an_unreadable_x_gain_in_the_config_keeps_the_pointer_following_the_head(junk) -> None:  # type: ignore[no-untyped-def]
    cfg = HeadpointerConfig()
    cfg.x_gain = junk  # type: ignore[assignment]
    calib = settings_from_config(cfg).calib
    assert calib.x_gain == WEBCAM_X_GAIN, "a typo must not mirror the horizontal axis"


def test_a_non_finite_x_gain_handed_straight_to_the_controller_keeps_the_sign_too() -> None:
    """The controller repairs it itself, and used to repair it to the *inverted* direction."""
    sink = FakePointerSink()
    calib = PointerCalib(
        x_gain=math.nan, max_speed_x=1e9, max_speed_y=1e9, max_speed_overall=1e9
    )
    ctl = HeadPointerController(sink, HeadPointerSettings(calib=calib))
    t = 100.0
    for yaw in (0.0, 0.0, 0.3, 0.3, 0.3):
        t += FRAME
        ctl.update(HeadPoseSignal(t, yaw, 0.0, 0.0, 1.0), t)
    moves = [a for a in sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE]
    assert moves and sum(a.x for a in moves) < 0.0, "head turned left (+yaw): pointer goes left"


def test_a_controller_built_without_settings_follows_the_head_not_a_mirror_of_it() -> None:
    sink = FakePointerSink()
    ctl = HeadPointerController(sink)
    t = 100.0
    for yaw in (0.0, 0.0, 0.3, 0.3, 0.3, 0.3):
        t += FRAME
        ctl.update(HeadPoseSignal(t, yaw, 0.0, 0.0, 1.0), t)
    moves = [a for a in sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE]
    assert moves and sum(a.x for a in moves) < 0.0
