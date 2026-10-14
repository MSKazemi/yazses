"""Characterisation: the face switch's OWN camera path, end to end (EYE-FACE-004, #404 follow-up).

When no shared camera source exists -- the shipped state, `[perception]` off -- the backend must
keep doing exactly what it has always done: open its own `cv2.VideoCapture`, run its own
FaceLandmarker, step the detectors once per frame it reads, and tear both down in a fixed order.
These tests pin that sequence through the real `run()` with fakes at the three heavy seams
(`_build_landmarker`, `_open_camera`, `mediapipe`), and were written green against the code
BEFORE the shared-camera path was added, so a later change that disturbs this path fails here
rather than in front of a user.

Every score is a hand-written numeric fixture; none of it is evidence about a real face.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from types import SimpleNamespace

from yazses.config import FacegestureConfig
from yazses.facegesture.backend import FaceGestureBackend


class _Cat:
    def __init__(self, name, score):
        self.category_name, self.score = name, score


class _Cv2:
    COLOR_BGR2RGB = 0

    def cvtColor(self, frame, code):
        return frame


class _FakeMediapipe(SimpleNamespace):
    """Just enough of `mediapipe` for `run()`'s `import mediapipe as mp`."""

    def __init__(self):
        super().__init__(
            ImageFormat=type("F", (), {"SRGB": 0}),
            Image=lambda image_format, data: data,
        )


def _wire(backend, frames, order):
    """Fake the camera + model seams of ``backend``; ``frames`` is a list of jawOpen or None."""
    queue = list(frames)

    class _Landmarker:
        def __init__(self):
            self.current = None

        def detect(self, image):
            shapes = [] if self.current is None else [[_Cat("jawOpen", self.current)]]
            return type("R", (), {"face_blendshapes": shapes})

        def close(self):
            order.append("landmarker.close")

    landmarker = _Landmarker()

    class _Cap:
        def read(self):
            landmarker.current = queue.pop(0)
            if not queue:
                backend.stop()
            return True, object()

        def release(self):
            order.append("cap.release")

    backend._build_landmarker = lambda: (order.append("landmarker.build"), landmarker)[1]
    backend._open_camera = lambda: (order.append("camera.open"), (_Cap(), _Cv2()))[1]


def _run(frames, monkeypatch, **cfg):
    monkeypatch.setitem(sys.modules, "mediapipe", _FakeMediapipe())
    events: list[str] = []
    order: list[str] = []
    backend = FaceGestureBackend(
        replace(FacegestureConfig(enabled=True), fps=60, **cfg),
        lambda n: events.append("start"),
        lambda: events.append("end"),
    )
    _wire(backend, frames, order)
    backend.run()
    return events, order


def test_run_opens_its_own_model_then_its_own_camera_and_closes_both_in_order(monkeypatch):
    events, order = _run([0.9] * 4 + [0.0] * 3, monkeypatch)
    assert order == ["landmarker.build", "camera.open", "cap.release", "landmarker.close"]
    assert events == ["start", "end"]


def test_a_backend_built_without_a_lease_has_no_shared_source():
    backend = FaceGestureBackend(FacegestureConfig(enabled=True))
    assert getattr(backend, "_lease", None) is None


def test_a_face_that_leaves_the_frame_mid_hold_releases_after_the_release_debounce(monkeypatch):
    events, _ = _run([0.9] * 4 + [None] * 3, monkeypatch)
    assert events == ["start", "end"]


def test_a_single_blurred_frame_does_not_cut_a_hold(monkeypatch):
    events, _ = _run([0.9] * 4 + [None] + [0.9] * 3 + [0.0] * 3, monkeypatch)
    assert events == ["start", "end"]


def test_speech_range_scores_below_the_hold_threshold_never_start_anything(monkeypatch):
    # Synthetic: a wobble that stays under the shipped 0.5 hold threshold.
    events, _ = _run([0.2, 0.3, 0.26, 0.3, 0.2] * 4, monkeypatch)
    assert events == []


def test_a_camera_that_will_not_open_ends_run_and_closes_the_model(monkeypatch):
    monkeypatch.setitem(sys.modules, "mediapipe", _FakeMediapipe())
    order: list[str] = []
    backend = FaceGestureBackend(FacegestureConfig(enabled=True))
    backend._build_landmarker = lambda: SimpleNamespace(close=lambda: order.append("lm.close"))
    backend._open_camera = lambda: (None, None)
    backend.run()
    assert order == ["lm.close"]


def test_the_camera_index_is_the_facegesture_sections_own(monkeypatch):
    seen: list[int] = []

    class _Cv2Probe:
        class VideoCapture:
            def __init__(self, index):
                seen.append(index)

            def isOpened(self):
                return False

            def release(self):
                pass

    monkeypatch.setitem(sys.modules, "cv2", _Cv2Probe)
    backend = FaceGestureBackend(replace(FacegestureConfig(enabled=True), camera_index=3))
    assert backend._open_camera() == (None, None)
    assert seen == [3]
