"""Derived camera perception signals — pure values, no camera, no model (ADR-v2-145).

Three accessibility features want the same webcam: Glance-Type gaze routing, the
Head-Pointer and face-gesture switch access. Today two of them open their own
``cv2.VideoCapture`` and their own FaceLandmarker, which is how you get "device
already busy", duplicated inference and two different opinions about confidence.
ADR-v2-145 puts one source behind them; this module is the boundary that source
emits *across*.

Everything here is a value: a frozen dataclass of derived numbers with a timestamp
and an explicit confidence. Nothing in this file imports OpenCV or MediaPipe, opens
a camera, or starts a thread — a consumer can be unit-tested with numbers alone, on
a machine where no camera extra is installed. That is the point: the privacy rule
(frames stay in RAM inside the source, ADR-011) is only auditable if frames have no
way to cross this line, and no field here can carry one.

Two conventions the rest of the programme depends on:

**Absent is not zero.** A channel that produced nothing this observation is ``None``
on :class:`PerceptionSample` — never a ``0.0`` that reads like "looking dead ahead"
or "jaw shut". Per-channel degradation is normal (a missing facial transform costs
head pose and leaves gaze alone), so a sample may carry one channel, two, or all
three. :meth:`FaceSignal.score` keeps the same promise one level down: a blendshape
nobody reported comes back ``None``, not ``0.0``.

**The clock is monotonic.** ``timestamp_s`` is a :func:`time.monotonic` reading taken
when the source observed the face, so freshness survives a wall-clock jump and a
consumer can ask :meth:`PerceptionSample.age_s` whether a sample is too old to act
on. Its reference point is undefined by the standard library, so only *differences*
mean anything — which is why validation below checks that a timestamp is finite and
deliberately does not check its sign.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, runtime_checkable

__all__ = [
    "FacePerceptionSource",
    "FaceSignal",
    "GazeSignal",
    "HeadPoseSignal",
    "PerceptionSample",
]


def _finite(name: str, value: float) -> float:
    """Return ``value`` as a float, rejecting NaN and infinity.

    A NaN confidence compares false against every threshold, so it would silently
    disable a guard rather than fail; an infinite angle would fly the cursor off
    screen. Both are cheaper to refuse at the boundary than to debug downstream.
    """
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number, got {value!r}")
    return number


def _unit(name: str, value: float) -> float:
    """Return ``value`` as a float in ``0.0..1.0`` inclusive.

    Confidence and blendshape activation are both normalized by contract. Pinning
    the range here is what lets every consumer compare against a plain threshold
    without first asking which backend produced the number.
    """
    number = _finite(name, value)
    if not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be within 0.0..1.0, got {number!r}")
    return number


def _freeze(instance: object, name: str, value: object) -> None:
    """Normalize a field on a frozen dataclass during ``__post_init__``."""
    object.__setattr__(instance, name, value)


@dataclass(frozen=True)
class GazeSignal:
    """One eye observation: a raw gaze feature plus how much to trust it.

    ``raw_x``/``raw_y`` are the backend's *uncalibrated* 2D gaze feature, not screen
    coordinates — the normalized iris offset for the MediaPipe backend, a yaw/pitch
    pair for L2CS. Calibration owns the map from this to a screen point
    (``gaze/calibrate.py``), which is exactly why the signal stops short of it: a
    future dedicated eye tracker should be able to feed the same calibration and
    routing layer without pretending to be a webcam.

    No range is asserted on the feature itself beyond finiteness, because each
    backend normalizes differently and a contract that guessed would reject good
    samples. ``confidence`` is normalized 0..1 and is the number consumers gate on.
    """

    timestamp_s: float
    raw_x: float
    raw_y: float
    confidence: float

    def __post_init__(self) -> None:
        _freeze(self, "timestamp_s", _finite("timestamp_s", self.timestamp_s))
        _freeze(self, "raw_x", _finite("raw_x", self.raw_x))
        _freeze(self, "raw_y", _finite("raw_y", self.raw_y))
        _freeze(self, "confidence", _unit("confidence", self.confidence))


@dataclass(frozen=True)
class HeadPoseSignal:
    """Head orientation in **radians**, with confidence.

    Radians because that is what the consumer already speaks: ``pose_to_cursor()``
    in ``headpointer/pointer.py`` takes centered yaw/pitch in radians and its
    deadzone is expressed in them. Converting at the boundary once beats every
    consumer guessing the unit.

    Angles are validated as finite only. They are not clamped to a plausible range
    for a human neck: an odd pose is a quality question the confidence field
    answers, and a contract that rejected it would turn a bad reading into a crash.
    """

    timestamp_s: float
    yaw: float
    pitch: float
    roll: float
    confidence: float

    def __post_init__(self) -> None:
        _freeze(self, "timestamp_s", _finite("timestamp_s", self.timestamp_s))
        _freeze(self, "yaw", _finite("yaw", self.yaw))
        _freeze(self, "pitch", _finite("pitch", self.pitch))
        _freeze(self, "roll", _finite("roll", self.roll))
        _freeze(self, "confidence", _unit("confidence", self.confidence))


@dataclass(frozen=True)
class FaceSignal:
    """Blendshape activations for switch access, with face-detection confidence.

    ``blendshapes`` maps an ARKit-style category name (``"jawOpen"``,
    ``"browInnerUp"``) to its 0..1 activation, the same vocabulary
    ``facegesture/detector.py`` already consumes. The mapping is copied and wrapped
    read-only at construction, so a caller that keeps mutating the dict it passed in
    cannot reach back and change a sample another consumer is still reading.

    They are control features and nothing else. ADR-v2-145 forbids reading identity
    or emotion out of them, and no field here carries a face mesh or an image.

    An **empty** mapping is legal and means "a face was seen, no scores were
    requested or reported" — presence without a switch channel. The absence of a
    whole face is ``PerceptionSample.face is None``, and the absence of one category
    is :meth:`score` returning ``None``.
    """

    timestamp_s: float
    confidence: float
    blendshapes: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _freeze(self, "timestamp_s", _finite("timestamp_s", self.timestamp_s))
        _freeze(self, "confidence", _unit("confidence", self.confidence))
        scores = {
            name: _unit(f"blendshapes[{name!r}]", value)
            for name, value in dict(self.blendshapes).items()
        }
        _freeze(self, "blendshapes", MappingProxyType(scores))

    def score(self, name: str) -> float | None:
        """This frame's activation for ``name``, or ``None`` if it was not reported.

        ``None`` rather than ``0.0`` on purpose: "the model did not send this
        category" and "the user is not making this movement" are different
        observations, and a hold detector that confuses them releases the key.
        """
        return self.blendshapes.get(name)

    def __hash__(self) -> int:
        # A frozen dataclass holding a mapping gets no usable generated hash, and
        # these are values — worth being able to put in a set or a dict key.
        return hash((self.timestamp_s, self.confidence, frozenset(self.blendshapes.items())))


@dataclass(frozen=True)
class PerceptionSample:
    """One observation of one face, carrying whichever channels were derived from it.

    The channels share ``timestamp_s`` because they come from the same frame; that
    alignment is the whole reason for a shared source rather than three cameras.
    Any of them may be ``None``: ADR-v2-145 invariant 6 says one channel failing
    must not take the others with it, so a missing facial-transform matrix costs
    ``head_pose`` and leaves ``gaze`` and ``face`` intact.
    """

    timestamp_s: float
    gaze: GazeSignal | None = None
    head_pose: HeadPoseSignal | None = None
    face: FaceSignal | None = None

    def __post_init__(self) -> None:
        _freeze(self, "timestamp_s", _finite("timestamp_s", self.timestamp_s))

    @property
    def channels(self) -> tuple[str, ...]:
        """Names of the channels this sample actually carries, in a stable order.

        Enough for a status line to say *gaze only* without a consumer having to
        re-derive it, and enough for a degradation test to assert on.
        """
        present = (("gaze", self.gaze), ("head_pose", self.head_pose), ("face", self.face))
        return tuple(name for name, value in present if value is not None)

    def age_s(self, now_s: float) -> float:
        """Seconds between this observation and ``now_s`` (a monotonic reading).

        Freshness is the consumer's decision, not the source's: a gaze route wants a
        sample from the last few hundred milliseconds, a dwell click tolerates less.
        The source never restamps a sample because someone read it, so this number
        keeps growing while the camera is blind — which is what makes "no face" and
        "the same face, still there" distinguishable.
        """
        return _finite("now_s", now_s) - self.timestamp_s


@runtime_checkable
class FacePerceptionSource(Protocol):
    """The single camera owner, seen from a consumer (implemented by EYE-CAM-001).

    Declared here, beside the values it emits, so a consumer can be written and
    tested against a numeric fake today — importing this module pulls in no camera,
    no model and no thread. The lifecycle is subscriber-driven: the first consumer
    to :meth:`start` opens the camera once, the last to :meth:`stop` closes it, and
    both are idempotent.
    """

    def start(self) -> None:
        """Acquire a lease on the source, opening the camera if it is the first."""
        ...

    def stop(self) -> None:
        """Release this consumer's lease; the last release closes the camera."""
        ...

    def latest(self) -> PerceptionSample | None:
        """The most recent observation, or ``None`` if there has not been one.

        Never blocks on the capture loop and never invents a sample: an
        implementation returns the last real observation with its original
        timestamp, so the caller can judge its age.
        """
        ...
