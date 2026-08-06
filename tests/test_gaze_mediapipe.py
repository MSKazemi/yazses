"""MediaPipe FaceLandmarker gaze backend + model download (design §3.3).

Hermetic: fake ``cv2``/``mediapipe`` module trees and a monkeypatched model
resolver stand in for the webcam and the ~3.7 MB TFLite asset, so the iris-offset
estimate and every None-branch are pinned in CI without a camera, the deps, or a
network fetch.
"""
from __future__ import annotations

import sys
import types

import pytest

from yazses.config import GazeConfig

# ---- fake landmark tree -----------------------------------------------------


class _Pt:
    def __init__(self, x, y):
        self.x = x
        self.y = y


def _landmarks(left_off, right_off):
    """478 landmarks with eye corners at 0.4/0.6 (width 0.2) so the iris offset
    equals the requested value: iris = 0.5 + off*0.2 → (iris-0.5)/0.2 = off."""
    pts = [_Pt(0.5, 0.5) for _ in range(478)]
    pts[33], pts[133] = _Pt(0.4, 0.5), _Pt(0.6, 0.5)
    pts[468] = _Pt(0.5 + left_off[0] * 0.2, 0.5 + left_off[1] * 0.2)
    pts[362], pts[263] = _Pt(0.4, 0.5), _Pt(0.6, 0.5)
    pts[473] = _Pt(0.5 + right_off[0] * 0.2, 0.5 + right_off[1] * 0.2)
    return pts


class _FakeResult:
    def __init__(self, landmarks):
        self.face_landmarks = [landmarks] if landmarks is not None else []


class _FakeLandmarker:
    def __init__(self):
        self.result = _FakeResult(_landmarks((0.5, 0.0), (0.5, 0.0)))
        self.raise_on_detect = False

    def detect(self, _image):
        if self.raise_on_detect:
            raise RuntimeError("inference failed")
        return self.result


class _FakeCapture:
    def __init__(self, index):
        self.index = index
        self.read_result = (True, object())
        self.released = False

    def read(self):
        return self.read_result

    def release(self):
        self.released = True


@pytest.fixture
def mp_backend(monkeypatch):
    """Build a MediapipeGazeBackend with fake cv2/mediapipe + a stub model path."""
    captures: list[_FakeCapture] = []
    landmarker = _FakeLandmarker()

    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.VideoCapture = lambda i: captures.append(_FakeCapture(i)) or captures[-1]
    fake_cv2.cvtColor = lambda frame, code: frame
    fake_cv2.COLOR_BGR2RGB = 4

    # mediapipe + nested tasks.python.vision tree
    fake_mp = types.ModuleType("mediapipe")
    fake_mp.Image = lambda image_format, data: ("img", data)
    fake_mp.ImageFormat = types.SimpleNamespace(SRGB=1)
    fake_tasks = types.ModuleType("mediapipe.tasks")
    fake_python = types.ModuleType("mediapipe.tasks.python")
    fake_python.BaseOptions = lambda model_asset_path: ("base", model_asset_path)
    fake_vision = types.ModuleType("mediapipe.tasks.python.vision")
    fake_vision.FaceLandmarkerOptions = lambda **kw: kw
    fake_vision.RunningMode = types.SimpleNamespace(IMAGE="image")
    fake_vision.FaceLandmarker = types.SimpleNamespace(create_from_options=lambda opts: landmarker)
    fake_tasks.python = fake_python
    fake_python.vision = fake_vision

    for name, mod in {
        "cv2": fake_cv2, "mediapipe": fake_mp, "mediapipe.tasks": fake_tasks,
        "mediapipe.tasks.python": fake_python, "mediapipe.tasks.python.vision": fake_vision,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)

    monkeypatch.setattr(
        "yazses.gaze.download.ensure_face_landmarker", lambda *a, **k: "/tmp/fake.task"
    )

    from yazses.gaze.mediapipe_backend import MediapipeGazeBackend

    backend = MediapipeGazeBackend(GazeConfig(enabled=True, camera_index=1))
    fake_cv2._captures = captures
    return backend, fake_cv2, landmarker


# ---- tests ------------------------------------------------------------------


def test_name_is_mediapipe(mp_backend):
    backend, _, _ = mp_backend
    assert backend.name == "mediapipe"


def test_camera_opened_lazily_at_configured_index(mp_backend):
    backend, fake_cv2, _ = mp_backend
    assert fake_cv2._captures == []  # ADR-011: not opened at construction
    backend.estimate()
    assert fake_cv2._captures[0].index == 1


def test_estimate_returns_mean_iris_offset(mp_backend):
    backend, _, landmarker = mp_backend
    landmarker.result = _FakeResult(_landmarks((0.4, -0.2), (0.6, 0.2)))
    # mean of the two eyes → (0.5, 0.0)
    gx, gy = backend.estimate()
    assert gx == pytest.approx(0.5)
    assert gy == pytest.approx(0.0)


def test_estimate_none_when_no_frame(mp_backend):
    backend, fake_cv2, _ = mp_backend
    backend.estimate()
    fake_cv2._captures[0].read_result = (False, None)
    assert backend.estimate() is None


def test_estimate_none_when_no_face(mp_backend):
    backend, _, landmarker = mp_backend
    landmarker.result = _FakeResult(None)  # empty face_landmarks
    assert backend.estimate() is None


def test_estimate_none_when_detect_raises(mp_backend):
    backend, _, landmarker = mp_backend
    landmarker.raise_on_detect = True
    assert backend.estimate() is None


def test_close_releases_camera(mp_backend):
    backend, fake_cv2, _ = mp_backend
    backend.estimate()
    backend.close()
    assert fake_cv2._captures[0].released is True
    assert backend._cap is None


# ---- factory routes to mediapipe -------------------------------------------


def test_factory_builds_mediapipe_by_default(monkeypatch):
    built = {}

    def _fake_ctor(config):
        built["cfg"] = config
        return "MP"

    fake_mod = types.ModuleType("yazses.gaze.mediapipe_backend")
    fake_mod.MediapipeGazeBackend = _fake_ctor
    monkeypatch.setitem(sys.modules, "yazses.gaze.mediapipe_backend", fake_mod)
    from yazses.gaze.factory import build_gaze

    assert build_gaze(GazeConfig(enabled=True)) == "MP"  # default backend == mediapipe
    assert built["cfg"].backend == "mediapipe"


# ---- download helper --------------------------------------------------------


def test_ensure_face_landmarker_returns_existing_without_download(tmp_path, monkeypatch):
    from yazses.gaze import download

    model = tmp_path / "face_landmarker.task"
    model.write_bytes(b"x" * 10)
    called = {"n": 0}
    monkeypatch.setattr(download.urllib.request, "urlretrieve", lambda *a, **k: called.__setitem__("n", 1))
    out = download.ensure_face_landmarker(model)
    assert out == model
    assert called["n"] == 0  # already present → no fetch


def test_ensure_face_landmarker_downloads_when_absent(tmp_path, monkeypatch):
    from yazses.gaze import download

    model = tmp_path / "sub" / "face_landmarker.task"
    calls = []

    def fake_retrieve(url, dest):
        calls.append((url, dest))
        with open(dest, "wb") as fh:
            fh.write(b"model")

    monkeypatch.setattr(download.urllib.request, "urlretrieve", fake_retrieve)
    out = download.ensure_face_landmarker(model)
    assert out == model and model.exists()
    assert calls[0][0] == download.FACE_LANDMARKER_URL
