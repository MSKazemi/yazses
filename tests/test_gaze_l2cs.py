"""L2CS-Net webcam gaze backend (design/v2-cognitive-layer §3.3).

Covers the camera-touching backend (`yazses.gaze.l2cs.L2csGazeBackend`) without
the heavy `gaze` extra: fake ``cv2``/``torch``/``l2cs`` modules are injected so
the OpenCV capture path and the L2CS ``step`` → ``(yaw, pitch)`` flow are exercised
in CI on any machine (no webcam, no model download). The real hardware path is
verified separately by capturing a live frame; this pins the branch behaviour.
"""
from __future__ import annotations

import sys
import types

import pytest

from yazses.config import GazeConfig


# ---- fakes ------------------------------------------------------------------


class _FakeResults:
    """Mimics an L2CS pipeline result: parallel yaw/pitch arrays, one per face."""

    def __init__(self, yaw=(), pitch=()):
        self.yaw = list(yaw)
        self.pitch = list(pitch)


class _FakePipeline:
    """Stands in for ``l2cs.Pipeline``; ``step`` returns a preset result or raises."""

    def __init__(self, *_, **__):
        self.step_result = _FakeResults(yaw=[0.42], pitch=[-0.17])
        self.raise_on_step = False
        self.steps = 0

    def step(self, _frame):
        self.steps += 1
        if self.raise_on_step:
            raise RuntimeError("inference blew up")
        return self.step_result


class _FakeCapture:
    """Stands in for ``cv2.VideoCapture``; hands out preset frames then EOF."""

    def __init__(self, index):
        self.index = index
        self.read_result = (True, object())  # (ok, frame); frame is opaque here
        self.released = False
        self.reads = 0

    def read(self):
        self.reads += 1
        return self.read_result

    def release(self):
        self.released = True


@pytest.fixture
def gaze_backend(monkeypatch):
    """Build an ``L2csGazeBackend`` with fake cv2/torch/l2cs modules injected.

    Returns ``(backend, cv2_module, pipeline)`` so a test can steer the fake
    capture's ``read_result`` and the fake pipeline's ``step`` behaviour.
    """
    captures: list[_FakeCapture] = []

    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.VideoCapture = lambda index: captures.append(_FakeCapture(index)) or captures[-1]

    fake_torch = types.ModuleType("torch")
    fake_torch.device = lambda name: name

    fake_l2cs = types.ModuleType("l2cs")
    fake_l2cs.Pipeline = _FakePipeline

    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "l2cs", fake_l2cs)

    from yazses.gaze.l2cs import L2csGazeBackend

    backend = L2csGazeBackend(GazeConfig(enabled=True, camera_index=2, confidence_min=0.5))
    fake_cv2._captures = captures  # expose for assertions
    return backend, fake_cv2, backend._pipeline


# ---- tests ------------------------------------------------------------------


def test_name_is_l2cs(gaze_backend):
    backend, _, _ = gaze_backend
    assert backend.name == "l2cs"


def test_camera_opened_lazily_not_at_construction(gaze_backend):
    backend, fake_cv2, _ = gaze_backend
    # ADR-011: the camera must not be opened until we actually sample.
    assert fake_cv2._captures == []
    backend.estimate()
    assert len(fake_cv2._captures) == 1
    assert fake_cv2._captures[0].index == 2  # honours config.camera_index


def test_estimate_returns_yaw_pitch_for_a_detected_face(gaze_backend):
    backend, _, pipeline = gaze_backend
    pipeline.step_result = _FakeResults(yaw=[0.42], pitch=[-0.17])
    assert backend.estimate() == (0.42, -0.17)


def test_estimate_takes_the_first_face_when_several_detected(gaze_backend):
    backend, _, pipeline = gaze_backend
    pipeline.step_result = _FakeResults(yaw=[1.0, 2.0], pitch=[3.0, 4.0])
    assert backend.estimate() == (1.0, 3.0)


def test_estimate_none_when_no_frame(gaze_backend):
    backend, fake_cv2, _ = gaze_backend
    backend.estimate()  # opens the camera
    fake_cv2._captures[0].read_result = (False, None)
    assert backend.estimate() is None


def test_estimate_none_when_frame_is_none_even_if_ok(gaze_backend):
    backend, fake_cv2, _ = gaze_backend
    backend.estimate()
    fake_cv2._captures[0].read_result = (True, None)
    assert backend.estimate() is None


def test_estimate_none_when_pipeline_returns_none(gaze_backend):
    backend, _, pipeline = gaze_backend
    pipeline.step_result = None
    assert backend.estimate() is None


def test_estimate_none_when_no_face_detected(gaze_backend):
    backend, _, pipeline = gaze_backend
    pipeline.step_result = _FakeResults(yaw=[], pitch=[])  # empty → no face
    assert backend.estimate() is None


def test_estimate_none_when_pipeline_raises(gaze_backend):
    backend, _, pipeline = gaze_backend
    pipeline.raise_on_step = True
    assert backend.estimate() is None  # swallowed, not propagated


def test_close_releases_camera_and_reopens_on_next_estimate(gaze_backend):
    backend, fake_cv2, _ = gaze_backend
    backend.estimate()
    first = fake_cv2._captures[0]
    backend.close()
    assert first.released is True
    assert backend._cap is None
    backend.estimate()  # lazily reopens
    assert len(fake_cv2._captures) == 2


def test_close_is_a_noop_before_any_capture(gaze_backend):
    backend, fake_cv2, _ = gaze_backend
    backend.close()  # never opened → must not raise
    assert fake_cv2._captures == []
