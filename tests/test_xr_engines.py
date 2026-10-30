"""Tests for yazses.xr.engines -- Unity / Unreal / Godot frames, mirrors proven by raycast.

The core claim: a panel and a ray converted from an engine's frame give the *identical* hit
(u, v, distance) through ``xr.raycast`` as an independent ray cast written in the engine's
own frame. The engine-side reference below is deliberately not built from the module under
test: it is written in plain tuples, with the right-hand direction of a left-handed engine
spelled out (``normal x up``), and is anchored by hand-computed scenes ("the panel to my
right is on my right") so a reference that agrees with a wrong module cannot pass.
All data is synthetic.
"""
from __future__ import annotations

import math

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from yazses.xr.conventions import Convention, Handedness, handedness_of, to_canonical_vec
from yazses.xr.engines import (
    IDENTITY,
    EngineAxes,
    EngineConvention,
    EnginePanel,
    Quat,
    convention_of,
    direction_from_canonical,
    direction_to_canonical,
    engine_axes,
    length_from_canonical,
    length_to_canonical,
    panel_from_canonical,
    panel_from_pose,
    panel_right,
    panel_to_canonical,
    position_from_canonical,
    position_to_canonical,
    quat_from_basis,
    quat_from_canonical,
    quat_rotate,
    quat_to_canonical,
    ray_from_canonical,
    ray_from_pose,
    ray_to_canonical,
    unity_euler_to_quat,
    unreal_rotator_to_quat,
)
from yazses.xr.geometry import norm
from yazses.xr.raycast import hit_panel
from yazses.xr.types import Panel, Ray, Vec3

ENGINES = list(EngineConvention)
LEFT_HANDED = (EngineConvention.UNITY, EngineConvention.UNREAL)
MPU = {EngineConvention.UNITY: 1.0, EngineConvention.UNREAL: 0.01, EngineConvention.GODOT: 1.0}
SLOW = settings(
    max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)

T = tuple[float, float, float]


# ---- independent reference arithmetic (plain tuples, no module under test) --------------

def _t(v: Vec3) -> T:
    return (v.x, v.y, v.z)


def _v(t: T) -> Vec3:
    return Vec3(*t)


def _add(a: T, b: T) -> T:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: T, b: T) -> T:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(a: T, k: float) -> T:
    return (a[0] * k, a[1] * k, a[2] * k)


def _dot(a: T, b: T) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: T, b: T) -> T:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _unit(a: T) -> T:
    n = math.sqrt(_dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


def _close(a: Vec3, b: Vec3, tol: float = 1e-9) -> bool:
    return all(math.isclose(p, q, rel_tol=1e-9, abs_tol=tol) for p, q in zip(_t(a), _t(b)))


def engine_right(engine: EngineConvention, up: T, normal: T) -> T:
    """The viewer's right of a panel, written the way an engine author would.

    Right-handed (Godot): up x normal.  Left-handed (Unity, Unreal): the same sign rule
    in a mirrored frame is normal x up. Anchored below by hand-computed scenes.
    """
    return _cross(up, normal) if engine is EngineConvention.GODOT else _cross(normal, up)


def engine_raycast(
    engine: EngineConvention,
    origin: T,
    direction: T,
    center: T,
    normal: T,
    up: T,
    width: float,
    height: float,
) -> tuple[float, float, float] | None:
    """Front-face ray cast written entirely in the engine's own frame and units."""
    denom = _dot(normal, direction)
    if denom >= 0 or abs(denom) < 1e-9:
        return None
    t = _dot(normal, _sub(center, origin)) / denom
    if t < 0:
        return None
    rel = _sub(_add(origin, _mul(direction, t)), center)
    right = engine_right(engine, up, normal)
    u = 0.5 + _dot(rel, right) / width
    v = 0.5 + _dot(rel, up) / height
    if not (0.0 <= u <= 1.0 and 0.0 <= v <= 1.0):
        return None
    return (u, v, t)


def rot_matrix(q: Quat) -> tuple[T, T, T]:
    """Textbook rotation matrix of a unit quaternion (rows), independent of quat_rotate."""
    x, y, z, w = q.x, q.y, q.z, q.w
    return (
        (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
        (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
        (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
    )


def apply_rows(m: tuple[T, T, T], v: T) -> T:
    return (_dot(m[0], v), _dot(m[1], v), _dot(m[2], v))


# ---- strategies -------------------------------------------------------------------------

coord = st.floats(min_value=-100.0, max_value=100.0, allow_nan=False, allow_infinity=False)
nonzero = st.builds(lambda a, b, c: (a, b, c), coord, coord, coord).filter(
    lambda t: _dot(t, t) > 0.1
)


@st.composite
def unit_quats(draw: st.DrawFn) -> Quat:
    a, b, c, d = (draw(st.floats(min_value=-1, max_value=1)) for _ in range(4))
    assume(a * a + b * b + c * c + d * d > 0.05)
    n = math.sqrt(a * a + b * b + c * c + d * d)
    return Quat(a / n, b / n, c / n, d / n)


@st.composite
def scenes(draw: st.DrawFn, engine: EngineConvention):
    """An engine-frame panel, and a ray aimed at a chosen panel coordinate (maybe off it)."""
    k = 1.0 / MPU[engine]  # engine units per metre
    n = _unit(draw(nonzero))
    b = draw(nonzero)
    perp = _sub(b, _mul(n, _dot(b, n)))
    assume(_dot(perp, perp) > 0.1)
    up = _unit(perp)
    centre = _mul(draw(nonzero), k * 0.3)
    width = draw(st.floats(min_value=0.2, max_value=5.0)) / MPU[engine]
    height = draw(st.floats(min_value=0.2, max_value=5.0)) / MPU[engine]
    su = draw(st.floats(min_value=-0.3, max_value=1.3))
    sv = draw(st.floats(min_value=-0.3, max_value=1.3))
    dist = draw(st.floats(min_value=0.2, max_value=8.0)) * k
    behind = draw(st.booleans())
    lateral = _mul(draw(nonzero), k * 0.02)
    right = engine_right(engine, up, n)
    target = _add(
        centre, _add(_mul(right, (su - 0.5) * width), _mul(up, (sv - 0.5) * height))
    )
    origin = _add(target, _add(_mul(n, -dist if behind else dist), lateral))
    direction = _unit(_sub(target, origin))
    return n, up, centre, width, height, su, sv, origin, direction


# ---- documented facts agree with the matrices actually applied -------------------------

@pytest.mark.parametrize("engine", ENGINES)
def test_documented_axes_land_on_canonical_axes(engine: EngineConvention) -> None:
    a = engine_axes(engine)
    assert isinstance(a, EngineAxes)
    assert direction_to_canonical(a.right, engine) == Vec3(1, 0, 0)
    assert direction_to_canonical(a.up, engine) == Vec3(0, 1, 0)
    assert direction_to_canonical(a.forward, engine) == Vec3(0, 0, -1)
    assert a.metres_per_unit == MPU[engine]
    assert norm(to_canonical_vec(Vec3(1, 0, 0), convention_of(engine))) == a.metres_per_unit


def test_documented_handedness_matches_the_derived_one() -> None:
    for engine in ENGINES:
        expected = Handedness.LEFT if engine in LEFT_HANDED else Handedness.RIGHT
        assert engine_axes(engine).handedness is expected
        assert handedness_of(convention_of(engine)) is expected


@pytest.mark.parametrize("engine", ENGINES)
@SLOW
@given(d=nonzero)
def test_direction_round_trip_and_never_scaled(engine: EngineConvention, d: T) -> None:
    unit = _v(_unit(d))
    c = direction_to_canonical(unit, engine)
    assert norm(c) == pytest.approx(1.0, abs=1e-12)  # Unreal's cm scale must not leak in
    assert _close(direction_from_canonical(c, engine), unit, 1e-12)


def test_godot_is_the_canonical_frame() -> None:
    assert convention_of(EngineConvention.GODOT) is Convention.OPENXR
    p = Vec3(1.5, -2.0, 3.25)
    assert position_to_canonical(p, EngineConvention.GODOT) == p


def test_unreal_centimetres() -> None:
    p = position_to_canonical(Vec3(100.0, 200.0, 300.0), EngineConvention.UNREAL)
    # x_c = right = y_u, y_c = up = z_u, z_c = -forward = -x_u, then cm -> m
    assert _close(p, Vec3(2.0, 3.0, -1.0))
    assert length_to_canonical(250.0, EngineConvention.UNREAL) == pytest.approx(2.5)
    assert length_from_canonical(2.5, EngineConvention.UNREAL) == pytest.approx(250.0)


# ---- hand-computed scenes: the mirror in plain words ----------------------------------

def test_unity_panel_on_my_right_is_on_my_right() -> None:
    """Unity, I stand at the origin looking +Z; a panel 5 m ahead faces me (-Z side)."""
    e = EngineConvention.UNITY
    panel = panel_to_canonical("p", Vec3(0, 0, 5), Vec3(0, 0, -1), Vec3(0, 1, 0), 2.0, 1.0, e)
    # Aim at x = +0.5 (Unity right, 25 % of the width right of centre).
    ray = ray_to_canonical(Vec3(0, 0, 0), _v(_unit((0.5, 0.0, 5.0))), e)
    hit = hit_panel(ray, panel)
    assert hit is not None
    assert hit.u == pytest.approx(0.75)
    assert hit.v == pytest.approx(0.5)
    assert hit.distance_m == pytest.approx(math.hypot(0.5, 5.0) )


def test_unity_aiming_up_is_v_above_half() -> None:
    e = EngineConvention.UNITY
    panel = panel_to_canonical("p", Vec3(0, 0, 5), Vec3(0, 0, -1), Vec3(0, 1, 0), 2.0, 1.0, e)
    hit = hit_panel(ray_to_canonical(Vec3(0, 0, 0), _v(_unit((0.0, 0.25, 5.0))), e), panel)
    assert hit is not None and hit.v == pytest.approx(0.75)


def test_unreal_panel_on_my_right_is_on_my_right() -> None:
    """Unreal, cm: panel 500 cm ahead (+X) facing me (-X); +Y is right; width 200 cm."""
    e = EngineConvention.UNREAL
    panel = panel_to_canonical("p", Vec3(500, 0, 0), Vec3(-1, 0, 0), Vec3(0, 0, 1), 200.0, 100.0, e)
    hit = hit_panel(ray_to_canonical(Vec3(0, 0, 0), _v(_unit((500.0, 50.0, 25.0))), e), panel)
    assert hit is not None
    assert hit.u == pytest.approx(0.75)
    assert hit.v == pytest.approx(0.75)
    assert hit.distance_m == pytest.approx(math.sqrt(500**2 + 50**2 + 25**2) / 100.0)


def test_godot_panel_on_my_right_is_on_my_right() -> None:
    """Godot: I look along -Z; a panel 5 m ahead faces me (+Z); +X is right."""
    e = EngineConvention.GODOT
    panel = panel_to_canonical("p", Vec3(0, 0, -5), Vec3(0, 0, 1), Vec3(0, 1, 0), 2.0, 1.0, e)
    hit = hit_panel(ray_to_canonical(Vec3(0, 0, 0), _v(_unit((0.5, 0.0, -5.0))), e), panel)
    assert hit is not None and hit.u == pytest.approx(0.75)


def test_the_silent_bug_raw_engine_numbers_through_raycast_mirror_u() -> None:
    """Documents the failure this module exists to prevent: skip the conversion and a
    Unity panel reads left-right mirrored -- no error, no crash, wrong target."""
    raw_panel = Panel("p", Vec3(0, 0, 5), Vec3(0, 0, -1), Vec3(0, 1, 0), 2.0, 1.0)
    raw_ray = Ray(Vec3(0, 0, 0), _v(_unit((0.5, 0.0, 5.0))))
    raw = hit_panel(raw_ray, raw_panel)
    assert raw is not None
    assert raw.u == pytest.approx(0.25)  # mirrored: should be 0.75
    e = EngineConvention.UNITY
    fixed = hit_panel(
        ray_to_canonical(Vec3(0, 0, 0), _v(_unit((0.5, 0.0, 5.0))), e),
        panel_to_canonical("p", Vec3(0, 0, 5), Vec3(0, 0, -1), Vec3(0, 1, 0), 2.0, 1.0, e),
    )
    assert fixed is not None and fixed.u == pytest.approx(0.75)


@pytest.mark.parametrize("engine", ENGINES)
def test_panel_right_matches_the_engine_cross_rule(engine: EngineConvention) -> None:
    n, up = (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)
    if engine is EngineConvention.UNITY:
        n = (0.0, 0.0, -1.0)  # facing a viewer who looks along +Z
        want: T = (1.0, 0.0, 0.0)
    elif engine is EngineConvention.UNREAL:
        n, up = (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
        want = (0.0, 1.0, 0.0)
    else:
        want = (1.0, 0.0, 0.0)
    p = EnginePanel("p", Vec3(0, 0, 0), _v(n), _v(up), 1.0, 1.0)
    r = panel_right(p, engine)
    assert _close(r, _v(want))
    assert _close(r, _v(engine_right(engine, up, n)))


# ---- the central property: identical hit before and after conversion --------------------

@pytest.mark.parametrize("engine", ENGINES)
@SLOW
@given(data=st.data())
def test_raycast_hit_is_identical_before_and_after_conversion(
    engine: EngineConvention, data: st.DataObject
) -> None:
    n, up, centre, width, height, su, sv, origin, direction = data.draw(scenes(engine))
    ref = engine_raycast(engine, origin, direction, centre, n, up, width, height)
    # Skip scenes whose aim point sits on a boundary: a 1e-12 difference in rounding there
    # legitimately flips hit/miss in either implementation.
    margin = 1e-6
    assume(not any(abs(s - e) < margin for s in (su, sv) for e in (0.0, 1.0)))

    panel = panel_to_canonical("p", _v(centre), _v(n), _v(up), width, height, engine)
    ray = ray_to_canonical(_v(origin), _v(direction), engine)
    got = hit_panel(ray, panel, max_distance_m=1e6)

    inside = 0.0 < su < 1.0 and 0.0 < sv < 1.0
    if ref is None:
        assert got is None
        return
    assert inside  # the reference only hits when the construction aimed inside
    assert got is not None
    u, v, t = ref
    assert got.u == pytest.approx(u, abs=1e-7)
    assert got.v == pytest.approx(v, abs=1e-7)
    assert got.distance_m == pytest.approx(t * MPU[engine], rel=1e-9, abs=1e-9)
    # And both agree with the coordinate the scene was *built* to hit.
    assert got.u == pytest.approx(su, abs=1e-6)
    assert got.v == pytest.approx(sv, abs=1e-6)


@pytest.mark.parametrize("engine", ENGINES)
@SLOW
@given(data=st.data())
def test_panel_and_ray_round_trip_back_to_the_engine(
    engine: EngineConvention, data: st.DataObject
) -> None:
    n, up, centre, width, height, _su, _sv, origin, direction = data.draw(scenes(engine))
    panel = panel_to_canonical("p", _v(centre), _v(n), _v(up), width, height, engine)
    back = panel_from_canonical(panel, engine)
    assert _close(back.center, _v(centre), 1e-7)
    assert _close(back.normal, _v(n), 1e-9)
    assert _close(back.up, _v(up), 1e-9)
    assert back.width == pytest.approx(width, rel=1e-12)
    assert back.height == pytest.approx(height, rel=1e-12)
    o, d = ray_from_canonical(ray_to_canonical(_v(origin), _v(direction), engine), engine)
    assert _close(o, _v(origin), 1e-7)
    assert _close(d, _v(direction), 1e-9)


# ---- quaternions ------------------------------------------------------------------------

@pytest.mark.parametrize("engine", ENGINES)
@SLOW
@given(q=unit_quats(), v=nonzero)
def test_rotating_commutes_with_conversion(
    engine: EngineConvention, q: Quat, v: tuple[float, float, float]
) -> None:
    """R_c(v_c) == convert(R_e(v)): the converted quaternion is the same physical turn."""
    qc = quat_to_canonical(q, engine)
    want = direction_free_axes(engine, apply_rows(rot_matrix(q), v))
    got = apply_rows(rot_matrix(qc), direction_free_axes(engine, v))
    assert all(math.isclose(a, b, abs_tol=1e-9, rel_tol=1e-9) for a, b in zip(got, want))


def direction_free_axes(engine: EngineConvention, v: T) -> T:
    """Axes-only change of frame for an arbitrary-length vector (no unit requirement)."""
    if engine is EngineConvention.UNITY:
        return (v[0], v[1], -v[2])
    if engine is EngineConvention.UNREAL:
        return (v[1], v[2], -v[0])
    return v


@pytest.mark.parametrize("engine", ENGINES)
@SLOW
@given(q=unit_quats())
def test_quaternion_round_trip(engine: EngineConvention, q: Quat) -> None:
    back = quat_from_canonical(quat_to_canonical(q, engine), engine)
    assert (back.x, back.y, back.z, back.w) == pytest.approx((q.x, q.y, q.z, q.w), abs=1e-12)


@SLOW
@given(q=unit_quats())
def test_unity_quaternion_is_metas_flipped_z(q: Quat) -> None:
    """Meta's documented ToFlippedZQuatf: 'negates the X and Y components'."""
    c = quat_to_canonical(q, EngineConvention.UNITY)
    assert (c.x, c.y, c.z, c.w) == pytest.approx((-q.x, -q.y, q.z, q.w), abs=1e-12)


@SLOW
@given(q=unit_quats())
def test_godot_quaternion_is_unchanged(q: Quat) -> None:
    c = quat_to_canonical(q, EngineConvention.GODOT)
    assert (c.x, c.y, c.z, c.w) == pytest.approx((q.x, q.y, q.z, q.w), abs=1e-12)


def test_the_det_factor_matters_turning_right_stays_turning_right() -> None:
    """Unity: yaw +90 degrees about +Y turns forward (+Z) to the right (+X). A converter
    that forgot det(M) would turn the canonical forward (-Z) to the LEFT (-X)."""
    s = math.sqrt(0.5)
    q = Quat(0.0, s, 0.0, s)
    assert _close(quat_rotate(q, Vec3(0, 0, 1)), Vec3(1, 0, 0))
    qc = quat_to_canonical(q, EngineConvention.UNITY)
    assert _close(quat_rotate(qc, Vec3(0, 0, -1)), Vec3(1, 0, 0))
    wrong = Quat(0.0, s, 0.0, s)  # the unconverted numbers: turns -Z toward -X
    assert _close(quat_rotate(wrong, Vec3(0, 0, -1)), Vec3(-1, 0, 0))


def test_unreal_yaw_90_turns_forward_to_right() -> None:
    q = unreal_rotator_to_quat(0.0, 90.0, 0.0)
    assert _close(quat_rotate(q, Vec3(1, 0, 0)), Vec3(0, 1, 0))  # +X forward -> +Y right
    qc = quat_to_canonical(q, EngineConvention.UNREAL)
    assert _close(quat_rotate(qc, Vec3(0, 0, -1)), Vec3(1, 0, 0))  # forward -> right


def test_godot_yaw_turns_forward_to_right() -> None:
    s = math.sqrt(0.5)
    q = Quat(0.0, -s, 0.0, s)  # -90 degrees about +Y: -Z turns to +X in a right-handed frame
    assert _close(quat_rotate(q, Vec3(0, 0, -1)), Vec3(1, 0, 0))
    qc = quat_to_canonical(q, EngineConvention.GODOT)
    assert _close(quat_rotate(qc, Vec3(0, 0, -1)), Vec3(1, 0, 0))


def test_unity_euler_order_and_sign() -> None:
    # Documented: z first, then x, then y (extrinsic).
    q = unity_euler_to_quat(90.0, 90.0, 0.0)
    # x=90 sends forward +Z to -Y; then y=90 about world Y leaves -Y alone.
    assert _close(quat_rotate(q, Vec3(0, 0, 1)), Vec3(0, -1, 0))
    # y=90 alone: forward -> right.
    assert _close(quat_rotate(unity_euler_to_quat(0.0, 90.0, 0.0), Vec3(0, 0, 1)), Vec3(1, 0, 0))
    # z=90: +x toward +y (documented: counterclockwise from +x to +y looking along +z).
    assert _close(quat_rotate(unity_euler_to_quat(0.0, 0.0, 90.0), Vec3(1, 0, 0)), Vec3(0, 1, 0))
    # The order is observable: z-then-x differs from x-then-z.
    a = quat_rotate(unity_euler_to_quat(90.0, 0.0, 90.0), Vec3(1, 0, 0))
    assert _close(a, Vec3(0, 0, 1))  # z first: x->y ; then x(90): y->z


@SLOW
@given(
    p=st.floats(min_value=-89, max_value=89),
    y=st.floats(min_value=-180, max_value=180),
    r=st.floats(min_value=-180, max_value=180),
)
def test_unreal_rotator_matches_the_known_fquat_expansion(p: float, y: float, r: float) -> None:
    """Epic's FRotator::Quaternion expansion, written out as the independent oracle."""
    sp, cp = math.sin(math.radians(p) / 2), math.cos(math.radians(p) / 2)
    sy, cy = math.sin(math.radians(y) / 2), math.cos(math.radians(y) / 2)
    sr, cr = math.sin(math.radians(r) / 2), math.cos(math.radians(r) / 2)
    want = (
        cr * sp * sy - sr * cp * cy,
        -cr * sp * cy - sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    )
    q = unreal_rotator_to_quat(p, y, r)
    assert (q.x, q.y, q.z, q.w) == pytest.approx(want, abs=1e-9)


def test_unreal_pitch_up_and_roll_signs() -> None:
    up = quat_rotate(unreal_rotator_to_quat(30.0, 0.0, 0.0), Vec3(1, 0, 0))
    assert up.z > 0 and up.y == pytest.approx(0.0, abs=1e-12)  # nose up
    roll = quat_rotate(unreal_rotator_to_quat(0.0, 0.0, 30.0), Vec3(0, 1, 0))
    assert roll.z < 0  # right side down


# ---- basis -> quaternion (Godot Basis columns) ------------------------------------------

@SLOW
@given(q=unit_quats())
def test_quat_from_basis_round_trip_using_columns(q: Quat) -> None:
    m = rot_matrix(q)
    cols = [(m[0][i], m[1][i], m[2][i]) for i in range(3)]  # Basis(x, y, z): columns
    got = quat_from_basis(_v(cols[0]), _v(cols[1]), _v(cols[2]))
    same = (got.x, got.y, got.z, got.w)
    want = (q.x, q.y, q.z, q.w)
    flipped = tuple(-c for c in want)
    assert same == pytest.approx(want, abs=1e-9) or same == pytest.approx(flipped, abs=1e-9)


def test_rows_instead_of_columns_gives_the_inverse_rotation() -> None:
    s = math.sqrt(0.5)
    q = Quat(0.0, s, 0.0, s)
    m = rot_matrix(q)
    rows = [m[0], m[1], m[2]]
    cols = [(m[0][i], m[1][i], m[2][i]) for i in range(3)]
    good = quat_from_basis(*(_v(c) for c in cols))
    bad = quat_from_basis(*(_v(r) for r in rows))
    assert _close(quat_rotate(good, Vec3(0, 0, 1)), Vec3(1, 0, 0))
    assert _close(quat_rotate(bad, Vec3(0, 0, 1)), Vec3(-1, 0, 0))  # turns the other way


def test_mirrored_basis_has_no_quaternion() -> None:
    with pytest.raises(ValueError, match="mirrored"):
        quat_from_basis(Vec3(-1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1))


def test_non_orthogonal_basis_is_refused() -> None:
    with pytest.raises(ValueError, match="perpendicular"):
        quat_from_basis(Vec3(1, 0, 0), _v(_unit((1, 1, 0))), Vec3(0, 0, 1))


# ---- poses ------------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("engine", "q"),
    [
        (EngineConvention.UNITY, unity_euler_to_quat(0.0, 90.0, 0.0)),
        (EngineConvention.UNREAL, unreal_rotator_to_quat(0.0, 90.0, 0.0)),
        (EngineConvention.GODOT, Quat(0.0, -math.sqrt(0.5), 0.0, math.sqrt(0.5))),
    ],
)
def test_turning_right_in_any_engine_points_the_canonical_ray_to_plus_x(
    engine: EngineConvention, q: Quat
) -> None:
    ray = ray_from_pose(Vec3(0, 0, 0), q, engine)
    assert _close(ray.direction, Vec3(1, 0, 0))


@pytest.mark.parametrize("engine", ENGINES)
def test_identity_pose_looks_canonical_forward(engine: EngineConvention) -> None:
    ray = ray_from_pose(Vec3(1, 2, 3), IDENTITY, engine)
    assert _close(ray.direction, Vec3(0, 0, -1))
    assert _close(ray.origin, position_to_canonical(Vec3(1, 2, 3), engine))


def test_pose_with_explicit_local_forward() -> None:
    ray = ray_from_pose(Vec3(0, 0, 0), IDENTITY, EngineConvention.UNITY, Vec3(1, 0, 0))
    assert _close(ray.direction, Vec3(1, 0, 0))  # Unity +X is right and stays right


def test_panel_from_pose_unity_quad_faces_minus_z() -> None:
    """A Unity quad turned 180 degrees about Y at z=5 faces the +Z side; with the identity
    rotation it is readable from -Z (the origin). Local -Z is the viewer side."""
    e = EngineConvention.UNITY
    panel = panel_from_pose(
        "q", Vec3(0, 0, 5), IDENTITY, 2.0, 1.0, e, normal_local=Vec3(0, 0, -1), up_local=Vec3(0, 1, 0)
    )
    hit = hit_panel(ray_to_canonical(Vec3(0, 0, 0), _v(_unit((0.5, 0.0, 5.0))), e), panel)
    assert hit is not None and hit.u == pytest.approx(0.75)


@SLOW
@given(q=unit_quats(), c=nonzero)
def test_panel_from_pose_matches_converting_the_rotated_axes_by_hand(
    q: Quat, c: tuple[float, float, float]
) -> None:
    for engine in ENGINES:
        n = apply_rows(rot_matrix(q), (0.0, 0.0, 1.0))
        u = apply_rows(rot_matrix(q), (0.0, 1.0, 0.0))
        a = panel_from_pose(
            "p", _v(c), q, 1.0, 1.0, engine, normal_local=Vec3(0, 0, 1), up_local=Vec3(0, 1, 0)
        )
        b = panel_to_canonical("p", _v(c), _v(n), _v(u), 1.0, 1.0, engine)
        assert _close(a.normal, b.normal, 1e-9)
        assert _close(a.up, b.up, 1e-9)


# ---- hostile input ----------------------------------------------------------------------

BAD_NUMBERS = [math.nan, math.inf, -math.inf, 1e300, "1.0", None, True]


def _forged(x: float) -> Vec3:
    v = Vec3(0.0, 0.0, 0.0)
    object.__setattr__(v, "x", x)
    return v


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 1e300])
def test_forged_non_finite_or_huge_vectors_raise(engine: EngineConvention, bad: float) -> None:
    f = _forged(bad)
    with pytest.raises(ValueError):
        position_to_canonical(f, engine)
    with pytest.raises(ValueError):
        ray_to_canonical(f, Vec3(0, 0, -1), engine)
    with pytest.raises(ValueError):
        ray_to_canonical(Vec3(0, 0, 0), f, engine)
    with pytest.raises(ValueError):
        direction_to_canonical(f, engine)


@pytest.mark.parametrize("engine", ENGINES)
def test_huge_but_finite_positions_raise(engine: EngineConvention) -> None:
    with pytest.raises(ValueError):
        position_to_canonical(Vec3(2e9, 0, 0), engine)
    with pytest.raises(ValueError):
        position_from_canonical(Vec3(0, 2e9, 0), engine)


@pytest.mark.parametrize("engine", ENGINES)
def test_zero_and_non_unit_directions_raise(engine: EngineConvention) -> None:
    for d in (Vec3(0, 0, 0), Vec3(0, 0, 2), Vec3(0, 0, 0.5), Vec3(3, 4, 0)):
        with pytest.raises(ValueError):
            direction_to_canonical(d, engine)
        with pytest.raises(ValueError):
            ray_to_canonical(Vec3(0, 0, 0), d, engine)


@pytest.mark.parametrize("engine", ENGINES)
def test_slightly_off_unit_float32_directions_are_accepted_and_made_exact(
    engine: EngineConvention,
) -> None:
    ray = ray_to_canonical(Vec3(0, 0, 0), Vec3(0, 0, 1.0 + 2e-7), engine)
    assert norm(ray.direction) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("bad", [None, "unity", 1, Convention.UNITY, object()])
def test_unknown_engine_raises_value_error(bad: object) -> None:
    with pytest.raises(ValueError, match="EngineConvention"):
        position_to_canonical(Vec3(0, 0, 0), bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        engine_axes(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [(0.0, 0.0, 0.0), [1, 2, 3], "abc", None, 5])
def test_wrong_types_raise_value_error(bad: object) -> None:
    e = EngineConvention.UNITY
    with pytest.raises(ValueError, match="Vec3"):
        position_to_canonical(bad, e)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        direction_to_canonical(bad, e)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Quat"):
        quat_to_canonical(bad, e)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Ray"):
        ray_from_canonical(bad, e)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Panel"):
        panel_from_canonical(bad, e)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "xyzw",
    [(0, 0, 0, 0), (0, 0, 0, 2), (0.5, 0.5, 0.5, 0.0), (math.nan, 0, 0, 1), (0, 0, 0, math.inf), (1e300, 0, 0, 1)],
)
def test_non_unit_or_non_finite_quaternions_raise(xyzw: tuple[float, float, float, float]) -> None:
    with pytest.raises(ValueError):
        Quat(*xyzw)


def test_forged_quaternion_is_caught_at_the_converter() -> None:
    q = Quat(0.0, 0.0, 0.0, 1.0)
    object.__setattr__(q, "w", 3.0)
    for engine in ENGINES:
        with pytest.raises(ValueError):
            quat_to_canonical(q, engine)
        with pytest.raises(ValueError):
            quat_rotate(q, Vec3(0, 0, 1))


def test_slightly_off_unit_quaternion_is_renormalised() -> None:
    q = Quat(0.0, 0.0, 0.0, 1.0 + 5e-4)
    c = quat_to_canonical(q, EngineConvention.UNITY)
    assert math.hypot(c.x, c.y, c.z, c.w) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -1.0, 1e300, "3", None])
def test_bad_lengths_raise(bad: object) -> None:
    with pytest.raises(ValueError):
        length_to_canonical(bad, EngineConvention.UNREAL)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        length_from_canonical(bad, EngineConvention.UNREAL)  # type: ignore[arg-type]


def test_bad_euler_angles_raise() -> None:
    for bad in (math.nan, math.inf, 1e9, "1", None):
        with pytest.raises(ValueError):
            unity_euler_to_quat(bad, 0.0, 0.0)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            unreal_rotator_to_quat(0.0, bad, 0.0)  # type: ignore[arg-type]


def test_bad_panels_raise() -> None:
    e = EngineConvention.UNITY
    n, u = Vec3(0, 0, -1), Vec3(0, 1, 0)
    ok = (Vec3(0, 0, 5), n, u)
    with pytest.raises(ValueError):
        panel_to_canonical("p", ok[0], n, n, 1.0, 1.0, e)  # up parallel to normal
    with pytest.raises(ValueError, match="perpendicular"):
        panel_to_canonical("p", ok[0], n, _v(_unit((0, 1, 1))), 1.0, 1.0, e)
    for w, h in ((0.0, 1.0), (1.0, -1.0), (math.nan, 1.0), (1.0, math.inf)):
        with pytest.raises(ValueError):
            panel_to_canonical("p", ok[0], n, u, w, h, e)
    with pytest.raises(ValueError):
        panel_to_canonical("", ok[0], n, u, 1.0, 1.0, e)  # Panel refuses an empty id
    with pytest.raises(ValueError):
        panel_to_canonical("p", ok[0], Vec3(0, 0, 0), u, 1.0, 1.0, e)
    with pytest.raises(ValueError):
        EnginePanel("p", ok[0], n, u, 0.0, 1.0)


def test_slightly_skewed_panel_axes_are_made_exactly_perpendicular() -> None:
    e = EngineConvention.UNITY
    up = _v(_unit((0.0, 1.0, 1e-4)))  # 1e-4 off perpendicular, float32-ish noise
    p = panel_to_canonical("p", Vec3(0, 0, 5), Vec3(0, 0, -1), up, 1.0, 1.0, e)
    assert abs(p.normal.x * p.up.x + p.normal.y * p.up.y + p.normal.z * p.up.z) < 1e-12


@SLOW
@given(
    v=st.one_of(
        st.floats(allow_nan=True, allow_infinity=True),
        st.integers(min_value=-(10**400), max_value=10**400),
    )
)
def test_nothing_but_value_error_escapes(v: float) -> None:
    """Fuzz the scalar entry points: a result or ValueError, never anything else."""
    for engine in ENGINES:
        for f in (
            lambda: length_to_canonical(v, engine),
            lambda: unity_euler_to_quat(v, 0.0, 0.0),
            lambda: unreal_rotator_to_quat(0.0, 0.0, v),
        ):
            try:
                f()
            except ValueError:
                pass
