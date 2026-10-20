"""Glance-Type gaze sees the same camera and the same model on both paths (#396).

The other three #396 files compare what the two paths *do with* a face:

* ``tests/test_gaze_glance_type_unchanged.py`` -- the arithmetic, landmark for landmark;
* ``tests/test_gaze_glance_type_end_to_end.py`` -- the routing decisions, down both whole
  paths, over one fake landmarker;
* ``tests/test_gaze_shared_source.py`` -- who owns the camera, and the wiring.

All three hand both paths the **same landmarks**, so none of them can see a difference in
what produces the landmarks. Two things do, and both sit outside the gaze code:

* **The FaceLandmarker's options.** The shared processor is built by the daemon for every
  camera feature and passes ``min_face_detection_confidence`` and
  ``min_face_presence_confidence`` explicitly (its ``DEFAULT_PRESENCE_CONFIDENCE``); the
  legacy gaze backend passes neither and gets MediaPipe's defaults. Today they agree, at
  0.5. Tune the face-switch floor to 0.7 and Glance-Type would silently drop every face
  MediaPipe scores between 0.5 and 0.7 -- "no gaze, focused window" -- with every existing
  equivalence test still green, because they all inject a result rather than a detection.
* **The asset and the device.** The daemon picks the shared processor's model path and the
  capture's camera index from config sections gaze does not own; an existing ``[gaze]
  model_path`` or ``camera_index`` must still mean the same file and the same device.

So these tests build both paths through their real constructors, under a fake
``cv2``/``mediapipe`` tree that **records** what each asked for, and compare the requests.
The shared side is built the way the daemon builds it (``Daemon._build_perception_source``),
not by hand, so a change in the daemon's wiring is a change here too.

Hermetic: no camera, no model file, no network. One test reads MediaPipe's own option
defaults and runs only where the real ``mediapipe`` package is installed.
"""
from __future__ import annotations

import json
import subprocess
import sys
import types
from importlib.machinery import PathFinder

import pytest

from yazses.config import Config

# --------------------------------------------------------------------------- #
# What the comparison is over
# --------------------------------------------------------------------------- #

#: ``FaceLandmarkerOptions`` defaults for every field the legacy backend leaves unset.
#: Source: ``mediapipe/tasks/python/vision/face_landmarker.py``, ``class
#: FaceLandmarkerOptions`` (read from the mediapipe 1.0.1 and 1.1.1 wheels on 2026-10-20;
#: identical in both). ``test_the_pinned_defaults_are_mediapipes_own`` re-reads them from
#: the installed package wherever it is present, so this table cannot quietly go stale.
_MEDIAPIPE_DEFAULTS: dict[str, object] = {
    "running_mode": "IMAGE",
    "num_faces": 1,
    "min_face_detection_confidence": 0.5,
    "min_face_presence_confidence": 0.5,
    "min_tracking_confidence": 0.5,
    "output_face_blendshapes": False,
    "output_facial_transformation_matrixes": False,
}

#: Options that change *which faces are found or where their landmarks land*. Every one
#: must be equal on both paths, or the two paths are not looking at the same face.
_LANDMARK_AFFECTING = frozenset({
    "model",
    "running_mode",
    "num_faces",
    "min_face_detection_confidence",
    "min_face_presence_confidence",
    "min_tracking_confidence",
})

#: Options that only add extra outputs to the same result. The shared processor asks for
#: them because head pose and the face switch read them; gaze reads landmarks only.
_OUTPUT_ONLY = frozenset({"output_face_blendshapes", "output_facial_transformation_matrixes"})


def _effective(kwargs: dict) -> dict[str, object]:
    """The options a landmarker was really built with: MediaPipe's defaults, then the
    caller's explicit arguments, with ``base_options`` reduced to the asset path."""
    out = dict(_MEDIAPIPE_DEFAULTS)
    for key, value in kwargs.items():
        if key == "base_options":
            out["model"] = value[1]
        elif key == "running_mode":
            out[key] = str(value)
        else:
            out[key] = value
    return out


def _landmark_differences(legacy: dict, shared: dict) -> dict[str, tuple]:
    """Every option the two paths disagree on, other than the output-only ones."""
    keys = set(legacy) | set(shared)
    unclassified = keys - _LANDMARK_AFFECTING - _OUTPUT_ONLY
    # A new option MediaPipe grows, or a new argument either constructor starts passing,
    # must be classified before it can be compared -- never silently ignored.
    assert not unclassified, f"classify these FaceLandmarker options first: {sorted(unclassified)}"
    return {
        key: (legacy.get(key), shared.get(key))
        for key in sorted(keys - _OUTPUT_ONLY)
        if legacy.get(key) != shared.get(key)
    }


# --------------------------------------------------------------------------- #
# A fake cv2/mediapipe tree that records what it is asked for
# --------------------------------------------------------------------------- #


class _Recorder:
    def __init__(self) -> None:
        self.options: list[dict] = []        # one per FaceLandmarker built, in order
        self.devices: list[int] = []         # one per cv2.VideoCapture built, in order
        self.capture_settings: list[tuple] = []  # every VideoCapture.set(...) call


class _Capture:
    def __init__(self, recorder: _Recorder, index: int) -> None:
        self._recorder = recorder
        self.index = index

    def isOpened(self) -> bool:  # noqa: N802 - OpenCV's spelling
        return True

    def read(self):
        return True, object()

    def set(self, prop, value):
        self._recorder.capture_settings.append((self.index, prop, value))
        return True

    def release(self) -> None:
        pass


class _Landmarker:
    def detect(self, _image):
        return types.SimpleNamespace(
            face_landmarks=[], face_blendshapes=[], facial_transformation_matrixes=[]
        )

    def close(self) -> None:
        pass


_AUTO_MODEL = "/cache/yazses/face_landmarker.task"


@pytest.fixture
def recorder(monkeypatch) -> _Recorder:
    rec = _Recorder()

    def video_capture(index):
        rec.devices.append(index)
        return _Capture(rec, index)

    fake_cv2 = types.ModuleType("cv2")
    fake_cv2.VideoCapture = video_capture
    fake_cv2.cvtColor = lambda frame, code: frame
    fake_cv2.COLOR_BGR2RGB = 4

    fake_mp = types.ModuleType("mediapipe")
    fake_mp.Image = lambda image_format, data: ("img", data)
    fake_mp.ImageFormat = types.SimpleNamespace(SRGB=1)
    fake_tasks = types.ModuleType("mediapipe.tasks")
    fake_python = types.ModuleType("mediapipe.tasks.python")
    fake_python.BaseOptions = lambda model_asset_path: ("base", model_asset_path)
    fake_vision = types.ModuleType("mediapipe.tasks.python.vision")

    def options(**kwargs):
        rec.options.append(kwargs)
        return kwargs

    fake_vision.FaceLandmarkerOptions = options
    fake_vision.RunningMode = types.SimpleNamespace(IMAGE="IMAGE", VIDEO="VIDEO")
    fake_vision.FaceLandmarker = types.SimpleNamespace(
        create_from_options=lambda opts: _Landmarker()
    )
    fake_tasks.python = fake_python
    fake_python.vision = fake_vision

    for name, module in {
        "cv2": fake_cv2,
        "mediapipe": fake_mp,
        "mediapipe.tasks": fake_tasks,
        "mediapipe.tasks.python": fake_python,
        "mediapipe.tasks.python.vision": fake_vision,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    # Both paths resolve an empty model_path through this one resolver; neither may reach
    # the network from a test.
    monkeypatch.setattr("yazses.gaze.download.ensure_face_landmarker", lambda *a, **k: _AUTO_MODEL)
    return rec


def _config(*, model_path: str = "", camera_index: int = 0) -> Config:
    """A config with Glance-Type on the shared source: the case #396 changed."""
    cfg = Config()
    cfg.gaze.enabled = True
    cfg.gaze.route_dictation = True
    cfg.gaze.model_path = model_path
    cfg.gaze.camera_index = camera_index
    cfg.perception.enabled = True
    cfg.perception.camera_index = camera_index
    return cfg


def _legacy_options(cfg: Config, recorder: _Recorder) -> dict:
    from yazses.gaze.mediapipe_backend import MediapipeGazeBackend

    before = len(recorder.options)
    MediapipeGazeBackend(cfg.gaze)
    assert len(recorder.options) == before + 1, "the legacy backend builds exactly one model"
    return _effective(recorder.options[-1])


def _daemon_source(cfg: Config):
    """The shared source exactly as the daemon builds it for *cfg*."""
    from yazses.core.daemon import Daemon
    from yazses.gaze.shared import shared_source_for_gaze
    from yazses.platform import get_platform

    daemon = Daemon(config=Config(), platform=get_platform())
    source = daemon._build_perception_source(cfg)
    assert source is not None, "[perception] is on, so the daemon must build a source"
    # The precondition for any of this mattering: gaze really leases this source.
    assert shared_source_for_gaze(cfg.gaze, cfg.perception, source).source is source
    return source


def _shared_options(cfg: Config, recorder: _Recorder) -> dict:
    source = _daemon_source(cfg)
    before = len(recorder.options)
    # The factory the source calls on its first open; calling it directly builds the same
    # processor without starting the capture thread.
    source._processor_factory()
    assert len(recorder.options) == before + 1, "the shared source builds exactly one model"
    return _effective(recorder.options[-1])


# --------------------------------------------------------------------------- #
# The model
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "model_path",
    ["", "/models/my-face_landmarker.task"],
    ids=["auto-downloaded", "gaze-model_path-override"],
)
def test_both_paths_build_the_landmarker_with_the_same_landmark_options(recorder, model_path):
    cfg = _config(model_path=model_path)
    legacy = _legacy_options(cfg, recorder)
    shared = _shared_options(cfg, recorder)

    assert _landmark_differences(legacy, shared) == {}
    # Spelled out, so a reader sees what "the same" was measured as, and so the comparison
    # above is not vacuously green over an empty or partial set of keys.
    expected_model = model_path or _AUTO_MODEL
    for options in (legacy, shared):
        assert options["model"] == expected_model
        assert options["running_mode"] == "IMAGE"
        assert options["num_faces"] == 1
        assert options["min_face_detection_confidence"] == 0.5
        assert options["min_face_presence_confidence"] == 0.5
        assert options["min_tracking_confidence"] == 0.5


def test_the_only_differences_are_extra_outputs_gaze_does_not_read(recorder):
    legacy = _legacy_options(_config(), recorder)
    shared = _shared_options(_config(), recorder)
    differing = {key for key in set(legacy) | set(shared) if legacy.get(key) != shared.get(key)}
    assert differing <= _OUTPUT_ONLY
    # The shared processor does ask for both by default, for head pose and the face switch.
    assert shared["output_face_blendshapes"] is True
    assert shared["output_facial_transformation_matrixes"] is True
    assert legacy["output_face_blendshapes"] is False


def test_the_comparison_catches_a_tuned_detection_floor(recorder):
    """The guard above must be able to fail. A shared processor whose presence floor was
    raised for the face switch is exactly the drift it exists to catch."""
    from yazses.perception.mediapipe_backend import MediapipeFaceProcessor

    legacy = _legacy_options(_config(), recorder)
    MediapipeFaceProcessor(model_path=_AUTO_MODEL, presence_confidence=0.7)
    tuned = _effective(recorder.options[-1])
    assert _landmark_differences(legacy, tuned) == {
        "min_face_detection_confidence": (0.5, 0.7),
        "min_face_presence_confidence": (0.5, 0.7),
    }


def test_the_comparison_refuses_an_option_nobody_classified(recorder):
    legacy = _legacy_options(_config(), recorder)
    with pytest.raises(AssertionError, match="classify these FaceLandmarker options"):
        _landmark_differences(legacy, {**legacy, "min_hand_detection_confidence": 0.5})


@pytest.mark.skipif(
    # PathFinder searches sys.path only: a fake ``mediapipe`` another test left in
    # sys.modules (a ModuleType with no __spec__) must neither fool nor crash this check.
    PathFinder.find_spec("mediapipe") is None,
    reason="the real mediapipe package (the `gaze` extra) is not installed",
)
def test_the_pinned_defaults_are_mediapipes_own():
    """``_MEDIAPIPE_DEFAULTS`` is what the legacy backend inherits by passing nothing.
    Read from the installed dataclass in a child interpreter, so the real package never
    shares a ``sys.modules`` with the fakes the rest of the suite installs."""
    probe = (
        "import dataclasses, json\n"
        "from mediapipe.tasks.python.vision import face_landmarker as f\n"
        "out = {}\n"
        "for field in dataclasses.fields(f.FaceLandmarkerOptions):\n"
        "    if field.default is dataclasses.MISSING:\n"
        "        continue\n"
        "    value = field.default\n"
        "    out[field.name] = getattr(value, 'name', value)\n"
        "print(json.dumps(out))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    real = json.loads(result.stdout.strip().splitlines()[-1])
    for key, pinned in _MEDIAPIPE_DEFAULTS.items():
        assert real.get(key) == pinned, f"mediapipe's default for {key} is now {real.get(key)!r}"


# --------------------------------------------------------------------------- #
# The camera
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("camera_index", [0, 2])
def test_both_paths_open_the_same_device_with_the_same_capture_settings(recorder, camera_index):
    """An existing ``[gaze] camera_index`` still means the same physical camera, and the
    shared capture negotiates nothing (no resolution, fps or format) the legacy one did not."""
    from yazses.gaze.mediapipe_backend import MediapipeGazeBackend

    cfg = _config(camera_index=camera_index)

    legacy = MediapipeGazeBackend(cfg.gaze)
    legacy.estimate_sample()  # the legacy backend opens its camera on the first sample
    legacy.close()
    legacy_devices, legacy_settings = list(recorder.devices), list(recorder.capture_settings)

    capture = _daemon_source(cfg)._capture_factory()
    capture.open()
    capture.read()
    capture.close()
    shared_devices = recorder.devices[len(legacy_devices):]
    shared_settings = recorder.capture_settings[len(legacy_settings):]

    assert legacy_devices == shared_devices == [camera_index]
    assert legacy_settings == shared_settings == []
