"""What a visionOS companion app can and cannot hand the XR adapter (pure, stdlib only).

Apple visionOS is the XR platform that **deliberately does not give an app the user's
gaze**. This module models exactly what a third-party companion *can* provide, converts it
into the adapter's canonical frame (``xr.types``), and states plainly what the binder
(``xr.binding``) loses because of it. It is a library fed synthetic data only: no Apple
framework is imported or needed, the companion (Swift) does the ARKit calls and ships
plain numbers; nothing here is wired to a session, a config key or a command.

What visionOS provides, with the evidence for each (``VERIFIED`` = read from the Apple
page named; the full table is :data:`CAPABILITIES`):

* **No continuous eye gaze.** "To protect people's privacy, the system applies hover
  effects outside your app's process, so your app doesn't know where people are looking."
  (WWDC25 "Design hover interactions for visionOS",
  https://developer.apple.com/videos/play/wwdc2025/303/). An Apple Vision Pro engineer on
  the developer forums: "For privacy reasons there is no way to read the location of a
  user's gaze" (https://developer.apple.com/forums/thread/757357). That is a forum
  statement, not an API reference page: no page that *enumerates* every gaze channel was
  found, and any enterprise-entitlement API was not checked. This module assumes there is
  no gaze channel and never invents one.
* **A selection ray only when the user pinches.** ``SpatialEventCollection.Event`` carries
  ``selectionRay`` ("The 3D ray used to target the touch"), ``location3D``, ``kind`` and
  ``inputDevicePose`` (https://developer.apple.com/documentation/swiftui/spatialeventcollection/event);
  the kinds are ``directPinch``, ``indirectPinch``, ``pointer``, ``touch`` and ``pencil``
  (.../event/kind-swift.enum). An event exists only when there is an input, so the app
  learns what the user looked at *at that instant* and never between pinches. Whether
  ``selectionRay`` is refreshed while a pinch is held: UNVERIFIED; the model assumes one
  ray per pinch (the conservative reading). The coordinate space of ``selectionRay``:
  UNVERIFIED; the companion must convert it into the canonical frame (the forum reply
  above shows ``value.convert(value.location3D, from: .local, to: .scene)``).
* **Hand skeleton, continuously, but only in a Full Space and with permission.** The hand
  skeleton is "a collection of joints in a hand"; ``HandSkeleton.JointName`` has **27**
  cases (https://developer.apple.com/documentation/arkit/handskeleton/jointname). A figure
  of 28 is sometimes quoted; the page lists 27 and that is what :class:`HandJointName`
  carries. "If
  your game lives in the Shared Space ... then ARKit and hand tracking isn't available to
  you" and "ARKit and full hand skeleton tracking lives in Full Space" (WWDC24 "Explore
  game input in visionOS", https://developer.apple.com/videos/play/wwdc2024/10094/);
  "Some types of ARKit data require permission to access" (WWDC23 "Meet ARKit for spatial
  computing", https://developer.apple.com/videos/play/wwdc2023/10082/).
* **Joint transforms** are ``simd_float4x4`` (``originFromAnchorTransform``,
  https://developer.apple.com/documentation/arkit/anchor/originfromanchortransform), and a
  joint in origin space is ``originFromAnchorTransform * anchorFromJointTransform``
  (WWDC24 10094 sample code, which also reads the translation as ``.columns.3``). SIMD
  matrices are column-major; the sample's ``.columns.3`` translation is consistent with it.
* **Device (head) pose** from ``WorldTrackingProvider``: "the position and orientation of
  the device relative to the app's origin"; querying it "is relatively expensive"
  (WWDC23 10082; ``queryDeviceAnchor(atTimestamp:)``).
* **Axes and units.** RealityKit is described as +X right, +Y up, -Z forward, metres
  (WWDC24 "Optimize your 3D assets for spatial computing",
  https://developer.apple.com/videos/play/wwdc2024/10186/, and WWDC23 10080, read through
  a summary of the transcripts, so second-hand). That ARKit's *origin frame and device
  anchor* use the same axes is **UNVERIFIED** here (no Apple page found that says so);
  the adapter treats them as canonical (``Convention.VISIONOS``) and the companion should
  confirm on a device before trusting any direction.

Everything numeric below that is not an Apple fact (pinch thresholds, freshness windows,
confidences, baselines) is a STARTING POINT to be measured on real hardware, not a
validated value.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from yazses.xr.geometry import add, cross, dot, norm, normalize, scale, sub
from yazses.xr.types import (
    GestureEvent,
    GestureKind,
    Ray,
    RaySource,
    Vec3,
    XrSample,
)

# ── limits and tolerances ────────────────────────────────────────────────────

_MAX_COORD_M = 1e6        # same bound as the wire layer: keeps every product finite
_SCALE_TOL = 1e-4         # a rigid transform's axes may be this far from unit length
_ORTHO_TOL = 1e-4         # ...and this far from perpendicular (simd_float4x4 is float32)
_AFFINE_TOL = 1e-6        # bottom row must be (0, 0, 0, 1) within this
_MAX_TIME_S = 1e9         # matches the wire layer: anything larger is garbage

# Defaults of ``binding.bind_demonstrative`` that this module reasons about. Copied, not
# imported, so a tweak elsewhere cannot silently change this module; the test suite
# compares them to the real signature and fails on drift.
BINDER_LEAD_S = 0.4
BINDER_LAG_S = 0.2
BINDER_MIN_SAMPLES = 3


class TransformError(ValueError):
    """A matrix, hand frame or system event was refused.

    The only exception the ``*_from_raw`` / ``rigid_from_column_major`` entry points let
    escape, whatever junk they are given (wrong length, NaN, strings, a reflection...).
    """


def _num(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransformError(f"{name} must be a number, got {type(value).__name__}")
    out = float(value)
    if not math.isfinite(out):
        raise TransformError(f"{name} must be finite")
    return out


def _time(name: str, value: object) -> float:
    t = _num(name, value)
    if t < 0 or t > _MAX_TIME_S:
        raise TransformError(f"{name} must be within [0, {_MAX_TIME_S:g}] seconds")
    return t


def _vec(name: str, value: object) -> Vec3:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) != 3:
        raise TransformError(f"{name} must be a sequence of 3 numbers")
    x, y, z = (_num(f"{name}[{i}]", v) for i, v in enumerate(value))
    return Vec3(x, y, z)


# ── rigid transform from a simd_float4x4 ─────────────────────────────────────


@dataclass(frozen=True)
class RigidTransform:
    """A proper rigid motion: an orthonormal right-handed basis plus a position.

    ``right``, ``up`` and ``back`` are the images of +X, +Y and +Z (columns 0..2 of the
    matrix); ``forward`` is ``-back`` because the package's forward is -Z. All three are
    unit and mutually perpendicular within 1e-6 and ``right x up == back`` (no mirror).
    """

    position: Vec3
    right: Vec3
    up: Vec3
    back: Vec3

    def __post_init__(self) -> None:
        for n, v in (("right", self.right), ("up", self.up), ("back", self.back)):
            if abs(norm(v) - 1.0) > 1e-6:
                raise ValueError(f"RigidTransform.{n} must be unit length")
        for a, b in ((self.right, self.up), (self.right, self.back), (self.up, self.back)):
            if abs(dot(a, b)) > 1e-6:
                raise ValueError("RigidTransform axes must be perpendicular")
        c = cross(self.right, self.up)
        if norm(sub(c, self.back)) > 1e-5:
            raise ValueError("RigidTransform must be right-handed (no mirror)")
        if max(abs(self.position.x), abs(self.position.y), abs(self.position.z)) > _MAX_COORD_M:
            raise ValueError("RigidTransform.position is out of range")

    @property
    def forward(self) -> Vec3:
        """-Z in this transform's frame, i.e. where a device or hand 'faces'."""
        return Vec3(-self.back.x, -self.back.y, -self.back.z)

    def apply_point(self, p: Vec3) -> Vec3:
        """``p`` (in this transform's local frame) expressed in the parent frame."""
        d = add(add(scale(self.right, p.x), scale(self.up, p.y)), scale(self.back, p.z))
        return add(d, self.position)

    def apply_direction(self, d: Vec3) -> Vec3:
        return add(add(scale(self.right, d.x), scale(self.up, d.y)), scale(self.back, d.z))


IDENTITY = RigidTransform(Vec3(0.0, 0.0, 0.0), Vec3(1.0, 0.0, 0.0), Vec3(0.0, 1.0, 0.0),
                          Vec3(0.0, 0.0, 1.0))


def compose(parent: RigidTransform, child: RigidTransform) -> RigidTransform:
    """``parent * child``: the child's frame expressed in the parent's parent frame.

    ``originFromJoint = compose(originFromAnchor, anchorFromJoint)``.
    """
    return RigidTransform(
        parent.apply_point(child.position),
        normalize(parent.apply_direction(child.right)),
        normalize(parent.apply_direction(child.up)),
        normalize(parent.apply_direction(child.back)),
    )


def rigid_from_column_major(values: object) -> RigidTransform:
    """A column-major 4x4 (a flattened ``simd_float4x4``) -> :class:`RigidTransform`.

    ``values`` holds 16 numbers: column 0 (``x`` axis, w=0), column 1, column 2, column 3
    (translation, w=1), i.e. element ``4 * col + row``. Refused with
    :class:`TransformError`, never clamped:

    * not 16 finite numbers (including booleans, strings, NaN, inf);
    * bottom row not ``(0, 0, 0, 1)`` -- a projective or non-affine matrix;
    * any axis not unit length within 1e-4 -- **non-unit scale** (a RealityKit entity
      transform may carry scale; strip it first, this seam takes rigid motions only);
    * axes not perpendicular within 1e-4 -- shear;
    * a reflection (negative determinant) -- a left-handed frame passed off as right;
    * translation beyond 1e6 m.

    A matrix inside those tolerances (float32 noise) is accepted and re-orthonormalised
    (Gram-Schmidt), so what comes out is exactly orthonormal.
    """
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise TransformError("a column-major 4x4 must be a sequence of 16 numbers")
    if len(values) != 16:
        raise TransformError(f"a column-major 4x4 has 16 elements, got {len(values)}")
    m = [_num(f"m[{i}]", v) for i, v in enumerate(values)]
    for i, want in ((3, 0.0), (7, 0.0), (11, 0.0), (15, 1.0)):
        if abs(m[i] - want) > _AFFINE_TOL:
            raise TransformError("bottom row must be (0, 0, 0, 1): not a rigid transform")
    cols = [Vec3(m[0], m[1], m[2]), Vec3(m[4], m[5], m[6]), Vec3(m[8], m[9], m[10])]
    for i, c in enumerate(cols):
        if abs(norm(c) - 1.0) > _SCALE_TOL:
            raise TransformError(f"axis {i} is not unit length: non-unit scale is refused")
    for i, j in ((0, 1), (0, 2), (1, 2)):
        if abs(dot(cols[i], cols[j])) > _ORTHO_TOL:
            raise TransformError("axes are not perpendicular: shear is refused")
    if dot(cross(cols[0], cols[1]), cols[2]) <= 0.0:
        raise TransformError("negative determinant: a mirrored (left-handed) frame is refused")
    if max(abs(m[12]), abs(m[13]), abs(m[14])) > _MAX_COORD_M:
        raise TransformError("translation is out of range")
    right = normalize(cols[0])
    up = normalize(sub(cols[1], scale(right, dot(cols[1], right))))
    back = cross(right, up)
    return RigidTransform(Vec3(m[12], m[13], m[14]), right, up, back)


def forward_ray(t: RigidTransform) -> Ray:
    """The ray out of ``t`` along its -Z (a device anchor's 'where the head faces')."""
    return Ray(t.position, normalize(t.forward))


# ── hands ────────────────────────────────────────────────────────────────────


class Chirality(Enum):
    LEFT = "left"
    RIGHT = "right"


class HandJointName(Enum):
    """The 27 ``HandSkeleton.JointName`` cases, spelled as Apple spells them."""

    FOREARM_ARM = "forearmArm"
    FOREARM_WRIST = "forearmWrist"
    WRIST = "wrist"
    THUMB_INTERMEDIATE_BASE = "thumbIntermediateBase"
    THUMB_INTERMEDIATE_TIP = "thumbIntermediateTip"
    THUMB_KNUCKLE = "thumbKnuckle"
    THUMB_TIP = "thumbTip"
    INDEX_INTERMEDIATE_BASE = "indexFingerIntermediateBase"
    INDEX_INTERMEDIATE_TIP = "indexFingerIntermediateTip"
    INDEX_KNUCKLE = "indexFingerKnuckle"
    INDEX_METACARPAL = "indexFingerMetacarpal"
    INDEX_TIP = "indexFingerTip"
    MIDDLE_INTERMEDIATE_BASE = "middleFingerIntermediateBase"
    MIDDLE_INTERMEDIATE_TIP = "middleFingerIntermediateTip"
    MIDDLE_KNUCKLE = "middleFingerKnuckle"
    MIDDLE_METACARPAL = "middleFingerMetacarpal"
    MIDDLE_TIP = "middleFingerTip"
    RING_INTERMEDIATE_BASE = "ringFingerIntermediateBase"
    RING_INTERMEDIATE_TIP = "ringFingerIntermediateTip"
    RING_KNUCKLE = "ringFingerKnuckle"
    RING_METACARPAL = "ringFingerMetacarpal"
    RING_TIP = "ringFingerTip"
    LITTLE_INTERMEDIATE_BASE = "littleFingerIntermediateBase"
    LITTLE_INTERMEDIATE_TIP = "littleFingerIntermediateTip"
    LITTLE_KNUCKLE = "littleFingerKnuckle"
    LITTLE_METACARPAL = "littleFingerMetacarpal"
    LITTLE_TIP = "littleFingerTip"


_JOINT_BY_APPLE_NAME: dict[str, HandJointName] = {j.value: j for j in HandJointName}


@dataclass(frozen=True)
class HandJointPose:
    """One joint: ``anchor_from_joint`` is Apple's ``anchorFromJointTransform``."""

    name: HandJointName
    anchor_from_joint: RigidTransform
    tracked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.name, HandJointName):
            raise ValueError("HandJointPose.name must be a HandJointName")
        if not isinstance(self.tracked, bool):
            raise ValueError("HandJointPose.tracked must be a bool")


@dataclass(frozen=True)
class HandFrame:
    """One ``HandAnchor`` update: the hand's pose, its joints, and whether it is tracked.

    ``origin_from_anchor`` is ``originFromAnchorTransform`` (the wrist, in the app origin
    space, per WWDC23 10082). ``timestamp_s`` is on the desktop clock (the wire layer
    maps the device clock before a frame is built). Joint names are unique.
    """

    timestamp_s: float
    chirality: Chirality
    tracked: bool
    origin_from_anchor: RigidTransform
    joints: tuple[HandJointPose, ...]

    def __post_init__(self) -> None:
        t = self.timestamp_s
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
            raise ValueError("HandFrame.timestamp_s must be a finite number")
        if t < 0:
            raise ValueError("HandFrame.timestamp_s must be >= 0")
        if not isinstance(self.chirality, Chirality):
            raise ValueError("HandFrame.chirality must be a Chirality")
        if not isinstance(self.tracked, bool):
            raise ValueError("HandFrame.tracked must be a bool")
        if len(self.joints) > len(HandJointName):
            raise ValueError("HandFrame has more joints than a HandSkeleton")
        names = [j.name for j in self.joints]
        if len(set(names)) != len(names):
            raise ValueError("HandFrame joint names must be unique")

    def joint(self, name: HandJointName) -> HandJointPose | None:
        for j in self.joints:
            if j.name is name:
                return j
        return None

    def joint_position(self, name: HandJointName) -> Vec3 | None:
        """The joint in origin space, or ``None`` if the hand or the joint is untracked."""
        j = self.joint(name)
        if not self.tracked or j is None or not j.tracked:
            return None
        return compose(self.origin_from_anchor, j.anchor_from_joint).position

    def thumb_index_distance_m(self) -> float | None:
        """Metres between ``thumbTip`` and ``indexFingerTip``; ``None`` if either is unknown."""
        a = self.joint_position(HandJointName.THUMB_TIP)
        b = self.joint_position(HandJointName.INDEX_TIP)
        if a is None or b is None:
            return None
        return norm(sub(a, b))


def hand_frame_from_raw(
    timestamp_s: object,
    chirality: object,
    tracked: object,
    origin_from_anchor: object,
    joints: object,
) -> HandFrame:
    """Build a :class:`HandFrame` from a companion's plain numbers; raises only
    :class:`TransformError`.

    ``chirality`` is ``"left"``/``"right"``; ``joints`` maps Apple's joint names
    (``"thumbTip"``...) to ``(column_major_16, is_tracked)``. An unknown joint name, a
    bad matrix or a duplicate is refused for the whole frame: a hostile or buggy frame is
    dropped and counted by the caller, never half-applied.
    """
    try:
        t = _time("timestamp_s", timestamp_s)
        if chirality not in ("left", "right"):
            raise TransformError("chirality must be 'left' or 'right'")
        if not isinstance(tracked, bool):
            raise TransformError("tracked must be a bool")
        if not isinstance(joints, Mapping):
            raise TransformError("joints must be a mapping of joint name to (matrix, tracked)")
        if len(joints) > len(HandJointName):
            raise TransformError("too many joints")
        poses: list[HandJointPose] = []
        for key, entry in joints.items():
            joint = _JOINT_BY_APPLE_NAME.get(key) if isinstance(key, str) else None
            if joint is None:
                raise TransformError("unknown joint name")
            if not isinstance(entry, (tuple, list)) or len(entry) != 2:
                raise TransformError("a joint entry is (matrix, tracked)")
            matrix, joint_tracked = entry
            if not isinstance(joint_tracked, bool):
                raise TransformError("a joint's tracked flag must be a bool")
            poses.append(HandJointPose(joint, rigid_from_column_major(matrix), joint_tracked))
        return HandFrame(
            t,
            Chirality(chirality),
            tracked,
            rigid_from_column_major(origin_from_anchor),
            tuple(poses),
        )
    except TransformError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:  # pragma: no cover - belt and braces
        raise TransformError(f"malformed hand frame: {exc}") from None


# ── pinch detection with hysteresis ──────────────────────────────────────────


@dataclass(frozen=True)
class PinchConfig:
    """Thresholds for :class:`PinchDetector`. STARTING POINTS, not validated values.

    A pinch starts when the thumb-tip/index-tip distance falls to ``close_m`` or below
    and ends when it rises to ``open_m`` or above. In between nothing changes: that gap
    is the hysteresis that stops a hand hovering at one distance from chattering. The
    distance is between *joint origins*; whether those lie at the fingertip surface or
    inside the finger is not stated by the pages read, which is why these are guesses.
    ``lost_grace_s`` is how long a held pinch survives with the hand or a tip untracked
    before it is ended (a dropout shorter than that does not release hold-to-talk).
    """

    close_m: float = 0.02
    open_m: float = 0.035
    lost_grace_s: float = 0.15

    def __post_init__(self) -> None:
        for n, v in (("close_m", self.close_m), ("open_m", self.open_m),
                     ("lost_grace_s", self.lost_grace_s)):
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"PinchConfig.{n} must be a finite number")
        if not 0.0 < self.close_m < self.open_m <= 0.3:
            raise ValueError("PinchConfig needs 0 < close_m < open_m <= 0.3 metres")
        if self.lost_grace_s < 0:
            raise ValueError("PinchConfig.lost_grace_s must be >= 0")


class PinchDetector:
    """Per-hand pinch state machine: :class:`HandFrame` in, :class:`GestureEvent` out.

    Pure: time comes only from the frames. A frame older than the newest one seen is
    dropped (counted in :attr:`dropped`), so a reordered stream cannot rewind the state.
    A pinch ended by tracking loss is reported with confidence 0.5 (inferred, not
    observed) and the timestamp of the frame that crossed the grace period.
    """

    def __init__(self, chirality: Chirality, config: PinchConfig | None = None) -> None:
        if not isinstance(chirality, Chirality):
            raise ValueError("chirality must be a Chirality")
        self._chirality = chirality
        self._config = config if config is not None else PinchConfig()
        self._pinching = False
        self._last_t = -math.inf
        self._lost_since: float | None = None
        self.dropped = 0

    @property
    def pinching(self) -> bool:
        return self._pinching

    def update(self, frame: HandFrame) -> GestureEvent | None:
        if frame.chirality is not self._chirality:
            raise ValueError("frame is for the other hand")
        t = frame.timestamp_s
        if t < self._last_t:
            self.dropped += 1
            return None
        self._last_t = t
        d = frame.thumb_index_distance_m()
        if d is None:
            if not self._pinching:
                return None
            if self._lost_since is None:
                self._lost_since = t
            if t - self._lost_since > self._config.lost_grace_s:
                self._pinching = False
                self._lost_since = None
                return GestureEvent(t, GestureKind.PINCH_END, 0.5)
            return None
        self._lost_since = None
        if not self._pinching and d <= self._config.close_m:
            self._pinching = True
            return GestureEvent(t, GestureKind.PINCH_START, 1.0)
        if self._pinching and d >= self._config.open_m:
            self._pinching = False
            return GestureEvent(t, GestureKind.PINCH_END, 1.0)
        return None


# ── derived (hand-anchored) pinch ray ────────────────────────────────────────


class PinchRayAnchor(Enum):
    """Where a derived pinch ray starts. See :func:`derived_pinch_ray` for the trade-off."""

    FOREARM = "forearm"  # elbow-side forearm joint (wrist if that is untracked) -> pinch point
    HEAD = "head"        # DeviceAnchor position -> pinch point


@dataclass(frozen=True)
class DerivedRay:
    ray: Ray
    anchor: PinchRayAnchor
    baseline_m: float  # origin-to-pinch-point distance: the lever arm of the estimate

    def angular_error_rad(self, position_sigma_m: float) -> float:
        """First-order angular error from joint-position noise alone (see :func:`pointing_error_rad`)."""
        return pointing_error_rad(self.baseline_m, position_sigma_m, position_sigma_m)


def pointing_error_rad(baseline_m: float, sigma_origin_m: float, sigma_target_m: float) -> float:
    """Angle a line through two noisy points can be off: ``atan2(hypot(so, st), baseline)``.

    Independent, perpendicular position noise ``so`` at the origin and ``st`` at the
    target tilts the line by about ``hypot(so, st) / baseline``. It is why a short lever
    arm is refused: 1 cm of noise over 8 cm is ~7 degrees, over 30 cm ~2 degrees. This is
    **only the measurement-noise term**. The dominant error of any derived ray is whether
    the line a person *intends* to point along is the line the geometry assumes, which
    is unmeasured and likely larger.
    """
    for n, v in (("baseline_m", baseline_m), ("sigma_origin_m", sigma_origin_m),
                 ("sigma_target_m", sigma_target_m)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{n} must be a finite number")
        if v < 0:
            raise ValueError(f"{n} must be >= 0")
    if baseline_m == 0:
        raise ValueError("baseline_m must be > 0")
    return math.atan2(math.hypot(sigma_origin_m, sigma_target_m), baseline_m)


def derived_pinch_ray(
    frame: HandFrame,
    device: RigidTransform,
    anchor: PinchRayAnchor,
    *,
    min_baseline_m: float = 0.08,
) -> DerivedRay | None:
    """A ray from ``anchor`` through the pinch point (midpoint of thumb tip and index tip).

    This is NOT gaze. It is a geometric guess at where a raised hand is pointing, and it
    is only meaningful when the user actually lifts the hand to point:

    * ``FOREARM`` (origin = ``forearmArm``, else ``wrist``): the elbow-through-hand line.
      Independent of head pose and steady, but it points where the *forearm* points, which
      for an indirect pinch (hand resting near the body, WWDC24 10094: "your hand can be
      held closer to your body") is toward the lap, not the target.
    * ``HEAD`` (origin = device position): the 'hand covers the target' line. Correct when
      the pinch is held up in the line of sight, wrong by the eye-to-device offset (a few
      centimetres, unmeasured) in origin, and wrong in direction whenever the hand is low.

    Returns ``None`` when the hand or a needed joint is untracked, or when the origin is
    closer than ``min_baseline_m`` to the pinch point (a short lever arm amplifies joint
    noise, see :func:`pointing_error_rad`) -- a refusal, not a guess.
    """
    if isinstance(min_baseline_m, bool) or not isinstance(min_baseline_m, (int, float)) \
            or not math.isfinite(min_baseline_m) or min_baseline_m <= 0:
        raise ValueError("min_baseline_m must be a positive finite number")
    thumb = frame.joint_position(HandJointName.THUMB_TIP)
    index = frame.joint_position(HandJointName.INDEX_TIP)
    if thumb is None or index is None:
        return None
    target = scale(add(thumb, index), 0.5)
    if anchor is PinchRayAnchor.HEAD:
        origin: Vec3 | None = device.position
    else:
        origin = frame.joint_position(HandJointName.FOREARM_ARM)
        if origin is None:
            origin = frame.joint_position(HandJointName.WRIST)
    if origin is None:
        return None
    delta = sub(target, origin)
    baseline = norm(delta)
    if not math.isfinite(baseline) or baseline < min_baseline_m:
        return None
    return DerivedRay(Ray(origin, normalize(delta)), anchor, baseline)


# ── system input events (the look-and-pinch channel) ─────────────────────────


class SystemInputKind(Enum):
    """``SpatialEventCollection.Event.Kind`` cases, as listed by Apple."""

    DIRECT_PINCH = "directPinch"
    INDIRECT_PINCH = "indirectPinch"
    POINTER = "pointer"
    TOUCH = "touch"
    PENCIL = "pencil"


class InputPhase(Enum):
    """Adapter-side begin/end of an input. Apple's own ``Phase`` cases were not read."""

    BEGAN = "began"
    ENDED = "ended"


@dataclass(frozen=True)
class SystemInputEvent:
    """One system input event, already converted to the canonical frame by the companion.

    ``selection_ray`` is ``selectionRay`` (present for an indirect pinch, where the system
    resolved the user's gaze to a target) and ``location`` is ``location3D`` (the contact
    point of a direct pinch or touch). Either may be ``None``.
    """

    timestamp_s: float
    kind: SystemInputKind
    phase: InputPhase
    selection_ray: Ray | None = None
    location: Vec3 | None = None

    def __post_init__(self) -> None:
        t = self.timestamp_s
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
            raise ValueError("SystemInputEvent.timestamp_s must be a finite number >= 0")
        if not isinstance(self.kind, SystemInputKind) or not isinstance(self.phase, InputPhase):
            raise ValueError("SystemInputEvent.kind / phase have the wrong type")


def system_event_from_raw(
    timestamp_s: object,
    kind: object,
    phase: object,
    ray_origin: object = None,
    ray_direction: object = None,
    location: object = None,
) -> SystemInputEvent:
    """Build a :class:`SystemInputEvent` from plain numbers; raises only
    :class:`TransformError`. The ray direction need not be unit (Apple's ``Ray3D`` makes no
    such promise on the page read); it is normalised, and a zero or huge-NaN one refused.
    A ray needs both ``ray_origin`` and ``ray_direction`` or neither.
    """
    try:
        t = _time("timestamp_s", timestamp_s)
        kinds = {k.value: k for k in SystemInputKind}
        phases = {p.value: p for p in InputPhase}
        if not isinstance(kind, str) or kind not in kinds:
            raise TransformError("unknown input kind")
        if not isinstance(phase, str) or phase not in phases:
            raise TransformError("unknown input phase")
        if (ray_origin is None) != (ray_direction is None):
            raise TransformError("a ray needs both origin and direction")
        ray: Ray | None = None
        if ray_origin is not None:
            origin = _vec("ray_origin", ray_origin)
            direction = _vec("ray_direction", ray_direction)
            if max(abs(origin.x), abs(origin.y), abs(origin.z)) > _MAX_COORD_M:
                raise TransformError("ray_origin is out of range")
            if max(abs(direction.x), abs(direction.y), abs(direction.z)) == 0.0:
                raise TransformError("ray_direction has zero length")
            ray = Ray(origin, normalize(direction))
        point: Vec3 | None = None
        if location is not None:
            point = _vec("location", location)
            if max(abs(point.x), abs(point.y), abs(point.z)) > _MAX_COORD_M:
                raise TransformError("location is out of range")
        return SystemInputEvent(t, kinds[kind], phases[phase], ray, point)
    except TransformError:
        raise
    except (TypeError, ValueError, OverflowError) as exc:  # pragma: no cover - belt and braces
        raise TransformError(f"malformed system event: {exc}") from None


# ── capability description ───────────────────────────────────────────────────


class Availability(Enum):
    CONTINUOUS = "continuous"          # a stream of samples while the app runs
    AT_EVENT_ONLY = "at_event_only"    # only at the instant of a user input (a pinch)
    NOT_PROVIDED = "not_provided"      # the platform withholds it from third-party apps


@dataclass(frozen=True)
class Capability:
    """One input channel, what it needs, and how well the claim is evidenced."""

    name: str
    availability: Availability
    conditions: str
    verified: bool
    source: str


_APPLE = "https://developer.apple.com/"

CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        "eye_gaze_ray", Availability.NOT_PROVIDED,
        "no continuous gaze ray is exposed to third-party apps",
        True,
        _APPLE + "videos/play/wwdc2025/303/ ; " + _APPLE + "forums/thread/757357 "
        "(forum reply by an Apple engineer; not an API reference page; enterprise APIs unchecked)",
    ),
    Capability(
        "hover_state", Availability.NOT_PROVIDED,
        "hover effects are applied by the system outside the app process; the app is not told",
        True,
        _APPLE + "videos/play/wwdc2025/303/",
    ),
    Capability(
        "selection_ray_at_pinch", Availability.AT_EVENT_ONLY,
        "SpatialEventCollection.Event.selectionRay on an input event; refresh during a held "
        "pinch and the ray's coordinate space are UNVERIFIED",
        True,
        _APPLE + "documentation/swiftui/spatialeventcollection/event",
    ),
    Capability(
        "direct_touch_location", Availability.AT_EVENT_ONLY,
        "SpatialEventCollection.Event.location3D for directPinch / touch kinds",
        True,
        _APPLE + "documentation/swiftui/spatialeventcollection/event/kind-swift.enum",
    ),
    Capability(
        "hand_skeleton", Availability.CONTINUOUS,
        "ARKit HandTrackingProvider; Full Space only (not the Shared Space); needs user "
        "permission; 27 joints",
        True,
        _APPLE + "videos/play/wwdc2024/10094/ ; " + _APPLE + "videos/play/wwdc2023/10082/ ; "
        + _APPLE + "documentation/arkit/handskeleton/jointname",
    ),
    Capability(
        "device_pose", Availability.CONTINUOUS,
        "WorldTrackingProvider.queryDeviceAnchor; the query is 'relatively expensive'; "
        "whether it needs permission and the exact forward axis are UNVERIFIED",
        True,
        _APPLE + "videos/play/wwdc2023/10082/",
    ),
)

_CAP_BY_NAME: dict[str, Capability] = {c.name: c for c in CAPABILITIES}


def capability(name: str) -> Capability:
    """Look a capability up by name; the ``KeyError`` lists the valid names."""
    try:
        return _CAP_BY_NAME[name]
    except (KeyError, TypeError):
        raise KeyError(f"unknown capability {name!r}; known: {', '.join(_CAP_BY_NAME)}") from None


# ── pointing source choice and its degradation ───────────────────────────────


class PointingMode(Enum):
    """Which channel :meth:`VisionOSPointer.choose` fell back to, best first."""

    PINCH_RAY = "pinch_ray"        # system look-and-pinch ray, at pinch time (gaze-derived)
    DIRECT_TOUCH = "direct_touch"  # contact point of a direct pinch / touch
    HAND_RAY = "hand_ray"          # derived hand ray; opt-in, see PointerConfig.use_hand_ray
    HEAD_RAY = "head_ray"          # DeviceAnchor forward; continuous but not gaze
    NONE = "none"

    @property
    def is_gaze_derived(self) -> bool:
        return self is PointingMode.PINCH_RAY

    @property
    def is_continuous(self) -> bool:
        return self in (PointingMode.HAND_RAY, PointingMode.HEAD_RAY)


@dataclass(frozen=True)
class PointerConfig:
    """Freshness and confidence for :class:`VisionOSPointer`. STARTING POINTS, unmeasured.

    ``pinch_ttl_s``: how long after a pinch / touch its ray is still the 'last pinch ray'
    fallback. ``stale_s``: how old a head or hand sample may be and still be current.
    Confidences are the tracking confidence stamped on emitted samples: a head ray is not
    gaze, so it is deliberately low; ``use_hand_ray`` is off because a hand resting low
    during an indirect pinch points at the lap.
    """

    pinch_ttl_s: float = 1.0
    stale_s: float = 0.25
    pinch_confidence: float = 0.9
    touch_confidence: float = 1.0
    head_confidence: float = 0.4
    hand_confidence: float = 0.5
    use_hand_ray: bool = False
    hand_anchor: PinchRayAnchor = PinchRayAnchor.FOREARM

    def __post_init__(self) -> None:
        for n in ("pinch_ttl_s", "stale_s", "pinch_confidence", "touch_confidence",
                  "head_confidence", "hand_confidence"):
            v = getattr(self, n)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"PointerConfig.{n} must be a finite number")
        for n in ("pinch_ttl_s", "stale_s"):
            if getattr(self, n) <= 0:
                raise ValueError(f"PointerConfig.{n} must be > 0")
        for n in ("pinch_confidence", "touch_confidence", "head_confidence", "hand_confidence"):
            if not 0.0 <= getattr(self, n) <= 1.0:
                raise ValueError(f"PointerConfig.{n} must be within [0, 1]")
        if not isinstance(self.use_hand_ray, bool):
            raise ValueError("PointerConfig.use_hand_ray must be a bool")
        if not isinstance(self.hand_anchor, PinchRayAnchor):
            raise ValueError("PointerConfig.hand_anchor must be a PinchRayAnchor")


@dataclass(frozen=True)
class PointingChoice:
    """The pointing source in force at one instant. ``sample`` keeps its ORIGINAL time."""

    mode: PointingMode
    sample: XrSample | None
    age_s: float
    reason: str


class VisionOSPointer:
    """Keeps only the latest sample per channel and picks the best fresh one.

    It stores at most three samples (the latest deliberate pinch/touch, head and hand),
    never a history: retention of a rolling window is the caller's
    (:class:`yazses.xr.privacy.SampleRetention`), so the privacy bound stays in one place.
    Every ``observe_*`` returns the real sample it made (or ``None``) for the caller to
    feed that window. Nothing is ever re-stamped: a stale pinch ray is not turned into a
    fresh-looking time series, because that would fabricate gaze the platform withheld.

    Priority in :meth:`choose`: a fresh pinch ray or touch contact, then (if enabled) a
    fresh hand ray, then a fresh head ray, else nothing.
    """

    def __init__(self, config: PointerConfig | None = None) -> None:
        self._cfg = config if config is not None else PointerConfig()
        self._deliberate: tuple[PointingMode, XrSample] | None = None
        self._head: XrSample | None = None
        self._hand: XrSample | None = None

    def clear(self) -> None:
        self._deliberate = None
        self._head = None
        self._hand = None

    def observe_device(self, timestamp_s: float, device: RigidTransform) -> XrSample:
        """The head ray from a ``DeviceAnchor`` update (always available while running)."""
        sample = XrSample(timestamp_s, RaySource.HEAD, forward_ray(device),
                          self._cfg.head_confidence)
        self._head = sample
        return sample

    def observe_hand(
        self, frame: HandFrame, device: RigidTransform
    ) -> XrSample | None:
        """A derived hand ray, or ``None`` when the hand or lever arm does not allow one."""
        derived = derived_pinch_ray(frame, device, self._cfg.hand_anchor)
        if derived is None:
            return None
        sample = XrSample(frame.timestamp_s, RaySource.HAND, derived.ray,
                          self._cfg.hand_confidence)
        self._hand = sample
        return sample

    def observe_system_event(self, event: SystemInputEvent) -> XrSample | None:
        """A pinch / touch began: the only moment the platform says where the user aimed.

        * indirect pinch with a ``selection_ray``: a pinch-ray sample, source ``EYE``
          (the system derived it from gaze at that instant; this is the only ``EYE``
          sample visionOS can ever produce, and it is a single instant, not a stream);
        * direct pinch / touch with a ``location``: a ray from the latest head position
          through the contact point, source ``HAND`` -- needs a head sample no older than
          ``stale_s``, else ``None`` (no origin to aim from);
        * anything else (ended phase, pointer, pencil, missing ray or point): ``None``.
        """
        if event.phase is not InputPhase.BEGAN:
            return None
        cfg = self._cfg
        if event.kind is SystemInputKind.INDIRECT_PINCH and event.selection_ray is not None:
            sample = XrSample(event.timestamp_s, RaySource.EYE, event.selection_ray,
                              cfg.pinch_confidence)
            self._deliberate = (PointingMode.PINCH_RAY, sample)
            return sample
        if event.kind in (SystemInputKind.DIRECT_PINCH, SystemInputKind.TOUCH) \
                and event.location is not None and self._head is not None:
            age = event.timestamp_s - self._head.timestamp_s
            if not 0.0 <= age <= cfg.stale_s:
                return None
            origin = self._head.ray.origin
            delta = sub(event.location, origin)
            d = norm(delta)
            if not math.isfinite(d) or d == 0.0:
                return None
            sample = XrSample(event.timestamp_s, RaySource.HAND, Ray(origin, normalize(delta)),
                              cfg.touch_confidence)
            self._deliberate = (PointingMode.DIRECT_TOUCH, sample)
            return sample
        return None

    def choose(self, now_s: float) -> PointingChoice:
        """The best channel that is fresh at ``now_s``; never raises on stale data."""
        if isinstance(now_s, bool) or not isinstance(now_s, (int, float)) \
                or not math.isfinite(now_s):
            raise ValueError("now_s must be a finite number")
        cfg = self._cfg
        if self._deliberate is not None:
            mode, s = self._deliberate
            age = now_s - s.timestamp_s
            if 0.0 <= age <= cfg.pinch_ttl_s:
                return PointingChoice(mode, s, age, f"{mode.value} {age:.2f}s old")
        if cfg.use_hand_ray and self._hand is not None:
            age = now_s - self._hand.timestamp_s
            if 0.0 <= age <= cfg.stale_s:
                return PointingChoice(PointingMode.HAND_RAY, self._hand, age, "derived hand ray")
        if self._head is not None:
            age = now_s - self._head.timestamp_s
            if 0.0 <= age <= cfg.stale_s:
                return PointingChoice(PointingMode.HEAD_RAY, self._head, age,
                                      "head ray: visionOS gives no continuous gaze")
        return PointingChoice(PointingMode.NONE, None, math.inf, "no fresh pointing source")


# ── what the binder loses ────────────────────────────────────────────────────


@dataclass(frozen=True)
class WindowEvidence:
    """How much pointing evidence falls in a demonstrative's binding window.

    ``pinch_rays`` counts ``EYE`` samples (on visionOS: pinch-time rays), ``head`` the
    ``HEAD`` ones, ``hand`` the ``HAND`` ones. ``meets_binder_minimum`` is whether the
    window holds at least ``BINDER_MIN_SAMPLES`` samples at all, the binder's floor for
    returning anything but NONE ("insufficient evidence").
    """

    in_window: int
    pinch_rays: int
    head: int
    hand: int
    meets_binder_minimum: bool
    gaze_in_window: bool


def window_evidence(
    samples: Sequence[XrSample],
    word_onset_s: float,
    *,
    lead_s: float = BINDER_LEAD_S,
    lag_s: float = BINDER_LAG_S,
) -> WindowEvidence:
    """Count the samples inside ``[onset - lead_s, onset + lag_s]`` by source.

    Why this matters (the capability loss, in numbers): the binder resolves 'here' from
    the pointing history around the word's onset and needs ``BINDER_MIN_SAMPLES`` (3)
    usable observations. A gaze-capable headset streams tens of ``EYE`` samples per second,
    so a 0.6 s window holds dozens. On visionOS the only gaze-derived sample is the single
    pinch-time ray, so the window holds **0 or 1** of them, and unless the head stream is
    used (which is not gaze), the binder returns NONE for lack of evidence by design.
    """
    for n, v in (("word_onset_s", word_onset_s), ("lead_s", lead_s), ("lag_s", lag_s)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{n} must be a finite number")
    if lead_s < 0 or lag_s < 0:
        raise ValueError("lead_s and lag_s must be >= 0")
    lo, hi = word_onset_s - lead_s, word_onset_s + lag_s
    inside = [s for s in samples if lo <= s.timestamp_s <= hi]
    pinch = sum(1 for s in inside if s.source is RaySource.EYE)
    head = sum(1 for s in inside if s.source is RaySource.HEAD)
    hand = sum(1 for s in inside if s.source is RaySource.HAND)
    return WindowEvidence(len(inside), pinch, head, hand, len(inside) >= BINDER_MIN_SAMPLES,
                          pinch > 0)


def nearest_pinch_sample(
    samples: Sequence[XrSample],
    word_onset_s: float,
    *,
    max_skew_s: float = 1.5,
) -> tuple[XrSample, float] | None:
    """The pinch-time ray closest in time to the word, as ``(sample, signed skew)``.

    The 'last pinch ray' fallback when the binder has too little in its window: a user
    often pinches a beat after (or before) saying 'here'. Skew is ``sample time - word
    onset`` (positive = pinched after the word). Returns ``None`` beyond ``max_skew_s``.
    This is ONE observation, not a distribution: treat any binding built on it as weaker
    evidence than the binder's, and route it through confirmation (``xr.confirm``).
    Ties go to the earlier sample.
    """
    for n, v in (("word_onset_s", word_onset_s), ("max_skew_s", max_skew_s)):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError(f"{n} must be a finite number")
    if max_skew_s < 0:
        raise ValueError("max_skew_s must be >= 0")
    best: tuple[XrSample, float] | None = None
    for s in samples:
        if s.source is not RaySource.EYE:
            continue
        skew = s.timestamp_s - word_onset_s
        if abs(skew) > max_skew_s:
            continue
        if best is None or abs(skew) < abs(best[1]) \
                or (abs(skew) == abs(best[1]) and s.timestamp_s < best[0].timestamp_s):
            best = (s, skew)
    return best
