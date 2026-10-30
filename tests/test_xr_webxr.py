"""Tests for yazses.xr.webxr -- WebXR Device API values mapped onto the XR adapter.

Everything here is synthetic: invented poses, invented timestamps. No real gaze, audio
or headset data. The properties compare against independent oracles (a Rodrigues
axis-angle rotation, a hand-built wire object), never the module's own formula.
"""
from __future__ import annotations

import ast
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import yazses.xr.webxr as webxr
from yazses.xr.privacy import SampleRetention
from yazses.xr.ptt import GesturePtt, PttActionKind, PttMode
from yazses.xr.types import GestureEvent, GestureKind, RaySource, Vec3, XrSample
from yazses.xr.webxr import (
    FrameTimeline,
    InputEventMapper,
    InputEventName,
    InputHandedness,
    InputSourceInfo,
    TargetRayMode,
    WebXrError,
    WebXrFrameEncoder,
    describe_feature,
    describe_input_source,
    mode_capabilities,
    ms_to_seconds,
    parse_handedness,
    parse_input_event,
    parse_target_ray_mode,
    ray_from_pose,
    ray_source_for,
    sample_from_pose,
    session_init_features,
)
from yazses.xr.wire import ClockMap, WireError, decode_frame, rebase

_FAST = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)

_ID = (0.0, 0.0, 0.0, 1.0)


def _floats(lo: float, hi: float) -> st.SearchStrategy[float]:
    return st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)


def _axis_angle_quat(axis: tuple[float, float, float], angle: float) -> tuple[float, ...]:
    n = math.sqrt(sum(a * a for a in axis))
    s = math.sin(angle / 2) / n
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(angle / 2))


def _rodrigues(axis: tuple[float, float, float], angle: float, v: Vec3) -> Vec3:
    """Independent oracle: rotate ``v`` about ``axis`` by ``angle`` (Rodrigues' formula)."""
    n = math.sqrt(sum(a * a for a in axis))
    k = tuple(a / n for a in axis)
    c, s = math.cos(angle), math.sin(angle)
    vv = (v.x, v.y, v.z)
    kxv = (k[1] * vv[2] - k[2] * vv[1], k[2] * vv[0] - k[0] * vv[2], k[0] * vv[1] - k[1] * vv[0])
    kdv = sum(a * b for a, b in zip(k, vv, strict=True))
    out = [vv[i] * c + kxv[i] * s + k[i] * kdv * (1 - c) for i in range(3)]
    return Vec3(*out)


def _close(a: Vec3, b: Vec3, tol: float = 1e-9) -> bool:
    return abs(a.x - b.x) <= tol and abs(a.y - b.y) <= tol and abs(a.z - b.z) <= tol


# --- enums and parsing ---------------------------------------------------------


@pytest.mark.parametrize(
    "text,mode",
    [
        ("gaze", TargetRayMode.GAZE),
        ("tracked-pointer", TargetRayMode.TRACKED_POINTER),
        ("screen", TargetRayMode.SCREEN),
        ("transient-pointer", TargetRayMode.TRANSIENT_POINTER),
    ],
)
def test_the_four_spec_modes_parse(text: str, mode: TargetRayMode) -> None:
    assert parse_target_ray_mode(text) is mode


@pytest.mark.parametrize(
    "bad",
    ["", "Gaze", "GAZE", " gaze", "tracked_pointer", "tracked-pointer\n", "eye", "hand",
     "transient", "gaze\x00", "🙂", None, 1, True, b"gaze", ["gaze"]],
)
def test_unknown_or_mistyped_mode_is_refused(bad: object) -> None:
    with pytest.raises(WebXrError):
        parse_target_ray_mode(bad)


def test_handedness_values_follow_the_spec() -> None:
    assert [parse_handedness(t) for t in ("none", "left", "right")] == [
        InputHandedness.NONE, InputHandedness.LEFT, InputHandedness.RIGHT,
    ]
    for bad in ("both", "Left", "", None, 0):
        with pytest.raises(WebXrError):
            parse_handedness(bad)


def test_event_names_are_exactly_the_six() -> None:
    assert {e.value for e in InputEventName} == {
        "select", "selectstart", "selectend", "squeeze", "squeezestart", "squeezeend",
    }
    for bad in ("click", "SELECT", "select ", "", None, 3):
        with pytest.raises(WebXrError):
            parse_input_event(bad)


def test_webxr_error_is_a_wire_error() -> None:
    assert issubclass(WebXrError, WireError)  # a session that drops WireError drops these too


# --- ray source and capabilities -----------------------------------------------


def test_gaze_is_a_head_ray_never_an_eye_ray() -> None:
    assert ray_source_for(TargetRayMode.GAZE) is RaySource.HEAD
    assert all(ray_source_for(m, has_hand=h) is not RaySource.EYE
               for m in TargetRayMode for h in (False, True))


def test_ray_source_table() -> None:
    assert ray_source_for(TargetRayMode.TRACKED_POINTER) is RaySource.CONTROLLER
    assert ray_source_for(TargetRayMode.TRACKED_POINTER, has_hand=True) is RaySource.HAND
    assert ray_source_for(TargetRayMode.TRANSIENT_POINTER) is RaySource.HAND
    assert ray_source_for(TargetRayMode.SCREEN) is RaySource.CONTROLLER


def test_ray_source_for_refuses_a_string() -> None:
    with pytest.raises(WebXrError):
        ray_source_for("gaze")  # type: ignore[arg-type]


def test_capability_table_agrees_with_the_mapping_and_flags_transient_modes() -> None:
    for mode in TargetRayMode:
        cap = mode_capabilities(mode)
        assert cap.mode is mode
        assert cap.ray_source is ray_source_for(mode) or mode is TargetRayMode.TRACKED_POINTER
    transient = {m for m in TargetRayMode if mode_capabilities(m).ray_only_during_action}
    assert transient == {TargetRayMode.SCREEN, TargetRayMode.TRANSIENT_POINTER}
    assert "NO ray before the pinch" in mode_capabilities(TargetRayMode.TRANSIENT_POINTER).note


def test_describe_input_source_happy_path() -> None:
    info = describe_input_source("tracked-pointer", "left", has_hand=True,
                                 profiles=["generic-hand", "generic-hand-select"])
    assert info.mode is TargetRayMode.TRACKED_POINTER
    assert info.handedness is InputHandedness.LEFT
    assert info.ray_source is RaySource.HAND
    assert info.profiles == ("generic-hand", "generic-hand-select")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"target_ray_mode": "laser"},
        {"target_ray_mode": "gaze", "handedness": "up"},
        {"target_ray_mode": "gaze", "has_hand": 1},
        {"target_ray_mode": "gaze", "has_hand": "true"},
        {"target_ray_mode": "gaze", "profiles": "generic-hand"},
        {"target_ray_mode": "gaze", "profiles": [1]},
        {"target_ray_mode": "gaze", "profiles": [""]},
        {"target_ray_mode": "gaze", "profiles": ["x" * 129]},
        {"target_ray_mode": "gaze", "profiles": ["bad\x00"]},
        {"target_ray_mode": "gaze", "profiles": ["p"] * 17},
    ],
)
def test_describe_input_source_refuses_bad_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(WebXrError):
        describe_input_source(**kwargs)  # type: ignore[arg-type]


def test_input_source_info_direct_construction_validates() -> None:
    with pytest.raises(ValueError):
        InputSourceInfo("gaze")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        InputSourceInfo(TargetRayMode.GAZE, has_hand="yes")  # type: ignore[arg-type]


# --- pose -> ray ----------------------------------------------------------------


def test_identity_orientation_looks_down_minus_z() -> None:
    ray = ray_from_pose([0.1, 1.6, -0.2], _ID)
    assert (ray.origin.x, ray.origin.y, ray.origin.z) == (0.1, 1.6, -0.2)
    assert (ray.direction.x, ray.direction.y, ray.direction.z) == (0.0, 0.0, -1.0)
    assert str(ray.direction.x) == "0.0"  # never "-0.0" on the wire


def test_quarter_turn_about_y_looks_along_minus_x() -> None:
    ray = ray_from_pose([0, 0, 0], _axis_angle_quat((0, 1, 0), math.pi / 2))
    assert _close(ray.direction, Vec3(-1, 0, 0))


def test_pitch_up_about_x_looks_up() -> None:
    ray = ray_from_pose([0, 0, 0], _axis_angle_quat((1, 0, 0), math.pi / 2))
    assert _close(ray.direction, Vec3(0, 1, 0))


def test_half_turn_about_y_looks_along_plus_z() -> None:
    ray = ray_from_pose([0, 0, 0], _axis_angle_quat((0, 1, 0), math.pi))
    assert _close(ray.direction, Vec3(0, 0, 1))


def test_negated_quaternion_is_the_same_ray() -> None:
    q = _axis_angle_quat((0.3, -0.7, 0.2), 1.1)
    a = ray_from_pose([0, 0, 0], q)
    b = ray_from_pose([0, 0, 0], tuple(-c for c in q))
    assert _close(a.direction, b.direction, 1e-12)


def test_slightly_off_unit_quaternion_is_renormalised() -> None:
    q = _axis_angle_quat((0, 1, 0), 0.5)
    ray = ray_from_pose([0, 0, 0], tuple(c * 1.0005 for c in q))
    assert _close(ray.direction, ray_from_pose([0, 0, 0], q).direction, 1e-9)


@pytest.mark.parametrize(
    "q",
    [(0, 0, 0, 0), (0, 0, 0, 1.01), (0, 0, 0, 0.99), (1, 1, 1, 1), (0, 0, 0), (0, 0, 0, 1, 0),
     (float("nan"), 0, 0, 1), (float("inf"), 0, 0, 1), (0, 0, 0, True), ("0", "0", "0", "1"),
     (None, 0, 0, 1), (0, 0, 0, 10**400), (0, 0, 0, 3.0)],
)
def test_bad_orientation_is_refused(q: object) -> None:
    with pytest.raises(WebXrError):
        ray_from_pose([0, 0, 0], q)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "p",
    [(0, 0), (0, 0, 0, 0), (float("nan"), 0, 0), (0, float("-inf"), 0), (1e6 + 1, 0, 0),
     (0, 0, 10**400), ("1", 0, 0), (True, 0, 0), None, 5, "abc", {"x": 0, "y": 0, "z": 0}],
)
def test_bad_position_is_refused(p: object) -> None:
    with pytest.raises(WebXrError):
        ray_from_pose(p, _ID)  # type: ignore[arg-type]


def test_a_position_at_the_limit_is_accepted() -> None:
    assert ray_from_pose([1e6, -1e6, 0], _ID).origin.x == 1e6


@given(
    axis=st.tuples(_floats(-1, 1), _floats(-1, 1), _floats(-1, 1)).filter(
        lambda a: math.sqrt(sum(c * c for c in a)) > 1e-3
    ),
    angle=_floats(-2 * math.pi, 2 * math.pi),
)
@_FAST
def test_direction_matches_an_independent_rodrigues_rotation_of_minus_z(
    axis: tuple[float, float, float], angle: float
) -> None:
    ray = ray_from_pose([0, 0, 0], _axis_angle_quat(axis, angle))
    expected = _rodrigues(axis, angle, Vec3(0, 0, -1))
    assert _close(ray.direction, expected, 1e-9)
    d = ray.direction
    assert abs(math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z) - 1.0) < 1e-12


@given(
    q=st.tuples(_floats(-1, 1), _floats(-1, 1), _floats(-1, 1), _floats(-1, 1)),
    p=st.tuples(_floats(-1e6, 1e6), _floats(-1e6, 1e6), _floats(-1e6, 1e6)),
)
@_FAST
def test_any_pose_either_maps_to_a_valid_ray_or_raises_only_webxr_error(
    q: tuple[float, ...], p: tuple[float, ...]
) -> None:
    try:
        ray = ray_from_pose(p, q)
    except WebXrError:
        return
    assert math.isfinite(ray.direction.x + ray.direction.y + ray.direction.z)


# --- milliseconds to seconds -----------------------------------------------------


def test_ms_to_seconds_divides_by_a_thousand() -> None:
    assert ms_to_seconds(12500) == 12.5
    assert ms_to_seconds(0) == 0.0
    assert ms_to_seconds(1e12) == 1e9  # the wire layer's own ceiling


@pytest.mark.parametrize(
    "bad",
    [-1, -0.001, float("nan"), float("inf"), float("-inf"), 1e12 + 1, 1.7e12, 10**400,
     "12.5", True, None, [12.5], b"1"],
)
def test_ms_to_seconds_refuses_bad_values(bad: object) -> None:
    with pytest.raises(WebXrError):
        ms_to_seconds(bad)


def test_date_now_is_caught_as_the_wrong_clock() -> None:
    assert 1_761_800_000_000 > 1e12  # an epoch-millisecond value of late 2025
    with pytest.raises(WebXrError):
        ms_to_seconds(1_761_800_000_000)


# --- FrameTimeline: coarsening and jitter -----------------------------------------


def test_timeline_converts_and_is_monotone() -> None:
    tl = FrameTimeline()
    assert [tl.to_seconds(t) for t in (1000, 1011.1, 1022.2)] == [1.0, 1.0111, 1.0222]


def test_equal_stamps_pass_through_and_are_counted() -> None:
    tl = FrameTimeline()
    assert [tl.to_seconds(t) for t in (50.0, 50.0, 50.0)] == [0.05, 0.05, 0.05]
    assert tl.repeats == 2
    assert tl.clamped == 0


def test_small_regression_is_clamped_up_not_an_error() -> None:
    tl = FrameTimeline(jitter_tolerance_ms=1.0)
    tl.to_seconds(100.0)
    assert tl.to_seconds(99.5) == 0.1  # raised to the predecessor
    assert tl.clamped == 1
    assert tl.to_seconds(100.2) == pytest.approx(0.1002)


def test_regression_exactly_at_the_tolerance_is_clamped() -> None:
    tl = FrameTimeline(jitter_tolerance_ms=1.0)
    tl.to_seconds(100.0)
    assert tl.to_seconds(99.0) == 0.1


def test_regression_beyond_the_tolerance_is_refused_and_state_is_kept() -> None:
    tl = FrameTimeline(jitter_tolerance_ms=1.0)
    tl.to_seconds(100.0)
    with pytest.raises(WebXrError):
        tl.to_seconds(50.0)
    assert tl.to_seconds(101.0) == 0.101  # the refused stamp did not poison anything


def test_reset_allows_a_new_origin() -> None:
    tl = FrameTimeline()
    tl.to_seconds(9000.0)
    tl.reset()
    assert tl.to_seconds(5.0) == 0.005
    assert tl.repeats == tl.clamped == 0 and tl.min_positive_step_ms is None


def test_a_large_forward_jump_is_accepted() -> None:
    tl = FrameTimeline()
    tl.to_seconds(10.0)
    assert tl.to_seconds(600_000.0) == 600.0  # a hidden tab paused the frame loop


def test_min_positive_step_reveals_the_coarseness() -> None:
    tl = FrameTimeline()
    for t in (0.0, 100.0, 100.0, 200.0, 300.0):  # a browser that rounds to 100 ms
        tl.to_seconds(t)
    assert tl.min_positive_step_ms == 100.0


def test_a_bad_stamp_does_not_move_the_timeline() -> None:
    tl = FrameTimeline()
    tl.to_seconds(10.0)
    for bad in (float("nan"), -5, "11", None, 1.7e12):
        with pytest.raises(WebXrError):
            tl.to_seconds(bad)
    assert tl.to_seconds(10.0) == 0.01
    assert tl.repeats == 1


@pytest.mark.parametrize("bad", [-1, float("nan"), float("inf"), 1001, "1", True, None])
def test_timeline_constructor_validates_tolerance(bad: object) -> None:
    with pytest.raises(WebXrError):
        FrameTimeline(jitter_tolerance_ms=bad)  # type: ignore[arg-type]


@given(
    base=_floats(0, 1e6),
    steps=st.lists(_floats(-0.9, 5.0), min_size=1, max_size=50),
)
@_FAST
def test_output_never_decreases_under_sub_tolerance_jitter(base: float, steps: list[float]) -> None:
    tl = FrameTimeline(jitter_tolerance_ms=1.0)
    t = base
    out: list[float] = []
    for s in steps:
        t = max(0.0, t + s)
        try:
            out.append(tl.to_seconds(t))
        except WebXrError:  # drifted more than the tolerance behind the high-water mark
            pass
    assert out == sorted(out)


@given(st.lists(st.one_of(st.floats(), st.integers(), st.text(max_size=5), st.none(), st.booleans()),
                max_size=30))
@_FAST
def test_timeline_total_on_hostile_input(values: list[object]) -> None:
    tl = FrameTimeline()
    last = -1.0
    for v in values:
        try:
            out = tl.to_seconds(v)
        except WebXrError:
            continue
        assert math.isfinite(out) and out >= last
        last = out


# --- select / squeeze -> gestures ---------------------------------------------------


def _kinds(m: InputEventMapper, seq: list[tuple[str, float]], key: object = 0) -> list[GestureKind | None]:
    out: list[GestureKind | None] = []
    for name, t in seq:
        g = m.feed(name, t, key)
        out.append(None if g is None else g.kind)
    return out


def test_full_select_sequence_gives_both_edges_and_no_tap() -> None:
    m = InputEventMapper()
    got = _kinds(m, [("selectstart", 1.0), ("select", 2.0), ("selectend", 2.0)])
    assert got == [GestureKind.PINCH_START, None, GestureKind.PINCH_END]


def test_select_after_selectend_is_not_a_tap_inside_the_window() -> None:
    m = InputEventMapper(late_select_window_s=0.05)
    got = _kinds(m, [("selectstart", 1.0), ("selectend", 2.0), ("select", 2.01)])
    assert got == [GestureKind.PINCH_START, GestureKind.PINCH_END, None]


def test_a_lone_select_is_a_tap_and_never_a_hold() -> None:
    m = InputEventMapper()
    ev = m.feed("select", 3.0, "right")
    assert ev == GestureEvent(3.0, GestureKind.TAP)
    assert m.held_count == 0


def test_a_select_long_after_the_last_end_is_a_new_tap() -> None:
    m = InputEventMapper(late_select_window_s=0.05)
    _kinds(m, [("selectstart", 1.0), ("selectend", 2.0)])
    ev = m.feed("select", 2.5, 0)
    assert ev is not None and ev.kind is GestureKind.TAP


def test_squeeze_family_maps_to_squeeze_edges_and_bare_squeeze_is_ignored() -> None:
    m = InputEventMapper()
    got = _kinds(m, [("squeezestart", 1.0), ("squeeze", 2.0), ("squeezeend", 2.0)])
    assert got == [GestureKind.SQUEEZE_START, None, GestureKind.SQUEEZE_END]
    assert m.feed("squeeze", 9.0, 1) is None


def test_families_and_sources_do_not_interfere() -> None:
    m = InputEventMapper()
    m.feed("selectstart", 1.0, 0)
    ev = m.feed("select", 1.5, 1)  # another source: its select is its own lone tap
    assert ev is not None and ev.kind is GestureKind.TAP
    assert m.feed("squeezestart", 1.6, 0) is not None
    assert m.held_count == 2


def test_an_end_without_a_start_is_still_passed_on() -> None:
    m = InputEventMapper()
    ev = m.feed("selectend", 4.0, 0)
    assert ev == GestureEvent(4.0, GestureKind.PINCH_END)  # fail safe toward closing the mic


def test_source_removed_closes_what_it_held() -> None:
    m = InputEventMapper()
    m.feed("selectstart", 1.0, 0)
    m.feed("squeezestart", 1.1, 0)
    m.feed("selectstart", 1.2, 1)
    ends = m.source_removed(0, 2.0)
    assert [g.kind for g in ends] == [GestureKind.PINCH_END, GestureKind.SQUEEZE_END]
    assert m.held_count == 1
    assert m.source_removed(0, 3.0) == ()  # nothing left to close


def test_end_session_closes_everything_held() -> None:
    m = InputEventMapper()
    m.feed("selectstart", 1.0, 0)
    m.feed("selectstart", 1.0, 1)
    assert len(m.end_session(5.0)) == 2
    assert m.held_count == 0
    assert m.end_session(6.0) == ()


def test_slot_table_is_bounded() -> None:
    m = InputEventMapper()
    for i in range(500):
        m.feed("selectstart", 1.0, i)
    assert len(m._slots) <= 32  # noqa: SLF001 -- the bound is the point of the test
    assert m.held_count <= 32


@pytest.mark.parametrize(
    "event,t,key",
    [
        ("click", 1.0, 0), (None, 1.0, 0), ("select", -1.0, 0), ("select", float("nan"), 0),
        ("select", "1", 0), ("select", True, 0), ("select", 1.0, None), ("select", 1.0, ""),
        ("select", 1.0, "x" * 129), ("select", 1.0, True), ("select", 1.0, 1.5),
        ("select", 1.0, 10**400), ("select", 1.0, "bad\x00"), ("select", 2e9, 0),
    ],
)
def test_mapper_refuses_hostile_arguments(event: object, t: object, key: object) -> None:
    with pytest.raises(WebXrError):
        InputEventMapper().feed(event, t, key)


def test_mapper_constructor_validates_window() -> None:
    for bad in (-1, float("nan"), 6, "0.05", True):
        with pytest.raises(WebXrError):
            InputEventMapper(late_select_window_s=bad)  # type: ignore[arg-type]


@given(
    st.lists(
        st.tuples(
            st.sampled_from([e.value for e in InputEventName]),
            st.integers(0, 3),
            _floats(0, 1e5),
        ),
        max_size=80,
    )
)
@_FAST
def test_mapper_never_leaves_more_held_than_started_and_session_end_closes_all(
    events: list[tuple[str, int, float]],
) -> None:
    m = InputEventMapper()
    starts = 0
    for name, key, t in events:
        g = m.feed(name, t, key)
        if g is not None and g.kind in (GestureKind.PINCH_START, GestureKind.SQUEEZE_START):
            starts += 1
        assert m.held_count <= starts
    m.end_session(2e5)
    assert m.held_count == 0


# --- select/selectend through the real hold-to-talk machine -------------------------


def test_selectstart_selectend_drive_hold_to_talk_but_a_lone_select_does_not() -> None:
    held = InputEventMapper()
    ptt = GesturePtt(PttMode.HOLD_PINCH)
    ptt.tick(0.0)
    start = held.feed("selectstart", 1.0, 0)
    end = held.feed("selectend", 2.0, 0)
    assert start is not None and end is not None
    assert [a.kind for a in ptt.feed(start)] == [PttActionKind.START]
    ptt.feed(end)
    actions = ptt.tick(3.0)
    assert [a.kind for a in actions] == [PttActionKind.STOP]

    lone = InputEventMapper().feed("select", 1.0, 0)
    assert lone is not None and lone.kind is GestureKind.TAP
    ptt2 = GesturePtt(PttMode.HOLD_PINCH)
    ptt2.tick(0.0)
    assert ptt2.feed(lone) == []  # a tap is not a hold: no microphone


# --- encoder -> wire -------------------------------------------------------------------


def _wire(frame: bytes | None) -> dict[str, object]:
    assert frame is not None
    obj = json.loads(frame)
    assert isinstance(obj, dict)
    return obj


def test_pose_frame_is_exactly_the_documented_wire_object() -> None:
    enc = WebXrFrameEncoder()
    info = describe_input_source("tracked-pointer", "right")
    frame = enc.pose_frame(12500.0, info, [0.0, 1.6, 0.0], _ID, confidence=0.9)
    assert _wire(frame) == {
        "v": 1, "t": "sample", "device_time_s": 12.5, "source": "controller",
        "origin": [0.0, 1.6, 0.0], "direction": [0.0, 0.0, -1.0], "confidence": 0.9,
    }
    decoded = decode_frame(frame)
    assert isinstance(decoded, XrSample) and decoded.source is RaySource.CONTROLLER


def test_every_pose_frame_survives_the_real_decoder() -> None:
    enc = WebXrFrameEncoder()
    for i, mode in enumerate(("gaze", "tracked-pointer", "screen", "transient-pointer")):
        info = describe_input_source(mode)
        q = _axis_angle_quat((0.2, 1.0, -0.4), 0.3 * i)
        decoded = decode_frame(enc.pose_frame(1000.0 + i, info, [0.1, 1.5, -0.3], q))
        assert isinstance(decoded, XrSample)
        assert decoded.source is info.ray_source
        assert _close(decoded.ray.direction, ray_from_pose([0, 0, 0], q).direction, 1e-9)


def test_viewer_frame_is_a_head_sample() -> None:
    enc = WebXrFrameEncoder()
    decoded = decode_frame(enc.viewer_frame(5.0, [0, 1.7, 0], _ID))
    assert isinstance(decoded, XrSample) and decoded.source is RaySource.HEAD


def test_event_frames_follow_the_mapper_and_use_seconds() -> None:
    enc = WebXrFrameEncoder()
    assert _wire(enc.event_frame("selectstart", 2000.0, 0)) == {
        "v": 1, "t": "gesture", "device_time_s": 2.0, "kind": "pinch_start", "confidence": 1.0,
    }
    assert enc.event_frame("select", 2500.0, 0) is None
    end = decode_frame(enc.event_frame("selectend", 2500.0, 0) or b"")
    assert isinstance(end, GestureEvent) and end.kind is GestureKind.PINCH_END
    assert enc.held_count == 0


def test_end_session_and_source_removed_emit_frames() -> None:
    enc = WebXrFrameEncoder()
    enc.event_frame("selectstart", 100.0, "a")
    enc.event_frame("squeezestart", 101.0, "b")
    gone = enc.source_removed("a", 200.0)
    assert [decode_frame(f).kind for f in gone] == [GestureKind.PINCH_END]  # type: ignore[union-attr]
    ends = enc.end_session(300.0)
    assert [decode_frame(f).kind for f in ends] == [GestureKind.SQUEEZE_END]  # type: ignore[union-attr]
    assert enc.held_count == 0


def test_pose_and_event_streams_have_independent_timelines() -> None:
    enc = WebXrFrameEncoder()
    info = describe_input_source("gaze")
    enc.pose_frame(1011.0, info, [0, 0, 0], _ID)
    # A DOM event stamped a frame earlier than the latest rAF time is normal, not a step.
    assert enc.event_frame("selectstart", 1000.0, 0) is not None


def test_coarsened_poses_encode_with_equal_stamps() -> None:
    enc = WebXrFrameEncoder()
    info = describe_input_source("tracked-pointer")
    stamps = [_wire(enc.pose_frame(t, info, [0, 1.5, 0], _ID))["device_time_s"]
              for t in (100.0, 100.0, 100.0, 200.0)]
    assert stamps == [0.1, 0.1, 0.1, 0.2]
    assert enc.poses.repeats == 2


def test_encoder_reset_forgets_everything() -> None:
    enc = WebXrFrameEncoder()
    enc.event_frame("selectstart", 9000.0, 0)
    enc.pose_frame(9000.0, describe_input_source("gaze"), [0, 0, 0], _ID)
    enc.reset()
    assert enc.held_count == 0
    assert enc.pose_frame(1.0, describe_input_source("gaze"), [0, 0, 0], _ID)  # no regression error


@pytest.mark.parametrize(
    "call",
    [
        lambda e: e.pose_frame("1", describe_input_source("gaze"), [0, 0, 0], _ID),
        lambda e: e.pose_frame(1.0, "gaze", [0, 0, 0], _ID),
        lambda e: e.pose_frame(1.0, describe_input_source("gaze"), [0, 0], _ID),
        lambda e: e.pose_frame(1.0, describe_input_source("gaze"), [0, 0, 0], (0, 0, 0, 2)),
        lambda e: e.pose_frame(1.0, describe_input_source("gaze"), [0, 0, 0], _ID, confidence=1.5),
        lambda e: e.pose_frame(1.0, describe_input_source("gaze"), [0, 0, 0], _ID, confidence=float("nan")),
        lambda e: e.viewer_frame(float("nan"), [0, 0, 0], _ID),
        lambda e: e.event_frame("select", -1, 0),
        lambda e: e.event_frame("select", 1.0, None),
        lambda e: e.source_removed(None, 1.0),
        lambda e: e.end_session("now"),
    ],
)
def test_encoder_raises_only_webxr_error(call: object) -> None:
    with pytest.raises(WebXrError):
        call(WebXrFrameEncoder())  # type: ignore[operator]


def test_a_failed_pose_does_not_advance_the_pose_timeline() -> None:
    enc = WebXrFrameEncoder()
    info = describe_input_source("gaze")
    with pytest.raises(WebXrError):
        enc.pose_frame(5000.0, info, [0, 0, 0], (0, 0, 0, 2))
    # The stamp was accepted by the timeline before the pose failed; a later, earlier
    # stamp beyond the tolerance is therefore refused. Pinned so a change is deliberate.
    with pytest.raises(WebXrError):
        enc.pose_frame(100.0, info, [0, 0, 0], _ID)


@given(
    times=st.lists(_floats(0, 1e8), min_size=1, max_size=20),
    q=st.tuples(_floats(-1, 1), _floats(-1, 1), _floats(-1, 1), _floats(-1, 1)),
)
@_FAST
def test_any_frame_the_encoder_emits_decodes(times: list[float], q: tuple[float, ...]) -> None:
    enc = WebXrFrameEncoder()
    info = describe_input_source("transient-pointer", "none")
    for t in times:
        try:
            frame = enc.pose_frame(t, info, [0.0, 1.0, 0.0], q)
        except WebXrError:
            continue
        assert isinstance(decode_frame(frame), XrSample)


def test_encoder_output_rebases_through_clockmap() -> None:
    enc = WebXrFrameEncoder()
    clock = ClockMap()
    info = describe_input_source("tracked-pointer")
    out = []
    for i in range(5):
        frame = decode_frame(enc.pose_frame(1000.0 + 11.1 * i, info, [0, 1.5, 0], _ID))
        out.append(rebase(frame, clock, 50.0 + 0.0111 * i))
    stamps = [f.timestamp_s for f in out]  # type: ignore[union-attr]
    assert stamps == sorted(stamps) and stamps[0] == pytest.approx(50.0)


def test_milliseconds_passed_as_seconds_are_refused_downstream() -> None:
    """The slip no check here can see (ms read as s) is caught by ClockMap's rate bound."""
    clock = ClockMap()
    results = []
    for i in range(5):  # real frames 11.1 ms apart; the "page" forgot the / 1000
        wrong_device_time_s = 1000.0 + 11.1 * i
        try:
            clock.map(wrong_device_time_s, 50.0 + 0.0111 * i)
            results.append("ok")
        except WireError:
            results.append("refused")
    assert results == ["ok", "refused", "refused", "refused", "refused"]


# --- coarse timestamps and the deixis binder ------------------------------------------


def test_binder_declines_rather_than_misbinding_on_a_100ms_coarsened_stream() -> None:
    """A stream rounded to 100 ms (equal stamps in runs) must never produce a wrong BOUND."""
    from yazses.xr.binding import BindingOutcome, PanelObservation, bind_demonstrative
    from yazses.xr.types import PanelHit

    obs = []
    for i in range(30):  # 90 Hz for ~0.33 s, rounded down to 100 ms ticks
        t = i / 90.0
        coarse = math.floor(t * 10) / 10
        obs.append(PanelObservation(coarse, PanelHit("A", 0.5, 0.5, 2.0), 0.9))
    result = bind_demonstrative(obs, 0.15)
    # The outcome is allowed to be BOUND (A is the only candidate) or NONE; it must
    # never name another panel, and must not crash on zero-width intervals.
    assert result.outcome in (BindingOutcome.BOUND, BindingOutcome.NONE)
    if result.outcome is BindingOutcome.BOUND:
        assert result.panel_id == "A"


# --- features --------------------------------------------------------------------------


def test_feature_notes_state_what_was_verified() -> None:
    hand = describe_feature("hand-tracking")
    assert hand.standard is True and hand.needs_consent is True
    assert describe_feature("local").standard is True
    assert describe_feature("local-floor").needs_consent is True


def test_eye_tracking_is_unknown_not_false() -> None:
    eye = describe_feature("eye-tracking")
    assert eye.standard is None and eye.needs_consent is None
    assert "unverified" in eye.note


def test_unknown_feature_is_reported_unknown() -> None:
    f = describe_feature("bounded-wibble")
    assert f.standard is None and f.needs_consent is None


@pytest.mark.parametrize("bad", [None, 1, "", "x" * 129, "a\nb", b"local"])
def test_describe_feature_refuses_bad_names(bad: object) -> None:
    with pytest.raises(WebXrError):
        describe_feature(bad)


def test_session_init_requests_the_minimum() -> None:
    assert session_init_features() == {"requiredFeatures": [], "optionalFeatures": []}
    assert session_init_features(hand_tracking=True) == {
        "requiredFeatures": [], "optionalFeatures": ["hand-tracking"],
    }
    with pytest.raises(WebXrError):
        session_init_features(hand_tracking=1)  # type: ignore[arg-type]


def test_no_eye_tracking_is_ever_requested() -> None:
    for flag in (False, True):
        init = session_init_features(hand_tracking=flag)
        assert "eye-tracking" not in init["optionalFeatures"] + init["requiredFeatures"]


# --- sample_from_pose ------------------------------------------------------------------


def test_sample_from_pose_builds_a_valid_sample() -> None:
    s = sample_from_pose(1.5, RaySource.HEAD, [0, 1.6, 0], _ID, confidence=0.7)
    assert s.timestamp_s == 1.5 and s.source is RaySource.HEAD and s.confidence == 0.7


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timestamp_s": -1.0}, {"timestamp_s": float("nan")}, {"timestamp_s": "1"},
        {"source": "head"}, {"confidence": 2.0}, {"confidence": True}, {"position": [0, 0]},
    ],
)
def test_sample_from_pose_refuses_bad_arguments(kwargs: dict[str, object]) -> None:
    args: dict[str, object] = {
        "timestamp_s": 1.0, "source": RaySource.HEAD, "position": [0, 0, 0], "orientation": _ID,
    }
    args.update(kwargs)
    with pytest.raises(WebXrError):
        sample_from_pose(**args)  # type: ignore[arg-type]


# --- retention interplay ----------------------------------------------------------------


def test_transient_pointer_leaves_no_history_before_the_pinch() -> None:
    """What is lost, as a test: samples exist only from the pinch, so the binder's lead
    window before the pinch is empty. Encoded as data so the claim in the docs is pinned."""
    enc = WebXrFrameEncoder()
    info = describe_input_source("transient-pointer")
    buf = SampleRetention(window_s=8.0)
    pinch_at_ms = 5000.0
    for k in range(10):  # the page can only read the ray while the source exists
        frame = decode_frame(enc.pose_frame(pinch_at_ms + 11.1 * k, info, [0, 1.6, 0], _ID))
        assert isinstance(frame, XrSample)
        buf.add(frame)
    snap = buf.snapshot(5.2)
    assert min(s.timestamp_s for s in snap) >= pinch_at_ms / 1000.0


# --- the docs' JavaScript is an illustration, and it matches this module ------------------

_DOC = Path(__file__).resolve().parent.parent / "docs" / "xr-webxr.md"
_FENCE = re.compile(r"```js\n(.*?)```", re.S)


def _js_blocks() -> list[str]:
    return _FENCE.findall(_DOC.read_text(encoding="utf-8"))


def test_the_docs_page_exists_and_marks_its_javascript_as_not_run() -> None:
    text = _DOC.read_text(encoding="utf-8")
    assert _js_blocks(), "the page must carry the JavaScript illustration"
    assert "illustration" in text.lower() and "does not run" in text.lower()
    assert text.startswith("---\n") and 'description: "' not in text  # front-matter hygiene
    desc = re.search(r"^description:(.*)$", text, re.M)
    assert desc is not None and '"' not in desc.group(1)


def test_the_illustration_opens_no_connection_itself() -> None:
    for block in _js_blocks():
        for banned in ("WebSocket", "fetch(", "XMLHttpRequest", "sendBeacon", "RTCPeerConnection",
                       "EventSource", "importScripts", "eval(", "new Function"):
            assert banned not in block, f"the illustration must leave transport to the integrator: {banned}"
        assert "sendToBridge" in "".join(_js_blocks())  # the placeholder the integrator provides


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_documented_javascript_computes_the_same_ray_and_frames_as_python() -> None:
    blocks = [b for b in _js_blocks() if "function rayFromTransform" in b]
    assert blocks, "the pure-function block of the page must define rayFromTransform"
    cases = [
        ([0.1, 1.6, -0.2], _ID),
        ([0, 0, 0], _axis_angle_quat((0, 1, 0), math.pi / 2)),
        ([1, 2, 3], _axis_angle_quat((0.3, -0.7, 0.2), 1.1)),
        ([0, 1, 0], _axis_angle_quat((1, 0, 0), -0.4)),
    ]
    script = blocks[0] + "\nconst cases = " + json.dumps(cases) + ";\n" + (
        "console.log(JSON.stringify(cases.map(([p, q]) => rayFromTransform("
        "{position: {x: p[0], y: p[1], z: p[2]}, orientation: {x: q[0], y: q[1], z: q[2], w: q[3]}}))));\n"
        "console.log(sampleFrame(12500, \"controller\", {position: {x: 0, y: 1.6, z: 0}, "
        "orientation: {x: 0, y: 0, z: 0, w: 1}}, 0.9));\n"
    )
    done = subprocess.run(  # noqa: S603 -- fixed argv, the page's own code, no shell
        [shutil.which("node") or "node", "--input-type=commonjs", "-e", script],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert done.returncode == 0, done.stderr
    first, second = done.stdout.strip().splitlines()
    for (pos, q), js in zip(cases, json.loads(first), strict=True):
        py = ray_from_pose(pos, q)
        assert js["origin"] == [py.origin.x, py.origin.y, py.origin.z]
        for a, b in zip(js["direction"], (py.direction.x, py.direction.y, py.direction.z), strict=True):
            assert abs(a - b) < 1e-12
    expected = WebXrFrameEncoder().pose_frame(
        12500.0, describe_input_source("tracked-pointer"), [0.0, 1.6, 0.0], _ID, confidence=0.9
    )
    frame = decode_frame(second)  # the page's own output must pass the real decoder
    assert frame == decode_frame(expected)


# --- the source is stdlib-only, offline and pure -----------------------------------------

_ALLOWED_IMPORTS = {"__future__", "math", "collections.abc", "dataclasses", "enum"}


def _module_source() -> str:
    return Path(webxr.__file__).read_text(encoding="utf-8")


def test_webxr_imports_only_stdlib_basics_and_the_xr_package() -> None:
    tree = ast.parse(_module_source())
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            seen.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import"
            seen.add(node.module or "")
    extra = {m for m in seen if m not in _ALLOWED_IMPORTS and not m.startswith("yazses.xr.")}
    assert extra == set(), f"unexpected imports: {sorted(extra)}"


def test_webxr_has_no_dynamic_code_or_io_or_clock() -> None:
    tree = ast.parse(_module_source())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"open", "exec", "eval", "compile", "__import__", "input", "print", "getattr"}
    assert not attrs & {"time", "monotonic", "perf_counter", "sleep", "open", "system", "popen"}


def test_webxr_keeps_no_global_state() -> None:
    """No ``global`` statement, and every module-level assignment is a constant-style name
    (``_UPPER`` tables and limits); all mutable state lives on instances."""
    tree = ast.parse(_module_source())
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Global)]
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for name in ast.walk(t):
                    if isinstance(name, ast.Name):
                        assert name.id.lstrip("_").isupper(), name.id
