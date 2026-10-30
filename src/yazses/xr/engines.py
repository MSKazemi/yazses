"""Game-engine coordinate conversion for XR companions (pure, stdlib only, total).

Most headset apps are built in Unity, Unreal Engine or Godot, and each engine hands the
companion app numbers in its own frame. ``yazses.xr`` works in one canonical frame (see
``xr.types``): **right-handed, +X right, +Y up, -Z forward, metres, radians**. This module
converts positions, directions, quaternions, rays and :class:`~yazses.xr.types.Panel`
definitions between each engine's frame and that one, and back. It *composes*
``xr.conventions`` (it does not edit it): the axis matrices and the centimetre scale come
from there, so the two modules cannot disagree.

Engine facts (checked 2026-10-30 against the public documentation; "unverified" marks what
the documentation did not settle):

* **UNITY** -- left-handed; +X right, +Y up, +Z forward; one unit is one metre; Euler angles
  are degrees applied about z, then x, then y (extrinsic).
  https://docs.unity.com/en-us/engine/6000.3/manual/working-with-gameobjects/gameobject-fundamentals/rotation-orientation/quaternion-and-euler-rotations-in-unity
  (handedness, axes, degrees, Euler order; also the manual page "Controlling rotation with the
  Quaternion class") and, for one metre per unit,
  https://dev.epicgames.com/documentation/en-us/unreal-engine/unity-to-unreal-engine-frequently-asked-questions-faq
* **UNREAL** -- left-handed; +X forward, +Y right, +Z up; one unit is one **centimetre**.
  https://dev.epicgames.com/documentation/unreal-engine/coordinate-system-and-spaces-in-unreal-engine
  (handedness and axes) and the Unity-to-Unreal FAQ above (centimetres). The sign convention
  of pitch/yaw/roll (``FRotator``) was **unverified** against the public pages (the API pages
  returned no member text); :func:`unreal_rotator_to_quat` states what it assumes. (UEFN/Verse
  uses a different "left-up-forward" frame; it is *not* this convention.)
* **GODOT** -- right-handed; +X right, +Y up; metres. ``Vector3.FORWARD`` is ``(0, 0, -1)``
  (the forward of cameras and lights), while *imported assets* face ``+Z``
  (``Vector3.MODEL_FRONT``). ``Basis(x, y, z)`` takes the three axes as the **columns** of
  the matrix (it is stored row-major internally but exposed column-major).
  https://docs.godotengine.org/en/stable/tutorials/3d/introduction_to_3d.html
  https://docs.godotengine.org/en/stable/classes/class_vector3.html
  https://docs.godotengine.org/en/stable/classes/class_basis.html
  The Godot "Using transforms" page contradicts itself about the forward axis (it says both
  "-Z is forward" and "Z is the Forward axis"); this module follows the class reference.
* **Meta Quest** -- not a fourth frame. A Unity/Meta XR app is UNITY; an Unreal/Meta XR app is
  UNREAL; the native plugin underneath is right-handed (OpenXR-style) and Meta's Unity code
  converts with ``flipZ``: positions negate z, quaternions negate x and y
  (``ToFlippedZQuatf``: "negates the X and Y components"; ``ToFlippedZVector3f``: "negates
  the Z component").
  https://developers.meta.com/horizon/reference/unity/v74/struct_o_v_r_pose
  https://developers.meta.com/horizon/reference/unity/v83/class_o_v_r_extensions
  This module's UNITY quaternion rule reproduces exactly that (see the tests). Whether a
  given Quest controller's pointing ray is the engine's local forward axis is **unverified**
  here: use :func:`ray_from_pose` with the axis the SDK documents for the pose you read.

Why a quaternion needs its own rule. Write the axis change as a signed permutation ``M``
(from ``xr.conventions``). A rotation ``R`` in the engine frame is ``M R M^-1`` in the
canonical frame. Its axis is a *pseudovector*: it maps to ``det(M) * M * axis``, not
``M * axis``. For a left-handed engine ``det(M) = -1``, which is why Unity's
``(x, y, z, w)`` becomes ``(-x, -y, z, w)`` and not ``(x, y, -z, w)``. Skipping the
``det`` factor turns a left turn into a right turn: no error, no crash, a mirrored
pointing ray.

A panel is converted by converting its ``normal`` and ``up`` as *directions*. The canonical
``right = up x normal`` (``xr.raycast``) is then the physical right-hand side seen by a
viewer in front of the panel, because the mirror is already inside the converted vectors;
the numeric cross product in a left-handed engine has the opposite sign, which is exactly
what this module accounts for (use :func:`panel_right` instead of crossing engine numbers).

Totality. Every public function either returns a valid value or raises ``ValueError``:
NaN, infinities, magnitudes beyond 1e9 engine units, non-``Vec3`` arguments, zero or
non-unit directions, non-unit quaternions, non-orthonormal or mirrored (negative-scale)
bases, and an unknown engine all raise it. Nothing is clamped quietly.

Units: lengths are the engine's own on the engine side (Unreal: centimetres) and metres on
the canonical side. Angles are radians except the two ``*_euler``/``*_rotator`` helpers,
which take degrees because that is what the engines show.

Not wired into anything: there is no config key, command or IPC method.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from yazses.xr.conventions import (
    Convention,
    Handedness,
    from_canonical_vec,
    to_canonical_ray,
    to_canonical_vec,
)
from yazses.xr.geometry import cross, dot, norm, normalize, scale, sub
from yazses.xr.types import Panel, Ray, Vec3

# Engine-side magnitudes beyond this are garbage, not a level: 1e9 cm is 10,000 km. It keeps
# every product and the centimetre rescale far from overflow.
_MAX_ABS = 1e9
# A direction or quaternion this close to unit length is accepted and renormalised (single
# precision engine floats drift ~1e-7); further out it is a caller bug (a position passed
# as a direction, a half-built quaternion) and is refused.
_UNIT_TOL = 1e-3
_MAX_DEGREES = 1e6

_ZERO = Vec3(0.0, 0.0, 0.0)
_EX = Vec3(1.0, 0.0, 0.0)
_EY = Vec3(0.0, 1.0, 0.0)
_EZ = Vec3(0.0, 0.0, 1.0)


class EngineConvention(Enum):
    """The game-engine frame a companion reports in. Closed; add via review.

    Meta Quest apps use the frame of the engine they are built in (UNITY or UNREAL), so
    there is deliberately no ``QUEST`` member; see the module docstring.
    """

    UNITY = "unity"      # left-handed, +Y up, +Z forward, metres
    UNREAL = "unreal"    # left-handed, +Z up, +X forward, centimetres
    GODOT = "godot"      # right-handed, +Y up, -Z forward, metres


# GODOT has no row in xr.conventions because it *is* the canonical frame.
_CONVENTION: dict[EngineConvention, Convention] = {
    EngineConvention.UNITY: Convention.UNITY,
    EngineConvention.UNREAL: Convention.UNREAL,
    EngineConvention.GODOT: Convention.OPENXR,
}


@dataclass(frozen=True)
class EngineAxes:
    """One engine's frame in its own coordinates (documented facts, not derived)."""

    right: Vec3
    up: Vec3
    forward: Vec3
    metres_per_unit: float
    handedness: Handedness


def _engine(engine: EngineConvention) -> Convention:
    if not isinstance(engine, EngineConvention):
        raise ValueError(f"engine must be an EngineConvention, got {engine!r}")
    return _CONVENTION[engine]


def _metres_per_unit(conv: Convention) -> float:
    return norm(to_canonical_vec(_EX, conv))


# Documented facts, written out by hand. tests/test_xr_engines.py checks them against the
# conversion matrices actually applied, so a typo here (or there) is caught.
_AXES: dict[EngineConvention, EngineAxes] = {
    EngineConvention.UNITY: EngineAxes(_EX, _EY, _EZ, 1.0, Handedness.LEFT),
    EngineConvention.UNREAL: EngineAxes(_EY, _EZ, _EX, 0.01, Handedness.LEFT),
    EngineConvention.GODOT: EngineAxes(_EX, _EY, Vec3(0.0, 0.0, -1.0), 1.0, Handedness.RIGHT),
}


def engine_axes(engine: EngineConvention) -> EngineAxes:
    """The right/up/forward axes, unit and handedness of ``engine`` (documented)."""
    _engine(engine)
    return _AXES[engine]


def convention_of(engine: EngineConvention) -> Convention:
    """The ``xr.conventions`` entry this engine converts through (Godot -> OPENXR)."""
    return _engine(engine)


# ---- argument validation ----------------------------------------------------------------

def _within(x: object, limit: float) -> bool:
    """A real number (not bool) that is finite and no larger than ``limit`` in magnitude.

    Compares before converting, so an int with 400 digits is "too large", not an
    ``OverflowError`` from ``math.isfinite``.
    """
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return False
    if isinstance(x, int):
        return abs(x) <= limit
    return math.isfinite(x) and abs(x) <= limit


def _vec(name: str, v: Vec3, limit: float = _MAX_ABS) -> Vec3:
    if not isinstance(v, Vec3):
        raise ValueError(f"{name} must be a Vec3, got {v!r}")
    for axis, c in (("x", v.x), ("y", v.y), ("z", v.z)):
        # Re-checked here: a Vec3 can be forged past its own validation with
        # object.__setattr__, and this module's whole job is to not trust its inputs.
        if not _within(c, limit):
            raise ValueError(f"{name}.{axis} must be finite with magnitude <= {limit:g}, got {c!r}")
    return v


def _number(name: str, x: float, limit: float) -> float:
    if not _within(x, limit):
        raise ValueError(f"{name} must be finite with magnitude <= {limit:g}, got {x!r}")
    return float(x)


def _unit_dir(name: str, d: Vec3) -> Vec3:
    """``d`` as an exact unit vector; zero and clearly non-unit vectors raise."""
    d = _vec(name, d)
    n = norm(d)
    if n == 0.0:
        raise ValueError(f"{name} must not be the zero vector")
    if abs(n - 1.0) > _UNIT_TOL:
        raise ValueError(f"{name} must be unit length (tolerance {_UNIT_TOL:g}), length is {n:g}")
    return normalize(d)


# ---- the engine frame as three canonical columns ----------------------------------------

def _columns(conv: Convention) -> tuple[Vec3, Vec3, Vec3]:
    """``M e_x, M e_y, M e_z``: the engine axes written in canonical axes (no scale)."""
    return tuple(to_canonical_ray(Ray(_ZERO, e), conv).direction for e in (_EX, _EY, _EZ))  # type: ignore[return-value]


def _det(cols: tuple[Vec3, Vec3, Vec3]) -> float:
    return dot(cols[0], cross(cols[1], cols[2]))


def _mat(cols: tuple[Vec3, Vec3, Vec3], v: Vec3) -> Vec3:
    """``M v``."""
    a, b, c = cols
    return Vec3(
        a.x * v.x + b.x * v.y + c.x * v.z,
        a.y * v.x + b.y * v.y + c.y * v.z,
        a.z * v.x + b.z * v.y + c.z * v.z,
    )


def _mat_t(cols: tuple[Vec3, Vec3, Vec3], v: Vec3) -> Vec3:
    """``M^T v`` -- the exact inverse, because M is a signed permutation."""
    a, b, c = cols
    return Vec3(dot(a, v), dot(b, v), dot(c, v))


# ---- positions, lengths, directions -----------------------------------------------------

def position_to_canonical(p: Vec3, engine: EngineConvention) -> Vec3:
    """An engine position (Unreal: centimetres) -> canonical metres."""
    conv = _engine(engine)
    return to_canonical_vec(_vec("position", p), conv)


def position_from_canonical(p: Vec3, engine: EngineConvention) -> Vec3:
    """Canonical metres -> an engine position (Unreal: centimetres)."""
    conv = _engine(engine)
    return from_canonical_vec(_vec("position", p), conv)


def length_to_canonical(length: float, engine: EngineConvention) -> float:
    """An engine length (a panel width, Unreal: centimetres) -> metres. Must be >= 0."""
    conv = _engine(engine)
    x = _number("length", length, _MAX_ABS)
    if x < 0:
        raise ValueError(f"length must be >= 0, got {length!r}")
    return x * _metres_per_unit(conv)


def length_from_canonical(length_m: float, engine: EngineConvention) -> float:
    """Metres -> an engine length (Unreal: centimetres). Must be >= 0."""
    conv = _engine(engine)
    x = _number("length_m", length_m, _MAX_ABS)
    if x < 0:
        raise ValueError(f"length_m must be >= 0, got {length_m!r}")
    return x / _metres_per_unit(conv)


def direction_to_canonical(d: Vec3, engine: EngineConvention) -> Vec3:
    """An engine unit direction -> canonical unit direction. Axes only, never scaled."""
    conv = _engine(engine)
    return to_canonical_ray(Ray(_ZERO, _unit_dir("direction", d)), conv).direction


def direction_from_canonical(d: Vec3, engine: EngineConvention) -> Vec3:
    """A canonical unit direction -> the engine's axes."""
    conv = _engine(engine)
    u = _unit_dir("direction", d)
    return normalize(_mat_t(_columns(conv), u))


def ray_to_canonical(origin: Vec3, direction: Vec3, engine: EngineConvention) -> Ray:
    """An engine ray (origin position + direction) -> a canonical :class:`Ray`.

    The direction need only be unit to 1e-3 (single-precision engine floats); the returned
    ray is exactly unit. A zero or wildly non-unit direction raises.
    """
    conv = _engine(engine)
    o = to_canonical_vec(_vec("origin", origin), conv)
    return Ray(o, to_canonical_ray(Ray(_ZERO, _unit_dir("direction", direction)), conv).direction)


def ray_from_canonical(ray: Ray, engine: EngineConvention) -> tuple[Vec3, Vec3]:
    """A canonical ray -> ``(origin, direction)`` in the engine's frame and units."""
    if not isinstance(ray, Ray):
        raise ValueError(f"ray must be a Ray, got {ray!r}")
    return (
        position_from_canonical(ray.origin, engine),
        direction_from_canonical(ray.direction, engine),
    )


# ---- quaternions ------------------------------------------------------------------------

@dataclass(frozen=True)
class Quat:
    """A unit quaternion ``(x, y, z, w)``, vector part first (Unity, Unreal and Godot order).

    ``q`` rotates a vector ``v`` by ``q v q^-1`` (Hamilton product, the same in all three
    engines). Unit length is required to 1e-3: a non-unit quaternion is not a rotation, and
    guessing is how a pointing ray ends up wrong.
    """

    x: float
    y: float
    z: float
    w: float

    def __post_init__(self) -> None:
        for field, c in (("x", self.x), ("y", self.y), ("z", self.z), ("w", self.w)):
            _number(f"Quat.{field}", c, 1e3)
        length = math.hypot(self.x, self.y, self.z, self.w)
        if abs(length - 1.0) > _UNIT_TOL:
            raise ValueError(
                f"Quat must be unit length (tolerance {_UNIT_TOL:g}), length is {length:g}"
            )


IDENTITY = Quat(0.0, 0.0, 0.0, 1.0)


def _quat(q: Quat) -> Quat:
    if not isinstance(q, Quat):
        raise ValueError(f"rotation must be a Quat, got {q!r}")
    # Re-run the validation: a Quat can be forged past __post_init__ like a Vec3.
    Quat(q.x, q.y, q.z, q.w)
    return q


def _unit_quat(x: float, y: float, z: float, w: float) -> Quat:
    n = math.hypot(x, y, z, w)
    if not math.isfinite(n) or n == 0.0:  # pragma: no cover - inputs are validated unit
        raise ValueError("quaternion collapsed to zero length")
    return Quat(x / n, y / n, z / n, w / n)


def quat_to_canonical(q: Quat, engine: EngineConvention) -> Quat:
    """An engine rotation -> the *same physical rotation* in the canonical frame.

    The vector part is a pseudovector: ``v_c = det(M) * M * v_e`` (``det(M) = -1`` for
    Unity and Unreal, ``+1`` for Godot); ``w`` is unchanged. For Unity this is
    ``(x, y, z, w) -> (-x, -y, z, w)``, which is what Meta's ``ToFlippedZQuatf`` does.
    """
    conv = _engine(engine)
    q = _quat(q)
    cols = _columns(conv)
    d = _det(cols)
    v = scale(_mat(cols, Vec3(q.x, q.y, q.z)), d)
    return _unit_quat(v.x, v.y, v.z, q.w)


def quat_from_canonical(q: Quat, engine: EngineConvention) -> Quat:
    """Inverse of :func:`quat_to_canonical`."""
    conv = _engine(engine)
    q = _quat(q)
    cols = _columns(conv)
    d = _det(cols)
    v = scale(_mat_t(cols, Vec3(q.x, q.y, q.z)), d)
    return _unit_quat(v.x, v.y, v.z, q.w)


def quat_rotate(q: Quat, v: Vec3) -> Vec3:
    """Rotate ``v`` by ``q`` (frame-agnostic: use it in whichever frame ``q`` lives)."""
    q = _quat(q)
    v = _vec("vector", v)
    n = _unit_quat(q.x, q.y, q.z, q.w)
    u = Vec3(n.x, n.y, n.z)
    t = scale(cross(u, v), 2.0)
    # v' = v + w t + u x t   with   t = 2 (u x v)
    return Vec3(
        v.x + n.w * t.x + (u.y * t.z - u.z * t.y),
        v.y + n.w * t.y + (u.z * t.x - u.x * t.z),
        v.z + n.w * t.z + (u.x * t.y - u.y * t.x),
    )


def _qmul(a: Quat, b: Quat) -> Quat:
    return _unit_quat(
        a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y,
        a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
        a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w,
        a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z,
    )


def _axis_angle(axis: Vec3, radians: float) -> Quat:
    s, c = math.sin(radians / 2.0), math.cos(radians / 2.0)
    return Quat(axis.x * s, axis.y * s, axis.z * s, c)


def unity_euler_to_quat(x_deg: float, y_deg: float, z_deg: float) -> Quat:
    """Unity's ``Quaternion.Euler(x, y, z)`` (degrees), in Unity's frame.

    "Unity performs the Euler rotations sequentially around the z-axis, the x-axis and then
    the y-axis" (extrinsic; degrees) -- so ``q = Ry * Rx * Rz``. Each positive rotation is
    the plain Hamilton rotation about that axis (in Unity "the direction of rotation from
    the positive x-axis to the positive y-axis is counterclockwise when looking along the
    positive z-axis", i.e. +z rotates +x toward +y), so +y turns forward (+z) toward the
    right (+x).
    """
    ax = math.radians(_number("x_deg", x_deg, _MAX_DEGREES))
    ay = math.radians(_number("y_deg", y_deg, _MAX_DEGREES))
    az = math.radians(_number("z_deg", z_deg, _MAX_DEGREES))
    return _qmul(_qmul(_axis_angle(_EY, ay), _axis_angle(_EX, ax)), _axis_angle(_EZ, az))


def unreal_rotator_to_quat(pitch_deg: float, yaw_deg: float, roll_deg: float) -> Quat:
    """Unreal's ``FRotator(Pitch, Yaw, Roll)`` (degrees) as an ``FQuat``, in Unreal's frame.

    **Unverified against the public documentation** (the API pages carry no member text).
    Assumed, and cross-checked against the well-known ``FRotator::Quaternion`` expansion in
    ``tests/test_xr_engines.py``: yaw is about +Z and turns forward (+X) toward right (+Y);
    positive pitch lifts the nose (+X toward +Z); positive roll lowers the right side
    (+Y toward -Z); yaw is applied outermost, then pitch, then roll. As plain Hamilton
    rotations that is ``q = Rz(yaw) * Ry(-pitch) * Rx(-roll)``. If your Unreal version
    differs, build the ``Quat`` from ``FQuat`` directly, which needs no assumption.
    """
    p = math.radians(_number("pitch_deg", pitch_deg, _MAX_DEGREES))
    y = math.radians(_number("yaw_deg", yaw_deg, _MAX_DEGREES))
    r = math.radians(_number("roll_deg", roll_deg, _MAX_DEGREES))
    return _qmul(_qmul(_axis_angle(_EZ, y), _axis_angle(_EY, -p)), _axis_angle(_EX, -r))


def quat_from_basis(x_axis: Vec3, y_axis: Vec3, z_axis: Vec3) -> Quat:
    """The rotation whose matrix has these three vectors as its **columns**.

    That is Godot's ``Basis(x_axis, y_axis, z_axis)``, and Unity's
    ``transform.right / up / forward``. If you hold the *rows* instead you hold the
    transpose, which is the inverse rotation: the result would turn the wrong way. Frame
    agnostic: the quaternion lives in the same frame as the axes.

    The axes must be orthonormal (1e-3) and right-handed *as a rotation*
    (``det = +1``). A basis with a negative-scale axis (a mirror) has no quaternion and
    raises, rather than silently returning a rotation that is not the object's orientation.
    """
    x = _unit_dir("x_axis", x_axis)
    y = _unit_dir("y_axis", y_axis)
    z = _unit_dir("z_axis", z_axis)
    for na, a, b in (("x/y", x, y), ("x/z", x, z), ("y/z", y, z)):
        if abs(dot(a, b)) > _UNIT_TOL:
            raise ValueError(f"basis axes {na} are not perpendicular")
    if dot(x, cross(y, z)) <= 0.0:
        raise ValueError("basis is mirrored (negative determinant): it is not a rotation")
    m00, m01, m02 = x.x, y.x, z.x
    m10, m11, m12 = x.y, y.y, z.y
    m20, m21, m22 = x.z, y.z, z.z
    t = m00 + m11 + m22
    if t > 0.0:
        s = math.sqrt(t + 1.0) * 2.0
        return _unit_quat((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, s / 4.0)
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return _unit_quat(s / 4.0, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return _unit_quat((m01 + m10) / s, s / 4.0, (m12 + m21) / s, (m02 - m20) / s)
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return _unit_quat((m02 + m20) / s, (m12 + m21) / s, s / 4.0, (m10 - m01) / s)


# ---- rays from poses --------------------------------------------------------------------

def ray_from_pose(
    position: Vec3,
    rotation: Quat,
    engine: EngineConvention,
    local_forward: Vec3 | None = None,
) -> Ray:
    """A canonical pointing ray from an engine pose (head, hand, controller, camera).

    ``local_forward`` is the pose's pointing axis in the pose's own local frame; it
    defaults to the engine's documented forward (Unity +Z, Unreal +X, Godot -Z). A head or
    camera pose points along that axis. A controller/hand *pointer* pose might not:
    **unverified** per device -- pass the axis your SDK documents.
    """
    eng_axes = engine_axes(engine)
    fwd = eng_axes.forward if local_forward is None else _unit_dir("local_forward", local_forward)
    d = quat_rotate(rotation, fwd)
    return ray_to_canonical(position, d, engine)


# ---- panels -----------------------------------------------------------------------------

@dataclass(frozen=True)
class EnginePanel:
    """A panel expressed in an engine's frame and units (the inverse direction)."""

    panel_id: str
    center: Vec3
    normal: Vec3
    up: Vec3
    width: float
    height: float
    label: str = ""

    def __post_init__(self) -> None:
        _vec("EnginePanel.center", self.center)
        _vec("EnginePanel.normal", self.normal)
        _vec("EnginePanel.up", self.up)
        for n, s in (("width", self.width), ("height", self.height)):
            if _number(f"EnginePanel.{n}", s, _MAX_ABS) <= 0:
                raise ValueError(f"EnginePanel.{n} must be > 0")


def panel_to_canonical(
    panel_id: str,
    center: Vec3,
    normal: Vec3,
    up: Vec3,
    width: float,
    height: float,
    engine: EngineConvention,
    label: str = "",
) -> Panel:
    """An engine panel -> a canonical :class:`Panel` that raycasts identically.

    ``normal`` points toward the side a viewer stands on (the readable face); ``up`` is the
    panel's top edge direction; ``width``/``height`` are in engine units. Both axes are
    converted as *directions*, so the mirror of a left-handed engine lands in them and
    ``xr.raycast`` (``right = up x normal``) yields the viewer's real right. ``up`` is made
    exactly perpendicular to ``normal`` (engine floats are only perpendicular to ~1e-7);
    axes further than 1e-3 from perpendicular, parallel axes, and non-positive sizes raise.
    """
    conv = _engine(engine)
    n = _unit_dir("normal", normal)
    u = _unit_dir("up", up)
    if abs(dot(n, u)) > _UNIT_TOL:
        raise ValueError("panel normal and up must be perpendicular (tolerance 1e-3)")
    u = normalize(sub(u, scale(n, dot(u, n))))
    w = length_to_canonical(width, engine)
    h = length_to_canonical(height, engine)
    if w <= 0 or h <= 0:
        raise ValueError("panel width and height must be > 0")
    return Panel(
        panel_id=panel_id,
        center=to_canonical_vec(_vec("center", center), conv),
        normal=to_canonical_ray(Ray(_ZERO, n), conv).direction,
        up=to_canonical_ray(Ray(_ZERO, u), conv).direction,
        width=w,
        height=h,
        label=label,
    )


def panel_from_canonical(panel: Panel, engine: EngineConvention) -> EnginePanel:
    """A canonical :class:`Panel` -> the same panel in an engine's frame and units."""
    if not isinstance(panel, Panel):
        raise ValueError(f"panel must be a Panel, got {panel!r}")
    return EnginePanel(
        panel_id=panel.panel_id,
        center=position_from_canonical(panel.center, engine),
        normal=direction_from_canonical(panel.normal, engine),
        up=direction_from_canonical(panel.up, engine),
        width=length_from_canonical(panel.width, engine),
        height=length_from_canonical(panel.height, engine),
        label=panel.label,
    )


def panel_right(panel: EnginePanel, engine: EngineConvention) -> Vec3:
    """The viewer's right-hand direction of an engine panel, in engine axes.

    Right-handed engine (Godot): ``up x normal``. Left-handed engine (Unity, Unreal): the
    numeric cross product flips, so it is ``normal x up``. Computed through the canonical
    frame so it is correct by construction, not by remembering which engine flips.
    """
    if not isinstance(panel, EnginePanel):
        raise ValueError(f"panel must be an EnginePanel, got {panel!r}")
    canonical = panel_to_canonical(
        panel.panel_id, panel.center, panel.normal, panel.up, panel.width, panel.height, engine
    )
    return direction_from_canonical(cross(canonical.up, canonical.normal), engine)


def panel_from_pose(
    panel_id: str,
    position: Vec3,
    rotation: Quat,
    width: float,
    height: float,
    engine: EngineConvention,
    *,
    normal_local: Vec3,
    up_local: Vec3,
    label: str = "",
) -> Panel:
    """A canonical Panel from an engine transform (position + rotation) of a panel object.

    ``normal_local`` is the object's *local* axis that points at the viewer (the readable
    face), ``up_local`` its local top edge; both are required because they depend on the
    asset, not the engine (a Unity quad or world-space canvas is readable from its local
    -Z side, a Godot ``QuadMesh`` from +Z; both **unverified** here, so check your asset).
    ``width``/``height`` are the object's size in engine units after scale.
    """
    n = quat_rotate(rotation, _unit_dir("normal_local", normal_local))
    u = quat_rotate(rotation, _unit_dir("up_local", up_local))
    return panel_to_canonical(panel_id, position, n, u, width, height, engine, label)
