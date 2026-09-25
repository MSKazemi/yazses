"""The shared-perception value contracts: immutable, timestamped, and never fake-zero.

These types (`src/yazses/perception/signals.py`, ADR-v2-145) are the boundary the one
camera owner emits across. Three properties are worth a test each, because each one
is a bug this programme has already had somewhere:

* **absent is not zero** — the gaze backend returning `None` for "no face" is the
  reason `GazeTargeter` does not type into whatever the cursor last touched. The
  shared source has three channels that can each vanish independently, so the
  contract has to keep saying it at three levels: a channel is `None`, a blendshape
  nobody reported is `None`, and no consumer has to spot the difference between a
  reading of 0.0 and no reading at all;
* **immutable** — a sample is read by more than one consumer now. A mapping handed
  in and kept is a mutable value shared across features;
* **dependency-free** — the whole point of deriving numbers inside the source is
  that a consumer can be tested without a camera, a model, or MediaPipe installed.

The last one is asserted by reading the package's own imports rather than by
catching an ImportError, because on a developer machine with the `gaze` extra
installed a heavy import would succeed and the test would pass while the promise
broke for everyone else.
"""
from __future__ import annotations

import ast
import dataclasses
import math
from pathlib import Path

import pytest

import yazses.perception as perception
from yazses.perception.signals import (
    FacePerceptionSource,
    FaceSignal,
    GazeSignal,
    HeadPoseSignal,
    PerceptionSample,
)

PACKAGE = Path(perception.__file__).resolve().parent


# --------------------------------------------------------------------------- #
# Value semantics
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "signal",
    [
        GazeSignal(timestamp_s=10.0, raw_x=0.2, raw_y=-0.1, confidence=0.9),
        HeadPoseSignal(timestamp_s=10.0, yaw=0.1, pitch=-0.2, roll=0.0, confidence=0.8),
        FaceSignal(timestamp_s=10.0, confidence=0.95, blendshapes={"jawOpen": 0.7}),
        PerceptionSample(timestamp_s=10.0),
    ],
)
def test_signals_are_frozen(signal) -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        signal.timestamp_s = 11.0


def test_equal_by_value_not_identity() -> None:
    one = GazeSignal(timestamp_s=1.0, raw_x=0.5, raw_y=0.25, confidence=0.7)
    two = GazeSignal(timestamp_s=1.0, raw_x=0.5, raw_y=0.25, confidence=0.7)
    assert one == two and one is not two
    assert hash(one) == hash(two)
    assert one != GazeSignal(timestamp_s=1.0, raw_x=0.5, raw_y=0.25, confidence=0.6)


def test_face_signals_are_hashable_despite_carrying_a_mapping() -> None:
    """A frozen dataclass holding a dict has no usable generated hash. These are
    values; a consumer should be able to put one in a set without a workaround."""
    one = FaceSignal(timestamp_s=1.0, confidence=0.9, blendshapes={"jawOpen": 0.4})
    two = FaceSignal(timestamp_s=1.0, confidence=0.9, blendshapes={"jawOpen": 0.4})
    assert hash(one) == hash(two)
    assert len({one, two}) == 1
    assert len({PerceptionSample(timestamp_s=1.0, face=one),
                PerceptionSample(timestamp_s=1.0, face=two)}) == 1


def test_integers_are_normalized_to_floats() -> None:
    """A caller passing `1` for confidence must not make `0.9 < conf` behave one way
    for ints and another for floats downstream."""
    signal = GazeSignal(timestamp_s=1, raw_x=0, raw_y=0, confidence=1)
    assert isinstance(signal.confidence, float)
    assert isinstance(signal.timestamp_s, float)


def test_replace_produces_a_new_value() -> None:
    original = HeadPoseSignal(timestamp_s=1.0, yaw=0.1, pitch=0.0, roll=0.0, confidence=0.5)
    later = dataclasses.replace(original, timestamp_s=2.0)
    assert later.timestamp_s == 2.0
    assert original.timestamp_s == 1.0
    assert later.yaw == original.yaw


# --------------------------------------------------------------------------- #
# The mapping cannot be reached back through
# --------------------------------------------------------------------------- #
def test_blendshapes_are_copied_from_the_callers_dict() -> None:
    """The source will reuse a scratch dict per frame. If the signal kept it, every
    consumer holding an old sample would silently see the newest frame's scores."""
    scratch = {"jawOpen": 0.7}
    signal = FaceSignal(timestamp_s=1.0, confidence=0.9, blendshapes=scratch)
    scratch["jawOpen"] = 0.0
    scratch["browInnerUp"] = 1.0
    assert signal.blendshapes == {"jawOpen": 0.7}


def test_blendshapes_cannot_be_mutated_through_the_signal() -> None:
    signal = FaceSignal(timestamp_s=1.0, confidence=0.9, blendshapes={"jawOpen": 0.7})
    with pytest.raises(TypeError):
        signal.blendshapes["jawOpen"] = 0.1  # type: ignore[index]


# --------------------------------------------------------------------------- #
# Absent is not zero
# --------------------------------------------------------------------------- #
def test_an_absent_channel_is_none_not_a_zeroed_signal() -> None:
    sample = PerceptionSample(
        timestamp_s=5.0,
        gaze=GazeSignal(timestamp_s=5.0, raw_x=0.1, raw_y=0.1, confidence=0.9),
    )
    assert sample.head_pose is None
    assert sample.face is None
    assert sample.channels == ("gaze",)


def test_one_missing_channel_does_not_take_the_others() -> None:
    """ADR-v2-145 invariant 6: a missing facial-transform matrix costs head pose and
    leaves gaze and the blendshape switch alive."""
    sample = PerceptionSample(
        timestamp_s=5.0,
        gaze=GazeSignal(timestamp_s=5.0, raw_x=0.1, raw_y=0.1, confidence=0.9),
        head_pose=None,
        face=FaceSignal(timestamp_s=5.0, confidence=0.9, blendshapes={"jawOpen": 0.8}),
    )
    assert sample.channels == ("gaze", "face")
    assert sample.gaze is not None and sample.face is not None


def test_an_unreported_blendshape_reads_none_and_a_reported_zero_reads_zero() -> None:
    """The distinction the hold detector depends on: "the model sent nothing" is not
    "the jaw is shut"."""
    signal = FaceSignal(timestamp_s=1.0, confidence=0.9, blendshapes={"jawOpen": 0.0})
    assert signal.score("jawOpen") == 0.0
    assert signal.score("browInnerUp") is None


def test_a_face_with_no_scores_is_presence_without_a_switch_channel() -> None:
    """Legal, and different from `face is None`: the face was seen, no blendshapes
    were requested or reported."""
    signal = FaceSignal(timestamp_s=1.0, confidence=0.9)
    assert dict(signal.blendshapes) == {}
    assert signal.score("jawOpen") is None


def test_an_empty_sample_carries_no_channels() -> None:
    assert PerceptionSample(timestamp_s=1.0).channels == ()


# --------------------------------------------------------------------------- #
# Freshness
# --------------------------------------------------------------------------- #
def test_age_grows_with_the_clock_and_reading_does_not_restamp() -> None:
    """The source records the true observation time. A stale sample must keep
    ageing, or "the camera went blind" reads exactly like "the face has not moved"."""
    sample = PerceptionSample(timestamp_s=100.0)
    assert sample.age_s(100.0) == 0.0
    assert sample.age_s(100.5) == pytest.approx(0.5)
    assert sample.age_s(103.0) == pytest.approx(3.0)
    assert sample.timestamp_s == 100.0


def test_a_negative_monotonic_reading_is_accepted() -> None:
    """`time.monotonic()`'s reference point is undefined, so only differences mean
    anything. Rejecting a sign the standard library does not promise would reject
    good samples on some platform we cannot test here."""
    sample = PerceptionSample(timestamp_s=-42.0)
    assert sample.age_s(-40.0) == pytest.approx(2.0)


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_timestamp_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="timestamp_s"):
        PerceptionSample(timestamp_s=bad)


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_a_non_finite_gaze_feature_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="raw_x"):
        GazeSignal(timestamp_s=1.0, raw_x=bad, raw_y=0.0, confidence=0.5)


@pytest.mark.parametrize("bad", [-0.01, 1.01, math.nan])
def test_confidence_outside_the_unit_range_is_refused(bad: float) -> None:
    """A NaN confidence is the dangerous one: it compares false against every
    threshold, so a guard would not fire and nothing would look wrong."""
    with pytest.raises(ValueError, match="confidence"):
        GazeSignal(timestamp_s=1.0, raw_x=0.0, raw_y=0.0, confidence=bad)
    with pytest.raises(ValueError, match="confidence"):
        HeadPoseSignal(timestamp_s=1.0, yaw=0.0, pitch=0.0, roll=0.0, confidence=bad)
    with pytest.raises(ValueError, match="confidence"):
        FaceSignal(timestamp_s=1.0, confidence=bad)


@pytest.mark.parametrize("bad", [-0.5, 2.0, math.nan])
def test_a_blendshape_outside_the_unit_range_is_refused(bad: float) -> None:
    with pytest.raises(ValueError, match="jawOpen"):
        FaceSignal(timestamp_s=1.0, confidence=0.9, blendshapes={"jawOpen": bad})


@pytest.mark.parametrize("edge", [0.0, 1.0])
def test_the_unit_range_is_inclusive(edge: float) -> None:
    """The permissive direction, tested on purpose: a guard that also refused the
    endpoints would reject a perfectly confident sample."""
    assert GazeSignal(timestamp_s=1.0, raw_x=0.0, raw_y=0.0, confidence=edge).confidence == edge
    assert FaceSignal(
        timestamp_s=1.0, confidence=0.5, blendshapes={"jawOpen": edge}
    ).score("jawOpen") == edge


def test_head_pose_accepts_an_implausible_but_finite_angle() -> None:
    """Quality is what `confidence` is for. A contract that clamped a strange pose
    would turn a bad reading into a crash or a lie."""
    pose = HeadPoseSignal(timestamp_s=1.0, yaw=9.0, pitch=-9.0, roll=3.0, confidence=0.1)
    assert pose.yaw == 9.0


# --------------------------------------------------------------------------- #
# The source protocol, satisfied by a numeric fake
# --------------------------------------------------------------------------- #
class _FakeSource:
    """What every consumer test in this programme will use instead of a webcam."""

    def __init__(self, sample: PerceptionSample | None = None) -> None:
        self.sample = sample
        self.leases = 0

    def start(self) -> None:
        self.leases += 1

    def stop(self) -> None:
        self.leases = max(0, self.leases - 1)

    def latest(self) -> PerceptionSample | None:
        return self.sample


def test_a_numeric_fake_satisfies_the_source_protocol() -> None:
    fake = _FakeSource(PerceptionSample(timestamp_s=1.0))
    assert isinstance(fake, FacePerceptionSource)
    fake.start()
    assert fake.latest() is not None
    fake.stop()
    assert fake.leases == 0


def test_something_without_the_methods_is_not_a_source() -> None:
    """Guard the guard: a runtime_checkable Protocol that accepted anything would
    make the test above meaningless."""
    assert not isinstance(object(), FacePerceptionSource)


# --------------------------------------------------------------------------- #
# Dependency-free by construction
# --------------------------------------------------------------------------- #
def _imported_modules() -> set[str]:
    """Every module name imported anywhere in `yazses/perception/`, at any depth —
    module level or inside a function."""
    names: set[str] = set()
    files = sorted(PACKAGE.rglob("*.py"))
    assert files, f"no source found under {PACKAGE} — this scan proves nothing"
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
    return names


def test_the_scan_sees_the_imports_at_all() -> None:
    """Guard the guard: a wrong path would find nothing and report compliance."""
    assert "math" in _imported_modules()
    assert "yazses.perception.signals" in _imported_modules()


@pytest.mark.parametrize(
    "forbidden",
    ["cv2", "mediapipe", "numpy", "torch", "threading", "yazses.config"],
)
def test_the_package_imports_nothing_heavy(forbidden: str) -> None:
    """A camera, a model, a thread or a config object on this side of the boundary
    would make every consumer test need one too."""
    offenders = {name for name in _imported_modules() if name.split(".")[0] == forbidden}
    assert not offenders, f"{PACKAGE.name} imports {sorted(offenders)}"


def test_no_signal_field_can_carry_a_frame() -> None:
    """ADR-011/ADR-v2-145: frames stay inside the source. The cheapest way to keep
    that auditable is a boundary with no field that could hold one."""
    for signal_type in (GazeSignal, HeadPoseSignal, FaceSignal, PerceptionSample):
        names = dataclasses.fields(signal_type)
        assert names, f"{signal_type.__name__} reported no fields — this loop proves nothing"
        for field in names:
            assert "frame" not in field.name
            assert "image" not in field.name
            assert "landmark" not in field.name
