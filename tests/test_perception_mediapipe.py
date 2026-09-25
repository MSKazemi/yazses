"""One MediaPipe result → three channels, and a failure in one that stays in one.

`src/yazses/perception/mediapipe_backend.py` (ADR-v2-145, EYE-CAM-002) is the model
half of the shared camera source: one FaceLandmarker, one `detect` per frame, three
derived channels out. The claims worth a test are the ones a reader cannot check by
looking — that the landmarker really is *one* object however many consumers arrive,
that the camera behind it is opened once, and above all that a missing transform
costs head pose **and nothing else**. That last one is the criterion this task is
most likely to fail silently, so every missing-piece case below is its own test with
its own assertion about the channels that survived.

Hermetic, like `tests/test_gaze_mediapipe.py`, whose fake `cv2`/`mediapipe` module
tree these extend rather than replace: the fakes here add the two outputs EYE-CAM-002
turns on (the facial transformation matrix and the blendshapes) and count how many
landmarkers were created. No camera, no model, no `gaze` extra, no network.
"""
from __future__ import annotations

import logging
import math
import sys
import types
import weakref

import pytest

from yazses.perception import SharedPerceptionSource, SourceState
from yazses.perception.derive import (
    blendshape_activations,
    derive_face,
    derive_gaze,
    derive_head_pose,
    euler_angles,
    iris_offset,
)

# --------------------------------------------------------------------------- #
# Fake MediaPipe results — landmarks, a transform, blendshapes
# --------------------------------------------------------------------------- #


class Pt:
    """A landmark, as MediaPipe hands one over: something with `.x` and `.y`."""

    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y


class Cat:
    """A blendshape category, as MediaPipe hands one over."""

    def __init__(self, name, score) -> None:
        self.category_name = name
        self.score = score


class Frame:
    """Stands in for whatever the capture hands back. Identity is the point."""


def landmarks(left=(0.5, 0.0), right=(0.5, 0.0)):
    """478 landmarks whose iris offsets are exactly *left* and *right*.

    The eye corners sit at 0.4/0.6 (width 0.2), so an iris at `0.5 + off * 0.2`
    normalises back to `off` — the same construction `tests/test_gaze_mediapipe.py`
    uses, so both suites are asserting against one arithmetic, not two.
    """
    pts = [Pt(0.5, 0.5) for _ in range(478)]
    pts[33], pts[133] = Pt(0.4, 0.5), Pt(0.6, 0.5)
    pts[468] = Pt(0.5 + left[0] * 0.2, 0.5 + left[1] * 0.2)
    pts[362], pts[263] = Pt(0.4, 0.5), Pt(0.6, 0.5)
    pts[473] = Pt(0.5 + right[0] * 0.2, 0.5 + right[1] * 0.2)
    return pts


def _matmul(a, b):
    return [[sum(a[r][k] * b[k][c] for k in range(3)) for c in range(3)] for r in range(3)]


def rotation(yaw: float, pitch: float, roll: float):
    """A 4x4 row-major facial transformation matrix for `R = Rz(roll)·Ry(yaw)·Rx(pitch)`.

    Built from the angles rather than copied from a capture, so the head-pose test
    is a round trip: these angles in, the same angles out, or the decomposition is
    wrong in a way no eyeball on a real face would catch.
    """
    cx, sx = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cz, sz = math.cos(roll), math.sin(roll)
    rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    block = _matmul(_matmul(rz, ry), rx)
    return [[*block[0], 0.0], [*block[1], 0.0], [*block[2], 0.0], [0.0, 0.0, 0.0, 1.0]]


BLENDSHAPES = [Cat("jawOpen", 0.8), Cat("browInnerUp", 0.1)]


class FakeResult:
    """A FaceLandmarkerResult: one list per detected face, per output."""

    def __init__(self, *, faces=True, transform=True, shapes=True, offsets=None,
                 angles=(0.2, -0.1, 0.05), categories=None) -> None:
        left, right = offsets or ((0.5, 0.0), (0.5, 0.0))
        self.face_landmarks = [landmarks(left, right)] if faces else []
        self.facial_transformation_matrixes = [rotation(*angles)] if transform else []
        if shapes:
            self.face_blendshapes = [BLENDSHAPES if categories is None else categories]
        else:
            self.face_blendshapes = []


class FakeLandmarker:
    """The one model: counts detections, closes once, and can be made to raise."""

    def __init__(self, options) -> None:
        self.options = options
        self.result = FakeResult()
        self.detections = 0
        self.closes = 0
        self.detect_error: Exception | None = None

    def detect(self, image):
        self.detections += 1
        if self.detect_error is not None:
            raise self.detect_error
        return self.result

    def close(self) -> None:
        self.closes += 1


class FakeVideoCapture:
    """A `cv2.VideoCapture`, counted: how many were built is the ADR's hard gate."""

    def __init__(self, index) -> None:
        self.index = index
        self.opened = True
        self.released = 0
        self.frames: list[object] = []

    def isOpened(self):  # noqa: N802 - the cv2 spelling
        return self.opened

    def read(self):
        frame = Frame()
        self.frames.append(frame)
        return True, frame

    def release(self):
        self.released += 1


class MediaPipeWorld:
    """The fake `cv2`/`mediapipe` tree, plus counters for what was built."""

    def __init__(self) -> None:
        self.landmarkers: list[FakeLandmarker] = []
        self.captures: list[FakeVideoCapture] = []
        self.convert_error: Exception | None = None
        self.capture_opens_ok = True

    @property
    def landmarker(self) -> FakeLandmarker:
        assert len(self.landmarkers) == 1, f"{len(self.landmarkers)} landmarkers exist"
        return self.landmarkers[0]

    def _create(self, options):
        self.landmarkers.append(FakeLandmarker(options))
        return self.landmarkers[-1]

    def _cvt(self, frame, code):
        if self.convert_error is not None:
            raise self.convert_error
        return ("rgb", frame)

    def _capture(self, index):
        capture = FakeVideoCapture(index)
        capture.opened = self.capture_opens_ok
        self.captures.append(capture)
        return capture


@pytest.fixture
def world(monkeypatch) -> MediaPipeWorld:
    """Install the fake camera/model modules and a model path that needs no fetch."""
    world = MediaPipeWorld()

    cv2 = types.ModuleType("cv2")
    cv2.cvtColor = world._cvt
    cv2.COLOR_BGR2RGB = 4
    cv2.VideoCapture = world._capture

    mp = types.ModuleType("mediapipe")
    mp.Image = lambda image_format, data: ("img", image_format, data)
    mp.ImageFormat = types.SimpleNamespace(SRGB=1)
    tasks = types.ModuleType("mediapipe.tasks")
    python = types.ModuleType("mediapipe.tasks.python")
    python.BaseOptions = lambda model_asset_path: ("base", model_asset_path)
    vision = types.ModuleType("mediapipe.tasks.python.vision")
    vision.FaceLandmarkerOptions = lambda **kw: kw
    vision.RunningMode = types.SimpleNamespace(IMAGE="image")
    vision.FaceLandmarker = types.SimpleNamespace(create_from_options=world._create)
    tasks.python = python
    python.vision = vision

    for name, module in {
        "cv2": cv2, "mediapipe": mp, "mediapipe.tasks": tasks,
        "mediapipe.tasks.python": python, "mediapipe.tasks.python.vision": vision,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    def _no_fetch(*args, **kwargs):
        raise AssertionError("the model asset was resolved when a path was given")

    monkeypatch.setattr("yazses.gaze.download.ensure_face_landmarker", _no_fetch)
    return world


def build(world: MediaPipeWorld, **kwargs):
    """A processor over the fake world, with a model path so nothing is fetched."""
    from yazses.perception.mediapipe_backend import MediapipeFaceProcessor

    kwargs.setdefault("model_path", "/models/face_landmarker.task")
    return MediapipeFaceProcessor(**kwargs)


# --------------------------------------------------------------------------- #
# One model, one camera — the ADR's architectural gate, as a number
# --------------------------------------------------------------------------- #
def test_one_processor_builds_exactly_one_landmarker(world) -> None:
    build(world)
    assert len(world.landmarkers) == 1


def test_many_frames_reuse_the_one_landmarker(world) -> None:
    """A model rebuilt per frame would be a second instance and 100x the cost."""
    processor = build(world)
    for _ in range(5):
        processor.process(Frame(), 1.0)
    assert len(world.landmarkers) == 1
    assert world.landmarker.detections == 5


def test_two_consumers_share_one_landmarker_and_one_camera_open(world) -> None:
    """ADR-v2-145 invariant 1, end to end: the real processor over a counted camera.

    Gaze and the face switch each take a lease on the same source. What is counted
    is what actually touches the device — one `cv2.VideoCapture`, one FaceLandmarker
    and one `detect` for the observation both consumers then read.
    """
    from yazses.perception.camera import opencv_capture_factory
    from yazses.perception.mediapipe_backend import mediapipe_processor_factory

    source = SharedPerceptionSource(
        capture_factory=lambda: opencv_capture_factory(2),
        processor_factory=mediapipe_processor_factory(model_path="/models/f.task"),
        spawn=lambda body, name: _DeadWorker(),
    )
    gaze, switch = source.consumer("gaze"), source.consumer("facegesture")
    gaze.start()
    switch.start()
    try:
        assert source.observe() is True
        assert len(world.captures) == 1, "a second camera was opened"
        assert world.captures[0].index == 2
        assert len(world.landmarkers) == 1, "a second FaceLandmarker was built"
        assert world.landmarker.detections == 1, "the frame was inferred twice"
        assert gaze.latest() is switch.latest(), "the consumers saw different observations"
        assert gaze.latest().channels == ("gaze", "head_pose", "face")
    finally:
        source.close()
    assert world.captures[0].released == 1
    assert world.landmarker.closes == 1


class _DeadWorker:
    """A worker that never runs the loop, so these tests drive `observe` by hand."""

    def join(self, timeout: float | None = None) -> None:
        return None

    def is_alive(self) -> bool:
        return False


def test_the_options_ask_for_all_three_families_from_one_model(world) -> None:
    """EYE-CAM-002 at the MediaPipe layer: the two extra outputs are requested."""
    build(world)
    options = world.landmarker.options
    assert options["output_face_blendshapes"] is True
    assert options["output_facial_transformation_matrixes"] is True
    assert options["num_faces"] == 1
    assert options["running_mode"] == "image"
    assert options["base_options"] == ("base", "/models/face_landmarker.task")


def test_the_reported_confidence_is_the_floor_the_detector_was_given(world) -> None:
    """The number claimed and the number enforced come from one place, or they drift."""
    processor = build(world, presence_confidence=0.7)
    options = world.landmarker.options
    assert options["min_face_detection_confidence"] == pytest.approx(0.7)
    assert options["min_face_presence_confidence"] == pytest.approx(0.7)
    sample = processor.process(Frame(), 3.0)
    assert sample.head_pose.confidence == pytest.approx(0.7)
    assert sample.face.confidence == pytest.approx(0.7)


def test_a_given_model_path_resolves_no_asset(world) -> None:
    """The fixture's resolver raises, so reaching it at all fails this test."""
    build(world, model_path="  /models/explicit.task  ")
    assert world.landmarker.options["base_options"] == ("base", "/models/explicit.task")


def test_an_empty_model_path_falls_back_to_the_shipped_resolver(world, monkeypatch) -> None:
    monkeypatch.setattr(
        "yazses.gaze.download.ensure_face_landmarker", lambda *a, **k: "/cache/face.task"
    )
    from yazses.perception.mediapipe_backend import MediapipeFaceProcessor

    MediapipeFaceProcessor(model_path="")
    assert world.landmarker.options["base_options"] == ("base", "/cache/face.task")


def test_closing_the_processor_closes_the_model_once(world) -> None:
    processor = build(world)
    processor.close()
    processor.close()
    assert world.landmarker.closes == 1


# --------------------------------------------------------------------------- #
# The three channels, from one result and one clock
# --------------------------------------------------------------------------- #
def test_one_result_yields_three_channels_on_one_timestamp(world) -> None:
    processor = build(world)
    world.landmarker.result = FakeResult(
        offsets=((0.4, -0.2), (0.6, 0.2)), angles=(0.2, -0.1, 0.05)
    )
    sample = processor.process(Frame(), 12.5)

    assert sample.channels == ("gaze", "head_pose", "face")
    assert sample.timestamp_s == 12.5
    assert {s.timestamp_s for s in (sample.gaze, sample.head_pose, sample.face)} == {12.5}


def test_the_gaze_channel_is_the_mean_iris_offset_with_eye_agreement(world) -> None:
    from yazses.gaze.confidence import eye_agreement_confidence

    processor = build(world)
    world.landmarker.result = FakeResult(offsets=((0.4, -0.2), (0.6, 0.2)))
    gaze = processor.process(Frame(), 1.0).gaze

    assert gaze.raw_x == pytest.approx(0.5)
    assert gaze.raw_y == pytest.approx(0.0)
    assert gaze.confidence == pytest.approx(eye_agreement_confidence((0.4, -0.2), (0.6, 0.2)))
    assert gaze.confidence < 1.0, "eyes this far apart must not read as perfect agreement"


def test_the_head_pose_channel_round_trips_the_matrix_angles(world) -> None:
    processor = build(world)
    world.landmarker.result = FakeResult(angles=(0.3, -0.45, 0.15))
    pose = processor.process(Frame(), 1.0).head_pose

    assert pose.yaw == pytest.approx(0.3)
    assert pose.pitch == pytest.approx(-0.45)
    assert pose.roll == pytest.approx(0.15)


def test_the_face_channel_is_the_blendshape_names_and_scores(world) -> None:
    processor = build(world)
    face = processor.process(Frame(), 1.0).face

    assert dict(face.blendshapes) == {"jawOpen": 0.8, "browInnerUp": 0.1}
    assert face.score("jawOpen") == pytest.approx(0.8)
    assert face.score("mouthPucker") is None, "an unreported category must not read as relaxed"


def test_no_face_at_all_is_no_sample(world) -> None:
    """Not an empty sample: the source must be able to tell "nothing seen" apart."""
    processor = build(world)
    world.landmarker.result = FakeResult(faces=False, transform=False, shapes=False)
    assert processor.process(Frame(), 1.0) is None


# --------------------------------------------------------------------------- #
# Per-channel degradation — one test per missing piece (ADR-v2-145 invariant 6)
# --------------------------------------------------------------------------- #
def test_a_missing_transform_costs_only_the_head_pose_channel(world) -> None:
    processor = build(world)
    world.landmarker.result = FakeResult(transform=False)
    sample = processor.process(Frame(), 1.0)

    assert sample.channels == ("gaze", "face")
    assert sample.head_pose is None


def test_a_missing_blendshape_list_costs_only_the_face_channel(world) -> None:
    processor = build(world)
    world.landmarker.result = FakeResult(shapes=False)
    sample = processor.process(Frame(), 1.0)

    assert sample.channels == ("gaze", "head_pose")
    assert sample.face is None


def test_unreadable_landmarks_cost_only_the_gaze_channel(world) -> None:
    """A 468-landmark model has no irises; the other two outputs are unaffected."""
    processor = build(world)
    result = FakeResult()
    result.face_landmarks = [landmarks()[:468]]
    world.landmarker.result = result
    sample = processor.process(Frame(), 1.0)

    assert sample.channels == ("head_pose", "face")
    assert sample.gaze is None


def test_a_degenerate_transform_costs_only_head_pose_and_is_not_a_centred_pose(world) -> None:
    """A matrix of zeros decomposes to `0,0,0`: a confident lie about looking ahead."""
    processor = build(world)
    result = FakeResult()
    result.facial_transformation_matrixes = [[[0.0] * 4 for _ in range(4)]]
    world.landmarker.result = result
    sample = processor.process(Frame(), 1.0)

    assert sample.head_pose is None
    assert sample.channels == ("gaze", "face")


def test_a_non_finite_transform_entry_costs_only_head_pose(world) -> None:
    processor = build(world)
    result = FakeResult()
    broken = rotation(0.1, 0.1, 0.1)
    broken[0][0] = float("nan")
    result.facial_transformation_matrixes = [broken]
    world.landmarker.result = result
    sample = processor.process(Frame(), 1.0)

    assert sample.head_pose is None
    assert sample.channels == ("gaze", "face")


def test_a_mis_shaped_transform_costs_only_head_pose(world) -> None:
    processor = build(world)
    result = FakeResult()
    result.facial_transformation_matrixes = [[1.0] * 16]  # flat, not rows
    world.landmarker.result = result
    sample = processor.process(Frame(), 1.0)

    assert sample.head_pose is None
    assert sample.channels == ("gaze", "face")


def test_one_unusable_blendshape_score_costs_only_that_category(world) -> None:
    """A score outside 0..1 would raise inside `FaceSignal` and cost all three."""
    processor = build(world)
    world.landmarker.result = FakeResult(
        categories=[Cat("jawOpen", 0.6), Cat("browInnerUp", 4.2), Cat("mouthPucker", None)]
    )
    sample = processor.process(Frame(), 1.0)

    assert sample.channels == ("gaze", "head_pose", "face")
    assert dict(sample.face.blendshapes) == {"jawOpen": 0.6}


def test_a_face_with_no_usable_scores_is_still_a_face_channel(world) -> None:
    """Presence without a switch score is a fact, and it is not absence."""
    processor = build(world)
    world.landmarker.result = FakeResult(categories=[])
    sample = processor.process(Frame(), 1.0)

    assert sample.channels == ("gaze", "head_pose", "face")
    assert dict(sample.face.blendshapes) == {}
    assert sample.face.score("jawOpen") is None


@pytest.mark.parametrize(
    ("victim", "survivors"),
    [
        ("derive_gaze", ("head_pose", "face")),
        ("derive_head_pose", ("gaze", "face")),
        ("derive_face", ("gaze", "head_pose")),
    ],
)
def test_a_derivation_that_raises_costs_only_its_own_channel(
    world, monkeypatch, victim: str, survivors: tuple[str, ...]
) -> None:
    """The guard `derive.py` cannot provide: a bug, not a shape it anticipated."""
    processor = build(world)

    def explode(*args, **kwargs):
        raise RuntimeError("derivation is broken")

    monkeypatch.setattr(f"yazses.perception.mediapipe_backend.{victim}", explode)
    sample = processor.process(Frame(), 1.0)

    assert sample is not None, "one broken derivation took the whole observation"
    assert sample.channels == survivors


def test_every_derivation_failing_is_no_sample_rather_than_an_empty_one(world, monkeypatch) -> None:
    processor = build(world)
    for name in ("derive_gaze", "derive_head_pose", "derive_face"):
        monkeypatch.setattr(
            f"yazses.perception.mediapipe_backend.{name}", lambda *a, **k: None
        )
    assert processor.process(Frame(), 1.0) is None


# --------------------------------------------------------------------------- #
# A bad frame is a skipped frame, not a dead source
# --------------------------------------------------------------------------- #
def test_inference_that_raises_is_a_skipped_frame(world) -> None:
    processor = build(world)
    world.landmarker.detect_error = RuntimeError("inference failed")
    assert processor.process(Frame(), 1.0) is None


def test_a_frame_that_cannot_be_converted_is_a_skipped_frame(world) -> None:
    processor = build(world)
    world.convert_error = ValueError("bad frame")
    assert processor.process(Frame(), 1.0) is None
    assert world.landmarker.detections == 0


def test_a_skipped_frame_leaves_the_source_running_and_replays_nothing(world) -> None:
    """A model failure must not be reported to the source as a camera failure."""
    from yazses.perception.mediapipe_backend import mediapipe_processor_factory

    source = SharedPerceptionSource(
        capture_factory=lambda: _CountingCapture(),
        processor_factory=mediapipe_processor_factory(model_path="/models/f.task"),
        spawn=lambda body, name: _DeadWorker(),
    )
    lease = source.consumer("gaze")
    lease.start()
    try:
        assert source.observe() is True
        first = lease.latest()
        world.landmarker.detect_error = RuntimeError("inference failed")
        assert source.observe() is False
        assert source.status().state is SourceState.RUNNING
        assert lease.latest() is first, "a stale sample was restamped as a new one"
    finally:
        source.close()


class _CountingCapture:
    """A capture that hands out a fresh frame and counts what was done to it."""

    def __init__(self) -> None:
        self.opens = 0
        self.closes = 0
        self.frames: list[Frame] = []

    def open(self) -> None:
        self.opens += 1

    def read(self) -> object:
        self.frames.append(Frame())
        return self.frames[-1]

    def close(self) -> None:
        self.closes += 1


# --------------------------------------------------------------------------- #
# Privacy: a frame lives inside one observation, and never in a log
# --------------------------------------------------------------------------- #
def test_the_processor_keeps_no_reference_to_the_frame(world) -> None:
    """ADR-011, asserted with a weak reference rather than by reading the code."""
    import gc

    processor = build(world)
    frame = Frame()
    ref = weakref.ref(frame)
    processor.process(frame, 1.0)
    del frame
    gc.collect()
    assert ref() is None, "the processor kept the frame it was handed"


def test_no_frame_content_reaches_the_log_when_inference_fails(world, caplog) -> None:
    """The one route pixels could take out: a model's own exception message."""
    processor = build(world)
    world.landmarker.detect_error = RuntimeError("tensor dump 0xDEADBEEF pixels here")
    with caplog.at_level(logging.DEBUG, logger="yazses.perception.mediapipe_backend"):
        assert processor.process(Frame(), 1.0) is None

    assert "0xDEADBEEF" not in caplog.text
    assert "RuntimeError" in caplog.text


# --------------------------------------------------------------------------- #
# Narrowing the channels narrows the model's work, not just the output
# --------------------------------------------------------------------------- #
def test_asking_for_gaze_only_turns_off_the_two_extra_outputs(world) -> None:
    processor = build(world, channels=["gaze"])
    options = world.landmarker.options
    assert options["output_face_blendshapes"] is False
    assert options["output_facial_transformation_matrixes"] is False

    # Even handed a result that carries them, a narrowed processor derives neither.
    sample = processor.process(Frame(), 1.0)
    assert sample.channels == ("gaze",)


def test_an_unrecognised_channel_name_falls_back_to_all_three(world) -> None:
    """Raising here would be a camera feature that refuses to start over a typo."""
    processor = build(world, channels=["wink"])
    assert processor.channels == ("gaze", "head_pose", "face")


def test_the_backend_names_itself_for_status(world) -> None:
    assert build(world).name == "mediapipe"


# --------------------------------------------------------------------------- #
# The camera: one device per open, and a refusal that says why
# --------------------------------------------------------------------------- #
def test_the_capture_opens_one_device_at_the_configured_index(world) -> None:
    from yazses.perception.camera import opencv_capture_factory

    capture = opencv_capture_factory(3)
    assert world.captures == [], "constructing a capture touched the device"
    capture.open()
    capture.open()
    assert [c.index for c in world.captures] == [3], "a second device was opened"
    capture.close()
    capture.close()
    assert world.captures[0].released == 1


def test_a_camera_that_will_not_open_raises_with_a_reason(world) -> None:
    from yazses.perception.camera import OpenCVFrameCapture

    world.capture_opens_ok = False
    with pytest.raises(OSError, match="camera 0 could not be opened"):
        OpenCVFrameCapture().open()
    assert world.captures[0].released == 1, "a refused device was not handed back"


def test_a_capture_that_is_not_open_reads_nothing(world) -> None:
    from yazses.perception.camera import OpenCVFrameCapture

    assert OpenCVFrameCapture().read() is None


def test_a_failed_read_is_a_dropped_frame(world) -> None:
    from yazses.perception.camera import OpenCVFrameCapture

    capture = OpenCVFrameCapture(1)
    capture.open()
    world.captures[0].read = lambda: (False, None)
    assert capture.read() is None


# --------------------------------------------------------------------------- #
# The pure derivations, driven with numbers and no fakes at all
# --------------------------------------------------------------------------- #
def test_euler_angles_round_trip_through_a_rotation() -> None:
    for yaw, pitch, roll in [(0.0, 0.0, 0.0), (0.4, -0.3, 0.2), (-1.0, 0.9, -0.7)]:
        got = euler_angles(rotation(yaw, pitch, roll))
        assert got == pytest.approx((yaw, pitch, roll), abs=1e-9)


def test_euler_angles_report_the_observable_angle_at_gimbal_lock() -> None:
    """At |yaw| = 90° only `pitch - roll` exists; reporting a split would invent one."""
    got = euler_angles(rotation(math.pi / 2, 0.3, 0.1))
    assert got is not None
    yaw, pitch, roll = got
    assert yaw == pytest.approx(math.pi / 2)
    assert pitch == pytest.approx(0.2)
    assert roll == 0.0


@pytest.mark.parametrize(
    "matrix",
    [
        None,
        [],
        [[0.0] * 3 for _ in range(3)],                     # zeros: decomposes to 0,0,0
        [[2.0, 0, 0], [0, 2.0, 0], [0, 0, 2.0]],           # scaled: not a rotation
        [[-1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]],          # reflection, not a rotation
        [[1.0, 0, 0], [0, 1.0, 0]],                        # truncated
        "not a matrix",
    ],
)
def test_a_matrix_that_is_not_a_rotation_is_no_pose(matrix) -> None:
    assert derive_head_pose(matrix, 1.0, 0.5) is None


def test_a_three_by_three_rotation_is_read_as_well_as_a_four_by_four() -> None:
    block = [row[:3] for row in rotation(0.2, 0.1, -0.1)[:3]]
    pose = derive_head_pose(block, 7.0, 0.5)
    assert pose is not None
    assert pose.yaw == pytest.approx(0.2)
    assert pose.timestamp_s == 7.0


def test_iris_offset_is_normalised_by_the_eye_width() -> None:
    assert iris_offset(landmarks((0.25, -0.5)), 468, 33, 133) == pytest.approx((0.25, -0.5))


@pytest.mark.parametrize(
    "points",
    [
        [],
        landmarks()[:468],
        [Pt(float("nan"), 0.5)] * 478,
        [object()] * 478,
    ],
)
def test_landmarks_that_cannot_be_measured_are_no_gaze(points) -> None:
    assert derive_gaze(points, 1.0) is None


def test_one_eye_alone_is_not_a_gaze_estimate() -> None:
    """Half an estimate is a different measurement, not a weaker one."""
    points = landmarks()
    points[473] = object()  # the right iris is unreadable
    assert derive_gaze(points, 1.0) is None


def test_blendshape_activations_drop_only_what_they_cannot_use() -> None:
    got = blendshape_activations(
        [
            Cat("jawOpen", 0.5),
            Cat("browInnerUp", -0.1),
            Cat("mouthPucker", float("inf")),
            Cat("smile", "loud"),
            Cat(None, 0.9),
            object(),
            Cat("eyeBlinkLeft", 1.0),
        ]
    )
    assert got == {"jawOpen": 0.5, "eyeBlinkLeft": 1.0}


def test_no_categories_at_all_is_no_face_channel() -> None:
    assert derive_face(None, 1.0, 0.5) is None
