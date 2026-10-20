"""An eyes-closed switch holds for 0.8 s of *time*, not of frames, on the paths that run (#406).

The defect: the Hands-free panel protects an eyes-closed binding by raising ``[facegesture]
min_hold_frames`` to ``eyes_closed_min_hold_frames([facegesture] fps)`` -- 12 frames, "0.8 s at
15 fps". But on the shared camera (``[perception]`` on, same device) the face switch counts one
frame per *observation*, at ``[perception] fps``. At 30 fps those 12 frames are 0.4 s, and an
ordinary long blink of 0.4 s dictated. A config-file binding, or a secondary
``[[facegesture.switches]]`` binding at the default 3 frames, was a tenth of a second. The chord
path (``[gesture.chords]``, ``gesture/sensors.py``) counted frames the same way.

These drive the real builders -- ``FaceGestureBackend`` over a real ``SharedPerceptionSource``,
and ``SensorTokens`` built by ``gesture.runtime.sensor_settings`` -- at 30 fps. Every score is a
SYNTHETIC numeric fixture. The 0.8 s floor (``EYES_CLOSED_MIN_HOLD_S``) is provisional and
unmeasured; nothing here makes it a recommendation.
"""
from __future__ import annotations

from dataclasses import replace

from tests.test_facegesture_shared_camera import Camera, Clock, Model, NoThread
from yazses.config import FacegestureConfig, GestureConfig
from yazses.facegesture.backend import FaceGestureBackend
from yazses.gesture.engine import ChordEngine
from yazses.gesture.runtime import sensor_settings
from yazses.gesture.sensors import SensorTokens
from yazses.handsfree.panel import EYES_CLOSED_MIN_HOLD_S, eyes_closed_min_hold_frames
from yazses.perception import FaceSignal, PerceptionSample, SharedPerceptionSource

PERCEPTION_FPS = 30
DT = 1.0 / PERCEPTION_FPS
OPEN, SHUT = 0.04, 0.95


def _eyes(b: float) -> dict[str, float]:
    return {"eyeBlinkLeft": b, "eyeBlinkRight": b, "jawOpen": 0.03, "mouthSmileLeft": 0.0}


def _closures(*closures_s: float, open_s: float = 1.0) -> list[float]:
    """Open, then each closure followed by ``open_s`` open, sampled at PERCEPTION_FPS."""
    out = [OPEN] * int(round(open_s * PERCEPTION_FPS))
    for closure in closures_s:
        out += [SHUT] * int(round(closure * PERCEPTION_FPS))
        out += [OPEN] * int(round(open_s * PERCEPTION_FPS))
    return out


class SharedRig:
    """The face switch leasing a real shared source whose camera delivers 30 observations/s."""

    def __init__(self, **face) -> None:
        self.clock = Clock()
        self.camera = Camera()
        self.model = Model()
        self.source = SharedPerceptionSource(
            lambda: self.camera, lambda: self.model, clock=self.clock, spawn=NoThread
        )
        self.events: list[str] = []
        self.intents: list[tuple[str, str]] = []
        cfg = replace(FacegestureConfig(enabled=True), fps=15, **face)
        self.lease = self.source.consumer("facegesture")
        self.backend = FaceGestureBackend(
            cfg,
            lambda n: self.events.append("start"),
            lambda: self.events.append("end"),
            perception=self.lease,
            clock=self.clock,
            failure_reason=lambda: self.source.status().failure_reason,
        )
        self.lease.start()

    def play(self, eyes: list[float]) -> None:
        for b in eyes:
            self.clock.tick(DT)
            self.model.shapes = _eyes(b)
            self.source.observe()
            self.backend._shared_step()


# ---------------------------------------------------------------- the panel-written floor


def test_the_panels_frame_floor_is_computed_from_the_face_switchs_own_fps():
    # The precondition of the bug, pinned: 12 frames, which is 0.4 s at the shared camera's 30.
    assert eyes_closed_min_hold_frames(15) == 12
    assert 12 / PERCEPTION_FPS < EYES_CLOSED_MIN_HOLD_S


def test_a_04_s_blink_on_a_30_fps_shared_camera_does_not_dictate_with_the_panels_floor():
    rig = SharedRig(gesture="eyes_closed", min_hold_frames=eyes_closed_min_hold_frames(15))
    rig.play(_closures(0.4))
    assert rig.events == []


def test_a_minute_of_ordinary_blinking_never_dictates():
    rig = SharedRig(gesture="eyes_closed", min_hold_frames=eyes_closed_min_hold_frames(15))
    rig.play(_closures(*([0.1, 0.25, 0.4] * 5), open_s=4.0))
    assert rig.events == []


def test_a_09_s_deliberate_closure_dictates_exactly_once():
    rig = SharedRig(gesture="eyes_closed", min_hold_frames=eyes_closed_min_hold_frames(15))
    rig.play(_closures(0.9))
    assert rig.events == ["start", "end"]


# ------------------------------------------------- a config-file binding at the default 3 frames


def test_a_secondary_eyes_closed_binding_at_default_frames_ignores_a_04_s_blink():
    rig = SharedRig(switches=[{"gesture": "eyes_closed", "intent": "hold_to_command"}])
    rig.backend._sink = lambda intent: rig.intents.append((intent.gesture, intent.phase))
    rig.play(_closures(0.4))
    assert rig.intents == []
    rig.play(_closures(0.9))
    assert rig.intents == [("eyes_closed", "press"), ("eyes_closed", "release")]


def test_only_eyes_closed_gets_the_floor_and_other_gestures_keep_their_frame_debounce():
    # Narrowness: jaw-open at the shipped 3 frames still fires after 0.1 s at 30 fps.
    rig = SharedRig()
    assert rig.backend._switches["jaw_open"].min_hold_s == 0.0
    for jaw in [0.0] * 10 + [0.9] * 3:
        rig.clock.tick(DT)
        rig.model.shapes = {"jawOpen": jaw}
        rig.source.observe()
        rig.backend._shared_step()
    assert rig.events == ["start"]


def test_every_eyes_closed_detector_the_backend_builds_carries_the_floor_and_gets_a_clock():
    rig = SharedRig(gesture="eyes_closed")
    switch = rig.backend._switches["eyes_closed"]
    assert switch.min_hold_s == EYES_CLOSED_MIN_HOLD_S
    assert switch.needs_clock  # and both backend loops pass now_s (the deliberate test fires)


# ------------------------------------------------------------------------- the chord path


def _chord_rig(min_hold_frames: int):
    calls: list[str] = []
    engine = ChordEngine(
        {"eyes_closed": "recenter"}, {"recenter": lambda: calls.append("recenter")},
        window_s=0.4, refractory_s=1.0, freeze_tail_s=0.3,
    )
    face = replace(FacegestureConfig(), min_hold_frames=min_hold_frames)
    sensors = SensorTokens(engine, sensor_settings(GestureConfig(), face))
    return sensors, calls


def _play_chord(sensors: SensorTokens, eyes: list[float], t0: float = 100.0) -> float:
    t = t0
    for b in eyes:
        t += DT
        sensors.update(PerceptionSample(t, face=FaceSignal(t, 0.9, _eyes(b))), t)
    return t


def test_a_04_s_blink_is_not_an_eyes_closed_chord_token_at_30_fps():
    sensors, calls = _chord_rig(min_hold_frames=3)
    _play_chord(sensors, _closures(0.4))
    assert calls == []


def test_a_09_s_closure_is_one_eyes_closed_chord_token():
    sensors, calls = _chord_rig(min_hold_frames=3)
    _play_chord(sensors, _closures(0.9))
    assert calls == ["recenter"]
