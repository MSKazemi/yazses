"""Tests for yazses.xr.conventions — hand-computed vectors, round trips, handedness."""
from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from yazses.xr.conventions import (
    Convention,
    Handedness,
    from_canonical_ray,
    from_canonical_vec,
    handedness_of,
    to_canonical_ray,
    to_canonical_vec,
)
from yazses.xr.geometry import cross, dot, norm, normalize
from yazses.xr.types import Ray, Vec3

ALL = list(Convention)
FINITE = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False)
vecs = st.builds(Vec3, FINITE, FINITE, FINITE)
nonzero_vecs = vecs.filter(lambda v: norm(v) > 1e-3)


def _close(a: Vec3, b: Vec3, tol: float = 1e-9) -> bool:
    return all(math.isclose(p, q, rel_tol=1e-12, abs_tol=tol) for p, q in
               ((a.x, b.x), (a.y, b.y), (a.z, b.z)))


# Independent, hand-written (right, up, forward) unit axes of each source frame, in that
# frame's own coordinates, plus the metres in one source unit (Unreal works in cm).
_AXES = {
    Convention.OPENXR: (Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, -1), 1.0),
    Convention.UNITY: (Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1), 1.0),
    Convention.UNREAL: (Vec3(0, 1, 0), Vec3(0, 0, 1), Vec3(1, 0, 0), 0.01),
    Convention.ANDROID_XR: (Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, -1), 1.0),
    Convention.VISIONOS: (Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, -1), 1.0),
}


# ---- hand-computed vectors --------------------------------------------------

def test_openxr_is_identity() -> None:
    v = Vec3(1.5, -2.0, 3.25)
    assert to_canonical_vec(v, Convention.OPENXR) == v
    assert from_canonical_vec(v, Convention.OPENXR) == v


def test_unity_forward_maps_to_minus_z() -> None:
    assert to_canonical_vec(Vec3(0, 0, 1), Convention.UNITY) == Vec3(0, 0, -1)


def test_unity_general_vector() -> None:
    # (x, y, z) -> (x, y, -z)
    assert to_canonical_vec(Vec3(1, 2, 3), Convention.UNITY) == Vec3(1, 2, -3)


def test_unreal_forward_cm_maps_to_minus_z_metres() -> None:
    out = to_canonical_vec(Vec3(1, 0, 0), Convention.UNREAL)
    assert _close(out, Vec3(0, 0, -0.01))


def test_unreal_general_vector() -> None:
    # (x_r, y_r, z_r) = (100, 200, 300) cm -> x_c=y_r, y_c=z_r, z_c=-x_r, x0.01
    out = to_canonical_vec(Vec3(100, 200, 300), Convention.UNREAL)
    assert _close(out, Vec3(2.0, 3.0, -1.0))


def test_unreal_up_and_right() -> None:
    assert _close(to_canonical_vec(Vec3(0, 0, 100), Convention.UNREAL), Vec3(0, 1, 0))
    assert _close(to_canonical_vec(Vec3(0, 100, 0), Convention.UNREAL), Vec3(1, 0, 0))


@pytest.mark.parametrize("conv", [Convention.ANDROID_XR, Convention.VISIONOS])
def test_assumed_conventions_are_canonical_for_now(conv: Convention) -> None:
    # Pins the documented ASSUMPTION; a deliberate change must update this test.
    v = Vec3(1, 2, 3)
    assert to_canonical_vec(v, conv) == v


@pytest.mark.parametrize("conv", ALL)
def test_origin_maps_to_origin(conv: Convention) -> None:
    assert _close(to_canonical_vec(Vec3(0, 0, 0), conv), Vec3(0, 0, 0))


# ---- named axes land on the canonical axes ----------------------------------

@pytest.mark.parametrize("conv", ALL)
def test_right_up_forward_land_on_canonical_axes(conv: Convention) -> None:
    right, up, fwd, m = _AXES[conv]
    assert _close(to_canonical_vec(right, conv), Vec3(m, 0, 0))    # +X right
    assert _close(to_canonical_vec(up, conv), Vec3(0, m, 0))       # +Y up
    assert _close(to_canonical_vec(fwd, conv), Vec3(0, 0, -m))     # -Z forward


# ---- handedness -------------------------------------------------------------

def test_declared_handedness() -> None:
    assert handedness_of(Convention.OPENXR) is Handedness.RIGHT
    assert handedness_of(Convention.UNITY) is Handedness.LEFT
    assert handedness_of(Convention.UNREAL) is Handedness.LEFT
    assert handedness_of(Convention.ANDROID_XR) is Handedness.RIGHT
    assert handedness_of(Convention.VISIONOS) is Handedness.RIGHT


@pytest.mark.parametrize("conv", ALL)
def test_canonical_frame_is_right_handed_for_every_source(conv: Convention) -> None:
    """right x up must equal -forward (i.e. 'backward', +Z) in the canonical frame.

    This is the right-hand rule applied to the *converted* named axes. A left-handed
    source converted without the mirror flip would give right x up == +forward instead.
    """
    right, up, fwd, m = _AXES[conv]
    # divide out the unit scale so the three are unit vectors (cross scales as m^2)
    r, u, f = (to_canonical_vec(a, conv) for a in (right, up, fwd))
    r, u, f = (Vec3(a.x / m, a.y / m, a.z / m) for a in (r, u, f))
    c = cross(r, u)
    assert _close(c, Vec3(-f.x, -f.y, -f.z))
    assert c.z > 0  # canonical backward is +Z


@pytest.mark.parametrize("conv", ALL)
def test_handedness_matches_basis_triple_product(conv: Convention) -> None:
    """Images of the source's own x, y, z basis: triple product sign == handedness."""
    ex, ey, ez = (to_canonical_vec(a, conv) for a in (Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1)))
    triple = dot(cross(ex, ey), ez)
    expected = Handedness.RIGHT if triple > 0 else Handedness.LEFT
    assert handedness_of(conv) is expected


def test_left_handed_source_is_mirrored_not_rotated() -> None:
    # In Unity, right x up (by the left-hand rule) is forward (+Z). Naively applying
    # the right-hand cross formula to the converted vectors must give the OPPOSITE of
    # the converted forward — proving a reflection happened.
    r = to_canonical_vec(Vec3(1, 0, 0), Convention.UNITY)
    u = to_canonical_vec(Vec3(0, 1, 0), Convention.UNITY)
    f = to_canonical_vec(Vec3(0, 0, 1), Convention.UNITY)
    assert cross(r, u) == Vec3(-f.x, -f.y, -f.z)


# ---- round trips ------------------------------------------------------------

@pytest.mark.parametrize("conv", ALL)
@given(v=vecs)
def test_vec_round_trip_from_source(conv: Convention, v: Vec3) -> None:
    assert _close(from_canonical_vec(to_canonical_vec(v, conv), conv), v, tol=1e-6)


@pytest.mark.parametrize("conv", ALL)
@given(v=vecs)
def test_vec_round_trip_from_canonical(conv: Convention, v: Vec3) -> None:
    assert _close(to_canonical_vec(from_canonical_vec(v, conv), conv), v, tol=1e-6)


@pytest.mark.parametrize("conv", ALL)
@given(o=vecs, d=nonzero_vecs)
def test_ray_round_trip(conv: Convention, o: Vec3, d: Vec3) -> None:
    ray = Ray(o, normalize(d))
    back = from_canonical_ray(to_canonical_ray(ray, conv), conv)
    assert _close(back.origin, ray.origin, tol=1e-6)
    assert _close(back.direction, ray.direction, tol=1e-12)


# ---- rays -------------------------------------------------------------------

@pytest.mark.parametrize("conv", ALL)
@given(o=vecs, d=nonzero_vecs)
def test_ray_stays_unit_length(conv: Convention, o: Vec3, d: Vec3) -> None:
    out = to_canonical_ray(Ray(o, normalize(d)), conv)
    assert abs(norm(out.direction) - 1.0) <= 1e-9


def test_unreal_ray_origin_scaled_direction_not() -> None:
    ray = Ray(Vec3(100, 200, 300), Vec3(1, 0, 0))  # forward in Unreal
    out = to_canonical_ray(ray, Convention.UNREAL)
    assert _close(out.origin, Vec3(2.0, 3.0, -1.0))
    assert out.direction == Vec3(0, 0, -1)


def test_unity_ray_forward() -> None:
    out = to_canonical_ray(Ray(Vec3(0, 1.6, 0), Vec3(0, 0, 1)), Convention.UNITY)
    assert out.origin == Vec3(0, 1.6, 0)
    assert out.direction == Vec3(0, 0, -1)


@pytest.mark.parametrize("conv", ALL)
@given(a=nonzero_vecs, b=nonzero_vecs)
def test_conversion_is_an_isometry(conv: Convention, a: Vec3, b: Vec3) -> None:
    """Angles are preserved (dot of unit directions unchanged), left- or right-handed."""
    ra, rb = normalize(a), normalize(b)
    ca = to_canonical_ray(Ray(Vec3(0, 0, 0), ra), conv).direction
    cb = to_canonical_ray(Ray(Vec3(0, 0, 0), rb), conv).direction
    assert math.isclose(dot(ca, cb), dot(ra, rb), abs_tol=1e-9)


# ---- failure modes ----------------------------------------------------------

@pytest.mark.parametrize("bad", ["unity", None, 3, Handedness.LEFT])
def test_non_convention_is_rejected(bad: object) -> None:
    with pytest.raises(TypeError):
        to_canonical_vec(Vec3(0, 0, 0), bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        from_canonical_vec(Vec3(0, 0, 0), bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        handedness_of(bad)  # type: ignore[arg-type]


def test_overflowing_conversion_is_refused_not_silenced() -> None:
    # 1e308 cm -> m is fine, but metres -> cm overflows to inf, which Vec3 refuses.
    with pytest.raises(ValueError):
        from_canonical_vec(Vec3(1e307, 0, 0), Convention.UNREAL)


def test_every_convention_has_a_spec() -> None:
    for conv in Convention:
        assert handedness_of(conv) in Handedness
