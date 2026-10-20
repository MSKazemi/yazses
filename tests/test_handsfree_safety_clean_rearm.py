"""A stop or a re-arm cuts every half-made face gesture, and the daemon closes the gate first (#417).

Two gaps EYE-SAFETY-001 left after the gate itself landed (``handsfree/safety.py``):

* **The face switch never read ``clear_pending``.** The gate bumps a source's epoch on every entry
  into suppression and on every re-arm, and the Head-Pointer drops its half-accumulated dwell on
  that latch. The face switch did not: ``GestureSwitch`` kept counting frames towards
  ``min_hold_frames`` straight through a pause and a Resume, so a gesture begun *before* a
  Resume could complete as a press on the first frame *after* it. ADR-v2-148's amendment already
  claimed "the re-arm bumps the epoch so no half-detected gesture survives"; nothing made it so.
  The pause-and-resume-between-two-frames case below is the one only the latch can see: by the
  next frame the gate is ACTIVE again and looks untouched.
* **``Daemon.shutdown`` stopped the activation sources before the gate closed.** The gate was
  closed in ``Daemon._shutdown``, which runs *after* ``shutdown()`` has already stopped the face
  switch, so the switch's last frames ran against an open gate.

Real gate, real detectors and the real backend shared-camera path, all on a fabricated clock.
Every score is a synthetic number; none is evidence about a real face. No camera, no thread.
"""
from __future__ import annotations

import threading
import types
from dataclasses import replace

import pytest

from yazses.config import FacegestureConfig
from yazses.core.daemon import Daemon
from yazses.facegesture.backend import FaceGestureBackend
from yazses.facegesture.detector import GestureSwitch
from yazses.facegesture.switches import (
    PRESS,
    RELEASE,
    SAFETY_SOURCE,
    SwitchAction,
    SwitchIntent,
    SwitchMapper,
)
from yazses.handsfree.safety import HandsFreeSafety
from yazses.perception import FaceSignal, PerceptionSample

HOLD = 0.9   # well above the default hold threshold (0.5)
REST = 0.0   # well below the default release threshold (0.35)
MIN_HOLD = 3


# ============================================================ the detector primitive


def test_discarding_a_half_made_gesture_restarts_the_full_hold_count():
    switch = GestureSwitch(min_hold_frames=MIN_HOLD)
    assert [switch.update(HOLD) for _ in range(MIN_HOLD - 1)] == [None, None]
    switch.discard_pending()
    # Without the discard, the very next frame would be the third and would start.
    assert [switch.update(HOLD) for _ in range(MIN_HOLD - 1)] == [None, None]
    assert switch.update(HOLD) == "start"


def test_discarding_leaves_an_open_hold_open_so_its_release_still_arrives():
    switch = GestureSwitch(min_hold_frames=MIN_HOLD, min_release_frames=2)
    events = [switch.update(HOLD) for _ in range(MIN_HOLD)]
    assert events[-1] == "start"
    switch.discard_pending()
    assert switch.update(HOLD) is None, "a held gesture must not start a second time"
    assert [switch.update(REST) for _ in range(2)] == [None, "end"]


# ============================================================ the mapper reports the latch


class _Clock:
    def __init__(self, now_ms: float = 1_000.0) -> None:
        self.now = now_ms

    def __call__(self) -> float:
        return self.now


def _armed_mapper(log: list[str]) -> tuple[SwitchMapper, HandsFreeSafety, _Clock]:
    clock = _Clock()
    gate = HandsFreeSafety((SAFETY_SOURCE,), clock=clock)
    mapper = SwitchMapper(
        {"jaw_open": "hold_to_talk"},
        {"hold_to_talk": SwitchAction(press=lambda: log.append("press"),
                                      release=lambda: log.append("release"))},
        gate=gate,
    )
    mapper.frame(True)
    assert gate.resume().ok
    mapper.frame(True)  # consumes the re-arm's latch
    return mapper, gate, clock


def test_without_a_gate_there_is_no_transition_to_report():
    mapper = SwitchMapper({"jaw_open": "hold_to_talk"}, {})
    assert mapper.frame(True) is False
    assert mapper.frame(False) is False


def test_a_frame_reports_a_pause_and_a_resume_exactly_once_each():
    mapper, gate, _ = _armed_mapper([])
    assert mapper.frame(True) is False, "a healthy frame is not a transition"
    gate.pause("tray")
    assert mapper.frame(True) is True
    assert mapper.frame(True) is False, "one-shot: the next frame is not told again"
    assert gate.resume().ok
    assert mapper.frame(True) is True
    assert mapper.frame(True) is False


def test_a_pause_and_resume_between_two_frames_is_still_reported():
    """The case only the latch can see: by the next frame the gate is ACTIVE again."""
    mapper, gate, _ = _armed_mapper([])
    gate.pause("voice")
    assert gate.resume().ok
    assert mapper.frame(True) is True


def test_a_latch_first_seen_by_a_press_is_handed_to_the_next_frame_not_lost():
    log: list[str] = []
    mapper, gate, _ = _armed_mapper(log)
    gate.pause("tray")
    assert gate.resume().ok
    assert mapper.handle(SwitchIntent("jaw_open", PRESS, 0.0)) is True  # consumes the latch
    mapper.handle(SwitchIntent("jaw_open", RELEASE, 0.0))
    assert mapper.frame(True) is True, "the camera loop must still be told to clear"


def test_a_stale_disarm_is_reported_on_the_first_face_back_before_it_is_counted():
    mapper, gate, clock = _armed_mapper([])
    for _ in range(20):  # two seconds with no face: past the 500 ms window
        clock.now += 100.0
        assert mapper.frame(False) is False, "a frame with no face counts nothing; not asked"
    clock.now += 100.0
    assert mapper.frame(True) is True, "the face is back: the cut lands before it is counted"


def test_a_blind_frame_does_not_register_the_face_switch_with_the_gate():
    """Asking the gate registers a source. A face switch that has never seen a face must not
    appear as "no signal yet", which would change what `handsfree resume` reports."""
    gate = HandsFreeSafety((), clock=_Clock())
    mapper = SwitchMapper({"jaw_open": "hold_to_talk"}, {}, gate=gate)
    for _ in range(5):
        mapper.frame(False)
    assert gate.status().source(SAFETY_SOURCE) is None


# ============================================================ end to end on the backend


class _Lease:
    """The face switch's lease on a shared camera, reduced to the newest observation."""

    name = SAFETY_SOURCE

    def __init__(self) -> None:
        self.sample: PerceptionSample | None = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def latest(self) -> PerceptionSample | None:
        return self.sample


class _Rig:
    """Real gate, real detectors, the real backend shared-camera step. Seconds on one clock."""

    def __init__(self) -> None:
        self.now = 500.0
        self.events: list[str] = []
        self.gate = HandsFreeSafety((SAFETY_SOURCE,), clock=lambda: self.now * 1000.0)
        self.lease = _Lease()
        cfg = replace(FacegestureConfig(enabled=True), fps=15, min_hold_frames=MIN_HOLD)
        self.backend = FaceGestureBackend(
            cfg,
            lambda _n: self.events.append("start"),
            lambda: self.events.append("end"),
            safety=self.gate,
            perception=self.lease,
            clock=lambda: self.now,
        )

    def frame(self, jaw: float) -> None:
        self.now += 1 / 15
        self.lease.sample = PerceptionSample(
            self.now, face=FaceSignal(self.now, 0.9, {"jawOpen": jaw})
        )
        self.backend._shared_step()

    def arm(self) -> None:
        self.frame(REST)  # the first face registers and samples the source
        assert self.gate.resume().ok
        self.frame(REST)  # the re-arm's latch is consumed on a face at rest
        assert self.events == []


@pytest.fixture
def rig() -> _Rig:
    r = _Rig()
    r.arm()
    return r


def test_the_rig_presses_on_a_plain_gesture_so_the_tests_below_can_fail(rig):
    for _ in range(MIN_HOLD):
        rig.frame(HOLD)
    assert rig.events == ["start"]


def _half_gesture_then_pause_and_resume_between_frames(rig: _Rig) -> list[str]:
    for _ in range(MIN_HOLD - 1):
        rig.frame(HOLD)
    assert rig.events == []
    rig.gate.pause("voice: stop")  # a tray click, a stop phrase ...
    assert rig.gate.resume().ok   # ... and Resume, both between two camera frames
    rig.frame(HOLD)               # without the cut, this frame completes the old gesture
    return list(rig.events)


def test_a_gesture_begun_before_a_resume_does_not_complete_after_it(rig):
    assert _half_gesture_then_pause_and_resume_between_frames(rig) == []
    rig.frame(HOLD)
    assert rig.events == [], "still inside the fresh count"
    rig.frame(HOLD)
    assert rig.events == ["start"], "a gesture made anew, in full, after Resume does act"


def test_the_case_above_really_is_the_half_made_gesture(rig, monkeypatch):
    """Mutation check: with the cut disabled the same timeline presses, so the test above is
    proving the cut and not a quirk of the rig."""
    monkeypatch.setattr(GestureSwitch, "discard_pending", lambda self: None)
    assert _half_gesture_then_pause_and_resume_between_frames(rig) == ["start"]


def test_a_gesture_held_across_a_pause_and_resume_must_be_relaxed_and_made_again(rig):
    for _ in range(MIN_HOLD):
        rig.frame(HOLD)
    assert rig.events == ["start"]
    rig.gate.pause("tray")
    rig.frame(HOLD)
    assert rig.events == ["start", "end"], "pausing closed the microphone at once"
    assert rig.gate.resume().ok
    for _ in range(10):  # the face never relaxes
        rig.frame(HOLD)
    assert rig.events == ["start", "end"], "a held face acted again after Resume"
    for _ in range(2):
        rig.frame(REST)
    for _ in range(MIN_HOLD):
        rig.frame(HOLD)
    # Relaxing delivers one more release (closing a closed microphone is harmless, and the
    # mapper never drops a hold's release), then a gesture made anew presses again.
    assert rig.events == ["start", "end", "end", "start"]


def test_a_gesture_begun_during_a_pause_needs_its_full_count_after_resume(rig):
    rig.gate.pause("tray")
    rig.frame(REST)  # the pause's latch is consumed here
    for _ in range(MIN_HOLD - 1):
        rig.frame(HOLD)  # counted while paused; a press now would be refused anyway
    assert rig.gate.resume().ok
    rig.frame(HOLD)
    assert rig.events == [], "frames counted under PAUSED completed a press after Resume"
    rig.frame(HOLD)
    rig.frame(HOLD)
    assert rig.events == ["start"]


# ============================================================ shutdown order


def test_the_stop_request_closes_the_gate_before_it_stops_any_activation_source():
    clock = _Clock()
    gate = HandsFreeSafety((SAFETY_SOURCE,), clock=clock)
    gate.sample(SAFETY_SOURCE)
    assert gate.resume().ok
    seen: list[tuple[str, bool]] = []

    def recorder(label: str):
        def stop() -> None:
            seen.append((label, gate.status().terminal and not gate.gate(SAFETY_SOURCE).allowed))

        return types.SimpleNamespace(stop=stop)

    daemon = Daemon.__new__(Daemon)
    daemon._stop_event = threading.Event()
    daemon._handsfree_safety = gate
    daemon._command_hotkey = recorder("command key")
    daemon._extra_activations = [recorder("face switch"), recorder("emg")]
    daemon._hotkey = recorder("dictation key")

    Daemon.shutdown(daemon)

    assert [label for label, _ in seen] == ["command key", "face switch", "emg", "dictation key"]
    assert all(closed for _, closed in seen), f"a source stopped while actions were allowed: {seen}"
    assert gate.resume().ok is False, "a stopping daemon must not be re-armable"


def test_the_stop_request_still_stops_every_source_when_the_gate_raises():
    def boom(_reason: str = "") -> None:
        raise RuntimeError("gate would not close")

    stopped: list[str] = []
    daemon = Daemon.__new__(Daemon)
    daemon._stop_event = threading.Event()
    daemon._handsfree_safety = types.SimpleNamespace(shutdown=boom)
    daemon._command_hotkey = None
    daemon._extra_activations = [types.SimpleNamespace(stop=lambda: stopped.append("face"))]
    daemon._hotkey = types.SimpleNamespace(stop=lambda: stopped.append("key"))

    Daemon.shutdown(daemon)

    assert stopped == ["face", "key"]


def test_the_stop_request_without_a_gate_is_unchanged():
    """`[handsfree_safety]` off (the shipped default): no gate, and shutdown is as before."""
    stopped: list[str] = []
    daemon = Daemon.__new__(Daemon)
    daemon._stop_event = threading.Event()
    daemon._handsfree_safety = None
    daemon._command_hotkey = None
    daemon._extra_activations = [types.SimpleNamespace(stop=lambda: stopped.append("face"))]
    daemon._hotkey = types.SimpleNamespace(stop=lambda: stopped.append("key"))

    Daemon.shutdown(daemon)

    assert stopped == ["face", "key"]
    assert daemon._stop_event.is_set()
