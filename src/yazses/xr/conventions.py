"""Coordinate-convention conversion for XR runtimes (pure, stdlib only).

Every XR runtime picks its own axes, handedness and unit. ``yazses.xr`` works in one
canonical frame (see ``xr.types``): **right-handed, +X right, +Y up, -Z forward, metres**,
which is also the OpenXR "local" convention. A device or engine that reports anything
else is converted here, at the seam, and nothing downstream ever sees the original.

Each supported convention is described by two facts that a reviewer can check by hand:

* the source axes — which source axis points right, up and forward, and with what sign;
* ``metres_per_unit`` — the length of one source unit.

From those, the conversion is a *signed permutation matrix* ``M`` (rows pick and sign
source components into canonical ones) times a uniform scale. Because ``M`` only
permutes and negates axes, it is exactly orthogonal: ``M^-1 == M^T``, lengths and angles
are preserved, and ``det(M) == -1`` exactly when the source is left-handed (a mirror
image of the canonical frame), ``+1`` when it is right-handed.

Derivations (canonical: x_c = right, y_c = up, z_c = -forward):

* **OPENXR** — already canonical. ``M = I``.
* **UNITY** — +X right, +Y up, +Z forward, left-handed.
  ``x_c = x_u``, ``y_c = y_u``, ``z_c = -z_u``  (forward flips sign to become -Z).
  ``det = -1``: the single sign flip is the mirror that fixes the handedness.
* **UNREAL** — +X forward, +Y right, +Z up, left-handed, centimetres.
  ``x_c = y_r`` (right), ``y_c = z_r`` (up), ``z_c = -x_r`` (forward negated), then
  x 0.01 for cm -> m. ``det = -1`` (one permutation cycle, one negation).
* **ANDROID_XR** — ASSUMPTION, not confirmed: treated as OpenXR-aligned (right-handed,
  +Y up, -Z forward, metres) on the reading that the platform exposes OpenXR-style
  poses. Confirm against the real Android XR SDK before relying on it; if it differs,
  only its row in ``_SPECS`` changes.
* **VISIONOS** — ASSUMPTION, to be confirmed: ARKit/RealityKit are generally described as
  right-handed, +Y up, -Z forward, metres, so it is treated as canonical. Confirm
  against Apple's visionOS documentation before shipping a companion that depends on it.

References (by name; nothing is fetched here): Unity Manual, "Coordinate systems"
(docs.unity3d.com — left-handed, +Y up, +Z forward); Unreal Engine docs, "Coordinate
System and Spaces" (dev.epicgames.com — left-handed, +Z up, +X forward, centimetres);
OpenXR specification, "Spaces" (registry.khronos.org/OpenXR — right-handed, +Y up,
-Z forward, metres).

Quaternions are deliberately not converted: no module in ``yazses.xr`` consumes
orientation, only positions and unit direction vectors.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from yazses.xr.types import Ray, Vec3


class Convention(Enum):
    """The coordinate convention a device/engine reports in. Closed; add via review."""

    OPENXR = "openxr"          # canonical: right-handed, +Y up, -Z forward, metres
    UNITY = "unity"            # left-handed, +Y up, +Z forward, metres
    UNREAL = "unreal"          # left-handed, +Z up, +X forward, centimetres
    ANDROID_XR = "android_xr"  # ASSUMED OpenXR-aligned — confirm against the real SDK
    VISIONOS = "visionos"      # ASSUMED right-handed, +Y up, -Z forward — to be confirmed


class Handedness(Enum):
    RIGHT = "right"
    LEFT = "left"


Matrix3 = tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]


@dataclass(frozen=True)
class _Spec:
    """Source -> canonical: ``v_c = metres_per_unit * (matrix @ v_src)``."""

    matrix: Matrix3
    metres_per_unit: float


_IDENTITY: Matrix3 = ((1, 0, 0), (0, 1, 0), (0, 0, 1))

_SPECS: dict[Convention, _Spec] = {
    Convention.OPENXR: _Spec(_IDENTITY, 1.0),
    # x_c = x_u, y_c = y_u, z_c = -z_u
    Convention.UNITY: _Spec(((1, 0, 0), (0, 1, 0), (0, 0, -1)), 1.0),
    # x_c = y_r, y_c = z_r, z_c = -x_r ; one cm = 0.01 m
    Convention.UNREAL: _Spec(((0, 1, 0), (0, 0, 1), (-1, 0, 0)), 0.01),
    # ASSUMPTION (unconfirmed): same as OpenXR.
    Convention.ANDROID_XR: _Spec(_IDENTITY, 1.0),
    # ASSUMPTION (to be confirmed): same as OpenXR.
    Convention.VISIONOS: _Spec(_IDENTITY, 1.0),
}


def _spec(src: Convention) -> _Spec:
    if not isinstance(src, Convention):
        raise TypeError(f"expected a Convention, got {src!r}")
    return _SPECS[src]


def _det(m: Matrix3) -> int:
    (a, b, c), (d, e, f), (g, h, i) = m
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def handedness_of(convention: Convention) -> Handedness:
    """Handedness of ``convention``'s own frame, derived from its matrix.

    The canonical frame is right-handed, so a source whose conversion matrix has a
    negative determinant is a mirror image of it, i.e. left-handed. Derived rather
    than hard-coded so it cannot drift from the matrix actually applied.
    """
    return Handedness.RIGHT if _det(_spec(convention).matrix) > 0 else Handedness.LEFT


def _apply(m: Matrix3, v: Vec3) -> Vec3:
    return Vec3(
        m[0][0] * v.x + m[0][1] * v.y + m[0][2] * v.z,
        m[1][0] * v.x + m[1][1] * v.y + m[1][2] * v.z,
        m[2][0] * v.x + m[2][1] * v.y + m[2][2] * v.z,
    )


def _transpose(m: Matrix3) -> Matrix3:
    # For a signed permutation matrix the transpose is the exact inverse.
    return (
        (m[0][0], m[1][0], m[2][0]),
        (m[0][1], m[1][1], m[2][1]),
        (m[0][2], m[1][2], m[2][2]),
    )


def _scaled(v: Vec3, k: float) -> Vec3:
    return Vec3(v.x * k, v.y * k, v.z * k)


def to_canonical_vec(v: Vec3, src: Convention) -> Vec3:
    """A *position or displacement* in ``src`` units/axes -> canonical metres."""
    s = _spec(src)
    return _scaled(_apply(s.matrix, v), s.metres_per_unit)


def from_canonical_vec(v: Vec3, dst: Convention) -> Vec3:
    """Inverse of :func:`to_canonical_vec`: canonical metres -> ``dst`` units/axes."""
    s = _spec(dst)
    return _apply(_transpose(s.matrix), _scaled(v, 1.0 / s.metres_per_unit))


def _direction_to_canonical(d: Vec3, src: Convention) -> Vec3:
    # A direction has no length unit: axes only, never scaled (a cm/m factor would
    # break the unit-length invariant of Ray.direction).
    return _apply(_spec(src).matrix, d)


def to_canonical_ray(ray: Ray, src: Convention) -> Ray:
    """Convert a ray: origin as a position (scaled), direction as axes only.

    The direction stays exactly unit length: the matrix is a signed permutation, so no
    arithmetic beyond sign flips and zero-adds touches the components.
    """
    return Ray(to_canonical_vec(ray.origin, src), _direction_to_canonical(ray.direction, src))


def from_canonical_ray(ray: Ray, dst: Convention) -> Ray:
    """Inverse of :func:`to_canonical_ray`."""
    return Ray(
        from_canonical_vec(ray.origin, dst),
        _apply(_transpose(_spec(dst).matrix), ray.direction),
    )
