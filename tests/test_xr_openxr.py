"""Tests for ``yazses.xr.openxr`` -- OpenXR data modelled as plain numbers (synthetic only).

No OpenXR runtime, SDK or device is involved: every pose, flag word, joint array and
``XrTime`` below is a hand-built number. Expected quaternion results are derived by hand
in the comments (right-hand rule, +Y up, -Z forward) rather than by calling the code under
test, and the property tests compare against independent oracles.
"""
from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import yazses.xr.openxr as openxr
from yazses.xr.geometry import dot, norm
from yazses.xr.openxr import (
    FORWARD,
    QUAT_IDENTITY,
    SPACE_LOCATION_ORIENTATION_TRACKED_BIT,
    SPACE_LOCATION_ORIENTATION_VALID_BIT,
    SPACE_LOCATION_POSITION_TRACKED_BIT,
    SPACE_LOCATION_POSITION_VALID_BIT,
    ClickTap,
    HandJoint,
    HandJoints,
    HoldGesture,
    HoldKind,
    OpenXrError,
    Quat,
    ReferenceSpace,
    XrPose,
    XrTimeBase,
    aim_sample,
    choose_gaze_time,
    gaze_sample,
    hand_joints_from_raw,
    hand_pinch_sample,
    location_confidence,
    parse_location_flags,
    pinch_strength,
    pose_forward,
    pose_from_raw,
    pose_transform_point,
    quat_conjugate,
    quat_from_axis_angle,
    quat_from_raw,
    quat_multiply,
    quat_rotate,
    ray_from_pose,
    require_world_space,
    xr_time_to_seconds,
)
from yazses.xr.types import GestureKind, RaySource, Vec3
from yazses.xr.wire import ClockMap, rebase

S = math.sqrt(0.5)
OV = SPACE_LOCATION_ORIENTATION_VALID_BIT
PV = SPACE_LOCATION_POSITION_VALID_BIT
OT = SPACE_LOCATION_ORIENTATION_TRACKED_BIT
PT = SPACE_LOCATION_POSITION_TRACKED_BIT
ALL = OV | PV | OT | PT
LOCAL = ReferenceSpace.LOCAL


def close(a: Vec3, b: tuple[float, float, float], tol: float = 1e-12) -> bool:
    return all(abs(p - q) <= tol for p, q in zip((a.x, a.y, a.z), b, strict=True))


# --- quaternions: hand-computed ---------------------------------------------


def test_identity_forward_is_minus_z() -> None:
    # No rotation: -Z stays -Z.
    assert pose_forward(XrPose(Vec3(0, 0, 0), QUAT_IDENTITY)) == Vec3(0.0, 0.0, -1.0)
    assert FORWARD == Vec3(0.0, 0.0, -1.0)


def test_yaw_90_turns_forward_to_minus_x() -> None:
    # q = (0, sin45, 0, cos45): +90 deg about +Y. Rotation about Y: x' = x cos + z sin,
    # z' = -x sin + z cos. For (0,0,-1): x' = -1, z' = 0  => (-1, 0, 0): the user looks left.
    q = quat_from_raw(0, S, 0, S)
    assert close(quat_rotate(q, FORWARD), (-1.0, 0.0, 0.0))


def test_pitch_up_90_turns_forward_to_plus_y() -> None:
    # +90 deg about +X: y' = y cos - z sin = 0 - (-1)(1) = 1, z' = y sin + z cos = 0.
    q = quat_from_raw(S, 0, 0, S)
    assert close(quat_rotate(q, FORWARD), (0.0, 1.0, 0.0))


def test_roll_90_turns_x_to_y() -> None:
    # +90 deg about +Z: (1,0,0) -> (0,1,0).
    q = quat_from_raw(0, 0, S, S)
    assert close(quat_rotate(q, Vec3(1, 0, 0)), (0.0, 1.0, 0.0))


def test_yaw_180_is_exact() -> None:
    # q = (0,1,0,0): u = (0,1,0), v = (0,0,-1): u x v = (-1,0,0), t = (-2,0,0), w = 0,
    # u x t = (0,0,2) => v + 0 + (0,0,2) = (0,0,1). Exact in floating point.
    assert quat_rotate(Quat(0.0, 1.0, 0.0, 0.0), FORWARD) == Vec3(0.0, 0.0, 1.0)


def test_q_and_minus_q_are_the_same_rotation() -> None:
    q = quat_from_raw(0.1, 0.2, 0.3, 0.9, tolerance=None)
    nq = Quat(-q.x, -q.y, -q.z, -q.w)
    v = Vec3(1.5, -2.0, 0.25)
    assert close(quat_rotate(q, v), (quat_rotate(nq, v).x, quat_rotate(nq, v).y, quat_rotate(nq, v).z))


def test_multiply_two_quarter_turns_make_a_half_turn() -> None:
    q = quat_from_raw(0, S, 0, S)
    h = quat_multiply(q, q)
    assert abs(h.y) == pytest.approx(1.0, abs=1e-12)
    assert close(quat_rotate(h, FORWARD), (0.0, 0.0, 1.0))


def test_multiply_applies_right_operand_first() -> None:
    yaw = quat_from_raw(0, S, 0, S)       # +90 about Y
    pitch = quat_from_raw(S, 0, 0, S)     # +90 about X
    # (yaw * pitch) v == yaw(pitch(v)). pitch(-Z) = +Y; yaw(+Y) = +Y (it is the yaw axis).
    assert close(quat_rotate(quat_multiply(yaw, pitch), FORWARD), (0.0, 1.0, 0.0))
    # (pitch * yaw) v == pitch(yaw(v)). yaw(-Z) = -X; pitch(-X) = -X (the pitch axis).
    assert close(quat_rotate(quat_multiply(pitch, yaw), FORWARD), (-1.0, 0.0, 0.0))


def test_conjugate_is_the_inverse() -> None:
    q = quat_from_raw(0.3, -0.4, 0.5, 0.7, tolerance=None)
    back = quat_multiply(q, quat_conjugate(q))
    assert back.w == pytest.approx(1.0, abs=1e-12)
    assert max(abs(back.x), abs(back.y), abs(back.z)) < 1e-12


def test_axis_angle_matches_the_hand_value() -> None:
    q = quat_from_axis_angle(Vec3(0, 1, 0), math.pi / 2)
    assert (q.x, q.z) == (0.0, 0.0)
    assert q.y == pytest.approx(S, abs=1e-15) and q.w == pytest.approx(S, abs=1e-15)
    with pytest.raises(OpenXrError):
        quat_from_axis_angle(Vec3(0, 0, 0), 1.0)  # zero axis
    with pytest.raises(OpenXrError):
        quat_from_axis_angle(Vec3(0, 1, 0), math.nan)


def test_transform_point_rotates_then_translates() -> None:
    # 180 about Y maps local (0,0,-1) to (0,0,1); then + position (1,2,3) = (1,2,4).
    pose = pose_from_raw((1, 2, 3), (0, 1, 0, 0))
    assert pose_transform_point(pose, Vec3(0, 0, -1)) == Vec3(1.0, 2.0, 4.0)
    # translation-first would give (1,2,3) rotated = (-1,2,-3) + ... so it differs:
    assert pose_transform_point(pose, Vec3(0, 0, 0)) == Vec3(1.0, 2.0, 3.0)


def test_ray_from_pose_origin_and_direction() -> None:
    pose = pose_from_raw((0.5, 1.6, -0.25), (0, S, 0, S))
    ray = ray_from_pose(pose)
    assert ray.origin == Vec3(0.5, 1.6, -0.25)
    assert close(ray.direction, (-1.0, 0.0, 0.0))
    assert norm(ray.direction) == pytest.approx(1.0, abs=1e-12)


def test_custom_forward_axis_is_honoured() -> None:
    # A source that points along +Z instead of -Z (identity pose) gives (0,0,1).
    ray = ray_from_pose(XrPose(Vec3(0, 0, 0), QUAT_IDENTITY), forward=Vec3(0, 0, 2))
    assert ray.direction == Vec3(0.0, 0.0, 1.0)
    with pytest.raises(ValueError):
        ray_from_pose(XrPose(Vec3(0, 0, 0), QUAT_IDENTITY), forward=Vec3(0, 0, 0))


# --- quaternion totality -----------------------------------------------------


@pytest.mark.parametrize(
    "components",
    [
        (0, 0, 0, 0),                      # zero: no orientation
        (math.nan, 0, 0, 1),
        (0, math.inf, 0, 1),
        (0, 0, -math.inf, 1),
        (0, 0, 0, 1.02),                   # norm 1.02: beyond the spec's 1 %
        (0, 0, 0, 0.98),
        (0, 0, 0, 2),
        (True, 0, 0, 1),                   # bool is not a number
        (0, 0, 0, "1"),
        (0, 0, 0, None),
        (0, 0, 0, 10**400),                # int too wide for a float
        (0, 0, 0, -(10**400)),
        (1e308, 1e308, 1e308, 1e308),
    ],
)
def test_strict_quaternion_refuses_bad_input(components: tuple[object, ...]) -> None:
    with pytest.raises(OpenXrError):
        quat_from_raw(*components)  # type: ignore[arg-type]


def test_quaternion_within_the_spec_tolerance_is_renormalised() -> None:
    q = quat_from_raw(0, 0, 0, 1.009)  # 0.9 % off: a conforming runtime may return it
    assert (q.x, q.y, q.z, q.w) == (0.0, 0.0, 0.0, 1.0)
    assert quat_from_raw(0, 0, 0, 0.991).w == 1.0


def test_tolerance_none_normalises_any_nonzero_quaternion() -> None:
    q = quat_from_raw(0, 0, 0, 5, tolerance=None)
    assert q == QUAT_IDENTITY
    big = quat_from_raw(1e308, 0, 0, 1e308, tolerance=None)  # naive squares overflow
    assert big.x == pytest.approx(S) and big.w == pytest.approx(S)
    tiny = quat_from_raw(5e-324, 0, 0, 5e-324, tolerance=None)  # naive squares underflow
    assert tiny.x == pytest.approx(S) and tiny.w == pytest.approx(S)
    for bad in ((0, 0, 0, 0), (math.nan, 0, 0, 1), (0, 0, 0, 10**400)):
        with pytest.raises(OpenXrError):
            quat_from_raw(*bad, tolerance=None)


@pytest.mark.parametrize("tol", [-0.1, 1.0, 2.0, math.nan, math.inf, True, "x"])
def test_bad_tolerance_is_refused(tol: object) -> None:
    with pytest.raises(OpenXrError):
        quat_from_raw(0, 0, 0, 1, tolerance=tol)  # type: ignore[arg-type]


def test_quat_constructor_requires_unit_length() -> None:
    with pytest.raises(OpenXrError):
        Quat(0.0, 0.0, 0.0, 2.0)
    with pytest.raises(OpenXrError):
        Quat(math.nan, 0.0, 0.0, 1.0)


def test_rotating_a_huge_vector_fails_cleanly_or_stays_finite() -> None:
    q = quat_from_raw(0.5, 0.5, 0.5, 0.5)
    try:
        r = quat_rotate(q, Vec3(1e308, 1e308, 1e308))
    except OpenXrError:
        return
    assert math.isfinite(r.x) and math.isfinite(r.y) and math.isfinite(r.z)


# --- location flags ----------------------------------------------------------


def test_flag_bit_values_are_pinned() -> None:
    # Unverified against the spec pages fetched (they list names only); taken from the
    # public header. If a spec diff ever disagrees, this test is where it surfaces.
    assert (OV, PV, OT, PT) == (0x1, 0x2, 0x4, 0x8)


def test_parse_flags_decodes_each_bit_independently() -> None:
    f = parse_location_flags(OV | PT)
    assert (f.orientation_valid, f.position_valid) == (True, False)
    assert (f.orientation_tracked, f.position_tracked) == (False, True)
    assert not f.usable
    assert not f.consistent  # position tracked without position valid
    assert parse_location_flags(0).usable is False
    assert parse_location_flags(OV | PV).usable and parse_location_flags(OV | PV).consistent


def test_unknown_flag_bits_are_ignored() -> None:
    assert parse_location_flags(ALL | (1 << 40)).usable


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", None, -1, 2**64, 10**400, (1,)])
def test_parse_flags_refuses_non_flags(bad: object) -> None:
    with pytest.raises(OpenXrError):
        parse_location_flags(bad)


def test_confidence_is_the_weaker_component() -> None:
    assert location_confidence(parse_location_flags(ALL)) == 1.0
    assert location_confidence(parse_location_flags(OV | PV | OT)) == 0.4   # position inferred
    assert location_confidence(parse_location_flags(OV | PV | PT)) == 0.4   # orientation inferred
    assert location_confidence(parse_location_flags(OV | PV), untracked_confidence=0.25) == 0.25
    assert location_confidence(parse_location_flags(OV)) == 0.0             # unusable
    assert location_confidence(parse_location_flags(OV | PV | PT | (OT & 0))) == 0.4
    for bad in (-0.1, 1.1, math.nan, True, "x"):
        with pytest.raises(OpenXrError):
            location_confidence(parse_location_flags(ALL), untracked_confidence=bad)  # type: ignore[arg-type]


# --- gaze / aim samples ------------------------------------------------------


def test_gaze_sample_maps_pose_to_an_eye_sample() -> None:
    s = gaze_sample(12.5, ALL, (0.0, 1.6, 0.0), (0, S, 0, S), LOCAL)
    assert s is not None
    assert s.source is RaySource.EYE
    assert s.timestamp_s == 12.5
    assert s.confidence == 1.0
    assert s.ray.origin == Vec3(0.0, 1.6, 0.0)
    assert close(s.ray.direction, (-1.0, 0.0, 0.0))


@pytest.mark.parametrize("flags", [0, OV, PV, OT | PT, OV | PT, PV | OT])
def test_gaze_sample_is_none_when_a_field_is_not_valid(flags: int) -> None:
    # The spec forbids reading a field whose VALID bit is clear. Even garbage in the
    # unreadable fields must therefore never be looked at... but the numbers still
    # have to be well-formed to be passed, which keeps the call total.
    assert gaze_sample(1.0, flags, (0, 0, 0), (0, 0, 0, 1), LOCAL) is None


def test_untracked_but_valid_pose_is_usable_with_reduced_confidence() -> None:
    s = gaze_sample(1.0, OV | PV, (0, 0, 0), (0, 0, 0, 1), LOCAL)
    assert s is not None and s.confidence == 0.4


def test_view_space_rays_are_refused() -> None:
    with pytest.raises(OpenXrError, match="head-relative"):
        gaze_sample(1.0, ALL, (0, 0, 0), (0, 0, 0, 1), ReferenceSpace.VIEW)
    with pytest.raises(OpenXrError):
        require_world_space("local")
    assert require_world_space(ReferenceSpace.STAGE) is ReferenceSpace.STAGE


def test_aim_sample_sources_and_forward() -> None:
    c = aim_sample(2.0, ALL, (0, 1, 0), (0, 0, 0, 1), LOCAL)
    h = aim_sample(2.0, ALL, (0, 1, 0), (0, 0, 0, 1), ReferenceSpace.STAGE, source=RaySource.HAND)
    assert c is not None and c.source is RaySource.CONTROLLER
    assert h is not None and h.source is RaySource.HAND
    assert c.ray.direction == Vec3(0.0, 0.0, -1.0)
    for src in (RaySource.EYE, RaySource.HEAD):
        with pytest.raises(OpenXrError):
            aim_sample(2.0, ALL, (0, 1, 0), (0, 0, 0, 1), LOCAL, source=src)
    assert aim_sample(2.0, OV, (0, 1, 0), (0, 0, 0, 1), LOCAL) is None


@pytest.mark.parametrize("t", [-1.0, math.nan, math.inf, 2e9, True, None, "1", 10**400])
def test_bad_timestamps_are_refused(t: object) -> None:
    with pytest.raises(OpenXrError):
        gaze_sample(t, ALL, (0, 0, 0), (0, 0, 0, 1), LOCAL)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "position",
    [(0, 0), (0, 0, 0, 0), "abc", None, 5, (math.nan, 0, 0), (0, math.inf, 0), (0, 0, True),
     (2e6, 0, 0), (0, 0, 10**400), {"x": 0}, [None, None, None]],
)
def test_bad_positions_are_refused(position: object) -> None:
    with pytest.raises(OpenXrError):
        gaze_sample(1.0, ALL, position, (0, 0, 0, 1), LOCAL)  # type: ignore[arg-type]


@pytest.mark.parametrize("orientation", [(0, 0, 0), (0, 0, 0, 0), None, "wxyz", (0, 0, 0, 1, 0), 3])
def test_bad_orientations_are_refused(orientation: object) -> None:
    with pytest.raises(OpenXrError):
        gaze_sample(1.0, ALL, (0, 0, 0), orientation, LOCAL)  # type: ignore[arg-type]


def test_bad_space_is_refused() -> None:
    for bad in (None, "local", 1, ReferenceSpace):
        with pytest.raises(OpenXrError):
            gaze_sample(1.0, ALL, (0, 0, 0), (0, 0, 0, 1), bad)  # type: ignore[arg-type]


def test_pose_from_raw_accepts_vec3_and_validates_bounds() -> None:
    p = pose_from_raw(Vec3(1, 2, 3), [0, 0, 0, 1])
    assert p.position == Vec3(1.0, 2.0, 3.0)
    with pytest.raises(OpenXrError):
        pose_from_raw(Vec3(1e7, 0, 0), (0, 0, 0, 1))


# --- time --------------------------------------------------------------------


def test_xr_time_to_seconds_is_exact_for_nanoseconds() -> None:
    assert xr_time_to_seconds(1_500_000_000) == 1.5
    assert xr_time_to_seconds(1) == 1e-9
    assert xr_time_to_seconds(123_456_789_012) == 123.456789012


@pytest.mark.parametrize(
    "bad", [0, -1, 2**63, 10**400, 1.5, True, None, "5", math.nan, 2_000_000_000_000_000_000]
)
def test_xr_time_refuses_invalid_values(bad: object) -> None:
    # 0 and negatives are invalid XrTime per the spec; the last one is a Unix-epoch-sized
    # value that exceeds the wire layer's device_time cap and must go via XrTimeBase.
    with pytest.raises(OpenXrError):
        xr_time_to_seconds(bad)


def test_choose_gaze_time_prefers_the_sample_time() -> None:
    assert choose_gaze_time(5_000, 9_000) == 5_000
    assert choose_gaze_time(0, 9_000) == 9_000            # 0 = "sample time not available"
    with pytest.raises(OpenXrError):
        choose_gaze_time(0, 0)                             # ... and then the fallback must be valid
    for bad in (-1, True, 1.0, None, 2**63):
        with pytest.raises(OpenXrError):
            choose_gaze_time(bad, 9_000)                   # type: ignore[arg-type]
    with pytest.raises(OpenXrError):
        choose_gaze_time(5_000, -3)


def test_time_base_handles_a_unix_epoch_runtime() -> None:
    t0 = 1_700_000_000_000_000_000                        # 1.7e9 s: too big for device_time_s
    with pytest.raises(OpenXrError):
        xr_time_to_seconds(t0)
    base = XrTimeBase()
    first = base.to_seconds(t0)
    assert first == 1.0                                    # origin = first - 1 s headroom
    assert base.origin_ns == t0 - 1_000_000_000
    assert base.to_seconds(t0 + 500_000_000) == 1.5
    assert base.to_seconds(t0 - 400_000_000) == pytest.approx(0.6)  # slightly earlier: still >= 0
    with pytest.raises(OpenXrError):
        base.to_seconds(t0 - 2_000_000_000)                # earlier than the headroom allows
    assert base.origin_ns == t0 - 1_000_000_000            # a refused value changes nothing
    base.reset()
    assert base.origin_ns is None
    assert base.to_seconds(t0 + 9_000_000_000) == 1.0


def test_time_base_with_a_small_epoch_never_goes_negative() -> None:
    base = XrTimeBase(headroom_s=1.0)
    assert base.to_seconds(250_000_000) == 0.25            # origin clamps to 0
    assert base.origin_ns == 0


def test_time_base_refuses_a_span_beyond_the_wire_cap() -> None:
    base = XrTimeBase(headroom_s=0.0)
    base.to_seconds(1)
    with pytest.raises(OpenXrError):
        base.to_seconds(2 * 10**18)


@pytest.mark.parametrize("h", [-1.0, 4000.0, math.nan, math.inf, True, "1"])
def test_time_base_validates_headroom(h: object) -> None:
    with pytest.raises(OpenXrError):
        XrTimeBase(headroom_s=h)  # type: ignore[arg-type]


def test_gaze_samples_flow_through_the_clock_map() -> None:
    base, clock = XrTimeBase(), ClockMap()
    t_ns = 1_700_000_000_000_000_000
    s = gaze_sample(base.to_seconds(t_ns), ALL, (0, 1.6, 0), (0, 0, 0, 1), LOCAL)
    assert s is not None
    mapped = rebase(s, clock, desktop_now_s=100.0)
    assert mapped.timestamp_s == 100.0                      # first frame anchors the offset
    s2 = gaze_sample(base.to_seconds(t_ns + 11_000_000), ALL, (0, 1.6, 0), (0, 0, 0, 1), LOCAL)
    assert s2 is not None
    assert rebase(s2, clock, desktop_now_s=100.011).timestamp_s == pytest.approx(100.011)


# --- gestures ----------------------------------------------------------------


def test_hold_gesture_has_hysteresis() -> None:
    g = HoldGesture(HoldKind.PINCH, press=0.8, release=0.5)
    evs = [g.update(t, v) for t, v in enumerate([0.0, 0.7, 0.79, 0.8, 0.75, 0.55, 0.51, 0.5, 0.6, 0.9])]
    kinds = [None if e is None else e.kind for e in evs]
    assert kinds == [
        None, None, None, GestureKind.PINCH_START, None, None, None, GestureKind.PINCH_END,
        None, GestureKind.PINCH_START,
    ]
    assert evs[3] is not None and evs[3].confidence == 0.8 and evs[3].timestamp_s == 3.0
    assert evs[7] is not None and evs[7].confidence == 1.0


def test_squeeze_kind_uses_squeeze_events() -> None:
    g = HoldGesture(HoldKind.SQUEEZE)
    a, b = g.update(0.0, 1.0), g.update(0.1, 0.0)
    assert a is not None and a.kind is GestureKind.SQUEEZE_START
    assert b is not None and b.kind is GestureKind.SQUEEZE_END


def test_inactive_action_releases_the_hold() -> None:
    g = HoldGesture()
    assert g.update(0.0, 1.0) is not None and g.pressed
    end = g.update(0.1, 1.0, active=False)               # source vanished: never stay stuck on
    assert end is not None and end.kind is GestureKind.PINCH_END and not g.pressed
    assert g.update(0.2, 0.0, active=False) is None


def test_values_outside_unit_range_are_clamped() -> None:
    g = HoldGesture()
    ev = g.update(0.0, 7.5)
    assert ev is not None and ev.confidence == 1.0
    end = g.update(0.1, -3.0)
    assert end is not None and end.kind is GestureKind.PINCH_END


def test_boolean_click_drives_a_hold() -> None:
    g = HoldGesture(HoldKind.SQUEEZE)
    start, end = g.update_bool(0.0, True), g.update_bool(0.5, False)
    assert start is not None and start.kind is GestureKind.SQUEEZE_START
    assert end is not None and end.kind is GestureKind.SQUEEZE_END
    assert g.update_bool(0.6, 1) is not None                # a raw XrBool32
    for bad in (2, -1, 1.0, None, "true"):
        with pytest.raises(OpenXrError):
            g.update_bool(0.7, bad)


def test_release_forces_the_end_once() -> None:
    g = HoldGesture()
    assert g.release(0.0) is None
    g.update(0.1, 1.0)
    ev = g.release(0.2)
    assert ev is not None and ev.kind is GestureKind.PINCH_END and not g.pressed
    assert g.release(0.3) is None


def test_bad_hold_input_leaves_state_untouched() -> None:
    g = HoldGesture()
    g.update(1.0, 1.0)
    for t, v in ((0.5, 0.0), (2.0, math.nan), (2.0, math.inf), (2.0, True), (2.0, None),
                 (2.0, "1"), (2.0, 10**400), (math.nan, 0.0), (-1.0, 0.0), (True, 0.0)):
        with pytest.raises(OpenXrError):
            g.update(t, v)  # type: ignore[arg-type]
    with pytest.raises(OpenXrError):
        g.update(2.0, 0.0, active="yes")  # type: ignore[arg-type]
    assert g.pressed                                        # none of that changed anything
    ev = g.update(2.0, 0.0)
    assert ev is not None and ev.kind is GestureKind.PINCH_END


@pytest.mark.parametrize(
    ("press", "release"),
    [(0.5, 0.5), (0.4, 0.6), (1.5, 0.5), (0.8, -0.1), (math.nan, 0.5), (0.8, math.nan),
     (True, 0.5), (0.8, "x")],
)
def test_bad_thresholds_are_refused(press: object, release: object) -> None:
    with pytest.raises(OpenXrError):
        HoldGesture(press=press, release=release)  # type: ignore[arg-type]
    with pytest.raises(OpenXrError):
        HoldGesture("pinch")  # type: ignore[arg-type]


def test_click_tap_is_one_event_per_press() -> None:
    c = ClickTap()
    out = [c.update(t, s) for t, s in enumerate([False, True, True, True, False, True, False])]
    kinds = [None if e is None else e.kind for e in out]
    assert kinds == [None, GestureKind.TAP, None, None, None, GestureKind.TAP, None]
    # an inactive source is released: re-activating a held button taps again.
    c2 = ClickTap()
    assert c2.update(0.0, True) is not None
    assert c2.update(0.1, True, active=False) is None
    assert c2.update(0.2, True) is not None


def test_click_tap_refuses_bad_input() -> None:
    c = ClickTap()
    c.update(1.0, False)
    for t, s in ((0.5, True), (2.0, 2), (2.0, 1.0), (2.0, None), (math.nan, True)):
        with pytest.raises(OpenXrError):
            c.update(t, s)  # type: ignore[arg-type]
    with pytest.raises(OpenXrError):
        c.update(2.0, True, active=None)  # type: ignore[arg-type]
    assert c.update(2.0, True) is not None                  # state survived


# --- hand tracking -----------------------------------------------------------

J_OK = ALL & ~OT & ~OV | PT          # position valid + tracked (orientation not needed)


def _hand(
    *, wrist: tuple[float, float, float] = (0.0, 0.0, 0.2),
    thumb: tuple[float, float, float] = (-0.01, 0.0, 0.0),
    index: tuple[float, float, float] = (0.01, 0.0, 0.0),
    radius: float = 0.005, flags: int = PV | PT, overrides: dict[int, tuple[int, object, object]] | None = None,
) -> list[tuple[int, object, object]]:
    joints: list[tuple[int, object, object]] = [(flags, (0.0, 0.0, 0.1), radius)] * 26
    joints[HandJoint.WRIST] = (flags, wrist, radius)
    joints[HandJoint.THUMB_TIP] = (flags, thumb, radius)
    joints[HandJoint.INDEX_TIP] = (flags, index, radius)
    joints = list(joints)
    for k, v in (overrides or {}).items():
        joints[k] = v
    return joints


def test_hand_joint_enum_matches_the_spec_table() -> None:
    assert len(HandJoint) == 26
    assert [int(j) for j in HandJoint] == list(range(26))
    assert (HandJoint.PALM, HandJoint.WRIST, HandJoint.THUMB_TIP, HandJoint.INDEX_TIP) == (0, 1, 5, 10)
    assert (HandJoint.MIDDLE_TIP, HandJoint.RING_TIP, HandJoint.LITTLE_TIP) == (15, 20, 25)


def test_pinch_strength_hand_computed() -> None:
    # Tips 0.05 m apart (centres), radii 0.005 each: surface gap = 0.05 - 0.01 = 0.04.
    # strength = (open - gap) / (open - closed) = (0.06 - 0.04) / (0.06 - 0.005) = 0.02/0.055.
    hand = hand_joints_from_raw(LOCAL, _hand(thumb=(-0.025, 0, 0), index=(0.025, 0, 0)))
    assert pinch_strength(hand) == pytest.approx(0.02 / 0.055)


def test_pinch_strength_saturates() -> None:
    touching = hand_joints_from_raw(LOCAL, _hand(thumb=(-0.005, 0, 0), index=(0.005, 0, 0)))
    assert pinch_strength(touching) == 1.0                  # gap 0 <= closed
    far = hand_joints_from_raw(LOCAL, _hand(thumb=(-0.2, 0, 0), index=(0.2, 0, 0)))
    assert pinch_strength(far) == 0.0
    overlapping = hand_joints_from_raw(LOCAL, _hand(thumb=(0, 0, 0), index=(0, 0, 0)))
    assert pinch_strength(overlapping) == 1.0               # gap floors at 0, never negative


def test_pinch_ray_points_from_wrist_through_the_pinch_point() -> None:
    # Wrist at z = +0.2, tips straddling the origin: midpoint (0,0,0). The reach
    # direction (0,0,0) - (0,0,0.2) = (0,0,-0.2) -> unit (0,0,-1).
    hand = hand_joints_from_raw(LOCAL, _hand())
    p = hand_pinch_sample(3.0, hand)
    assert p is not None
    assert p.sample.source is RaySource.HAND and p.sample.timestamp_s == 3.0
    assert p.sample.ray.origin == Vec3(0.0, 0.0, 0.0)
    assert close(p.sample.ray.direction, (0.0, 0.0, -1.0))
    assert p.sample.confidence == 1.0
    assert p.strength == pytest.approx(pinch_strength(hand))


def test_pinch_ray_with_an_origin_hint() -> None:
    # Shoulder estimate at (0, 0.3, 0.4); pinch point (0,0,0): direction (0,-0.3,-0.4)/0.5.
    hand = hand_joints_from_raw(LOCAL, _hand())
    p = hand_pinch_sample(1.0, hand, origin_hint=Vec3(0.0, 0.3, 0.4))
    assert p is not None
    assert close(p.sample.ray.direction, (0.0, -0.6, -0.8))
    # With a hint the wrist is not needed:
    no_wrist = hand_joints_from_raw(LOCAL, _hand(overrides={int(HandJoint.WRIST): (0, (0, 0, 0), 0.0)}))
    assert hand_pinch_sample(1.0, no_wrist) is None
    assert hand_pinch_sample(1.0, no_wrist, origin_hint=Vec3(0.0, 0.3, 0.4)) is not None


def test_invalid_joints_become_none_and_are_never_read() -> None:
    # Position-invalid entries may carry garbage: it must not be parsed.
    garbage = (OV, "not a position", "not a radius")
    h = hand_joints_from_raw(LOCAL, _hand(overrides={int(HandJoint.THUMB_TIP): garbage}))
    assert h.get(HandJoint.THUMB_TIP) is None
    assert pinch_strength(h) is None
    assert hand_pinch_sample(1.0, h) is None
    h2 = hand_joints_from_raw(LOCAL, _hand(overrides={int(HandJoint.INDEX_TIP): (0, None, None)}))
    assert hand_pinch_sample(1.0, h2) is None


def test_untracked_joint_lowers_pinch_confidence() -> None:
    h = hand_joints_from_raw(LOCAL, _hand(overrides={int(HandJoint.WRIST): (PV, (0.0, 0.0, 0.2), 0.01)}))
    p = hand_pinch_sample(1.0, h)
    assert p is not None and p.sample.confidence == 0.4
    p2 = hand_pinch_sample(1.0, h, untracked_confidence=0.7)
    assert p2 is not None and p2.sample.confidence == 0.7


def test_degenerate_pinch_direction_is_none() -> None:
    # Wrist exactly at the pinch point: no direction.
    h = hand_joints_from_raw(LOCAL, _hand(wrist=(0.0, 0.0, 0.0)))
    assert hand_pinch_sample(1.0, h) is None


def test_hand_joints_reject_malformed_arrays() -> None:
    good = _hand()
    for bad in (None, good[:25], good + good[:1], "x" * 26, {}, 26, [None] * 26, [(PV,)] * 26):
        with pytest.raises(OpenXrError):
            hand_joints_from_raw(LOCAL, bad)
    for radius in (0.0, -0.1, math.nan, math.inf, 2.0, True, None, 10**400):
        with pytest.raises(OpenXrError):
            hand_joints_from_raw(LOCAL, _hand(radius=radius))  # type: ignore[arg-type]
    with pytest.raises(OpenXrError):
        hand_joints_from_raw(LOCAL, _hand(thumb=(math.nan, 0, 0)))
    with pytest.raises(OpenXrError):
        hand_joints_from_raw(ReferenceSpace.VIEW, good)
    with pytest.raises(OpenXrError):
        hand_joints_from_raw(LOCAL, [(True, (0, 0, 0), 0.01)] * 26)  # bool flags
    with pytest.raises(OpenXrError):
        HandJoints(LOCAL, ())


def test_pinch_parameters_are_validated() -> None:
    h = hand_joints_from_raw(LOCAL, _hand())
    for closed, opened in ((0.06, 0.06), (0.07, 0.06), (-0.1, 0.06), (math.nan, 0.06), (0.0, math.inf),
                           (True, 0.06)):
        with pytest.raises(OpenXrError):
            pinch_strength(h, closed_gap_m=closed, open_gap_m=opened)  # type: ignore[arg-type]
    with pytest.raises(OpenXrError):
        hand_pinch_sample(math.nan, h)  # type: ignore[arg-type]
    with pytest.raises(OpenXrError):
        hand_pinch_sample(1.0, h, untracked_confidence=2.0)
    with pytest.raises(OpenXrError):
        hand_pinch_sample(1.0, h, origin_hint=(0, 0, math.nan))  # type: ignore[arg-type]


def test_pinch_strength_feeds_a_hold_gesture() -> None:
    g = HoldGesture(HoldKind.PINCH)
    kinds = []
    for t, gap in enumerate((0.07, 0.05, 0.02, 0.01, 0.03, 0.045, 0.07)):
        # centres gap + 2 radii apart, so the surface gap is exactly `gap`
        half = (gap + 0.01) / 2
        hand = hand_joints_from_raw(LOCAL, _hand(thumb=(-half, 0, 0), index=(half, 0, 0)))
        s = pinch_strength(hand)
        assert s is not None
        ev = g.update(float(t), s)
        kinds.append(None if ev is None else ev.kind)
    # strengths (open 0.06, closed 0.005): 0, .18, .73, .91 (start), .55, .27 (end), 0
    assert kinds == [None, None, None, GestureKind.PINCH_START, None, GestureKind.PINCH_END, None]


# --- properties --------------------------------------------------------------

_FAST = settings(max_examples=150, deadline=None)
_coord = st.floats(min_value=-1e3, max_value=1e3, allow_nan=False, allow_infinity=False)
_comp = st.floats(min_value=-1e300, max_value=1e300, allow_nan=False, allow_infinity=False)
_nonzero_quat = st.tuples(_comp, _comp, _comp, _comp).filter(lambda t: any(c != 0.0 for c in t))


@_FAST
@given(_nonzero_quat)
def test_normalised_quaternions_are_unit_for_any_scale(c: tuple[float, float, float, float]) -> None:
    q = quat_from_raw(*c, tolerance=None)
    assert math.hypot(q.x, q.y, q.z, q.w) == pytest.approx(1.0, abs=1e-12)


@_FAST
@given(_nonzero_quat, _coord, _coord, _coord)
def test_rotation_preserves_length_and_inverts(
    c: tuple[float, float, float, float], x: float, y: float, z: float
) -> None:
    q = quat_from_raw(*c, tolerance=None)
    v = Vec3(x, y, z)
    r = quat_rotate(q, v)
    assert norm(r) == pytest.approx(norm(v), rel=1e-9, abs=1e-9)
    back = quat_rotate(quat_conjugate(q), r)
    assert (back.x, back.y, back.z) == pytest.approx((x, y, z), rel=1e-9, abs=1e-8)


@_FAST
@given(_nonzero_quat, _nonzero_quat, _coord, _coord, _coord)
def test_multiply_composes_rotations(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float],
    x: float, y: float, z: float,
) -> None:
    qa, qb = quat_from_raw(*a, tolerance=None), quat_from_raw(*b, tolerance=None)
    v = Vec3(x, y, z)
    lhs = quat_rotate(quat_multiply(qa, qb), v)
    rhs = quat_rotate(qa, quat_rotate(qb, v))
    assert (lhs.x, lhs.y, lhs.z) == pytest.approx((rhs.x, rhs.y, rhs.z), rel=1e-8, abs=1e-8)


@_FAST
@given(_nonzero_quat)
def test_forward_matches_the_third_column_of_the_rotation_matrix(
    c: tuple[float, float, float, float]
) -> None:
    # Independent oracle: the rotation matrix of a unit quaternion; -Z forward is minus its
    # third column (R[0][2], R[1][2], R[2][2]).
    q = quat_from_raw(*c, tolerance=None)
    x, y, z, w = q.x, q.y, q.z, q.w
    col3 = (2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y))
    f = pose_forward(XrPose(Vec3(0, 0, 0), q))
    assert (f.x, f.y, f.z) == pytest.approx((-col3[0], -col3[1], -col3[2]), abs=1e-9)
    assert norm(f) == pytest.approx(1.0, abs=1e-12)


@_FAST
@given(_nonzero_quat, st.floats(min_value=0.9905, max_value=1.0095))
def test_scaled_unit_quaternion_within_spec_tolerance_is_accepted(
    c: tuple[float, float, float, float], k: float
) -> None:
    unit = quat_from_raw(*c, tolerance=None)
    q = quat_from_raw(unit.x * k, unit.y * k, unit.z * k, unit.w * k)
    assert (q.x, q.y, q.z, q.w) == pytest.approx((unit.x, unit.y, unit.z, unit.w), abs=1e-12)


@_FAST
@given(_nonzero_quat, _coord, _coord, _coord)
def test_gaze_ray_direction_is_always_unit(
    c: tuple[float, float, float, float], x: float, y: float, z: float
) -> None:
    s = gaze_sample(1.0, ALL, (x, y, z), tuple(quat_from_raw(*c, tolerance=None).__dict__.values()), LOCAL)
    assert s is not None
    d = s.ray.direction
    assert dot(d, d) == pytest.approx(1.0, abs=1e-9)


_hostile = st.one_of(
    st.none(), st.booleans(), st.text(max_size=5), st.binary(max_size=3),
    st.integers(), st.integers(min_value=10**30, max_value=10**500), st.floats(allow_nan=True, allow_infinity=True),
    st.lists(st.one_of(st.integers(), st.floats(), st.none(), st.text(max_size=3)), max_size=6),
    st.tuples(st.floats(), st.floats(), st.floats()),
    st.tuples(st.floats(), st.floats(), st.floats(), st.floats()),
    st.dictionaries(st.text(max_size=3), st.integers(), max_size=2),
    st.just(object()),
)


@_FAST
@given(_hostile, _hostile, _hostile, _hostile)
def test_gaze_and_aim_raise_only_openxr_error(t: object, f: object, p: object, o: object) -> None:
    for fn in (gaze_sample, aim_sample):
        try:
            fn(t, f, p, o, LOCAL)  # type: ignore[operator]
        except OpenXrError:
            pass


@_FAST
@given(_hostile)
def test_every_scalar_entry_point_raises_only_openxr_error(x: object) -> None:
    calls = (
        lambda: quat_from_raw(x, 0, 0, 1),  # type: ignore[arg-type]
        lambda: quat_from_raw(0, 0, 0, 1, tolerance=x),  # type: ignore[arg-type]
        lambda: parse_location_flags(x),
        lambda: xr_time_to_seconds(x),
        lambda: choose_gaze_time(x, x),
        lambda: XrTimeBase().to_seconds(x),
        lambda: XrTimeBase(headroom_s=x),  # type: ignore[arg-type]
        lambda: HoldGesture().update(x, 0.5),
        lambda: HoldGesture().update(0.0, x),
        lambda: HoldGesture().update_bool(0.0, x),
        lambda: ClickTap().update(0.0, x),
        lambda: ClickTap().update(x, True),
        lambda: pose_from_raw(x, (0, 0, 0, 1)),
        lambda: pose_from_raw((0, 0, 0), x),
        lambda: hand_joints_from_raw(LOCAL, x),
        lambda: require_world_space(x),
    )
    for call in calls:
        try:
            call()
        except OpenXrError:
            pass


@_FAST
@given(st.lists(st.floats(min_value=-0.5, max_value=1.5, allow_nan=False), min_size=1, max_size=60))
def test_hold_gesture_events_alternate_and_match_the_hysteresis_oracle(values: list[float]) -> None:
    g = HoldGesture(HoldKind.PINCH, press=0.8, release=0.5)
    pressed = False                      # independent oracle for the same state machine
    last: GestureKind | None = None
    for i, raw in enumerate(values):
        v = min(1.0, max(0.0, raw))
        expected: GestureKind | None = None
        if not pressed and v >= 0.8:
            pressed, expected = True, GestureKind.PINCH_START
        elif pressed and v <= 0.5:
            pressed, expected = False, GestureKind.PINCH_END
        ev = g.update(float(i), raw)
        assert (None if ev is None else ev.kind) == expected
        if ev is not None:
            assert ev.kind is not last      # never two STARTs or two ENDs in a row
            last = ev.kind
        assert g.pressed == pressed


@_FAST
@given(st.lists(st.integers(min_value=1, max_value=2**62), min_size=1, max_size=20))
def test_time_base_is_exact_and_nonnegative(times: list[int]) -> None:
    base = XrTimeBase(headroom_s=0.0)
    origin = times[0]
    for t in times:
        if t < origin:
            with pytest.raises(OpenXrError):
                base.to_seconds(t)
            continue
        try:
            s = base.to_seconds(t)
        except OpenXrError:
            assert (t - origin) / 10**9 > 1e9   # only the wire cap may refuse a later time
            continue
        assert s == (t - origin) / 10**9 and s >= 0.0


@_FAST
@given(
    st.floats(min_value=0.0, max_value=0.3),
    st.floats(min_value=0.0, max_value=0.3),
)
def test_pinch_strength_is_bounded_and_monotone_in_the_gap(a: float, b: float) -> None:
    lo, hi = sorted((a, b))
    h_lo = hand_joints_from_raw(LOCAL, _hand(thumb=(-lo / 2, 0, 0), index=(lo / 2, 0, 0)))
    h_hi = hand_joints_from_raw(LOCAL, _hand(thumb=(-hi / 2, 0, 0), index=(hi / 2, 0, 0)))
    s_lo, s_hi = pinch_strength(h_lo), pinch_strength(h_hi)
    assert s_lo is not None and s_hi is not None
    assert 0.0 <= s_hi <= s_lo <= 1.0   # farther apart never pinches harder


# --- source hygiene ----------------------------------------------------------

_OPENXR_SRC = Path(openxr.__file__).resolve()
_ALLOWED_ROOTS = {"__future__", "math", "dataclasses", "enum", "yazses"}
_BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "print", "input"}


def test_openxr_module_imports_only_stdlib_math_and_the_xr_package() -> None:
    tree = ast.parse(_OPENXR_SRC.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module
            roots.add(node.module.split(".")[0])
            if node.module.startswith("yazses"):
                assert node.module.startswith("yazses.xr."), node.module  # nothing outside xr
    assert roots <= _ALLOWED_ROOTS, roots - _ALLOWED_ROOTS


def test_openxr_module_opens_no_network_file_or_process_path() -> None:
    tree = ast.parse(_OPENXR_SRC.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & _BANNED_NAMES, names & _BANNED_NAMES
    text = _OPENXR_SRC.read_text(encoding="utf-8")
    for word in ("import socket", "import urllib", "import http", "import subprocess", "import requests",
                 "import openxr", "import numpy", "import xr "):
        assert word not in text, word


def test_openxr_module_reads_no_clock() -> None:
    tree = ast.parse(_OPENXR_SRC.read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not attrs & {"time", "monotonic", "perf_counter", "now", "sleep", "utcnow"}


def test_every_public_name_is_exported_and_resolves() -> None:
    for name in openxr.__all__:
        assert hasattr(openxr, name), name
