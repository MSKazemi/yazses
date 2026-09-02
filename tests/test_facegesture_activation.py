"""The face-gesture switch is really wired into the daemon (#102).

`[facegesture]` must not become another documented section nothing reads. These
pin the seam: the source is constructed only when the feature is on, a held
gesture drives the same callbacks as the hotkey (or the command key), the daemon
stops it at shutdown, and a machine without opencv/mediapipe degrades to a logged
no-op instead of a startup failure.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from yazses.config import Config, FacegestureConfig
from yazses.configcheck import build_section
from yazses.core.daemon import Daemon
from yazses.facegesture.backend import FaceGestureBackend
from yazses.facegesture.detector import DEFAULT_GESTURE
from yazses.platform import get_platform


def _daemon(**face) -> Daemon:
    cfg = replace(Config(), facegesture=replace(FacegestureConfig(), **face))
    return Daemon(config=cfg, platform=get_platform())


def test_off_by_default_builds_nothing():
    d = _daemon()
    assert d._config.facegesture.enabled is False
    assert d._build_face_gesture_source(d._config) == []


def test_enabled_builds_the_backend_on_the_dictation_callbacks():
    d = _daemon(enabled=True)
    sources = d._build_face_gesture_source(d._config)
    assert len(sources) == 1
    backend = sources[0]
    assert isinstance(backend, FaceGestureBackend)
    # `full_text` is the default here: a face gesture replaces the hotkey.
    assert backend._on_hold_start == d._on_hold_start
    assert backend._on_hold_end == d._on_hold_end


def test_command_mode_drives_the_command_key_callbacks():
    backend = _daemon(enabled=True, mode="command")
    d = backend
    source = d._build_face_gesture_source(d._config)[0]
    assert source._on_hold_start == d._on_command_hold_start
    assert source._on_hold_end == d._on_command_hold_end


def test_an_unrecognised_mode_dictates_rather_than_running_commands():
    # The `[emg] mode = "commmand"` shape: a typo must not silently select the
    # branch that presses Return.
    d = _daemon(enabled=True, mode="comand")
    source = d._build_face_gesture_source(d._config)[0]
    assert source._on_hold_start == d._on_hold_start


def test_an_unrecognised_gesture_falls_back_to_the_default():
    d = _daemon(enabled=True, gesture="wink")
    source = d._build_face_gesture_source(d._config)[0]
    assert source._gesture == DEFAULT_GESTURE


def test_the_source_joins_the_one_list_the_daemon_starts_and_stops():
    """It must ride the same seam as EMG, not a second list nobody stops."""
    d = _daemon(enabled=True)
    sources = d._build_activation_sources(d._config)
    assert any(isinstance(s, FaceGestureBackend) for s in sources)
    d._extra_activations = sources
    d.shutdown()
    assert all(s._stop_event.is_set() for s in sources)


def test_run_is_a_no_op_when_mediapipe_is_missing(monkeypatch):
    backend = FaceGestureBackend(FacegestureConfig())
    monkeypatch.setattr(backend, "_build_landmarker", lambda: None)
    backend.run()  # must return, not raise


def test_run_releases_a_held_gesture_when_the_camera_loop_ends():
    """A shutdown mid-gesture must release the key, not leave RECORDING open."""
    ended = []
    backend = FaceGestureBackend(FacegestureConfig(), lambda n: None, lambda: ended.append(1))
    backend._switch.update(1.0)
    backend._switch.update(1.0)
    backend._switch.update(1.0)
    assert backend._switch.held is True

    class _Cap:
        def release(self):
            pass

    class _Landmarker:
        def close(self):
            pass

    backend._build_landmarker = lambda: _Landmarker()
    backend._open_camera = lambda: (_Cap(), object())
    backend._loop = lambda *a: None
    backend.run()
    assert ended == [1]


@pytest.mark.parametrize("value", ["wink", "eyebrow", ""])
def test_configcheck_repairs_an_invalid_gesture(value):
    problems = []
    section = build_section(
        FacegestureConfig, {"gesture": value}, "facegesture", problems
    )
    assert section.gesture == FacegestureConfig().gesture
    assert problems


def test_configcheck_accepts_every_real_gesture():
    from yazses.facegesture.detector import gesture_names

    for name in gesture_names():
        problems = []
        section = build_section(
            FacegestureConfig, {"gesture": name}, "facegesture", problems
        )
        assert section.gesture == name
        assert problems == []


def test_a_case_variant_survives_config_and_the_backend():
    """configcheck accepts enum values case-insensitively and stores what was
    written, so the backend must normalise or the gesture is silently swapped."""
    problems = []
    section = build_section(
        FacegestureConfig, {"gesture": "Jaw_Open"}, "facegesture", problems
    )
    assert problems == []
    assert FaceGestureBackend(section)._gesture == "jaw_open"


class _Cat:
    def __init__(self, name, score):
        self.category_name, self.score = name, score


class _Cv2:
    COLOR_BGR2RGB = 0

    def cvtColor(self, frame, code):
        return frame


class _Mp:
    ImageFormat = type("F", (), {"SRGB": 0})

    def Image(self, image_format, data):
        return data


class _Cap:
    def read(self):
        return True, object()


def test_the_capture_loop_turns_blendshape_frames_into_hold_callbacks():
    """The frame plumbing, end to end, with fakes for the camera and the model.

    `_score` reaches three deep into MediaPipe's result shape
    (`face_blendshapes[0][n].category_name` / `.score`). The pure detector cannot
    catch a mistake there — it never sees a frame.
    """
    frames = [0.0, 0.9, 0.9, 0.9, 0.1, 0.1, 0.1]

    class _Landmarker:
        def detect(self, image):
            return type("R", (), {"face_blendshapes": [[_Cat("jawOpen", frames[0])]]})

    cap = _Cap()
    events = []
    cfg = replace(FacegestureConfig(), min_hold_frames=2, min_release_frames=2, fps=60)
    backend = FaceGestureBackend(
        cfg, lambda n: events.append("start"), lambda: events.append("end")
    )

    # Advance the script from the camera, and stop when it runs out — waiting on a
    # wall-clock guess instead would make this test a timeout waiting to happen.
    def _read():
        frames.pop(0)
        if not frames:
            backend.stop()
        return True, object()

    cap.read = _read
    backend._loop(_Landmarker(), cap, _Cv2(), _Mp())
    assert events == ["start", "end"]


def test_a_frame_with_no_face_scores_as_no_reading():
    class _Landmarker:
        def detect(self, image):
            return type("R", (), {"face_blendshapes": []})

    backend = FaceGestureBackend(FacegestureConfig())
    assert backend._score(_Landmarker(), _Cap(), _Cv2(), _Mp()) is None


def test_a_detector_that_raises_does_not_end_the_loop():
    """One bad frame must not cost the user their only input method."""
    calls = []

    class _Landmarker:
        def detect(self, image):
            calls.append(1)
            raise RuntimeError("bad frame")

    backend = FaceGestureBackend(replace(FacegestureConfig(), fps=60))
    cap = _Cap()

    def _read():
        if len(calls) >= 3:
            backend.stop()
        return True, object()

    cap.read = _read
    backend._loop(_Landmarker(), cap, _Cv2(), _Mp())
    # It kept going through three failing frames and exited only when asked to.
    assert len(calls) >= 3


def test_a_callback_that_raises_does_not_kill_the_capture_thread():
    """The daemon callback is not this module's code, and it runs in a thread
    whose death is silent."""
    def _boom(_n):
        raise RuntimeError("daemon exploded")

    FaceGestureBackend(FacegestureConfig(), _boom, lambda: None)._fire("start")
