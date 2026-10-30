"""Adversarial, cross-module properties for ``yazses.xr`` (Hypothesis).

The per-module unit tests pin the examples somebody thought of. These properties attack
the contracts instead -- "never raises anything but WireError", "unit length out",
"never exceeds the cap", "never BOUND below min_share" -- over inputs nobody wrote by hand:
huge and tiny magnitudes, duplicate timestamps, one flipped byte in a valid frame.

Each property compares against an *independent* oracle (a geometric construction, a
re-derivation of the binder's mass, an inverse function), never against the module's own
helper, so a wrong formula cannot agree with itself.

Hazards and ranges, stated rather than hidden:

* ``geometry.normalize`` / ``angle_between`` square their components, so they are only
  exact for components within roughly [1e-150, 1e150]; the geometry properties stay inside
  [1e-100, 1e100]. Outside that range the answer is silently wrong (see the report on
  this branch); every ``yazses.xr`` caller feeds them unit-scale data.
* Frames in the round-trip property are generated *exactly* valid (unit vectors within
  1e-9, panel axes perpendicular within 1e-9). A frame that is only valid to 1e-6 is
  legitimately renormalised by the decoder, so it is covered by the idempotence property
  (``decode(encode(decode(x))) == decode(x)``) instead.
"""
from __future__ import annotations

import importlib.util
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from yazses.xr.binding import (
    BindingOutcome,
    PanelObservation,
    bind_demonstrative,
)
from yazses.xr.confirm import (
    ConfirmDecision,
    ConfirmPolicy,
    ConfirmReason,
    Evidence,
    decide,
)
from yazses.xr.conventions import (
    Convention,
    Handedness,
    from_canonical_ray,
    from_canonical_vec,
    handedness_of,
    to_canonical_ray,
    to_canonical_vec,
)
from yazses.xr.geometry import angle_between, cross, dot, norm, normalize, scale
from yazses.xr.privacy import SampleRetention
from yazses.xr.raycast import all_hits, hit_panel, nearest_hit
from yazses.xr.smoothing import RayFilter, dwell_progress
from yazses.xr.types import (
    GestureEvent,
    GestureKind,
    Panel,
    PanelHit,
    Ray,
    RaySource,
    Vec3,
    XrSample,
)
from yazses.xr.wire import (
    ClockMap,
    PanelGone,
    PanelUpdate,
    WireError,
    decode_frame,
    encode_frame,
)

_FAST = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
_FUZZ = settings(
    max_examples=120,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

# ── strategies ───────────────────────────────────────────────────────────────


def _floats(lo: float, hi: float) -> st.SearchStrategy[float]:
    return st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)


@st.composite
def unit_vecs(draw: st.DrawFn) -> Vec3:
    """A unit vector (length error ~1e-16) from three arbitrary components."""
    comps = [draw(_floats(-1.0, 1.0)) for _ in range(3)]
    assume(max(abs(c) for c in comps) > 1e-3)
    return normalize(Vec3(*comps))


@st.composite
def safe_vecs(draw: st.DrawFn) -> Vec3:
    """A non-zero vector with components inside the safe magnitude range."""
    comps = [draw(_floats(-1e100, 1e100)) for _ in range(3)]
    assume(max(abs(c) for c in comps) >= 1e-100)
    return Vec3(*comps)


@st.composite
def frames(draw: st.DrawFn) -> tuple[Vec3, Vec3]:
    """An orthonormal (normal, up) pair, well conditioned at every orientation."""
    n = draw(unit_vecs())
    axes = (Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1))
    e = min(axes, key=lambda a: abs(dot(a, n)))
    right = normalize(cross(e, n))
    up0 = cross(n, right)
    theta = draw(_floats(0.0, 2.0 * math.pi))
    up = Vec3(
        math.cos(theta) * up0.x + math.sin(theta) * right.x,
        math.cos(theta) * up0.y + math.sin(theta) * right.y,
        math.cos(theta) * up0.z + math.sin(theta) * right.z,
    )
    return n, up


_text_chars = st.one_of(
    st.characters(categories=("L", "M", "N", "P", "S")),
    st.just(" "),
)
labels = st.text(_text_chars, max_size=256)
ident_chars = st.characters(categories=("L", "N", "P", "S"))
panel_ids = st.text(ident_chars, min_size=1, max_size=128)


@st.composite
def panels(draw: st.DrawFn) -> Panel:
    n, up = draw(frames())
    return Panel(
        panel_id=draw(panel_ids),
        center=Vec3(*(draw(_floats(-1e6, 1e6)) for _ in range(3))),
        normal=n,
        up=up,
        width=draw(_floats(1e-6, 1e6)),
        height=draw(_floats(1e-6, 1e6)),
        label=draw(labels),
    )


@st.composite
def samples(draw: st.DrawFn) -> XrSample:
    return XrSample(
        timestamp_s=draw(_floats(0.0, 1e9)),
        source=draw(st.sampled_from(RaySource)),
        ray=Ray(Vec3(*(draw(_floats(-1e6, 1e6)) for _ in range(3))), draw(unit_vecs())),
        confidence=draw(_floats(0.0, 1.0)),
    )


gestures = st.builds(
    GestureEvent,
    timestamp_s=_floats(0.0, 1e9),
    kind=st.sampled_from(GestureKind),
    confidence=_floats(0.0, 1.0),
)
valid_frames = st.one_of(
    samples(),
    gestures,
    panels().map(PanelUpdate),
    panel_ids.map(PanelGone),
)

_json_leaf = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(-(10**30), 10**30),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=20),
)
json_values = st.recursive(
    _json_leaf,
    lambda c: st.one_of(
        st.lists(c, max_size=4),
        st.dictionaries(st.text(max_size=6), c, max_size=3),
    ),
    max_leaves=8,
)


def _accepts_or_wire_error(data: bytes | str) -> Any:
    """Decode; WireError is the one permitted failure. Returns the frame or None."""
    try:
        return decode_frame(data)
    except WireError:
        return None


def _assert_idempotent(frame: Any) -> None:
    again = decode_frame(encode_frame(frame))
    assert again == frame, f"accepted frame is not a fixed point of encode/decode: {frame!r}"


# ── geometry ─────────────────────────────────────────────────────────────────


@_FAST
@given(v=safe_vecs())
def test_normalize_gives_unit_length_in_the_same_direction(v: Vec3) -> None:
    u = normalize(v)
    assert norm(u) == pytest.approx(1.0, abs=1e-12)
    # Same direction, not merely unit length: cos(angle) == 1, so angle ~ 0.
    assert angle_between(u, v) < 1e-6


@_FAST
@given(v=safe_vecs())
def test_normalize_is_idempotent(v: Vec3) -> None:
    u = normalize(v)
    w = normalize(u)
    assert (w.x, w.y, w.z) == pytest.approx((u.x, u.y, u.z), abs=1e-12)


@_FAST
@given(a=safe_vecs(), b=safe_vecs())
def test_angle_is_symmetric_and_within_zero_to_pi(a: Vec3, b: Vec3) -> None:
    ang = angle_between(a, b)
    assert 0.0 <= ang <= math.pi
    assert ang == pytest.approx(angle_between(b, a), abs=1e-12)


@_FAST
@given(a=safe_vecs(), k=_floats(1e-3, 1e3), j=_floats(1e-3, 1e3), b=safe_vecs())
def test_angle_ignores_positive_scale_and_flips_under_negation(
    a: Vec3, k: float, j: float, b: Vec3
) -> None:
    # Keep the scaled vectors inside the safe range as well.
    assume(max(abs(c) for c in (a.x, a.y, a.z)) * k < 1e100)
    assume(max(abs(c) for c in (b.x, b.y, b.z)) * j < 1e100)
    base = angle_between(a, b)
    # acos is ill-conditioned near 0 and pi (error ~ sqrt(eps)), hence the 1e-6.
    assert angle_between(scale(a, k), scale(b, j)) == pytest.approx(base, abs=1e-6)
    assert angle_between(scale(a, -1.0), b) == pytest.approx(math.pi - base, abs=1e-6)
    assert angle_between(a, scale(a, k)) < 1e-6
    assert angle_between(a, scale(a, -k)) > math.pi - 1e-6


# ── raycast ──────────────────────────────────────────────────────────────────


def _panel_axes(panel: Panel) -> tuple[Vec3, Vec3]:
    return cross(panel.up, panel.normal), panel.up  # (right, up) -- the documented frame


@st.composite
def panel_and_aim(draw: st.DrawFn) -> tuple[Panel, float, float, Vec3, float, float, float]:
    n, up = draw(frames())
    panel = Panel(
        panel_id="p",
        center=Vec3(*(draw(_floats(-10.0, 10.0)) for _ in range(3))),
        normal=n,
        up=up,
        width=draw(_floats(0.01, 10.0)),
        height=draw(_floats(0.01, 10.0)),
    )
    u = draw(st.one_of(_floats(0.0, 1.0), st.sampled_from([0.0, 1.0, 0.5])))
    v = draw(st.one_of(_floats(0.0, 1.0), st.sampled_from([0.0, 1.0, 0.5])))
    right, upv = _panel_axes(panel)
    target = Vec3(
        panel.center.x + right.x * (u - 0.5) * panel.width + upv.x * (v - 0.5) * panel.height,
        panel.center.y + right.y * (u - 0.5) * panel.width + upv.y * (v - 0.5) * panel.height,
        panel.center.z + right.z * (u - 0.5) * panel.width + upv.z * (v - 0.5) * panel.height,
    )
    d = draw(_floats(0.05, 5.0))
    a = draw(_floats(-5.0, 5.0))
    b = draw(_floats(-5.0, 5.0))
    return panel, u, v, target, d, a, b


def _origin_for(panel: Panel, target: Vec3, d: float, a: float, b: float) -> Vec3:
    """A point ``d`` m in front of ``target`` (along +normal), offset ``a``/``b`` in-plane."""
    right, up = _panel_axes(panel)
    n = panel.normal
    return Vec3(
        target.x + n.x * d + right.x * a + up.x * b,
        target.y + n.y * d + right.y * a + up.y * b,
        target.z + n.z * d + right.z * a + up.z * b,
    )


@_FAST
@given(case=panel_and_aim())
def test_a_ray_aimed_at_a_point_inside_the_rectangle_hits_with_matching_uv(
    case: tuple[Panel, float, float, Vec3, float, float, float],
) -> None:
    panel, u, v, target, d, a, b = case
    origin = _origin_for(panel, target, d, a, b)
    delta = Vec3(target.x - origin.x, target.y - origin.y, target.z - origin.z)
    ray = Ray(origin, normalize(delta))
    hit = hit_panel(ray, panel, max_distance_m=50.0)
    assert hit is not None, f"aimed at ({u}, {v}) but missed"
    assert hit.u == pytest.approx(u, abs=1e-6)
    assert hit.v == pytest.approx(v, abs=1e-6)
    assert hit.distance_m == pytest.approx(norm(delta), rel=1e-9, abs=1e-9)
    assert 0.0 <= hit.u <= 1.0 and 0.0 <= hit.v <= 1.0


@_FAST
@given(case=panel_and_aim())
def test_a_back_face_hit_needs_allow_back_face_and_keeps_the_panel_frame(
    case: tuple[Panel, float, float, Vec3, float, float, float],
) -> None:
    panel, u, v, target, d, a, b = case
    origin = _origin_for(panel, target, -d, a, b)  # behind the panel
    delta = Vec3(target.x - origin.x, target.y - origin.y, target.z - origin.z)
    ray = Ray(origin, normalize(delta))
    assert hit_panel(ray, panel, max_distance_m=50.0) is None
    hit = hit_panel(ray, panel, max_distance_m=50.0, allow_back_face=True)
    assert hit is not None
    assert hit.u == pytest.approx(u, abs=1e-6)  # u/v are always in the panel frame
    assert hit.v == pytest.approx(v, abs=1e-6)


@_FAST
@given(case=panel_and_aim(), overshoot=_floats(1e-3, 3.0), axis=st.booleans())
def test_a_ray_aimed_outside_the_rectangle_misses(
    case: tuple[Panel, float, float, Vec3, float, float, float],
    overshoot: float,
    axis: bool,
) -> None:
    panel, _u, _v, _target, d, a, b = case
    right, up = _panel_axes(panel)
    # Aim past the right edge (u = 1 + overshoot) or the top edge.
    u, v = (1.0 + overshoot, 0.5) if axis else (0.5, 1.0 + overshoot)
    c = panel.center
    target = Vec3(
        c.x + right.x * (u - 0.5) * panel.width + up.x * (v - 0.5) * panel.height,
        c.y + right.y * (u - 0.5) * panel.width + up.y * (v - 0.5) * panel.height,
        c.z + right.z * (u - 0.5) * panel.width + up.z * (v - 0.5) * panel.height,
    )
    origin = _origin_for(panel, target, d, a, b)
    delta = Vec3(target.x - origin.x, target.y - origin.y, target.z - origin.z)
    assert hit_panel(Ray(origin, normalize(delta)), panel, max_distance_m=50.0) is None


@_FAST
@given(
    ids=st.lists(st.text("abcdef", min_size=1, max_size=3), min_size=1, max_size=8),
    depths=st.lists(st.sampled_from([0.5, 1.0, 1.0, 2.0, 3.5]), min_size=8, max_size=8),
    d=unit_vecs(),
    ox=_floats(-0.2, 0.2),
    oy=_floats(-0.2, 0.2),
)
def test_all_hits_is_sorted_by_distance_then_id_and_agrees_with_hit_panel(
    ids: list[str], depths: list[float], d: Vec3, ox: float, oy: float
) -> None:
    # Ties are the point: depths repeat, and distinct ids share a distance.
    unique = list(dict.fromkeys(ids))
    ps = [
        Panel(
            panel_id=pid,
            center=Vec3(0.0, 0.0, -depths[i]),
            normal=Vec3(0, 0, 1),
            up=Vec3(0, 1, 0),
            width=40.0,
            height=40.0,
        )
        for i, pid in enumerate(unique)
    ]
    assume(d.z < -0.1)
    ray = Ray(Vec3(ox, oy, 0.0), d)
    hits = all_hits(ray, ps, max_distance_m=100.0)
    keys = [(h.distance_m, h.panel_id) for h in hits]
    assert keys == sorted(keys)
    for h in hits:
        panel = next(p for p in ps if p.panel_id == h.panel_id)
        assert hit_panel(ray, panel, max_distance_m=100.0) == h
    expected_ids = {p.panel_id for p in ps if hit_panel(ray, p, max_distance_m=100.0)}
    assert {h.panel_id for h in hits} == expected_ids
    nearest = nearest_hit(ray, ps, max_distance_m=100.0)
    assert nearest == (hits[0] if hits else None)


# ── wire ─────────────────────────────────────────────────────────────────────


@_FUZZ
@given(frame=valid_frames)
def test_decode_of_encode_is_the_identity_on_valid_frames(frame: Any) -> None:
    data = encode_frame(frame)
    assert len(data) <= 4096 or isinstance(frame, PanelUpdate)  # labels can be long
    if len(data) > 4096:
        with pytest.raises(WireError):  # over-size is refused, not truncated
            decode_frame(data)
        return
    assert decode_frame(data) == frame
    assert decode_frame(data.decode("ascii")) == frame  # the str door agrees


@_FUZZ
@given(data=st.one_of(st.binary(max_size=400), st.text(max_size=400)))
def test_decode_never_raises_anything_but_wire_error_on_arbitrary_input(
    data: bytes | str,
) -> None:
    _accepts_or_wire_error(data)


@_FUZZ
@given(data=st.binary(max_size=64), tail=st.binary(max_size=64))
def test_decode_is_total_on_random_prefixes_of_json_shaped_noise(
    data: bytes, tail: bytes
) -> None:
    _accepts_or_wire_error(b'{"v":1,"t":"sample",' + data + tail)
    _accepts_or_wire_error(b'{"v":1,"t":"panel","panel_id":"' + data + b'"' + tail)


@_FUZZ
@given(
    frame=valid_frames,
    index=st.integers(min_value=0, max_value=10_000),
    replacement=st.integers(min_value=0, max_value=255),
    use_xor=st.booleans(),
)
def test_one_mutated_byte_in_a_valid_frame_is_accepted_or_a_wire_error(
    frame: Any, index: int, replacement: int, use_xor: bool
) -> None:
    data = bytearray(encode_frame(frame))
    assume(len(data) <= 4096)
    i = index % len(data)
    data[i] = (data[i] ^ (1 << (replacement % 8))) if use_xor else replacement
    got = _accepts_or_wire_error(bytes(data))
    if got is not None:
        _assert_idempotent(got)


@_FUZZ
@given(frame=valid_frames, cut=st.integers(min_value=0, max_value=10_000))
def test_every_truncation_of_a_valid_frame_is_accepted_or_a_wire_error(
    frame: Any, cut: int
) -> None:
    data = encode_frame(frame)
    assume(len(data) <= 4096)
    got = _accepts_or_wire_error(data[: cut % (len(data) + 1)])
    if got is not None:
        _assert_idempotent(got)


@st.composite
def hostile_objects(draw: st.DrawFn) -> bytes:
    """A valid frame object with some fields replaced/removed/added by arbitrary JSON."""
    frame = draw(valid_frames)
    obj: dict[str, Any] = json.loads(encode_frame(frame))
    keys = sorted(obj) + ["v", "t", "extra"]
    for key, value in draw(st.lists(st.tuples(st.sampled_from(keys), json_values), max_size=3)):
        obj[key] = value
    for key in draw(st.lists(st.sampled_from(keys), max_size=2)):
        obj.pop(key, None)
    return json.dumps(obj, allow_nan=True).encode("utf-8")


@_FUZZ
@given(data=hostile_objects())
def test_structurally_hostile_frames_are_accepted_or_a_wire_error(data: bytes) -> None:
    got = _accepts_or_wire_error(data)
    if got is not None:
        _assert_idempotent(got)


@_FAST
@given(depth=st.integers(min_value=1, max_value=4000), opener=st.sampled_from(["[", "{\"a\":"]))
def test_deep_nesting_is_a_wire_error_not_a_recursion_error(depth: int, opener: str) -> None:
    _accepts_or_wire_error((opener * depth).encode())
    _accepts_or_wire_error(('{"v":1,"t":"panel_gone","panel_id":' + opener * depth).encode())


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\xef\xbb\xbf" + b'{"v":1,"t":"panel_gone","panel_id":"a"}',  # BOM
        b'{"v":1,"t":"panel_gone","panel_id":"a"}\x00',
        b'{"v":1,"t":"panel_gone","panel_id":"\\ud800"}',  # lone surrogate escape
        b'{"v":1,"t":"panel_gone","panel_id":"a","panel_id":"b"}',  # duplicate key
        b'{"v":1,"t":"sample","device_time_s":1e999,"source":"eye","origin":[0,0,0],'
        b'"direction":[0,0,-1],"confidence":1}',
        b'{"v":1,"t":"sample","device_time_s":NaN,"source":"eye","origin":[0,0,0],'
        b'"direction":[0,0,-1],"confidence":1}',
        b'{"v":1,"t":"sample","device_time_s":' + b"9" * 400 + b',"source":"eye",'
        b'"origin":[0,0,0],"direction":[0,0,-1],"confidence":1}',
        b'{"v":1.0,"t":"panel_gone","panel_id":"a"}',
        b'{"v":true,"t":"panel_gone","panel_id":"a"}',
        b'{"v":1,"t":["x"],"panel_id":"a"}',
        b"[1,2,3]",
        b"null",
        b"\xff\xfe\x00",
    ],
)
def test_named_hostile_frames_are_wire_errors(data: bytes) -> None:
    with pytest.raises(WireError):
        decode_frame(data)


@st.composite
def clock_streams(draw: st.DrawFn) -> list[tuple[float, float, float]]:
    """(device_dt, desktop_dt, device_jitter): both clocks run forward."""
    return draw(
        st.lists(
            st.tuples(_floats(0.0, 2.0), _floats(0.0, 2.0), _floats(-0.4, 0.4)),
            min_size=1,
            max_size=40,
        )
    )


@_FAST
@given(stream=clock_streams(), start=_floats(0.0, 1e5), jump=_floats(-1e4, 1e4))
def test_clock_map_never_maps_into_the_future_and_never_leaks_other_errors(
    stream: list[tuple[float, float, float]], start: float, jump: float
) -> None:
    clock = ClockMap()
    dev, now = start, 1000.0
    last_mapped = -math.inf
    for ddev, dnow, jitter in stream:
        dev += ddev
        now += dnow
        reported = max(0.0, dev + jitter)
        before = clock.offset_s
        try:
            mapped = clock.map(reported, now)
        except WireError:
            assert clock.offset_s == before  # a refused frame leaves the mapping untouched
            continue
        assert mapped <= now + 1e-6, "a sample was mapped into the future"
        assert math.isfinite(mapped) and mapped >= 0.0
        last_mapped = mapped
    try:
        clock.map(max(0.0, dev + jump), now)
    except WireError:
        pass
    assert last_mapped == last_mapped  # (kept: stream may have been fully refused)


# ── conventions ──────────────────────────────────────────────────────────────

_big_vecs = st.builds(Vec3, _floats(-1e100, 1e100), _floats(-1e100, 1e100), _floats(-1e100, 1e100))


def _close(a: Vec3, b: Vec3) -> bool:
    return all(
        math.isclose(p, q, rel_tol=1e-12, abs_tol=1e-300)
        for p, q in ((a.x, b.x), (a.y, b.y), (a.z, b.z))
    )


@_FAST
@given(v=_big_vecs, conv=st.sampled_from(Convention))
def test_vector_conversion_round_trips(v: Vec3, conv: Convention) -> None:
    assert _close(from_canonical_vec(to_canonical_vec(v, conv), conv), v)
    assert _close(to_canonical_vec(from_canonical_vec(v, conv), conv), v)


@_FAST
@given(origin=_big_vecs, direction=unit_vecs(), conv=st.sampled_from(Convention))
def test_ray_conversion_round_trips_and_keeps_directions_exactly_unit(
    origin: Vec3, direction: Vec3, conv: Convention
) -> None:
    ray = Ray(origin, direction)
    canon = to_canonical_ray(ray, conv)  # Ray() itself enforces unit length
    back = from_canonical_ray(canon, conv)
    assert back.direction == direction  # a signed permutation is exact
    assert _close(back.origin, origin)
    assert norm(canon.direction) == pytest.approx(1.0, abs=1e-12)


@_FAST
@given(a=unit_vecs(), b=unit_vecs(), c=unit_vecs(), conv=st.sampled_from(Convention))
def test_conversion_preserves_angles_and_flips_orientation_exactly_when_left_handed(
    a: Vec3, b: Vec3, c: Vec3, conv: Convention
) -> None:
    zero = Vec3(0, 0, 0)
    ca, cb, cc = (to_canonical_ray(Ray(zero, x), conv).direction for x in (a, b, c))
    assert angle_between(ca, cb) == pytest.approx(angle_between(a, b), abs=1e-6)
    sign = 1.0 if handedness_of(conv) is Handedness.RIGHT else -1.0
    assert dot(ca, cross(cb, cc)) == pytest.approx(sign * dot(a, cross(b, c)), abs=1e-12)


@_FAST
@given(v=_big_vecs, conv=st.sampled_from(Convention))
def test_positions_scale_by_the_declared_unit_and_directions_never_do(
    v: Vec3, conv: Convention
) -> None:
    factor = 0.01 if conv is Convention.UNREAL else 1.0
    assert norm(to_canonical_vec(v, conv)) == pytest.approx(factor * norm(v), rel=1e-9)


# ── smoothing ────────────────────────────────────────────────────────────────

_dts = st.one_of(
    st.sampled_from([0.0, 0.0, 1e-300, 1e-12, 1e-6, 0.004, 0.016, 0.4, 0.5, 0.6, 30.0, 1e6]),
    _floats(0.0, 2.0),
)
_extreme_mag = st.one_of(
    _floats(-1e308, 1e308),
    _floats(-1e-300, 1e-300),
    _floats(-10.0, 10.0),
    st.sampled_from([0.0, 1e308, -1e308, 5e-324]),
)
_rate = st.one_of(_floats(1e-300, 1e300), _floats(1e-3, 1e3))
_axis_dirs = st.sampled_from(
    [Vec3(1, 0, 0), Vec3(-1, 0, 0), Vec3(0, 1, 0), Vec3(0, -1, 0), Vec3(0, 0, 1), Vec3(0, 0, -1)]
)


@_FUZZ
@given(
    steps=st.lists(
        st.tuples(_dts, st.builds(Vec3, _extreme_mag, _extreme_mag, _extreme_mag),
                  st.one_of(unit_vecs(), _axis_dirs), _floats(0.0, 1.0)),
        min_size=1,
        max_size=40,
    ),
    min_cutoff=_rate,
    beta=st.one_of(st.just(0.0), _floats(0.0, 1e6), _floats(1e100, 1e300)),
    d_cutoff=_rate,
    gap=_floats(1e-3, 1e3),
    t0=_floats(0.0, 1e6),
)
def test_smoothed_direction_is_unit_for_any_finite_stream(
    steps: list[tuple[float, Vec3, Vec3, float]],
    min_cutoff: float,
    beta: float,
    d_cutoff: float,
    gap: float,
    t0: float,
) -> None:
    filt = RayFilter(min_cutoff, beta, d_cutoff, gap)
    t = t0
    for dt, origin, direction, conf in steps:
        t += dt
        sample = XrSample(t, RaySource.EYE, Ray(origin, direction), conf)
        out = filt.update(sample)
        assert out.timestamp_s == sample.timestamp_s
        assert out.source is sample.source and out.confidence == sample.confidence
        d = out.ray.direction
        assert math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z) == pytest.approx(1.0, abs=1e-9)
        o = out.ray.origin
        assert all(math.isfinite(c) for c in (o.x, o.y, o.z))


@_FAST
@given(
    stream=st.lists(st.tuples(_floats(0.0, 1e6), unit_vecs()), max_size=25),
    centre=safe_vecs(),
    radius=_floats(0.0, 4.0),
    now=_floats(0.0, 1e6),
    window=_floats(1e-6, 1e3),
)
def test_dwell_progress_stays_in_the_unit_interval(
    stream: list[tuple[float, Vec3]], centre: Vec3, radius: float, now: float, window: float
) -> None:
    ss = [XrSample(t, RaySource.EYE, Ray(Vec3(0, 0, 0), d), 1.0) for t, d in stream]
    p = dwell_progress(ss, centre, radius, now, window)
    assert 0.0 <= p <= 1.0
    # A radius of pi covers the whole sphere, so the answer is exactly "how much of the
    # window is covered by samples" -- never more than that, whatever the order.
    full = dwell_progress(ss, centre, math.pi + 1e-9, now, window)
    assert dwell_progress(list(reversed(ss)), centre, math.pi + 1e-9, now, window) == full
    assert p <= full + 1e-12


# ── privacy ──────────────────────────────────────────────────────────────────


@_FAST
@given(
    adds=st.lists(_floats(0.0, 1e4), max_size=60),
    window=st.one_of(_floats(1e-3, 20.0), st.sampled_from([1.0, 2.0])),
    cap=st.integers(min_value=1, max_value=12),
)
def test_retention_never_exceeds_its_caps_for_any_add_order(
    adds: list[float], window: float, cap: int
) -> None:
    # Arbitrary add order is the point of this property, so lift the future-stamp guard
    # (its own behaviour is pinned in test_xr_privacy.py).
    buf = SampleRetention(window_s=window, max_samples=cap, max_future_s=math.inf)
    newest = -math.inf
    for ts in adds:
        buf.add(XrSample(ts, RaySource.EYE, Ray(Vec3(0, 0, 0), Vec3(0, 0, -1)), 1.0))
        newest = max(newest, ts)
        assert len(buf) <= cap
        held = buf.snapshot(newest)
        assert len(held) <= cap
        times = [s.timestamp_s for s in held]
        assert times == sorted(times), "window must stay oldest -> newest"
        assert all(newest - t <= window for t in times), "retained a sample past its age cap"
    assert len(buf) <= cap
    buf.clear()
    assert len(buf) == 0 and buf.snapshot(newest if newest > -math.inf else 0.0) == ()


@_FAST
@given(
    adds=st.lists(_floats(0.0, 100.0), min_size=1, max_size=40),
    now=_floats(0.0, 1e3),
    window=_floats(1e-3, 20.0),
)
def test_snapshot_drops_exactly_what_is_older_than_the_window(
    adds: list[float], now: float, window: float
) -> None:
    buf = SampleRetention(window_s=window, max_samples=1000, max_future_s=math.inf)
    for ts in adds:
        buf.add(XrSample(ts, RaySource.HEAD, Ray(Vec3(0, 0, 0), Vec3(0, 0, -1)), 0.5))
    got = [s.timestamp_s for s in buf.snapshot(now)]
    assert all(now - t <= window for t in got)


# ── binding ──────────────────────────────────────────────────────────────────

_ONSET = 5.0
_IDS = ("a", "b", "c")


def _obs(ts: float, pid: str | None, conf: float) -> PanelObservation:
    hit = None if pid is None else PanelHit(pid, 0.5, 0.5, 1.0)
    return PanelObservation(ts, hit, conf)


observations = st.lists(
    st.builds(
        _obs,
        st.one_of(_floats(_ONSET - 0.6, _ONSET + 0.4), st.sampled_from([_ONSET - 0.4, _ONSET, _ONSET + 0.2])),
        st.one_of(st.none(), st.sampled_from(_IDS)),
        st.one_of(_floats(0.0, 1.0), st.sampled_from([0.0, 0.3, 1.0])),
    ),
    max_size=14,
)


@_FUZZ
@given(
    obs=observations,
    min_share=st.one_of(_floats(1e-3, 1.0), st.sampled_from([0.5, 0.6, 1.0])),
    min_conf=_floats(0.0, 1.0),
    min_mass=_floats(0.0, 2.0),
    lead=_floats(1e-3, 1.0),
    lag=_floats(1e-3, 1.0),
)
def test_a_binding_never_holds_less_than_min_share_and_is_the_top_panel(
    obs: list[PanelObservation],
    min_share: float,
    min_conf: float,
    min_mass: float,
    lead: float,
    lag: float,
) -> None:
    res = bind_demonstrative(
        obs, _ONSET, lead_s=lead, lag_s=lag, min_share=min_share,
        min_confidence=min_conf, min_mass=min_mass,
    )
    assert (res.outcome is BindingOutcome.BOUND) == (res.panel_id is not None)
    assert 0.0 <= res.margin <= 1.0 + 1e-9
    if res.outcome is BindingOutcome.BOUND:
        # Invariants that hold however the evidence is weighted. The exact weighting
        # (dwell-time x confidence x triangular time weight) is pinned by test_xr_binding.py.
        in_window = [
            o for o in obs
            if -lead <= o.timestamp_s - _ONSET <= lag and o.confidence >= min_conf
        ]
        assert len(in_window) >= 3, "BOUND on fewer than min_samples usable observations"
        assert res.panel_id in {o.hit.panel_id for o in in_window if o.hit is not None}
        assert res.top_share >= min_share - 1e-9, f"BOUND at share {res.top_share} < {min_share}"
        assert 0.0 < res.margin <= res.top_share + 1e-9, "BOUND without a strict lead"
        assert min_conf - 1e-9 <= res.confidence <= 1.0 + 1e-9


@_FUZZ
@given(obs=observations, seed=st.integers(min_value=0, max_value=2**32))
def test_binding_does_not_depend_on_observation_order(
    obs: list[PanelObservation], seed: int
) -> None:
    shuffled = list(obs)
    random.Random(seed).shuffle(shuffled)
    a = bind_demonstrative(obs, _ONSET)
    b = bind_demonstrative(shuffled, _ONSET)
    assert (a.outcome, a.panel_id) == (b.outcome, b.panel_id)
    assert a.margin == pytest.approx(b.margin, abs=1e-12)


# ── confirm ──────────────────────────────────────────────────────────────────

_panel_or_none = st.sampled_from([None, "a", "b"])


@_FUZZ
@given(
    outcome=st.sampled_from(["bound", "ambiguous", "none"]),
    margin=st.one_of(_floats(0.0, 1.0), st.sampled_from([0.0, 0.25, 1.0])),
    confidence=st.one_of(_floats(0.0, 1.0), st.sampled_from([0.0, 0.35, 1.0])),
    destructive=st.booleans(),
    onset=_panel_or_none,
    end=_panel_or_none,
    min_conf=st.one_of(_floats(0.0, 1.0), st.just(0.35)),
    min_margin=st.one_of(_floats(0.0, 1.0), st.just(0.25)),
)
def test_confirm_decide_agrees_with_an_independent_oracle(
    outcome: str,
    margin: float,
    confidence: float,
    destructive: bool,
    onset: str | None,
    end: str | None,
    min_conf: float,
    min_margin: float,
) -> None:
    d = decide(
        outcome=outcome, margin=margin, confidence=confidence, destructive=destructive,
        panel_at_onset=onset, panel_at_end=end, min_confidence=min_conf, min_margin=min_margin,
    )
    # The headline invariant: a prompt never carries a "silent" reason, and vice versa.
    if d.confirm:
        assert d.reason not in (ConfirmReason.NONE, ConfirmReason.NO_TARGET)
    else:
        assert d.reason in (ConfirmReason.NONE, ConfirmReason.NO_TARGET)

    moved = onset is not None and end is not None and onset != end
    weak = confidence < min_conf or margin < min_margin
    if outcome == "none":
        assert d == ConfirmDecision(False, ConfirmReason.NO_TARGET)  # never prompts, even if destructive
    elif outcome == "ambiguous" or moved or destructive or weak:
        assert d.confirm, "a checkable hold signal was ignored"
    else:
        assert d == ConfirmDecision(False, ConfirmReason.NONE)
    assert len(d.release_word.split()) == 1


@given(confirm=st.booleans(), reason=st.sampled_from(ConfirmReason))
def test_confirm_decision_refuses_every_contradictory_pair(
    confirm: bool, reason: ConfirmReason
) -> None:
    silent = reason in (ConfirmReason.NONE, ConfirmReason.NO_TARGET)
    if confirm == silent:
        with pytest.raises(ValueError):
            ConfirmDecision(confirm, reason)
    else:
        assert ConfirmDecision(confirm, reason).confirm is confirm


# ── the redesigned decision layer: evidence rules ────────────────────────────

def _with_rival(o: PanelObservation, deg: float) -> PanelObservation:
    if o.hit is None:
        return o
    other = "z" if o.hit.panel_id != "z" else "y"
    return PanelObservation(o.timestamp_s, o.hit, o.confidence, other, deg)


@_FUZZ
@given(obs=observations, deg=_floats(0.0, 40.0))
def test_rival_annotations_never_change_the_binding_verdict(obs: list[PanelObservation], deg: float) -> None:
    plain = bind_demonstrative(obs, _ONSET)
    rich = bind_demonstrative([_with_rival(o, deg) for o in obs], _ONSET)
    assert (plain.outcome, plain.panel_id, plain.margin, plain.confidence, plain.top_share) == (
        rich.outcome, rich.panel_id, rich.margin, rich.confidence, rich.top_share)
    assert plain.candidates == rich.candidates
    if rich.outcome is BindingOutcome.BOUND and rich.rival_deg is not None:
        assert rich.rival_deg == pytest.approx(deg, abs=1e-6)


@_FUZZ
@given(
    outcome=st.sampled_from(["bound", "ambiguous", "none"]),
    margin=_floats(0.0, 1.0),
    confidence=_floats(0.0, 1.0),
    destructive=st.booleans(),
    top_share=st.one_of(st.none(), _floats(0.0, 1.0)),
    rival_deg=st.one_of(st.none(), _floats(0.0, 20.0)),
    settled_s=st.one_of(st.none(), _floats(0.0, 3.0)),
    departure_s=st.one_of(st.none(), _floats(0.0, 3.0)),
    budget=_floats(0.0, 10.0),
    settle=_floats(0.0, 2.0),
    min_dep=_floats(0.0, 2.0),
    onset=_panel_or_none,
    end=_panel_or_none,
)
def test_confirm_with_evidence_agrees_with_an_independent_oracle(
    outcome: str, margin: float, confidence: float, destructive: bool, top_share: float | None,
    rival_deg: float | None, settled_s: float | None, departure_s: float | None, budget: float,
    settle: float, min_dep: float, onset: str | None, end: str | None,
) -> None:
    ev = Evidence(
        panel_id="a", top_share=top_share, runner_up="b",
        rival_id=None if rival_deg is None else "b", rival_deg=rival_deg,
        prior_panel=None if settled_s is None else "c", settled_s=settled_s,
        departure_s=departure_s, departure_panel="b" if departure_s else None,
    )
    pol = ConfirmPolicy(error_budget_deg=budget, settle_s=settle, min_departure_s=min_dep)
    d = decide(outcome=outcome, margin=margin, confidence=confidence, destructive=destructive,
               panel_at_onset=onset, panel_at_end=end, evidence=ev, policy=pol)
    switch = settled_s is not None and settled_s < settle
    edge = rival_deg is not None and rival_deg < budget
    if departure_s is not None:
        moved = departure_s > 0.0 and departure_s >= min_dep
    else:
        moved = onset is not None and end is not None and onset != end
    thin = top_share is not None and top_share < pol.min_top_share
    weak = confidence < 0.35 or margin < 0.25
    if outcome == "none":
        assert d == ConfirmDecision(False, ConfirmReason.NO_TARGET)
    elif outcome == "ambiguous" or switch or edge or moved or destructive or thin or weak:
        assert d.confirm, "a checkable hold signal was ignored"
    else:
        assert d == ConfirmDecision(False, ConfirmReason.NONE)
    assert d.candidates == () or d.confirm
    assert len(d.candidates) <= 2


# ── the fuzz harness target ──────────────────────────────────────────────────

_FUZZ_DIR = Path(__file__).resolve().parent.parent / "fuzz"


def _load_harness() -> Any:
    """Import fuzz/fuzz_xr_wire.py by path (fuzz/ is not a package); no atheris needed."""
    spec = importlib.util.spec_from_file_location("_fuzz_fuzz_xr_wire", _FUZZ_DIR / "fuzz_xr_wire.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _mutate(rng: random.Random, seed: bytes, pool: tuple[bytes, ...]) -> bytes:
    data = bytearray(seed)
    for _ in range(rng.choice((1, 1, 1, 2))):
        op = rng.randrange(8)
        i = rng.randrange(len(data) + 1)
        if op == 0 and data:  # flip a bit
            data[i % len(data)] ^= 1 << rng.randrange(8)
        elif op == 1 and data:  # overwrite a byte
            data[i % len(data)] = rng.randrange(256)
        elif op == 2:  # insert a byte
            data.insert(i, rng.randrange(256))
        elif op == 3 and data:  # delete a span
            del data[i % len(data) : i % len(data) + rng.randint(1, 8)]
        elif op == 4:  # truncate
            del data[i:]
        elif op == 5:  # splice another seed's tail in
            other = rng.choice(pool)
            data[i:] = other[rng.randrange(len(other) + 1) :]
        elif op == 6:  # change one digit: stays well-formed JSON, changes a value
            digits = [k for k, b in enumerate(data) if 48 <= b <= 57]
            if digits:
                data[rng.choice(digits)] = rng.randrange(48, 58)
        else:  # duplicate a span (repeated keys, doubled numbers)
            j = rng.randrange(len(data) + 1)
            lo, hi = sorted((i, j))
            data[lo:lo] = data[lo:hi]
    return bytes(data)


def test_the_fuzz_harness_survives_seeded_random_mutations_of_valid_frames() -> None:
    harness = _load_harness()
    assert callable(harness.one_input) and callable(harness.test_one_input)
    seeds = harness.SEED_FRAMES
    for seed in seeds:  # the seeds themselves are valid, or the mutations prove nothing
        harness.test_one_input(seed)
        assert decode_frame(seed) is not None
    rng = random.Random(20260430)
    accepted = rejected = 0
    for _ in range(2000):
        data = _mutate(rng, rng.choice(seeds), seeds)
        harness.test_one_input(data)
        if _accepts_or_wire_error(data) is None:
            rejected += 1
        else:
            accepted += 1
    # Non-vacuous: the mutator reaches both outcomes.
    assert accepted > 20 and rejected > 20, (accepted, rejected)


def test_the_fuzz_harness_reports_a_decoder_that_leaks_a_non_wire_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _load_harness()
    harness._load()  # populate the cache, then break the decoder it holds

    def leaky(_raw: object) -> None:
        raise KeyError("v")

    monkeypatch.setitem(harness._LOADED, "decode_frame", leaky)
    with pytest.raises(KeyError):
        harness.one_input(harness.SEED_FRAMES[0])
