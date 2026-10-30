"""Ray / panel intersection: hand-computed cases, boundaries, and a round-trip property."""
from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from yazses.xr.geometry import add, cross, dot, normalize, scale, sub
from yazses.xr.raycast import all_hits, hit_panel, nearest_hit
from yazses.xr.types import Panel, Ray, Vec3

S = math.sqrt(0.5)


def ray(ox: float, oy: float, oz: float, dx: float, dy: float, dz: float) -> Ray:
    return Ray(Vec3(ox, oy, oz), Vec3(dx, dy, dz))


FORWARD = (0.0, 0.0, -1.0)


def panel(
    pid: str = "p",
    center: tuple[float, float, float] = (0.0, 0.0, -2.0),
    normal: tuple[float, float, float] = (0.0, 0.0, 1.0),
    up: tuple[float, float, float] = (0.0, 1.0, 0.0),
    width: float = 2.0,
    height: float = 1.0,
) -> Panel:
    return Panel(pid, Vec3(*center), Vec3(*normal), Vec3(*up), width, height)


# --- axis-aligned panel at z=-2 (right = +X, up = +Y) ---------------------------------


def test_centre_hit() -> None:
    h = hit_panel(ray(0, 0, 0, *FORWARD), panel())
    assert h is not None
    assert (h.panel_id, h.u, h.v) == ("p", 0.5, 0.5)
    assert h.distance_m == pytest.approx(2.0)


def test_uv_orientation_left_to_right_bottom_to_top() -> None:
    # width 2, height 1: x=+0.5 -> u=0.75 (right of centre), y=+0.25 -> v=0.75 (above).
    h = hit_panel(ray(0.5, 0.25, 0, *FORWARD), panel())
    assert h is not None
    assert h.u == pytest.approx(0.75)
    assert h.v == pytest.approx(0.75)
    low_left = hit_panel(ray(-0.5, -0.25, 0, *FORWARD), panel())
    assert low_left is not None
    assert (low_left.u, low_left.v) == (pytest.approx(0.25), pytest.approx(0.25))


def test_oblique_ray_distance() -> None:
    # From the origin toward (0.6, 0, -0.8) the plane z=-2 is struck at t=2.5, x=1.5 (>1: miss).
    assert hit_panel(ray(0, 0, 0, 0.6, 0, -0.8), panel()) is None
    # Same direction from x=-1: x = -1 + 1.5 = 0.5 -> u = 0.75, distance 2.5.
    h = hit_panel(ray(-1, 0, 0, 0.6, 0, -0.8), panel())
    assert h is not None
    assert h.distance_m == pytest.approx(2.5)
    assert h.u == pytest.approx(0.75)


# --- tilted panel ----------------------------------------------------------------------


def test_tilted_panel_45_degrees_about_y() -> None:
    # normal (s,0,s), up +Y => right = up x normal = (s,0,-s). Centre (0,0,-2).
    tilted = panel(normal=(S, 0.0, S), width=2.0, height=1.0)
    centre = hit_panel(ray(0, 0, 0, *FORWARD), tilted)
    assert centre is not None
    assert (centre.u, centre.v) == (pytest.approx(0.5), pytest.approx(0.5))
    assert centre.distance_m == pytest.approx(2.0)
    # Origin (0.5,0,0): t = n.(c-o)/n.d = (s*-0.5 + s*-2)/(-s) = 2.5; p = (0.5,0,-2.5);
    # p-c = (0.5,0,-0.5); right.(p-c) = s*0.5 + s*0.5 = s; u = 0.5 + s/2.
    h = hit_panel(ray(0.5, 0, 0, *FORWARD), tilted)
    assert h is not None
    assert h.distance_m == pytest.approx(2.5)
    assert h.u == pytest.approx(0.5 + S / 2)
    assert h.v == pytest.approx(0.5)


# --- edges, corners, just outside -----------------------------------------------------


@pytest.mark.parametrize(
    "x,y,u,v",
    [(1.0, 0.0, 1.0, 0.5), (-1.0, 0.0, 0.0, 0.5), (0.0, 0.5, 0.5, 1.0),
     (0.0, -0.5, 0.5, 0.0), (1.0, 0.5, 1.0, 1.0), (-1.0, -0.5, 0.0, 0.0)],
)
def test_edge_and_corner_hits_count(x: float, y: float, u: float, v: float) -> None:
    h = hit_panel(ray(x, y, 0, *FORWARD), panel())
    assert h is not None
    assert (h.u, h.v) == (pytest.approx(u), pytest.approx(v))


@pytest.mark.parametrize("x,y", [(1.001, 0.0), (-1.001, 0.0), (0.0, 0.501), (0.0, -0.501)])
def test_just_outside_misses(x: float, y: float) -> None:
    assert hit_panel(ray(x, y, 0, *FORWARD), panel()) is None


def test_edge_hit_on_tilted_panel_is_clamped_into_unit_interval() -> None:
    tilted = panel(normal=(S, 0.0, S))
    # Right edge of the tilted panel lies at c + right*1 = (S, 0, -2-S); aim straight at it.
    h = hit_panel(ray(S, 0, 0, *FORWARD), tilted)
    assert h is not None
    assert 0.0 <= h.u <= 1.0
    assert h.u == pytest.approx(1.0)


# --- non-hits --------------------------------------------------------------------------


def test_parallel_ray_misses() -> None:
    assert hit_panel(ray(0, 0, 0, 1, 0, 0), panel()) is None  # parallel, off the plane
    assert hit_panel(ray(0, 0, -2, 1, 0, 0), panel()) is None  # parallel, lying in the plane
    nearly = ray(0, 0, 0, math.sqrt(1 - 1e-24), 0, -1e-12)
    assert hit_panel(nearly, panel()) is None


def test_panel_behind_origin_misses() -> None:
    assert hit_panel(ray(0, 0, 0, 0, 0, 1), panel()) is None  # facing away from z=-2


def test_origin_on_plane_hits_at_distance_zero() -> None:
    h = hit_panel(ray(0, 0, -2, *FORWARD), panel())
    assert h is not None
    assert h.distance_m == 0.0


def test_max_distance_is_inclusive() -> None:
    r = ray(0, 0, 0, *FORWARD)
    assert hit_panel(r, panel(), max_distance_m=2.0) is not None
    assert hit_panel(r, panel(), max_distance_m=1.999) is None
    assert hit_panel(r, panel()) is not None  # default 10 m


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf, -math.inf])
def test_invalid_max_distance_raises(bad: float) -> None:
    r = ray(0, 0, 0, *FORWARD)
    with pytest.raises(ValueError):
        hit_panel(r, panel(), max_distance_m=bad)
    with pytest.raises(ValueError):
        all_hits(r, [], max_distance_m=bad)
    with pytest.raises(ValueError):
        nearest_hit(r, [panel()], max_distance_m=bad)


# --- back face -------------------------------------------------------------------------


def test_back_face_requires_opt_in_and_keeps_panel_frame_uv() -> None:
    behind = ray(0.5, 0.25, -4, 0, 0, 1)  # looking +Z at the back of the panel
    assert hit_panel(behind, panel()) is None
    h = hit_panel(behind, panel(), allow_back_face=True)
    assert h is not None
    assert h.distance_m == pytest.approx(2.0)
    # Same world point as the front-face case, so the same (u, v): mirrored for the viewer.
    assert (h.u, h.v) == (pytest.approx(0.75), pytest.approx(0.75))


def test_front_face_unaffected_by_back_face_flag() -> None:
    r = ray(0, 0, 0, *FORWARD)
    assert hit_panel(r, panel(), allow_back_face=True) == hit_panel(r, panel())


# --- several panels --------------------------------------------------------------------


def test_stacked_panels_nearest_and_all_hits_order() -> None:
    far = panel("far", center=(0, 0, -3))
    near = panel("near", center=(0, 0, -2))
    r = ray(0, 0, 0, *FORWARD)
    hits = all_hits(r, [far, near])  # input deliberately far-first
    assert [h.panel_id for h in hits] == ["near", "far"]
    assert [h.distance_m for h in hits] == pytest.approx([2.0, 3.0])
    best = nearest_hit(r, [far, near])
    assert best is not None and best.panel_id == "near"


def test_miss_everywhere_and_empty_inputs() -> None:
    r = ray(0, 0, 0, 0, 1, 0)
    assert nearest_hit(r, [panel()]) is None
    assert all_hits(r, [panel()]) == []
    assert nearest_hit(r, []) is None
    assert all_hits(r, []) == []


def test_all_hits_skips_misses() -> None:
    off = panel("off", center=(5, 0, -2))
    on = panel("on")
    assert [h.panel_id for h in all_hits(ray(0, 0, 0, *FORWARD), [off, on])] == ["on"]


def test_equal_distance_ties_break_on_panel_id_regardless_of_order() -> None:
    a, b, c = panel("a"), panel("b"), panel("c")
    r = ray(0, 0, 0, *FORWARD)
    for order in ([a, b, c], [c, b, a], [b, c, a]):
        assert [h.panel_id for h in all_hits(r, order)] == ["a", "b", "c"]
        best = nearest_hit(r, order)
        assert best is not None and best.panel_id == "a"


def test_max_distance_filters_far_panel_only() -> None:
    near, far = panel("near"), panel("far", center=(0, 0, -6))
    r = ray(0, 0, 0, *FORWARD)
    assert [h.panel_id for h in all_hits(r, [near, far], max_distance_m=5.0)] == ["near"]


def test_back_face_flag_is_threaded_through_collections() -> None:
    r = ray(0, 0, -4, 0, 0, 1)
    assert nearest_hit(r, [panel()]) is None
    best = nearest_hit(r, [panel()], allow_back_face=True)
    assert best is not None and best.panel_id == "p"
    assert len(all_hits(r, [panel()], allow_back_face=True)) == 1


# --- property: a ray aimed at a point inside the rectangle hits it with the same (u, v) ----

_coord = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_offset = st.floats(min_value=-3.0, max_value=3.0, allow_nan=False, allow_infinity=False)
_gap = st.floats(min_value=0.1, max_value=2.0, allow_nan=False, allow_infinity=False)
_size = st.floats(min_value=0.05, max_value=5.0, allow_nan=False, allow_infinity=False)


def _basis(n_raw: Vec3, a_raw: Vec3) -> tuple[Vec3, Vec3] | None:
    """Orthonormal (normal, up) from two arbitrary vectors, or None if degenerate."""
    if dot(n_raw, n_raw) < 1e-6:
        return None
    n = normalize(n_raw)
    up_raw = sub(a_raw, scale(n, dot(a_raw, n)))
    if dot(up_raw, up_raw) < 1e-6:
        return None
    return n, normalize(up_raw)


@given(
    c=st.tuples(_offset, _offset, _offset),
    n_raw=st.tuples(_coord, _coord, _coord),
    a_raw=st.tuples(_coord, _coord, _coord),
    width=_size,
    height=_size,
    u=_unit,
    v=_unit,
    gap=_gap,
    side=_offset,
    lift=_offset,
    back=st.booleans(),
)
def test_ray_built_from_inner_point_hits_same_uv(
    c, n_raw, a_raw, width, height, u, v, gap, side, lift, back
) -> None:
    basis = _basis(Vec3(*n_raw), Vec3(*a_raw))
    if basis is None:
        return
    n, up = basis
    pnl = Panel("prop", Vec3(*c), n, up, width, height)
    right = cross(up, n)
    target = add(
        add(pnl.center, scale(right, (u - 0.5) * width)),
        scale(up, (v - 0.5) * height),
    )
    sign = -1.0 if back else 1.0
    eye = add(
        add(target, scale(n, sign * gap)),
        add(scale(right, side), scale(up, lift)),
    )
    r = Ray(eye, normalize(sub(target, eye)))
    h = hit_panel(r, pnl, allow_back_face=back)
    assert h is not None
    assert h.u == pytest.approx(u, abs=1e-6)
    assert h.v == pytest.approx(v, abs=1e-6)
    assert h.distance_m == pytest.approx(math.dist((eye.x, eye.y, eye.z), (target.x, target.y, target.z)), abs=1e-6)
    if back:  # the same ray is a miss unless back faces were allowed
        assert hit_panel(r, pnl) is None


# --- regressions: signed zero and extreme sizes ---------------------------------------


def test_origin_on_the_plane_reports_positive_zero_distance() -> None:
    # Reproducer: hit_panel returned distance_m == -0.0 when the origin lay on the plane.
    pnl = panel(center=(0.0, 0.0, 0.0))
    h = hit_panel(ray(0.0, 0.0, 0.0, *FORWARD), pnl, allow_back_face=True)
    assert h is not None
    assert h.distance_m == 0.0
    assert math.copysign(1.0, h.distance_m) == 1.0


def test_huge_panel_dimensions_do_not_overflow() -> None:
    pnl = panel(width=1e308, height=1e308)
    h = hit_panel(ray(0.0, 0.0, 0.0, *FORWARD), pnl)
    assert h is not None
    assert (h.u, h.v) == (0.5, 0.5)
    assert hit_panel(ray(0.0, 0.0, 0.0, 1.0, 0.0, 0.0), pnl) is None  # parallel


def test_huge_origin_is_a_miss_not_an_exception() -> None:
    far = ray(1e308, 1e308, 1e308, *FORWARD)
    assert hit_panel(far, panel()) is None
    assert hit_panel(far, panel(width=1e308, height=1e308), 1e308) is None
