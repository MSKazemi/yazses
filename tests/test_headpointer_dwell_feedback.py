"""Head-Pointer recenter / pause / clutch / dwell feedback, against the orderings a fake hides (#405).

``test_headpointer_controller.py`` and ``test_headpointer_dwell_time.py`` already pin each
control on its own. This file is about what happens when they **meet**, and about one promise the
issue makes that nothing yet checked against real timing:

    "user-visible dwell progress appears before firing"

* **A click is never the first the user hears of a dwell.** Progress used to be published after a
  frame's click decision, so a hold no longer than the gap between two camera frames (the config
  floor is 50 ms; a 15 fps frame is 66 ms) clicked on the very sample that began to show it --
  ``show()`` was never called and ``status().dwell_progress`` never read above zero. The
  controller now holds such a dwell at the brink for one sample. Time is a number the test
  assigns, so this is the 15 fps webcam, not a hope about one.
* **Which control wins, and does undoing one undo another?** Fault beats the global gate beats
  pause beats clutch; releasing a clutch never resumes a pause, resuming never releases a clutch,
  and a recenter requested under either waits for the first sample nobody is holding back.
* **Resume undoes only its own source.** After a global pause the Head-Pointer's ``resume`` arms
  the Head-Pointer and nothing else -- another camera feature stays suppressed until it is
  resumed itself.
* **Feedback leaks no position.** The ring is drawn by a process that reads the pointer from the
  OS; what crosses IPC is a fraction in ``[0, 1]`` and flags, identical for any two dwells
  however far apart on the screen they happened.
* **The reader of that progress is fast enough.** The overlay polls ``status``; it must already
  be polling fast when a dwell *can* start, not after progress is above zero.

No number is a recommendation: the traces are synthetic and the hold lengths are the config's
bounds and the shipped provisional default, not a measurement of any person (GOVERNANCE.md).
"""
from __future__ import annotations

import pytest

from tests.pointer_fake import FakePointerSink, PointerActionKind
from tests.test_headpointer_dwell_time import JUMP
from yazses.handsfree.safety import HandsFreeSafety
from yazses.headpointer.controller import (
    MIN_DWELL_S,
    HeadPointerController,
    HeadPointerSettings,
    State,
)
from yazses.headpointer.pointer import DwellClicker
from yazses.headpointer.runtime import status_dict
from yazses.overlay import poller
from yazses.perception.signals import HeadPoseSignal


class Feedback:
    """What the user is told, in order. Records only what the protocol carries."""

    def __init__(self) -> None:
        self.shown: list[float] = []
        self.hidden = 0

    def show(self, progress: float) -> None:
        self.shown.append(progress)

    def hide(self) -> None:
        self.hidden += 1


class Rig:
    """A controller on a hand-moved clock, a recording sink and (optionally) a real gate."""

    def __init__(self, fps: float = 30.0, *, gate_sources=None, **settings) -> None:
        settings.setdefault("calib", JUMP)
        settings.setdefault("dwell_enabled", True)
        settings.setdefault("dwell_hold_s", 0.7)
        self.fps = fps
        self.t = 1000.0
        self.sink = FakePointerSink()
        self.feedback = Feedback()
        self.gate = (
            HandsFreeSafety(gate_sources, clock=lambda: self.t * 1000.0)
            if gate_sources is not None
            else None
        )
        self.ctl = HeadPointerController(
            self.sink, HeadPointerSettings(**settings), safety=self.gate, feedback=self.feedback
        )
        self.polled: list[float] = []  # dwell_progress as a status poller sees it, after each tick

    def feed(self, yaw: float = 0.0, *, dt: float | None = None):
        self.t += (1.0 / self.fps) if dt is None else dt
        step = self.ctl.update(HeadPoseSignal(self.t, yaw, 0.0, 0.0, 1.0), self.t)
        self.polled.append(self.ctl.status().dwell_progress)
        return step

    @property
    def clicks(self) -> int:
        return sum(1 for a in self.sink.actions if a.kind is PointerActionKind.BUTTON_PRESS)

    @property
    def moves(self):
        return [a for a in self.sink.actions if a.kind is PointerActionKind.MOVE_RELATIVE]

    def arm_dwell(self) -> None:
        """Centre, settle, then one big turn past the radius: dwell armed and anchored."""
        self.feed(0.0)
        self.feed(0.0)
        self.feed(0.5)
        assert self.ctl.status().dwell_armed

    def rest_until_click(self, limit_s: float = 5.0) -> int | None:
        """Hold the head at neutral. The index (into ``polled``) of the tick that clicked."""
        start = self.t
        while self.t - start < limit_s:
            before = self.clicks
            self.feed(0.0)
            if self.clicks > before:
                return len(self.polled) - 1
        return None


# --------------------------------------------------------------------------- #
# Progress is published before the click it announces
# --------------------------------------------------------------------------- #

#: (fps, hold_s). The floor (50 ms) is shorter than one frame at 10/15/30 fps; "one frame" is
#: exactly one frame gap; 0.7 is the shipped provisional default.
CASES = [
    pytest.param(10, MIN_DWELL_S, id="10fps-floor"),
    pytest.param(15, MIN_DWELL_S, id="15fps-floor"),
    pytest.param(30, MIN_DWELL_S, id="30fps-floor"),
    pytest.param(60, MIN_DWELL_S, id="60fps-floor"),
    pytest.param(15, 1 / 15, id="15fps-one-frame"),
    pytest.param(30, 1 / 30, id="30fps-one-frame"),
    pytest.param(15, 0.7, id="15fps-default"),
    pytest.param(30, 0.7, id="30fps-default"),
]


@pytest.mark.parametrize(("fps", "hold_s"), CASES)
def test_the_user_is_shown_progress_on_an_earlier_sample_than_the_click(fps, hold_s):
    rig = Rig(fps, dwell_hold_s=hold_s)
    rig.arm_dwell()
    clicked_at = rig.rest_until_click()
    assert clicked_at is not None, "the dwell must still fire"
    seen_before = [p for p in rig.polled[:clicked_at] if p > 0.0]
    assert seen_before, f"clicked with no progress ever readable: {rig.polled[-6:]}"
    assert rig.feedback.shown, "show() was never called before the click"
    assert all(0.0 < p <= 1.0 for p in rig.feedback.shown)
    assert rig.feedback.hidden >= 1, "the indicator is withdrawn when it fires"
    assert rig.clicks == 1


def test_the_default_hold_is_not_delayed_by_the_rule():
    """At a hold of many frames the brink is never reached: the click lands where it always did."""
    rig = Rig(30, dwell_hold_s=0.7)
    rig.arm_dwell()
    start = rig.t
    clicked_at = rig.rest_until_click()
    assert clicked_at is not None
    waited = rig.t - start
    assert 0.7 - 1e-9 <= waited < 0.7 + 1 / 30 + 1e-9, waited


def test_a_dwell_held_at_the_brink_is_abandoned_if_the_head_moves_before_it_fires():
    rig = Rig(15, dwell_hold_s=MIN_DWELL_S)
    rig.arm_dwell()
    for _ in range(3):  # the sample that completes the hold is held back, not fired
        rig.feed(0.0)
        if rig.polled[-1] >= 1.0:
            break
    assert rig.polled[-1] == pytest.approx(1.0) and rig.clicks == 0
    rig.feed(0.5)  # the user moves instead of resting one frame longer
    assert rig.clicks == 0
    assert rig.polled[-1] < 1.0


def test_a_dwell_held_at_the_brink_does_not_survive_a_pause():
    rig = Rig(15, dwell_hold_s=MIN_DWELL_S)
    rig.arm_dwell()
    for _ in range(3):
        rig.feed(0.0)
        if rig.polled[-1] >= 1.0:
            break
    rig.ctl.pause()
    for _ in range(20):
        assert rig.feed(0.0).state is State.PAUSED
    assert rig.clicks == 0 and rig.ctl.status().dwell_progress == 0.0


class TestClickerBrink:
    """The pure half: ``may_fire=False`` holds a completed dwell, ``True`` (the default) is unchanged."""

    @staticmethod
    def _clicker() -> DwellClicker:
        clicker = DwellClicker(radius=5.0, hold_s=0.1)
        assert clicker.update(10.0, 10.0, 0.0) is False  # anchor
        return clicker

    def test_the_default_fires_on_the_completing_sample_as_it_always_did(self):
        clicker = self._clicker()
        assert clicker.update(10.0, 10.0, 0.05) is False
        assert clicker.update(10.0, 10.0, 0.11) is True

    def test_may_fire_false_holds_it_and_the_next_sample_fires(self):
        clicker = self._clicker()
        assert clicker.update(10.0, 10.0, 0.11, may_fire=False) is False
        assert clicker.progress == 1.0
        assert clicker.update(10.0, 10.0, 0.14) is True

    def test_moving_away_from_the_brink_restarts_the_dwell(self):
        clicker = self._clicker()
        clicker.update(10.0, 10.0, 0.11, may_fire=False)
        assert clicker.update(40.0, 10.0, 0.14) is False
        assert clicker.progress == 0.0

    def test_a_stall_at_the_brink_restarts_it_rather_than_completing_it(self):
        clicker = self._clicker()
        clicker.update(10.0, 10.0, 0.11, may_fire=False)
        assert clicker.update(10.0, 10.0, 5.0) is False  # five seconds nobody saw
        assert clicker.progress == 0.0

    def test_reset_clears_the_brink(self):
        clicker = self._clicker()
        clicker.update(10.0, 10.0, 0.11, may_fire=False)
        clicker.reset()
        assert clicker.progress == 0.0


# --------------------------------------------------------------------------- #
# Pause, clutch, recenter, fault and resume, interleaved
# --------------------------------------------------------------------------- #


def _tracking_rig(**kw) -> Rig:
    rig = Rig(30, dwell_enabled=False, **kw)
    rig.feed(0.0)  # neutral
    return rig


def test_pause_beats_clutch_and_releasing_the_clutch_does_not_resume():
    rig = _tracking_rig()
    rig.ctl.pause()
    rig.ctl.set_clutch("face", True)
    rig.ctl.set_clutch("face", False)
    for _ in range(10):
        assert rig.feed(0.4).state is State.PAUSED
    assert rig.moves == []


def test_resume_does_not_release_a_clutch_somebody_still_holds():
    rig = _tracking_rig()
    rig.ctl.set_clutch("face", True)
    rig.ctl.pause()
    assert rig.ctl.resume().ok
    for _ in range(10):
        step = rig.feed(0.4)
        assert step.state is State.CLUTCHED
    assert rig.moves == []
    status = rig.ctl.status()
    assert status.paused is False and status.clutched is True


def test_after_pause_resume_and_release_the_pointer_settles_before_it_moves():
    rig = _tracking_rig()
    rig.ctl.set_clutch("face", True)
    rig.ctl.pause()
    rig.ctl.resume()
    rig.ctl.set_clutch("face", False)
    assert rig.feed(0.4).reason == "settling"
    assert rig.moves == []
    rig.feed(0.4)
    assert len(rig.moves) == 1


def test_a_recenter_asked_under_a_clutch_waits_for_the_first_free_sample():
    rig = _tracking_rig()
    rig.ctl.set_clutch("face", True)
    rig.ctl.recenter()
    for _ in range(5):
        assert rig.feed(0.4).state is State.CLUTCHED
    assert rig.ctl.status().calibrated is False  # still pending: nobody has captured a pose
    rig.ctl.set_clutch("face", False)
    assert rig.feed(0.4).reason == "centred"  # captured here, with no motion
    assert rig.ctl.status().calibrated is True
    for _ in range(5):
        rig.feed(0.4)  # holding the new pose is the new straight ahead
    assert rig.moves == []


def test_a_recenter_asked_under_pause_and_clutch_is_captured_after_both_are_released():
    rig = _tracking_rig()
    rig.ctl.pause()
    rig.ctl.set_clutch("face", True)
    rig.ctl.recenter()
    rig.feed(0.9)
    rig.ctl.set_clutch("face", False)
    rig.feed(0.9)
    assert rig.ctl.status().calibrated is False  # still paused: nothing was captured yet
    assert rig.ctl.resume().ok
    assert rig.feed(0.2).reason == "centred"  # the pose at THIS sample is the new neutral
    rig.feed(0.2)
    assert rig.moves == []


def test_a_fault_beats_a_pause_and_one_resume_clears_both_but_not_a_clutch():
    rig = _tracking_rig()
    rig.ctl.pause()
    rig.ctl.set_clutch("key", True)
    rig.ctl.fail("sink gone")
    assert rig.feed(0.4).state is State.FAULTED
    assert rig.ctl.resume().ok
    assert rig.feed(0.4).state is State.CLUTCHED
    rig.ctl.set_clutch("key", False)
    assert rig.feed(0.4).reason == "settling"


def test_a_clutch_asked_for_during_a_dwell_drops_it_and_releasing_does_not_click():
    rig = Rig(30, dwell_hold_s=0.3)
    rig.arm_dwell()
    for _ in range(4):
        rig.feed(0.0)
    assert rig.ctl.status().dwell_progress > 0.0
    rig.ctl.set_clutch("face", True)
    assert rig.ctl.status().dwell_progress == 0.0
    for _ in range(30):
        rig.feed(0.0)
    rig.ctl.set_clutch("face", False)
    for _ in range(60):
        rig.feed(0.0)  # a still head after the clutch: nothing travelled, so nothing dwells
    assert rig.clicks == 0


def test_recenter_is_one_call_with_no_argument():
    """Reachable without precise pointer use (ADR-v2-148): no target, no position, no precision."""
    import inspect

    assert list(inspect.signature(HeadPointerController.recenter).parameters) == ["self"]
    assert list(inspect.signature(HeadPointerController.pause).parameters) == ["self"]


# --------------------------------------------------------------------------- #
# Resume undoes only its own source
# --------------------------------------------------------------------------- #


def test_resuming_the_head_pointer_after_a_global_pause_arms_only_the_head_pointer():
    rig = Rig(30, gate_sources=("headpointer", "facegesture"), dwell_enabled=False)
    rig.feed(0.0)
    rig.gate.sample("facegesture")
    assert rig.gate.resume().ok  # both armed
    rig.feed(0.0)
    rig.gate.pause("stop")
    assert rig.feed(0.4).state is State.SUPPRESSED

    assert rig.ctl.resume().ok
    rig.gate.sample("facegesture")
    assert rig.gate.gate("facegesture").allowed is False  # still waiting for its own resume
    rig.feed(0.4)
    rig.feed(0.4)
    assert len(rig.moves) >= 1  # and the pointer itself is back


def test_a_global_pause_beats_the_features_own_pause_state_in_what_is_reported():
    rig = Rig(30, gate_sources=("headpointer",), dwell_enabled=False)
    rig.feed(0.0)
    assert rig.ctl.resume().ok
    rig.ctl.pause()
    rig.gate.pause("stop")
    step = rig.feed(0.4)
    assert step.state is State.SUPPRESSED  # the gate is asked first
    assert rig.moves == []


# --------------------------------------------------------------------------- #
# Feedback leaks no position
# --------------------------------------------------------------------------- #


def _status_of_a_dwell_far_from_origin(yaw_out: float) -> dict[str, object]:
    rig = Rig(30, dwell_hold_s=0.7)
    rig.feed(0.0)
    rig.feed(0.0)
    rig.feed(yaw_out)  # travel left or right, by a different distance each time
    for _ in range(10):
        rig.feed(0.0)
    status = status_dict(rig.ctl.status())
    status["sample_age_s"] = None  # a clock reading, not a position; pinned elsewhere
    return status


def test_two_dwells_at_opposite_ends_of_the_screen_publish_the_same_status():
    left = _status_of_a_dwell_far_from_origin(-0.5)
    right = _status_of_a_dwell_far_from_origin(0.5)
    assert left == right
    assert 0.0 < float(left["dwell_progress"]) < 1.0  # it really was mid-dwell


def test_the_fed_back_progress_is_a_fraction_and_nothing_else():
    rig = Rig(30, dwell_hold_s=0.7)
    rig.arm_dwell()
    rig.rest_until_click()
    assert rig.feedback.shown
    assert all(isinstance(p, float) and 0.0 < p <= 1.0 for p in rig.feedback.shown)
    assert rig.feedback.shown == sorted(rig.feedback.shown)


def test_the_status_keys_are_the_known_value_free_set():
    rig = _tracking_rig()
    assert set(status_dict(rig.ctl.status())) == {
        "state", "reason", "paused", "clutched", "calibrated", "sample_age_s", "dwell_enabled",
        "dwell_armed", "dwell_progress", "fault", "backend", "consent", "consent_reason",
    }


# --------------------------------------------------------------------------- #
# The reader of the progress is already fast when a dwell can start
# --------------------------------------------------------------------------- #


def test_the_overlay_polls_fast_while_a_dwell_can_start_not_only_once_it_has():
    slow = poller.next_interval("idle")
    assert poller.next_interval("idle", 0.0, True) < slow
    assert poller.next_interval("idle", 0.4, False) < slow  # the existing rule, unchanged
    assert poller.next_interval("idle", 0.0, False) == slow


def test_the_fast_poll_is_not_slower_than_the_shortest_dwell_the_config_allows():
    """A dwell of ``MIN_DWELL_S`` is on screen for at least one poll of the fast cadence."""
    assert poller._FAST_INTERVAL_S <= MIN_DWELL_S  # noqa: SLF001


def test_dwell_armed_is_read_only_when_it_is_literally_true():
    armed = poller.parse_status({"state": "idle", "headpointer": {"dwell_armed": True}})
    assert armed.dwell_armed is True
    for hostile in ("true", 1, "yes", None, [True]):
        snap = poller.parse_status({"state": "idle", "headpointer": {"dwell_armed": hostile}})
        assert snap.dwell_armed is False, hostile
    assert poller.parse_status({"state": "idle"}).dwell_armed is False
    assert poller.parse_status({"state": "idle", "headpointer": "off"}).dwell_armed is False


def test_the_live_status_of_an_armed_controller_makes_the_poller_fast_and_a_click_makes_it_slow_again():
    rig = Rig(30, dwell_hold_s=0.7)
    assert poller.parse_status({"headpointer": status_dict(rig.ctl.status())}).dwell_armed is False
    rig.arm_dwell()
    armed = poller.parse_status({"headpointer": status_dict(rig.ctl.status())})
    assert armed.dwell_armed is True
    assert poller.next_interval(armed.state, armed.dwell_progress, armed.dwell_armed) < poller.next_interval("idle")
    assert rig.rest_until_click() is not None
    after = poller.parse_status({"headpointer": status_dict(rig.ctl.status())})
    assert after.dwell_armed is False  # one click, then the user must move
    assert poller.next_interval(after.state, after.dwell_progress, after.dwell_armed) == poller.next_interval("idle")
