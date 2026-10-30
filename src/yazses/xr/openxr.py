"""OpenXR data -> ``yazses.xr`` types (pure, stdlib only, hostile-input total).

A companion app on an OpenXR headset (Monado, SteamVR, a Quest or Pico runtime, Android
XR) calls the OpenXR API itself. This module never does: it has **no OpenXR import and no
SDK dependency**. It models the *data* those calls return -- poses, location flags,
action states, hand joints, ``XrTime`` -- as plain numbers, and maps them onto the
package types (:class:`~yazses.xr.types.XrSample`, :class:`~yazses.xr.types.GestureEvent`).
The companion fills in plain Python numbers and tuples; nothing here can fail with
anything but :class:`OpenXrError`, a ``ValueError``.

Conventions (OpenXR and this package agree, so no axis conversion is needed)
----------------------------------------------------------------------------
Right-handed, +X right, +Y up, -Z forward, metres, radians. Spec: OpenXR 1.1, "Spaces",
``XrReferenceSpaceType`` -- VIEW and LOCAL are "+Y up, +X to the right, and -Z forward"
(verified); STAGE has "+Y up" with X and Z "aligned with the rectangle edges" (verified).
**Pointing is along the pose's -Z axis**: that is verified for the eye-gaze pose
(``XR_EXT_eye_gaze_interaction``: "+Y up, +X to the right, and -Z forward", read from
the spec through a search excerpt, not from the extension page itself) and **unverified**
as a spec sentence for ``aim`` poses -- it is the ubiquitous convention, but this module
makes the forward axis a parameter (``forward=``) rather than hard-wiring an unconfirmed
claim into every caller.

What is verified, and where (fetched 2026-10-30, ``registry.khronos.org/OpenXR/specs/1.1``)
-------------------------------------------------------------------------------------------
* ``XrPosef`` -- ``orientation`` (``XrQuaternionf`` x, y, z, w floats) and ``position``
  (metres); orientation is a unit quaternion applied *before* the translation; a runtime
  must return ``XR_ERROR_POSE_INVALID`` if the orientation norm deviates by more than 1 %
  from unit length. That 1 % is this module's default quaternion tolerance
  (``man/html/XrPosef.html``, ``XrQuaternionf.html``).
* ``XrSpaceLocationFlagBits`` -- four bits: ORIENTATION_VALID, POSITION_VALID,
  ORIENTATION_TRACKED, POSITION_TRACKED. *Valid* means the field holds usable data and
  must not be read otherwise; *tracked* means actively tracked (an untracked but valid
  pose is an inferred or last-known value) (``man/html/XrSpaceLocationFlagBits.html``).
  The numeric bit values are **unverified** here (the fetched page lists names only);
  they are taken from the public ``openxr_core.h`` header from memory (0x1, 0x2, 0x4,
  0x8) and pinned by a test, so a mismatch surfaces as a spec diff to review.
* ``XrReferenceSpaceType`` -- VIEW tracks the head and so rotates with it; LOCAL is
  world-locked and gravity-aligned; STAGE is a room-scale rectangle
  (``man/html/XrReferenceSpaceType.html``).
* ``XrTime`` -- signed 64-bit count of nanoseconds since a *runtime-chosen* epoch,
  monotonically increasing; zero or negative is invalid (``man/html/XrTime.html``).
* ``XrEyeGazeSampleTimeEXT::time`` -- "may be in the future if a runtime is able to
  predict"; "the runtime must set the time field to 0 if the sample time is not
  available" (``man/html/XrEyeGazeSampleTimeEXT.html``).
* ``XrHandJointEXT`` -- 26 joints, values 0..25: PALM=0, WRIST=1, THUMB_TIP=5,
  INDEX_TIP=10 (``man/html/XrHandJointEXT.html``). ``XrHandJointLocationEXT`` has
  ``locationFlags``, ``pose`` (in ``baseSpace``) and ``radius`` in metres, positive
  whenever POSITION_VALID is set (``man/html/XrHandJointLocationEXT.html``).
* Interaction profile and input paths listed in the ``*_PROFILE`` / ``*_PATH`` constants
  below: from search excerpts of the spec's interaction-profile sections.

What is **unverified** (not confirmed against the spec text in this session)
----------------------------------------------------------------------------
* The numeric flag bits (above) and the numeric ``XrReferenceSpaceType`` values (not
  modelled at all).
* The range of ``XrActionStateFloat::currentState`` (the page does not state one). Trigger
  and pinch values are treated as 0..1 and clamped; see :class:`HoldGesture`.
* That an *inactive* action reports a state of zero.
* The ``-Z`` pointing axis of ``aim`` poses, as a spec sentence (see above).
* The ``pinch_ext/pose`` and ``poke_ext/pose`` pose paths of ``XR_EXT_hand_interaction``
  and the geometric definition of its pinch pose. This module therefore does **not** read
  those poses: it derives its own pinch ray from the 26-joint hand data
  (``XR_EXT_hand_tracking``), whose geometry is known.
* Every threshold and distance in this module (``press``/``release``, the pinch gap
  range, the untracked-confidence penalty) is a *heuristic default* chosen for synthetic
  tests, not measured on a device. They are parameters, not facts.

Not modelled on purpose: the ``grip`` pose. Its job is to describe how the hand holds an
object, not where it points -- the spec calls the *aim* pose the one for "interacting with
objects out of arm's reach" -- so :func:`aim_sample` exists and a grip sample does not.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, IntEnum

from yazses.xr.geometry import cross, scale, sub
from yazses.xr.geometry import normalize as _geo_normalize
from yazses.xr.types import GestureEvent, GestureKind, Ray, RaySource, Vec3, XrSample

# ── interaction profiles and paths (strings the companion binds; never called here) ─────

EYE_GAZE_EXTENSION = "XR_EXT_eye_gaze_interaction"
EYE_GAZE_PROFILE = "/interaction_profiles/ext/eye_gaze_interaction"
EYE_GAZE_POSE_PATH = "/user/eyes_ext/input/gaze_ext/pose"

SIMPLE_CONTROLLER_PROFILE = "/interaction_profiles/khr/simple_controller"
#: ``<hand>`` is ``left`` or ``right``. The profile also has ``menu/click``,
#: ``grip/pose`` and a haptic output (spec 1.0/1.1 profile table).
SIMPLE_CONTROLLER_SELECT_PATH = "/user/hand/<hand>/input/select/click"
SIMPLE_CONTROLLER_AIM_PATH = "/user/hand/<hand>/input/aim/pose"

HAND_INTERACTION_EXTENSION = "XR_EXT_hand_interaction"
HAND_INTERACTION_PROFILE = "/interaction_profiles/ext/hand_interaction_ext"
HAND_PINCH_VALUE_PATH = "/user/hand/<hand>/input/pinch_ext/value"
HAND_GRASP_VALUE_PATH = "/user/hand/<hand>/input/grasp_ext/value"
HAND_AIM_ACTIVATE_VALUE_PATH = "/user/hand/<hand>/input/aim_activate_ext/value"

HAND_TRACKING_EXTENSION = "XR_EXT_hand_tracking"

# ── limits ──────────────────────────────────────────────────────────────────────────────

_MAX_COORD_M = 1e6          # same cap as the wire layer: every product stays finite
_MAX_TIME_S = 1e9           # same cap as wire.ClockMap's device_time_s
_INT64_MAX = 2**63 - 1
_NS = 10**9
_UINT64_MAX = 2**64 - 1
_HAND_JOINT_COUNT = 26

#: Default tolerance on a quaternion's norm. Not arbitrary: it is the 1 % the spec lets a
#: runtime reject at (``XrPosef``), so anything a conforming runtime returns is accepted.
SPEC_QUATERNION_TOLERANCE = 0.01
_UNIT_TOL = 1e-6


class OpenXrError(ValueError):
    """Input that cannot be an OpenXR value, or a mapping that is refused.

    Every public function in this module raises this and nothing else for bad input,
    whatever its type or magnitude. The caller drops the frame and counts it.
    """


# ── scalar validation ───────────────────────────────────────────────────────────────────


def _number(name: str, value: object) -> float:
    """A finite real number as ``float``. ``bool`` is not a number; huge ints are refused."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OpenXrError(f"{name} must be a number, got {type(value).__name__}")
    try:
        number = float(value)
    except OverflowError:  # 10**400 does not fit a float
        raise OpenXrError(f"{name} is too large") from None
    if not math.isfinite(number):
        raise OpenXrError(f"{name} must be finite")
    return number


def _bounded(name: str, value: object) -> float:
    number = _number(name, value)
    if abs(number) > _MAX_COORD_M:
        raise OpenXrError(f"{name} is outside +-{_MAX_COORD_M:g}")
    return number


def _vec3(name: str, value: object) -> Vec3:
    if isinstance(value, Vec3):
        return Vec3(
            _bounded(f"{name}.x", value.x), _bounded(f"{name}.y", value.y), _bounded(f"{name}.z", value.z)
        )
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise OpenXrError(f"{name} must be a sequence of three numbers")
    return Vec3(*(_bounded(f"{name}[{i}]", c) for i, c in enumerate(value)))


def normalize(v: Vec3) -> Vec3:
    """Unit vector along ``v``; a zero vector raises :class:`OpenXrError`, not a bare ValueError."""
    try:
        return _geo_normalize(v)
    except ValueError:
        raise OpenXrError("a zero-length vector has no direction") from None


def _timestamp(name: str, value: object) -> float:
    number = _number(name, value)
    if number < 0 or number > _MAX_TIME_S:
        raise OpenXrError(f"{name} must be within [0, {_MAX_TIME_S:g}] seconds")
    return number


def _unit_value(name: str, value: object) -> float:
    """A finite number clamped into [0, 1] (the range of trigger-like values; see module doc)."""
    return min(1.0, max(0.0, _number(name, value)))


# ── quaternions ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Quat:
    """A unit quaternion ``(x, y, z, w)``, the layout of ``XrQuaternionf``.

    Construct with :func:`quat_from_raw` (which normalises); the constructor itself only
    accepts an already-unit value (tolerance 1e-6, as ``Ray`` does) so a ``Quat`` in hand
    is always a rotation.
    """

    x: float
    y: float
    z: float
    w: float

    def __post_init__(self) -> None:
        for n, v in (("x", self.x), ("y", self.y), ("z", self.z), ("w", self.w)):
            _number(f"Quat.{n}", v)
        if abs(math.hypot(self.x, self.y, self.z, self.w) - 1.0) > _UNIT_TOL:
            raise OpenXrError("Quat must be unit length")


QUAT_IDENTITY = Quat(0.0, 0.0, 0.0, 1.0)


def quat_from_raw(
    x: object,
    y: object,
    z: object,
    w: object,
    *,
    tolerance: float | None = SPEC_QUATERNION_TOLERANCE,
) -> Quat:
    """An ``XrQuaternionf`` as a unit :class:`Quat`.

    ``tolerance`` is the allowed deviation of the norm from 1 (default 1 %, the bound at
    which the spec has a runtime fail; ``XrPosef``). Within it the quaternion is
    renormalised; beyond it, or for a zero, NaN, infinite, non-numeric or ``bool``
    component, :class:`OpenXrError`. ``tolerance=None`` accepts any non-zero finite
    quaternion and normalises it explicitly (use for a source known to send unnormalised
    values); a zero quaternion is still refused, because it has no direction.

    Norms are computed with ``math.hypot`` and, for ``tolerance=None``, after scaling by
    the largest component, so components near 1e308 neither overflow nor, near 5e-324,
    underflow to a false zero.
    """
    if tolerance is not None:
        tol = _number("tolerance", tolerance)
        if not 0.0 <= tol < 1.0:
            raise OpenXrError("tolerance must be within [0, 1)")
    c = [_number(n, v) for n, v in (("x", x), ("y", y), ("z", z), ("w", w))]
    peak = max(abs(v) for v in c)
    if peak == 0.0:
        raise OpenXrError("a zero quaternion has no orientation")
    if tolerance is None:
        s = [v / peak for v in c]  # components in [-1, 1], peak == 1
        n = math.hypot(*s)
        return Quat(*(v / n for v in s))
    n = math.hypot(*c)
    if abs(n - 1.0) > tol:
        raise OpenXrError(f"quaternion norm {n:g} deviates from 1 by more than {tol:g}")
    return Quat(*(v / n for v in c))


def quat_conjugate(q: Quat) -> Quat:
    """The inverse rotation (for a unit quaternion the conjugate is the inverse)."""
    return Quat(-q.x, -q.y, -q.z, q.w)


def quat_multiply(a: Quat, b: Quat) -> Quat:
    """Hamilton product ``a * b``: apply ``b`` first, then ``a`` (renormalised).

    The renormalisation stops rounding drift from accumulating over a long chain.
    """
    x = a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y
    y = a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x
    z = a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w
    w = a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z
    return quat_from_raw(x, y, z, w, tolerance=None)


def quat_rotate(q: Quat, v: Vec3) -> Vec3:
    """Rotate ``v`` by ``q``: ``v + w*t + u x t`` with ``u = (x, y, z)`` and ``t = 2 u x v``."""
    u = Vec3(q.x, q.y, q.z)
    try:
        t = scale(cross(u, v), 2.0)
        ut = cross(u, t)
        return Vec3(v.x + q.w * t.x + ut.x, v.y + q.w * t.y + ut.y, v.z + q.w * t.z + ut.z)
    except ValueError:  # a vector near 1e308 overflowed to inf
        raise OpenXrError("rotated vector overflowed") from None


def quat_from_axis_angle(axis: Vec3, angle_rad: float) -> Quat:
    """Rotation by ``angle_rad`` about ``axis`` (right-hand rule). For tests and synthetics."""
    a = normalize(_vec3("axis", axis))
    half = _number("angle_rad", angle_rad) / 2.0
    s = math.sin(half)
    return quat_from_raw(a.x * s, a.y * s, a.z * s, math.cos(half), tolerance=None)


# ── poses and location flags ────────────────────────────────────────────────────────────


class ReferenceSpace(Enum):
    """The ``XrReferenceSpaceType`` a pose was *located relative to*.

    Closed. The numeric C values are not modelled (unverified); the companion maps its
    own enum onto these names.
    """

    VIEW = "view"    # head-locked: a ray located here rotates with the head
    LOCAL = "local"  # world-locked, gravity-aligned origin
    STAGE = "stage"  # runtime-defined room-scale rectangle; its origin differs from LOCAL's


#: Spaces in which a pointing ray is fixed in the world, hence comparable with panels.
_WORLD_FIXED = frozenset({ReferenceSpace.LOCAL, ReferenceSpace.STAGE})


def require_world_space(space: object) -> ReferenceSpace:
    """Refuse a ray from VIEW space: it is head-relative, so panels would 'move' with you.

    Locate gaze and aim poses against LOCAL or STAGE and send the panels in the *same*
    space. This module cannot check that the two agree (it only sees a label); that is
    the companion's contract.
    """
    if not isinstance(space, ReferenceSpace):
        raise OpenXrError(f"space must be a ReferenceSpace, got {type(space).__name__}")
    if space not in _WORLD_FIXED:
        raise OpenXrError(
            "a ray located in VIEW space is head-relative; locate it in LOCAL or STAGE"
        )
    return space


# Bit values from openxr_core.h -- UNVERIFIED against the spec pages fetched (names only).
SPACE_LOCATION_ORIENTATION_VALID_BIT = 0x1
SPACE_LOCATION_POSITION_VALID_BIT = 0x2
SPACE_LOCATION_ORIENTATION_TRACKED_BIT = 0x4
SPACE_LOCATION_POSITION_TRACKED_BIT = 0x8


@dataclass(frozen=True)
class LocationFlags:
    """Decoded ``XrSpaceLocationFlags`` (an ``XrFlags64``)."""

    orientation_valid: bool
    position_valid: bool
    orientation_tracked: bool
    position_tracked: bool

    @property
    def usable(self) -> bool:
        """Both fields may be read. A pointing ray needs an origin AND a direction."""
        return self.orientation_valid and self.position_valid

    @property
    def consistent(self) -> bool:
        """False when a *tracked* bit is set without its *valid* bit -- a runtime bug."""
        return (self.orientation_valid or not self.orientation_tracked) and (
            self.position_valid or not self.position_tracked
        )


def parse_location_flags(flags: object) -> LocationFlags:
    """Decode a raw ``XrSpaceLocationFlags`` integer. Unknown bits are ignored (forward compat).

    Only a real ``int`` in ``[0, 2**64)`` is accepted; ``bool``, floats and negatives are
    refused (a flags field is a bit set, not a quantity).
    """
    if isinstance(flags, bool) or not isinstance(flags, int):
        raise OpenXrError(f"location flags must be an int, got {type(flags).__name__}")
    if not 0 <= flags <= _UINT64_MAX:
        raise OpenXrError("location flags must fit an unsigned 64-bit integer")
    return LocationFlags(
        orientation_valid=bool(flags & SPACE_LOCATION_ORIENTATION_VALID_BIT),
        position_valid=bool(flags & SPACE_LOCATION_POSITION_VALID_BIT),
        orientation_tracked=bool(flags & SPACE_LOCATION_ORIENTATION_TRACKED_BIT),
        position_tracked=bool(flags & SPACE_LOCATION_POSITION_TRACKED_BIT),
    )


#: Confidence given to a *valid but not tracked* (inferred / last-known) component. A
#: heuristic default, not a spec value; override per call.
DEFAULT_UNTRACKED_CONFIDENCE = 0.4


def location_confidence(
    flags: LocationFlags, *, untracked_confidence: float = DEFAULT_UNTRACKED_CONFIDENCE
) -> float:
    """Confidence in [0, 1] for a located pose: the weaker of its two components.

    Not usable (a needed field is not valid, or the flags are inconsistent) -> 0.0.
    Tracked -> 1.0; valid but not tracked -> ``untracked_confidence``.
    """
    pen = _number("untracked_confidence", untracked_confidence)
    if not 0.0 <= pen <= 1.0:
        raise OpenXrError("untracked_confidence must be within [0, 1]")
    if not flags.usable or not flags.consistent:
        return 0.0
    pos = 1.0 if flags.position_tracked else pen
    ori = 1.0 if flags.orientation_tracked else pen
    return min(pos, ori)


@dataclass(frozen=True)
class XrPose:
    """An ``XrPosef``: ``position`` in metres, unit ``orientation``."""

    position: Vec3
    orientation: Quat


#: -Z, the pointing axis of a gaze pose (verified) and, by convention, of an aim pose.
FORWARD = Vec3(0.0, 0.0, -1.0)


def pose_from_raw(
    position: object,
    orientation: object,
    *,
    tolerance: float | None = SPEC_QUATERNION_TOLERANCE,
) -> XrPose:
    """An ``XrPosef`` from ``(x, y, z)`` and ``(x, y, z, w)`` sequences."""
    if not isinstance(orientation, (list, tuple)) or len(orientation) != 4:
        raise OpenXrError("orientation must be a sequence of four numbers (x, y, z, w)")
    return XrPose(
        _vec3("position", position),
        quat_from_raw(*orientation, tolerance=tolerance),
    )


def pose_forward(pose: XrPose, forward: Vec3 = FORWARD) -> Vec3:
    """World-frame unit direction of the pose's ``forward`` axis (default -Z)."""
    f = normalize(_vec3("forward", forward))
    return normalize(quat_rotate(pose.orientation, f))


def pose_transform_point(pose: XrPose, local: Vec3) -> Vec3:
    """``local`` (in the pose's own frame) expressed in the frame the pose is relative to.

    Rotation first, then translation -- the order the spec fixes for ``XrPosef``.
    """
    p = quat_rotate(pose.orientation, _vec3("local", local))
    try:
        return Vec3(p.x + pose.position.x, p.y + pose.position.y, p.z + pose.position.z)
    except ValueError:
        raise OpenXrError("transformed point overflowed") from None


def ray_from_pose(pose: XrPose, forward: Vec3 = FORWARD) -> Ray:
    """A pointing :class:`Ray` from a pose: origin at its position, direction along ``forward``."""
    return Ray(pose.position, pose_forward(pose, forward))


# ── pointing samples ────────────────────────────────────────────────────────────────────


def _located_ray(
    flags: object,
    position: object,
    orientation: object,
    space: object,
    *,
    tolerance: float | None,
    untracked_confidence: float,
    forward: Vec3,
) -> tuple[Ray, float] | None:
    """Shared body: ``None`` when the pose may not be read, else ``(ray, confidence)``."""
    require_world_space(space)
    decoded = parse_location_flags(flags)
    if not decoded.usable or not decoded.consistent:
        return None  # the spec forbids reading a field whose valid bit is clear
    pose = pose_from_raw(position, orientation, tolerance=tolerance)
    conf = location_confidence(decoded, untracked_confidence=untracked_confidence)
    return ray_from_pose(pose, forward), conf


def gaze_sample(
    timestamp_s: object,
    flags: object,
    position: object,
    orientation: object,
    space: ReferenceSpace,
    *,
    tolerance: float | None = SPEC_QUATERNION_TOLERANCE,
    untracked_confidence: float = DEFAULT_UNTRACKED_CONFIDENCE,
) -> XrSample | None:
    """An ``XR_EXT_eye_gaze_interaction`` gaze pose as an EYE :class:`XrSample`.

    Returns ``None`` (not an error) when the runtime reports the pose unusable -- position
    or orientation not valid -- because that is a normal blink or tracking-loss frame.
    ``timestamp_s`` is on the *device* clock; map it with ``wire.ClockMap`` before use.
    A gaze located in VIEW space is refused (:func:`require_world_space`).
    """
    t = _timestamp("timestamp_s", timestamp_s)
    got = _located_ray(
        flags, position, orientation, space,
        tolerance=tolerance, untracked_confidence=untracked_confidence, forward=FORWARD,
    )
    if got is None:
        return None
    ray, conf = got
    return XrSample(t, RaySource.EYE, ray, conf)


def aim_sample(
    timestamp_s: object,
    flags: object,
    position: object,
    orientation: object,
    space: ReferenceSpace,
    *,
    source: RaySource = RaySource.CONTROLLER,
    tolerance: float | None = SPEC_QUATERNION_TOLERANCE,
    untracked_confidence: float = DEFAULT_UNTRACKED_CONFIDENCE,
    forward: Vec3 = FORWARD,
) -> XrSample | None:
    """An ``aim`` pose (``khr/simple_controller`` or ``hand_interaction``) as a sample.

    ``source`` is CONTROLLER (default) or HAND. ``forward`` defaults to -Z (see module
    docs: unverified as spec text for aim poses). ``None`` when the pose is not usable.
    """
    if source not in (RaySource.CONTROLLER, RaySource.HAND):
        raise OpenXrError("an aim pose comes from a CONTROLLER or a HAND")
    t = _timestamp("timestamp_s", timestamp_s)
    got = _located_ray(
        flags, position, orientation, space,
        tolerance=tolerance, untracked_confidence=untracked_confidence, forward=forward,
    )
    if got is None:
        return None
    ray, conf = got
    return XrSample(t, source, ray, conf)


# ── time ────────────────────────────────────────────────────────────────────────────────


def _xr_time(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise OpenXrError(f"{name} must be an int count of nanoseconds, got {type(value).__name__}")
    if value <= 0:
        raise OpenXrError(f"{name} must be > 0 (the spec makes zero and negative XrTime invalid)")
    if value > _INT64_MAX:
        raise OpenXrError(f"{name} does not fit a signed 64-bit XrTime")
    return value


def xr_time_to_seconds(xr_time_ns: object) -> float:
    """An absolute ``XrTime`` (nanoseconds) as seconds on the runtime's own epoch.

    Exact for the conversion itself (Python's int/int division is correctly rounded).
    Refused above ~1e9 s, the largest ``device_time_s`` the wire layer accepts: a runtime
    whose epoch is the Unix epoch (~1.7e9 s) must use :class:`XrTimeBase` instead.
    """
    ns = _xr_time("xr_time_ns", xr_time_ns)
    seconds = ns / _NS
    if seconds > _MAX_TIME_S:
        raise OpenXrError("XrTime too far from zero for device_time_s; use XrTimeBase")
    return seconds


def choose_gaze_time(sample_time_ns: object, display_time_ns: object) -> int:
    """The nanosecond time to stamp a gaze sample with.

    ``XrEyeGazeSampleTimeEXT::time`` is the moment the gaze was actually measured -- and is
    ``0`` when the runtime cannot say (spec). In that case fall back to the predicted
    display time of the frame. A ``bool``/non-int, negative or out-of-range value is refused;
    ``0`` is valid *only* for the sample time.
    """
    if isinstance(sample_time_ns, bool) or not isinstance(sample_time_ns, int):
        raise OpenXrError("sample_time_ns must be an int")
    display = _xr_time("display_time_ns", display_time_ns)  # always supplied, always checked
    if sample_time_ns == 0:
        return display
    return _xr_time("sample_time_ns", sample_time_ns)


class XrTimeBase:
    """Turns ``XrTime`` nanoseconds into small non-negative device-clock seconds.

    The first time seen fixes the origin (minus ``headroom_s``, so a slightly earlier,
    reordered value still maps to >= 0). Feed the result to ``wire.ClockMap.map`` as
    ``device_time_s``; the ClockMap, not this class, anchors it to the desktop clock::

        base = XrTimeBase()
        sample = gaze_sample(base.to_seconds(t_ns), ...)
        desktop_t = clock.map(sample.timestamp_s, desktop_now_s)

    Instance state only; no global state and no clock. :meth:`reset` forgets the origin
    (do it together with ``ClockMap.reset()`` when the XR session restarts).
    """

    def __init__(self, *, headroom_s: float = 1.0) -> None:
        h = _number("headroom_s", headroom_s)
        if not 0.0 <= h <= 3600.0:
            raise OpenXrError("headroom_s must be within [0, 3600]")
        self._headroom_ns = int(h * _NS)
        self._origin_ns: int | None = None

    @property
    def origin_ns(self) -> int | None:
        return self._origin_ns

    def reset(self) -> None:
        self._origin_ns = None

    def to_seconds(self, xr_time_ns: object) -> float:
        ns = _xr_time("xr_time_ns", xr_time_ns)
        origin = self._origin_ns
        if origin is None:
            origin = max(0, ns - self._headroom_ns)
        rel = ns - origin
        if rel < 0:
            raise OpenXrError("XrTime is earlier than this time base's origin by more than headroom")
        seconds = rel / _NS
        if seconds > _MAX_TIME_S:
            raise OpenXrError("XrTime is too far past this time base's origin")
        self._origin_ns = origin  # only commit after the value was accepted
        return seconds


# ── gestures from action states ─────────────────────────────────────────────────────────


class HoldKind(Enum):
    """Which hold-to-talk gesture pair a float/bool action drives."""

    PINCH = (GestureKind.PINCH_START, GestureKind.PINCH_END)
    SQUEEZE = (GestureKind.SQUEEZE_START, GestureKind.SQUEEZE_END)


class HoldGesture:
    """Float action state (0..1) -> ``*_START`` / ``*_END`` events, with hysteresis.

    Press when the value rises to ``>= press``; release when it falls to ``<= release``.
    Between the two nothing changes, so a pinch value hovering near one threshold cannot
    chatter. Defaults (0.8 / 0.5) are heuristics for synthetic data, not device-measured.

    Source actions: ``pinch_ext/value`` or a derived :func:`pinch_strength` for PINCH;
    ``grasp_ext/value`` or a controller squeeze value for SQUEEZE. A boolean action
    (``XrActionStateBoolean::currentState``) is fed as ``1.0`` / ``0.0`` via
    :meth:`update_bool`.

    ``active=False`` (``XrActionStateFloat::isActive``) counts as released: a hold must
    never get stuck "on" because the input source disappeared. A non-finite value or a
    timestamp that goes backwards raises :class:`OpenXrError` and leaves the state
    untouched; the caller should then call :meth:`release` (fail-safe: end the hold).
    Values outside [0, 1] are clamped (the range is unverified; see module doc).
    """

    def __init__(
        self, kind: HoldKind = HoldKind.PINCH, *, press: float = 0.8, release: float = 0.5
    ) -> None:
        if not isinstance(kind, HoldKind):
            raise OpenXrError("kind must be a HoldKind")
        p = _number("press", press)
        r = _number("release", release)
        if not 0.0 <= r < p <= 1.0:
            raise OpenXrError("thresholds need 0 <= release < press <= 1")
        self._start, self._end = kind.value
        self._press = p
        self._release = r
        self._pressed = False
        self._last_t = 0.0

    @property
    def pressed(self) -> bool:
        return self._pressed

    def _check_time(self, timestamp_s: object) -> float:
        t = _timestamp("timestamp_s", timestamp_s)
        if t < self._last_t:
            raise OpenXrError("timestamp_s went backwards")
        return t

    def update(
        self, timestamp_s: object, value: object, *, active: bool = True
    ) -> GestureEvent | None:
        """Feed one sample; return the edge event it causes, or ``None``."""
        t = self._check_time(timestamp_s)
        if active is not True and active is not False:
            raise OpenXrError("active must be a bool")
        v = _unit_value("value", value) if active else 0.0
        self._last_t = t
        if not self._pressed and v >= self._press:
            self._pressed = True
            return GestureEvent(t, self._start, v)
        if self._pressed and v <= self._release:
            self._pressed = False
            return GestureEvent(t, self._end, 1.0)
        return None

    def update_bool(
        self, timestamp_s: object, state: object, *, active: bool = True
    ) -> GestureEvent | None:
        """Feed an ``XrActionStateBoolean``: ``True``/``1`` pressed, ``False``/``0`` released."""
        if isinstance(state, bool):
            value = 1.0 if state else 0.0
        elif isinstance(state, int) and state in (0, 1):  # a raw XrBool32
            value = float(state)
        else:
            raise OpenXrError("a boolean action state must be a bool or 0/1")
        return self.update(timestamp_s, value, active=active)

    def release(self, timestamp_s: object) -> GestureEvent | None:
        """Force the hold to end (tracking lost, session ended, bad input). ``None`` if not held."""
        t = self._check_time(timestamp_s)
        self._last_t = t
        if not self._pressed:
            return None
        self._pressed = False
        return GestureEvent(t, self._end, 1.0)


class ClickTap:
    """A boolean click action (``select/click``) -> one ``TAP`` per press (rising edge).

    ``active=False`` counts as released. The press must be seen released first, so holding
    the button, or a runtime re-sending ``True``, yields one tap, not many.
    """

    def __init__(self) -> None:
        self._down = False
        self._last_t = 0.0

    def update(
        self, timestamp_s: object, state: object, *, active: bool = True
    ) -> GestureEvent | None:
        t = _timestamp("timestamp_s", timestamp_s)
        if t < self._last_t:
            raise OpenXrError("timestamp_s went backwards")
        if active is not True and active is not False:
            raise OpenXrError("active must be a bool")
        if isinstance(state, bool):
            down = state
        elif isinstance(state, int) and state in (0, 1):
            down = bool(state)
        else:
            raise OpenXrError("a boolean action state must be a bool or 0/1")
        down = down and active
        self._last_t = t
        rising = down and not self._down
        self._down = down
        return GestureEvent(t, GestureKind.TAP, 1.0) if rising else None


# ── hand tracking (XR_EXT_hand_tracking, 26 joints) ─────────────────────────────────────


class HandJoint(IntEnum):
    """``XrHandJointEXT`` (values verified, ``man/html/XrHandJointEXT.html``)."""

    PALM = 0
    WRIST = 1
    THUMB_METACARPAL = 2
    THUMB_PROXIMAL = 3
    THUMB_DISTAL = 4
    THUMB_TIP = 5
    INDEX_METACARPAL = 6
    INDEX_PROXIMAL = 7
    INDEX_INTERMEDIATE = 8
    INDEX_DISTAL = 9
    INDEX_TIP = 10
    MIDDLE_METACARPAL = 11
    MIDDLE_PROXIMAL = 12
    MIDDLE_INTERMEDIATE = 13
    MIDDLE_DISTAL = 14
    MIDDLE_TIP = 15
    RING_METACARPAL = 16
    RING_PROXIMAL = 17
    RING_INTERMEDIATE = 18
    RING_DISTAL = 19
    RING_TIP = 20
    LITTLE_METACARPAL = 21
    LITTLE_PROXIMAL = 22
    LITTLE_INTERMEDIATE = 23
    LITTLE_DISTAL = 24
    LITTLE_TIP = 25


@dataclass(frozen=True)
class JointPose:
    """One hand joint with a *valid* position: where, how thick, and actively tracked or not."""

    position: Vec3
    radius_m: float
    tracked: bool


@dataclass(frozen=True)
class HandJoints:
    """The 26 joints of one hand in ``space``. ``None`` = position not valid (not readable)."""

    space: ReferenceSpace
    joints: tuple[JointPose | None, ...]

    def __post_init__(self) -> None:
        require_world_space(self.space)
        if len(self.joints) != _HAND_JOINT_COUNT:
            raise OpenXrError(f"a hand has exactly {_HAND_JOINT_COUNT} joints")

    def get(self, joint: HandJoint) -> JointPose | None:
        return self.joints[int(joint)]


def hand_joints_from_raw(space: ReferenceSpace, joints: object) -> HandJoints:
    """Build :class:`HandJoints` from the ``XrHandJointLocationEXT`` array.

    ``joints`` is a list/tuple of exactly 26 ``(location_flags, (x, y, z), radius_m)``
    entries in :class:`HandJoint` order (the pose's orientation is not needed here). An
    entry whose POSITION_VALID bit is clear becomes ``None`` and its position and radius
    are never looked at (the spec says an invalid radius is undefined). A valid position
    must come with a positive radius, as the spec requires of a runtime.
    """
    require_world_space(space)
    if not isinstance(joints, (list, tuple)) or len(joints) != _HAND_JOINT_COUNT:
        raise OpenXrError(f"joints must be a sequence of exactly {_HAND_JOINT_COUNT} entries")
    out: list[JointPose | None] = []
    for i, entry in enumerate(joints):
        if not isinstance(entry, (list, tuple)) or len(entry) != 3:
            raise OpenXrError(f"joint {i} must be (flags, (x, y, z), radius_m)")
        flags = parse_location_flags(entry[0])
        if not flags.position_valid:
            out.append(None)
            continue
        pos = _vec3(f"joint {i} position", entry[1])
        radius = _number(f"joint {i} radius", entry[2])
        if not 0.0 < radius <= 1.0:
            raise OpenXrError(f"joint {i} radius must be within (0, 1] metres")
        out.append(JointPose(pos, radius, flags.position_tracked))
    return HandJoints(space, tuple(out))


#: Surface-to-surface gap between thumb and index tips mapped to strength 1 and 0. Heuristic
#: defaults for synthetic data (a real hand/device needs measuring); they are parameters.
DEFAULT_CLOSED_GAP_M = 0.005
DEFAULT_OPEN_GAP_M = 0.06


def _midpoint(a: Vec3, b: Vec3) -> Vec3:
    return Vec3((a.x + b.x) / 2.0, (a.y + b.y) / 2.0, (a.z + b.z) / 2.0)


def _delta(a: Vec3, b: Vec3) -> tuple[float, float, float]:
    d = sub(a, b)
    return d.x, d.y, d.z


def pinch_strength(
    hand: HandJoints,
    *,
    closed_gap_m: float = DEFAULT_CLOSED_GAP_M,
    open_gap_m: float = DEFAULT_OPEN_GAP_M,
) -> float | None:
    """Pinch strength in [0, 1] from thumb-tip / index-tip distance, or ``None`` if unreadable.

    The gap is the distance between the two tip *centres* minus both joint radii (the
    surfaces, not the centres, touch), floored at 0. Gap <= ``closed_gap_m`` -> 1.0; gap >=
    ``open_gap_m`` -> 0.0; linear between. Feed the result to a :class:`HoldGesture`.
    """
    closed = _number("closed_gap_m", closed_gap_m)
    opened = _number("open_gap_m", open_gap_m)
    if not 0.0 <= closed < opened:
        raise OpenXrError("need 0 <= closed_gap_m < open_gap_m")
    thumb, index = hand.get(HandJoint.THUMB_TIP), hand.get(HandJoint.INDEX_TIP)
    if thumb is None or index is None:
        return None
    gap = max(0.0, math.hypot(*_delta(thumb.position, index.position)) - thumb.radius_m - index.radius_m)
    return min(1.0, max(0.0, (opened - gap) / (opened - closed)))


@dataclass(frozen=True)
class HandPinch:
    """A pinch ray (as a HAND :class:`XrSample`) and the pinch strength at that instant."""

    sample: XrSample
    strength: float


def hand_pinch_sample(
    timestamp_s: object,
    hand: HandJoints,
    *,
    origin_hint: Vec3 | None = None,
    closed_gap_m: float = DEFAULT_CLOSED_GAP_M,
    open_gap_m: float = DEFAULT_OPEN_GAP_M,
    untracked_confidence: float = DEFAULT_UNTRACKED_CONFIDENCE,
) -> HandPinch | None:
    """A pinch ray and strength from the hand joints, or ``None`` if they cannot be read.

    * **Origin** -- the midpoint of the thumb tip and index tip (the pinch point).
    * **Direction** -- unit vector from the *wrist* to the pinch point (the hand's reach
      direction), or, when ``origin_hint`` is given, from that point (a shoulder or head
      estimate in the same space) through the pinch point. The hint is the better pointer;
      the wrist-only ray is a fallback that follows hand roll and is jumpier.
      This is a heuristic ray, not a spec-defined pose, and no accuracy is claimed.
    * **Confidence** -- the weakest of the used joints (tracked 1.0, else
      ``untracked_confidence``).

    ``None`` when the thumb tip, index tip, or (without a hint) wrist has no valid position,
    or when the direction would be undefined (the pinch point coincides with its origin).
    """
    t = _timestamp("timestamp_s", timestamp_s)
    pen = _number("untracked_confidence", untracked_confidence)
    if not 0.0 <= pen <= 1.0:
        raise OpenXrError("untracked_confidence must be within [0, 1]")
    strength = pinch_strength(hand, closed_gap_m=closed_gap_m, open_gap_m=open_gap_m)
    thumb, index = hand.get(HandJoint.THUMB_TIP), hand.get(HandJoint.INDEX_TIP)
    if strength is None or thumb is None or index is None:
        return None
    used = [thumb, index]
    if origin_hint is not None:
        back = _vec3("origin_hint", origin_hint)
    else:
        wrist = hand.get(HandJoint.WRIST)
        if wrist is None:
            return None
        back = wrist.position
        used.append(wrist)
    point = _midpoint(thumb.position, index.position)
    aim = sub(point, back)
    if aim.x == aim.y == aim.z == 0.0:
        return None
    ray = Ray(point, normalize(aim))
    conf = min(1.0 if j.tracked else pen for j in used)
    return HandPinch(XrSample(t, RaySource.HAND, ray, conf), strength)


__all__ = [
    "DEFAULT_CLOSED_GAP_M",
    "DEFAULT_OPEN_GAP_M",
    "DEFAULT_UNTRACKED_CONFIDENCE",
    "EYE_GAZE_EXTENSION",
    "EYE_GAZE_POSE_PATH",
    "EYE_GAZE_PROFILE",
    "FORWARD",
    "HAND_AIM_ACTIVATE_VALUE_PATH",
    "HAND_GRASP_VALUE_PATH",
    "HAND_INTERACTION_EXTENSION",
    "HAND_INTERACTION_PROFILE",
    "HAND_PINCH_VALUE_PATH",
    "HAND_TRACKING_EXTENSION",
    "QUAT_IDENTITY",
    "SIMPLE_CONTROLLER_AIM_PATH",
    "SIMPLE_CONTROLLER_PROFILE",
    "SIMPLE_CONTROLLER_SELECT_PATH",
    "SPACE_LOCATION_ORIENTATION_TRACKED_BIT",
    "SPACE_LOCATION_ORIENTATION_VALID_BIT",
    "SPACE_LOCATION_POSITION_TRACKED_BIT",
    "SPACE_LOCATION_POSITION_VALID_BIT",
    "SPEC_QUATERNION_TOLERANCE",
    "ClickTap",
    "HandJoint",
    "HandJoints",
    "HandPinch",
    "HoldGesture",
    "HoldKind",
    "JointPose",
    "LocationFlags",
    "OpenXrError",
    "Quat",
    "ReferenceSpace",
    "XrPose",
    "XrTimeBase",
    "aim_sample",
    "choose_gaze_time",
    "gaze_sample",
    "hand_joints_from_raw",
    "hand_pinch_sample",
    "location_confidence",
    "parse_location_flags",
    "pinch_strength",
    "pose_forward",
    "pose_from_raw",
    "pose_transform_point",
    "quat_conjugate",
    "quat_from_axis_angle",
    "quat_from_raw",
    "quat_multiply",
    "quat_rotate",
    "ray_from_pose",
    "require_world_space",
    "xr_time_to_seconds",
]
