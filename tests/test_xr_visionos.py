"""visionOS model: matrices, hand frames, pinch hysteresis, the degraded pointing channels.

Every fixture is synthetic: invented transforms and joints, no recording, no device. The
exact cases are worked by hand in the comments; the properties compare against an
independent oracle (a direct 4x4 column-major multiply, Rodrigues rotations), never against
the module's own helpers.
"""
from __future__ import annotations

import inspect
import math
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.test_xr_privacy import _outbound_findings
from yazses.xr import devices
from yazses.xr.binding import BindingOutcome, PanelObservation, bind_demonstrative
from yazses.xr.conventions import Convention, to_canonical_vec
from yazses.xr.types import GestureKind, PanelHit, Ray, RaySource, Vec3, XrSample
from yazses.xr.visionos import (
    BINDER_LAG_S,
    BINDER_LEAD_S,
    BINDER_MIN_SAMPLES,
    CAPABILITIES,
    IDENTITY,
    Availability,
    Chirality,
    HandFrame,
    HandJointName,
    HandJointPose,
    InputPhase,
    PinchConfig,
    PinchDetector,
    PinchRayAnchor,
    PointerConfig,
    PointingMode,
    RigidTransform,
    SystemInputEvent,
    SystemInputKind,
    TransformError,
    VisionOSPointer,
    capability,
    compose,
    derived_pinch_ray,
    forward_ray,
    hand_frame_from_raw,
    nearest_pinch_sample,
    pointing_error_rad,
    rigid_from_column_major,
    system_event_from_raw,
    window_evidence,
)

_ROOT = Path(__file__).resolve().parents[1]
_FAST = settings(max_examples=100, deadline=None,
                 suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])


def _mat(c0=(1, 0, 0), c1=(0, 1, 0), c2=(0, 0, 1), t=(0, 0, 0)) -> list[float]:
    """Column-major flatten, the way ``simd_float4x4`` lays it out."""
    return [*c0, 0, *c1, 0, *c2, 0, *t, 1]


def _near(a: Vec3, b: tuple[float, float, float], tol: float = 1e-9) -> bool:
    return all(abs(x - y) <= tol for x, y in zip((a.x, a.y, a.z), b, strict=True))


# --- matrices: exact hand-computed cases ------------------------------------


def test_identity_matrix_is_the_identity_transform() -> None:
    t = rigid_from_column_major(_mat())
    assert t == IDENTITY
    assert _near(t.forward, (0, 0, -1))  # -Z is forward


def test_translation_sits_in_elements_12_to_14() -> None:
    t = rigid_from_column_major(_mat(t=(1.0, 2.0, 3.0)))
    assert _near(t.position, (1.0, 2.0, 3.0))


def test_quarter_turn_about_y_faces_minus_x() -> None:
    # R_y(+90 deg): +X -> -Z, +Z -> +X, so the columns are (0,0,-1), (0,1,0), (1,0,0)
    # and forward = -column2 = (-1, 0, 0): a device that turned left looks along -X.
    t = rigid_from_column_major(_mat(c0=(0, 0, -1), c1=(0, 1, 0), c2=(1, 0, 0)))
    assert _near(t.right, (0, 0, -1))
    assert _near(t.forward, (-1, 0, 0))
    ray = forward_ray(rigid_from_column_major(_mat(c0=(0, 0, -1), c1=(0, 1, 0), c2=(1, 0, 0),
                                                   t=(0.0, 1.6, 0.0))))
    assert _near(ray.origin, (0.0, 1.6, 0.0))
    assert _near(ray.direction, (-1, 0, 0))


def test_compose_worked_example() -> None:
    # parent: quarter turn about Y, at (1, 0, 0). child: 1 m behind it in its own frame
    # (local +Z = back, so the point is (0,0,1)... here (0,0,-1) = 1 m in front).
    # R_y(90) * (0,0,-1) = -column2 = (-1, 0, 0); plus (1,0,0) = the world origin.
    parent = rigid_from_column_major(_mat(c0=(0, 0, -1), c1=(0, 1, 0), c2=(1, 0, 0),
                                          t=(1.0, 0.0, 0.0)))
    child = rigid_from_column_major(_mat(t=(0.0, 0.0, -1.0)))
    out = compose(parent, child)
    assert _near(out.position, (0.0, 0.0, 0.0))
    assert _near(out.forward, (-1, 0, 0))  # the child inherits the parent's heading


def test_float32_noise_is_accepted_and_cleaned_up() -> None:
    noisy = _mat(c0=(1 + 5e-5, 0, 0), c1=(1e-5, 1 - 5e-5, 0), c2=(0, 0, 1))
    t = rigid_from_column_major(noisy)
    for axis in (t.right, t.up, t.back):
        assert abs(math.sqrt(axis.x**2 + axis.y**2 + axis.z**2) - 1.0) < 1e-12


# --- matrices: explicit refusals --------------------------------------------


def _scaled(k: float) -> list[float]:
    return _mat(c0=(k, 0, 0), c1=(0, k, 0), c2=(0, 0, k))


@pytest.mark.parametrize(
    ("bad", "fragment"),
    [
        (_scaled(2.0), "non-unit scale"),
        (_scaled(0.9), "non-unit scale"),
        (_scaled(0.0), "non-unit scale"),
        (_mat(c0=(1, 0, 0), c1=(0.6, 0.8, 0)), "shear"),  # unit c1 at 53 deg to c0: not perpendicular
        (_mat(c0=(-1, 0, 0)), "negative determinant"),  # a mirror
        ([*_mat()[:15], 2.0], "bottom row"),
        ([*_mat()[:3], 0.5, *_mat()[4:]], "bottom row"),
        (_mat(t=(1e7, 0, 0)), "out of range"),
    ],
)
def test_non_rigid_matrices_are_refused_by_name(bad: list[float], fragment: str) -> None:
    with pytest.raises(TransformError, match=fragment):
        rigid_from_column_major(bad)


@pytest.mark.parametrize(
    "junk",
    [
        None, 5, "x" * 16, b"\x00" * 16, [], [1.0] * 15, [1.0] * 17, [[1.0] * 4] * 4,
        [float("nan")] * 16, [*_mat()[:12], float("nan"), 0, 0, 1],
        [*_mat()[:12], float("inf"), 0, 0, 1], [True] * 16, [None] * 16, ["1"] * 16,
        {"m": 1},
    ],
)
def test_junk_raises_only_transform_error(junk: object) -> None:
    with pytest.raises(TransformError):
        rigid_from_column_major(junk)


def test_transform_error_is_a_value_error() -> None:
    assert issubclass(TransformError, ValueError)


_junk_numbers = st.one_of(
    st.floats(allow_nan=True, allow_infinity=True),
    st.integers(min_value=-(10**30), max_value=10**30),
    st.sampled_from([0.0, -0.0, 1.0, -1.0, 1e308, -1e308, 5e-324, float("nan")]),
)


@_FAST
@given(st.lists(_junk_numbers, min_size=0, max_size=20))
def test_any_numeric_list_is_total(values: list[float]) -> None:
    try:
        t = rigid_from_column_major(values)
    except TransformError:
        return
    assert len(values) == 16
    for axis in (t.right, t.up, t.back):
        assert abs(math.sqrt(axis.x**2 + axis.y**2 + axis.z**2) - 1.0) < 1e-9


@_FAST
@given(st.recursive(st.none() | st.booleans() | st.integers() | st.text(max_size=5)
                    | st.floats(), lambda c: st.lists(c, max_size=5) | st.dictionaries(
                        st.text(max_size=3), c, max_size=3), max_leaves=20))
def test_any_object_is_total(obj: object) -> None:
    try:
        rigid_from_column_major(obj)
    except TransformError:
        pass


# --- matrices: properties vs an independent oracle --------------------------


def _rodrigues(axis: tuple[float, float, float], angle: float) -> list[list[float]]:
    """3x3 rotation, row-major, by Rodrigues' formula (independent of the module)."""
    n = math.sqrt(sum(a * a for a in axis))
    x, y, z = (a / n for a in axis)
    c, s = math.cos(angle), math.sin(angle)
    k = 1 - c
    return [
        [c + x * x * k, x * y * k - z * s, x * z * k + y * s],
        [y * x * k + z * s, c + y * y * k, y * z * k - x * s],
        [z * x * k - y * s, z * y * k + x * s, c + z * z * k],
    ]


def _to_col_major(r: list[list[float]], t: tuple[float, float, float]) -> list[float]:
    return [r[0][0], r[1][0], r[2][0], 0, r[0][1], r[1][1], r[2][1], 0,
            r[0][2], r[1][2], r[2][2], 0, t[0], t[1], t[2], 1]


def _mul4(a: list[float], b: list[float]) -> list[float]:
    """Column-major 4x4 product ``a * b`` straight from the definition."""
    out = [0.0] * 16
    for col in range(4):
        for row in range(4):
            out[4 * col + row] = sum(a[4 * k + row] * b[4 * col + k] for k in range(4))
    return out


_axes = st.tuples(*[st.floats(-1, 1)] * 3).filter(lambda a: max(map(abs, a)) > 0.05)
_angles = st.floats(-math.pi, math.pi)
_trans = st.tuples(*[st.floats(-50, 50)] * 3)


@_FAST
@given(_axes, _angles, _trans, _axes, _angles, _trans)
def test_compose_matches_a_direct_matrix_product(a1, th1, t1, a2, th2, t2) -> None:
    ma = _to_col_major(_rodrigues(a1, th1), t1)
    mb = _to_col_major(_rodrigues(a2, th2), t2)
    want = _mul4(ma, mb)
    got = compose(rigid_from_column_major(ma), rigid_from_column_major(mb))
    assert _near(got.position, (want[12], want[13], want[14]), 1e-9)
    assert _near(got.right, (want[0], want[1], want[2]), 1e-9)
    assert _near(got.up, (want[4], want[5], want[6]), 1e-9)
    assert _near(got.back, (want[8], want[9], want[10]), 1e-9)


@_FAST
@given(_axes, _angles, _trans)
def test_rotation_round_trips_through_the_parser(axis, angle, t) -> None:
    r = _rodrigues(axis, angle)
    got = rigid_from_column_major(_to_col_major(r, t))
    assert _near(got.right, (r[0][0], r[1][0], r[2][0]), 1e-9)
    assert _near(got.forward, (-r[0][2], -r[1][2], -r[2][2]), 1e-9)
    # a point is moved exactly as R p + t
    p = Vec3(0.3, -0.2, 0.5)
    want = tuple(sum(r[i][j] * c for j, c in enumerate((0.3, -0.2, 0.5))) + t[i] for i in range(3))
    assert _near(got.apply_point(p), want, 1e-9)


# --- hand joints and frames --------------------------------------------------


def test_there_are_27_joints_with_apples_spellings() -> None:
    assert len(HandJointName) == 27
    values = [j.value for j in HandJointName]
    assert len(set(values)) == 27
    for expected in ("wrist", "forearmArm", "forearmWrist", "thumbTip", "indexFingerTip",
                     "littleFingerMetacarpal", "thumbKnuckle"):
        assert expected in values
    assert "thumbMetacarpal" not in values  # Apple's thumb has no metacarpal case


def _joint(name: HandJointName, x=0.0, y=0.0, z=0.0, tracked=True) -> HandJointPose:
    return HandJointPose(name, rigid_from_column_major(_mat(t=(x, y, z))), tracked)


def _frame(t: float, d: float | None, *, chirality=Chirality.RIGHT, hand_tracked=True,
           anchor=(0.0, 1.2, -0.4)) -> HandFrame:
    """A hand whose thumb and index tips are ``d`` apart along X (None = tips untracked)."""
    joints = (
        _joint(HandJointName.THUMB_TIP, -(d or 0.0) / 2, tracked=d is not None),
        _joint(HandJointName.INDEX_TIP, (d or 0.0) / 2, tracked=d is not None),
    )
    return HandFrame(t, chirality, hand_tracked, rigid_from_column_major(_mat(t=anchor)), joints)


def test_distance_is_measured_in_origin_space() -> None:
    assert _frame(0.0, 0.03).thumb_index_distance_m() == pytest.approx(0.03)


def test_distance_uses_the_anchor_rotation() -> None:
    # Anchor turned a quarter about Y: the tips' X-separation now lies along -Z, still 0.04.
    rot = rigid_from_column_major(_mat(c0=(0, 0, -1), c1=(0, 1, 0), c2=(1, 0, 0), t=(5, 5, 5)))
    f = HandFrame(0.0, Chirality.LEFT, True, rot, (
        _joint(HandJointName.THUMB_TIP, -0.02), _joint(HandJointName.INDEX_TIP, 0.02)))
    thumb = f.joint_position(HandJointName.THUMB_TIP)
    assert thumb is not None
    assert _near(thumb, (5, 5, 5.02))  # R_y(90) * (-0.02, 0, 0) = (0, 0, +0.02)
    assert f.thumb_index_distance_m() == pytest.approx(0.04)


def test_untracked_pieces_give_no_distance() -> None:
    assert _frame(0.0, None).thumb_index_distance_m() is None
    assert _frame(0.0, 0.03, hand_tracked=False).thumb_index_distance_m() is None
    no_index = HandFrame(0.0, Chirality.LEFT, True, IDENTITY,
                         (_joint(HandJointName.THUMB_TIP),))
    assert no_index.thumb_index_distance_m() is None


def test_frame_validation() -> None:
    j = _joint(HandJointName.WRIST)
    for t in (float("nan"), -1.0, True, "1", None):
        with pytest.raises(ValueError):
            HandFrame(t, Chirality.LEFT, True, IDENTITY, ())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        HandFrame(0.0, Chirality.LEFT, True, IDENTITY, (j, j))  # duplicate joint
    with pytest.raises(ValueError):
        HandFrame(0.0, "left", True, IDENTITY, ())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        HandJointPose("wrist", IDENTITY, True)  # type: ignore[arg-type]


def _raw_joint(x: float, tracked: bool = True):
    return (_mat(t=(x, 0, 0)), tracked)


def test_raw_frame_happy_path() -> None:
    f = hand_frame_from_raw(1.5, "left", True, _mat(t=(0, 1, 0)),
                            {"thumbTip": _raw_joint(-0.01), "indexFingerTip": _raw_joint(0.01)})
    assert f.chirality is Chirality.LEFT
    assert f.thumb_index_distance_m() == pytest.approx(0.02)


@pytest.mark.parametrize(
    "args",
    [
        (float("nan"), "left", True, _mat(), {}),
        (-1.0, "left", True, _mat(), {}),
        (1e12, "left", True, _mat(), {}),
        (True, "left", True, _mat(), {}),
        (1.0, "LEFT", True, _mat(), {}),
        (1.0, None, True, _mat(), {}),
        (1.0, "left", 1, _mat(), {}),
        (1.0, "left", True, _scaled(2.0), {}),
        (1.0, "left", True, _mat(), []),
        (1.0, "left", True, _mat(), {"pinkyTip": _raw_joint(0)}),
        (1.0, "left", True, _mat(), {1: _raw_joint(0)}),
        (1.0, "left", True, _mat(), {"wrist": (_mat(),)}),
        (1.0, "left", True, _mat(), {"wrist": (_mat(), 1)}),
        (1.0, "left", True, _mat(), {"wrist": (_scaled(0.5), True)}),
        (1.0, "left", True, _mat(), {"wrist": "ab"}),
    ],
)
def test_raw_frame_hostile_input_raises_only_transform_error(args) -> None:
    with pytest.raises(TransformError):
        hand_frame_from_raw(*args)


def test_raw_frame_refuses_more_joints_than_a_skeleton() -> None:
    too_many = {f"j{i}": _raw_joint(0) for i in range(28)}
    with pytest.raises(TransformError):
        hand_frame_from_raw(1.0, "left", True, _mat(), too_many)


# --- pinch detection with hysteresis ----------------------------------------


def _run(distances: list[float | None], *, config: PinchConfig | None = None,
         dt: float = 0.01) -> list[tuple[float, GestureKind, float]]:
    det = PinchDetector(Chirality.RIGHT, config)
    out = []
    for i, d in enumerate(distances):
        ev = det.update(_frame(i * dt, d))
        if ev is not None:
            out.append((ev.timestamp_s, ev.kind, ev.confidence))
    return out


def test_pinch_starts_at_close_and_ends_at_open_inclusive() -> None:
    cfg = PinchConfig(close_m=0.02, open_m=0.035)
    events = _run([0.05, 0.021, 0.02, 0.03, 0.034, 0.035, 0.05], config=cfg)
    assert [(round(t, 2), k) for t, k, _ in events] == [
        (0.02, GestureKind.PINCH_START), (0.05, GestureKind.PINCH_END)]


def test_hover_between_the_thresholds_does_not_chatter() -> None:
    # 0.025 sits inside (0.02, 0.035): never starts from open, never ends from closed.
    assert _run([0.025] * 20) == []
    assert [k for _, k, _ in _run([0.01, *[0.025] * 20])] == [GestureKind.PINCH_START]


def test_dropout_inside_the_grace_keeps_the_pinch() -> None:
    cfg = PinchConfig(lost_grace_s=0.15)
    seq: list[float | None] = [0.01, None, None, None, 0.01, 0.01]  # 0.03 s dark at 100 Hz
    assert [k for _, k, _ in _run(seq, config=cfg)] == [GestureKind.PINCH_START]


def test_dropout_beyond_the_grace_ends_with_reduced_confidence() -> None:
    cfg = PinchConfig(lost_grace_s=0.05)
    events = _run([0.01, *[None] * 10], config=cfg)  # dark from t=0.01
    assert [k for _, k, _ in events] == [GestureKind.PINCH_START, GestureKind.PINCH_END]
    # first frame past 0.05 s of darkness: t = 0.01 + 0.06 = 0.07
    assert events[1][0] == pytest.approx(0.07)
    assert events[1][2] == 0.5


def test_dropout_clock_restarts_after_tracking_returns() -> None:
    cfg = PinchConfig(lost_grace_s=0.05)
    seq: list[float | None] = [0.01, *[None] * 4, 0.01, *[None] * 4, 0.01]
    assert [k for _, k, _ in _run(seq, config=cfg)] == [GestureKind.PINCH_START]


def test_dropout_while_open_emits_nothing() -> None:
    assert _run([0.05, None, None, 0.05]) == []


def test_out_of_order_frames_are_dropped_and_counted() -> None:
    det = PinchDetector(Chirality.RIGHT)
    assert det.update(_frame(1.0, 0.05)) is None
    assert det.update(_frame(0.5, 0.01)) is None  # would have started a pinch
    assert not det.pinching and det.dropped == 1
    ev = det.update(_frame(1.0, 0.01))  # equal time is not "older"
    assert ev is not None and ev.kind is GestureKind.PINCH_START


def test_the_other_hands_frame_is_refused() -> None:
    with pytest.raises(ValueError):
        PinchDetector(Chirality.LEFT).update(_frame(0.0, 0.01, chirality=Chirality.RIGHT))


@pytest.mark.parametrize(
    ("close", "open_", "grace"),
    [(0.0, 0.03, 0.1), (0.03, 0.03, 0.1), (0.04, 0.03, 0.1), (0.02, 0.5, 0.1),
     (0.02, 0.03, -1.0), (float("nan"), 0.03, 0.1), (0.02, float("inf"), 0.1), (True, 0.03, 0.1)],
)
def test_bad_pinch_config_is_refused(close, open_, grace) -> None:
    with pytest.raises(ValueError):
        PinchConfig(close_m=close, open_m=open_, lost_grace_s=grace)


@_FAST
@given(st.lists(st.one_of(st.none(), st.floats(0.0, 0.15)), min_size=0, max_size=80))
def test_pinch_events_alternate_and_respect_the_thresholds(seq) -> None:
    cfg = PinchConfig(close_m=0.02, open_m=0.035, lost_grace_s=0.05)
    det = PinchDetector(Chirality.RIGHT, cfg)
    pinching = False
    for i, d in enumerate(seq):
        ev = det.update(_frame(i * 0.01, d))
        if ev is None:
            assert det.pinching == pinching
            continue
        if ev.kind is GestureKind.PINCH_START:
            assert not pinching and d is not None and d <= cfg.close_m
        else:
            assert ev.kind is GestureKind.PINCH_END and pinching
            assert d is None or d >= cfg.open_m
        pinching = det.pinching
        assert pinching == (ev.kind is GestureKind.PINCH_START)


# --- derived pinch ray --------------------------------------------------------


def _head_at(x=0.0, y=1.6, z=0.0) -> RigidTransform:
    return rigid_from_column_major(_mat(t=(x, y, z)))


def _hand_frame(thumb, index, arm=None, wrist=None, tracked=True) -> HandFrame:
    joints = [_joint(HandJointName.THUMB_TIP, *thumb), _joint(HandJointName.INDEX_TIP, *index)]
    if arm is not None:
        joints.append(_joint(HandJointName.FOREARM_ARM, *arm))
    if wrist is not None:
        joints.append(_joint(HandJointName.WRIST, *wrist))
    return HandFrame(0.0, Chirality.RIGHT, tracked, IDENTITY, tuple(joints))


def test_head_anchored_ray_goes_through_the_pinch_midpoint() -> None:
    # tips at (-0.01,1.6,-0.5) and (0.01,1.6,-0.5): midpoint (0,1.6,-0.5), head at (0,1.6,0)
    f = _hand_frame((-0.01, 1.6, -0.5), (0.01, 1.6, -0.5))
    d = derived_pinch_ray(f, _head_at(), PinchRayAnchor.HEAD)
    assert d is not None
    assert _near(d.ray.origin, (0.0, 1.6, 0.0))
    assert _near(d.ray.direction, (0.0, 0.0, -1.0))
    assert d.baseline_m == pytest.approx(0.5)


def test_forearm_ray_starts_at_the_elbow_side_joint() -> None:
    # elbow-side joint (0,1.0,0) -> midpoint (0,1.4,-0.3): delta (0,0.4,-0.3), length 0.5
    f = _hand_frame((-0.01, 1.4, -0.3), (0.01, 1.4, -0.3), arm=(0.0, 1.0, 0.0), wrist=(0, 1.3, -0.2))
    d = derived_pinch_ray(f, _head_at(), PinchRayAnchor.FOREARM)
    assert d is not None
    assert _near(d.ray.origin, (0.0, 1.0, 0.0))
    assert _near(d.ray.direction, (0.0, 0.8, -0.6))
    assert d.baseline_m == pytest.approx(0.5)


def test_forearm_ray_falls_back_to_the_wrist() -> None:
    f = _hand_frame((-0.01, 1.4, -0.3), (0.01, 1.4, -0.3), wrist=(0.0, 1.4, 0.0))
    d = derived_pinch_ray(f, _head_at(), PinchRayAnchor.FOREARM)
    assert d is not None and _near(d.ray.origin, (0.0, 1.4, 0.0))


def test_a_short_lever_arm_is_refused_not_guessed() -> None:
    f = _hand_frame((-0.01, 1.4, -0.05), (0.01, 1.4, -0.05), wrist=(0.0, 1.4, 0.0))
    assert derived_pinch_ray(f, _head_at(0, 1.4, 0.0), PinchRayAnchor.HEAD) is None
    assert derived_pinch_ray(f, _head_at(), PinchRayAnchor.FOREARM) is None  # 5 cm < 8 cm


def test_no_derived_ray_without_tracking() -> None:
    f = _hand_frame((0, 1.6, -0.5), (0.02, 1.6, -0.5))
    assert derived_pinch_ray(_hand_frame((0, 1.6, -0.5), (0.02, 1.6, -0.5), tracked=False),
                             _head_at(), PinchRayAnchor.HEAD) is None
    assert derived_pinch_ray(f, _head_at(), PinchRayAnchor.FOREARM) is None  # no arm/wrist joint
    with pytest.raises(ValueError):
        derived_pinch_ray(f, _head_at(), PinchRayAnchor.HEAD, min_baseline_m=0.0)


def test_pointing_error_worked_values() -> None:
    # 1 cm noise at each end over 8 cm: atan(0.0141421356 / 0.08) = 0.17497 rad (10.0 deg)
    assert pointing_error_rad(0.08, 0.01, 0.01) == pytest.approx(0.17497, abs=1e-4)
    # 1 cm at one end only over 30 cm: atan(0.01 / 0.3) = 0.03332 rad (1.9 deg)
    assert pointing_error_rad(0.30, 0.01, 0.0) == pytest.approx(0.03332, abs=1e-4)
    assert pointing_error_rad(1.0, 0.0, 0.0) == 0.0


@pytest.mark.parametrize("args", [(0.0, 0.01, 0.01), (-1.0, 0, 0), (1.0, -0.1, 0),
                                  (1.0, float("nan"), 0), (True, 0, 0)])
def test_pointing_error_rejects_bad_numbers(args) -> None:
    with pytest.raises(ValueError):
        pointing_error_rad(*args)


@_FAST
@given(st.floats(0.01, 5), st.floats(0, 0.05), st.floats(0, 0.05))
def test_longer_lever_arm_never_increases_the_error(base, so, st_) -> None:
    assert pointing_error_rad(base * 2, so, st_) <= pointing_error_rad(base, so, st_)


# --- system input events -----------------------------------------------------


def _ray(ox=0.0, oy=1.6, oz=0.0, dx=0.0, dy=0.0, dz=-1.0) -> Ray:
    return Ray(Vec3(ox, oy, oz), Vec3(dx, dy, dz))


def _pinch(t: float, ray: Ray | None = None, phase=InputPhase.BEGAN) -> SystemInputEvent:
    return SystemInputEvent(t, SystemInputKind.INDIRECT_PINCH, phase, ray or _ray(), None)


def test_system_event_from_raw_normalises_the_ray() -> None:
    e = system_event_from_raw(2.0, "indirectPinch", "began", [0, 1.6, 0], [0, 0, -4])
    assert e.selection_ray is not None
    assert _near(e.selection_ray.direction, (0, 0, -1))


def test_system_event_kinds_are_apples_five() -> None:
    assert {k.value for k in SystemInputKind} == {
        "directPinch", "indirectPinch", "pointer", "touch", "pencil"}


@pytest.mark.parametrize(
    "args",
    [
        (1.0, "gaze", "began"),
        (1.0, "indirectPinch", "held"),
        (1.0, None, "began"),
        (-1.0, "touch", "began"),
        (float("nan"), "touch", "began"),
        (1.0, "indirectPinch", "began", [0, 0, 0], None),
        (1.0, "indirectPinch", "began", None, [0, 0, -1]),
        (1.0, "indirectPinch", "began", [0, 0, 0], [0, 0, 0]),
        (1.0, "indirectPinch", "began", [0, 0, 0], [float("nan"), 0, 1]),
        (1.0, "indirectPinch", "began", [0, 0, 0], [0, 0, -1, 0]),
        (1.0, "indirectPinch", "began", "abc", [0, 0, -1]),
        (1.0, "indirectPinch", "began", [1e9, 0, 0], [0, 0, -1]),
        (1.0, "touch", "began", None, None, [1e9, 0, 0]),
        (1.0, "touch", "began", None, None, [True, 0, 0]),
    ],
)
def test_system_event_hostile_input(args) -> None:
    with pytest.raises(TransformError):
        system_event_from_raw(*args)


def test_system_event_survives_extreme_but_finite_directions() -> None:
    e = system_event_from_raw(1.0, "indirectPinch", "began", [0, 0, 0], [1e300, 1e300, 0])
    assert e.selection_ray is not None
    d = e.selection_ray.direction
    assert abs(math.hypot(d.x, d.y, d.z) - 1.0) < 1e-9
    tiny = system_event_from_raw(1.0, "indirectPinch", "began", [0, 0, 0], [5e-324, 0, 0])
    assert tiny.selection_ray is not None and tiny.selection_ray.direction.x == 1.0


# --- the pointer: channel choice and degradation -----------------------------


def _pointer(**kw) -> VisionOSPointer:
    return VisionOSPointer(PointerConfig(**kw))


def test_a_pinch_yields_one_eye_sample_with_its_real_time() -> None:
    p = _pointer()
    s = p.observe_system_event(_pinch(10.0))
    assert s is not None and s.source is RaySource.EYE and s.timestamp_s == 10.0
    assert s.confidence == 0.9


def test_pinch_ray_is_preferred_then_expires_into_the_head_ray() -> None:
    p = _pointer(pinch_ttl_s=1.0, stale_s=0.25)
    head = p.observe_device(10.0, _head_at())
    pinch = p.observe_system_event(_pinch(10.0, _ray(dx=1.0, dz=0.0)))
    c = p.choose(10.2)
    assert c.mode is PointingMode.PINCH_RAY and c.sample == pinch
    assert c.mode.is_gaze_derived and not c.mode.is_continuous
    # at 10.9 the pinch ray is 0.9 s old (inside ttl) even though the head sample is stale
    assert p.choose(10.9).mode is PointingMode.PINCH_RAY
    # ttl exceeded; head also stale -> nothing, and it says so
    c = p.choose(11.5)
    assert c.mode is PointingMode.NONE and c.sample is None
    p.observe_device(11.4, _head_at())
    c = p.choose(11.5)
    assert c.mode is PointingMode.HEAD_RAY and c.mode.is_continuous and not c.mode.is_gaze_derived
    assert c.sample is not None and c.sample.timestamp_s == 11.4 and c.sample != head


def test_choice_never_restamps_a_stale_sample() -> None:
    p = _pointer()
    s = p.observe_system_event(_pinch(5.0))
    assert p.choose(5.8).sample is s  # same object, same original timestamp
    assert p.choose(5.8).age_s == pytest.approx(0.8)


def test_future_stamped_samples_are_not_fresh() -> None:
    p = _pointer()
    p.observe_system_event(_pinch(100.0))
    p.observe_device(100.0, _head_at())
    assert p.choose(50.0).mode is PointingMode.NONE


def test_head_ray_is_forward_with_low_confidence() -> None:
    p = _pointer()
    s = p.observe_device(1.0, rigid_from_column_major(_mat(c0=(0, 0, -1), c1=(0, 1, 0),
                                                           c2=(1, 0, 0), t=(0, 1.7, 0))))
    assert s.source is RaySource.HEAD and s.confidence == 0.4
    assert _near(s.ray.direction, (-1, 0, 0))


def test_ended_and_unsupported_events_make_no_sample() -> None:
    p = _pointer()
    p.observe_device(1.0, _head_at())
    assert p.observe_system_event(_pinch(1.0, phase=InputPhase.ENDED)) is None
    for kind in (SystemInputKind.POINTER, SystemInputKind.PENCIL):
        ev = SystemInputEvent(1.0, kind, InputPhase.BEGAN, _ray(), Vec3(0, 1, -1))
        assert p.observe_system_event(ev) is None
    no_ray = SystemInputEvent(1.0, SystemInputKind.INDIRECT_PINCH, InputPhase.BEGAN)
    assert p.observe_system_event(no_ray) is None
    assert p.choose(1.0).mode is PointingMode.HEAD_RAY  # nothing deliberate was recorded


def test_direct_touch_aims_from_the_head_through_the_contact_point() -> None:
    p = _pointer()
    p.observe_device(5.0, _head_at(0.0, 1.6, 0.0))
    ev = SystemInputEvent(5.1, SystemInputKind.TOUCH, InputPhase.BEGAN, None, Vec3(0.0, 1.0, -0.8))
    s = p.observe_system_event(ev)
    assert s is not None and s.source is RaySource.HAND
    # delta (0, -0.6, -0.8) has length 1.0: the ray reaches the point at distance 1.0
    assert _near(s.ray.direction, (0.0, -0.6, -0.8))
    reach = Vec3(s.ray.origin.x + s.ray.direction.x, s.ray.origin.y + s.ray.direction.y,
                 s.ray.origin.z + s.ray.direction.z)
    assert _near(reach, (0.0, 1.0, -0.8))
    assert p.choose(5.2).mode is PointingMode.DIRECT_TOUCH


def test_direct_touch_needs_a_fresh_head_sample() -> None:
    ev = SystemInputEvent(5.0, SystemInputKind.DIRECT_PINCH, InputPhase.BEGAN, None,
                          Vec3(0, 1, -1))
    assert _pointer().observe_system_event(ev) is None  # no head sample at all
    p = _pointer(stale_s=0.25)
    p.observe_device(4.0, _head_at())
    assert p.observe_system_event(ev) is None  # head is 1 s old
    p.observe_device(5.5, _head_at())
    assert p.observe_system_event(ev) is None  # head is from the future relative to the touch


def test_touch_at_the_head_position_is_refused() -> None:
    p = _pointer()
    p.observe_device(1.0, _head_at(0, 1.6, 0))
    ev = SystemInputEvent(1.0, SystemInputKind.TOUCH, InputPhase.BEGAN, None, Vec3(0, 1.6, 0))
    assert p.observe_system_event(ev) is None


def test_hand_ray_is_off_by_default_and_opt_in() -> None:
    frame = _hand_frame((-0.01, 1.4, -0.3), (0.01, 1.4, -0.3), arm=(0.0, 1.0, 0.0))
    off = _pointer()
    off.observe_device(2.0, _head_at())
    assert off.observe_hand(frame, _head_at()) is not None  # computed, but not preferred
    assert off.choose(2.0).mode is PointingMode.HEAD_RAY
    on = _pointer(use_hand_ray=True)
    on.observe_device(0.0, _head_at())
    sample = on.observe_hand(
        HandFrame(0.0, Chirality.RIGHT, True, IDENTITY, frame.joints), _head_at())
    assert sample is not None and sample.source is RaySource.HAND
    assert on.choose(0.1).mode is PointingMode.HAND_RAY
    # a fresh pinch still outranks the hand ray
    on.observe_system_event(_pinch(0.05))
    assert on.choose(0.1).mode is PointingMode.PINCH_RAY


def test_clear_forgets_everything() -> None:
    p = _pointer()
    p.observe_device(1.0, _head_at())
    p.observe_system_event(_pinch(1.0))
    p.clear()
    assert p.choose(1.0).mode is PointingMode.NONE


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1", None])
def test_choose_rejects_a_bad_clock(bad) -> None:
    with pytest.raises(ValueError):
        VisionOSPointer().choose(bad)


@pytest.mark.parametrize(
    "kw",
    [{"pinch_ttl_s": 0.0}, {"stale_s": -1.0}, {"head_confidence": 1.5},
     {"pinch_confidence": float("nan")}, {"use_hand_ray": 1}, {"hand_anchor": "head"},
     {"touch_confidence": True}],
)
def test_bad_pointer_config_is_refused(kw) -> None:
    with pytest.raises(ValueError):
        PointerConfig(**kw)


# --- what the binder loses ---------------------------------------------------


def test_binder_constants_track_the_real_defaults() -> None:
    sig = inspect.signature(bind_demonstrative)
    assert sig.parameters["lead_s"].default == BINDER_LEAD_S
    assert sig.parameters["lag_s"].default == BINDER_LAG_S
    assert sig.parameters["min_samples"].default == BINDER_MIN_SAMPLES


def _sample(t: float, source: RaySource) -> XrSample:
    return XrSample(t, source, _ray(), 0.9)


def test_window_evidence_counts_by_source_and_window_edges() -> None:
    samples = [_sample(9.59, RaySource.HEAD), _sample(9.6, RaySource.HEAD),
               _sample(10.0, RaySource.EYE), _sample(10.2, RaySource.HAND),
               _sample(10.21, RaySource.HEAD)]
    ev = window_evidence(samples, 10.0)  # window [9.6, 10.2]
    assert (ev.in_window, ev.pinch_rays, ev.head, ev.hand) == (3, 1, 1, 1)
    assert ev.gaze_in_window and ev.meets_binder_minimum


def test_a_lone_pinch_ray_cannot_meet_the_binder_minimum() -> None:
    ev = window_evidence([_sample(10.0, RaySource.EYE)], 10.0)
    assert ev.in_window == 1 and ev.gaze_in_window and not ev.meets_binder_minimum


def test_a_head_stream_meets_the_minimum_but_is_not_gaze() -> None:
    head = [_sample(9.7 + i / 30, RaySource.HEAD) for i in range(15)]
    ev = window_evidence(head, 10.0)
    assert ev.meets_binder_minimum and not ev.gaze_in_window


@pytest.mark.parametrize("kw", [{"lead_s": -1.0}, {"lag_s": float("nan")}])
def test_window_evidence_rejects_bad_windows(kw) -> None:
    with pytest.raises(ValueError):
        window_evidence([], 10.0, **kw)
    with pytest.raises(ValueError):
        window_evidence([], float("nan"))


def _obs(t: float, panel: str | None, conf: float = 0.9) -> PanelObservation:
    return PanelObservation(t, None if panel is None else PanelHit(panel, 0.5, 0.5, 2.0), conf)


def test_the_real_binder_refuses_a_single_pinch_sample() -> None:
    """The measured consequence: one gaze-at-pinch observation is 'insufficient evidence'."""
    result = bind_demonstrative([_obs(10.0, "notes")], 10.0)
    assert result.outcome is BindingOutcome.NONE
    assert "insufficient evidence" in result.reason


def test_the_real_binder_binds_a_continuous_stream_so_the_loss_is_the_stream() -> None:
    stream = [_obs(9.7 + i * 0.03, "notes") for i in range(15)]
    assert bind_demonstrative(stream, 10.0).outcome is BindingOutcome.BOUND


def test_nearest_pinch_sample_is_the_last_pinch_ray_fallback() -> None:
    a, b = _sample(9.0, RaySource.EYE), _sample(10.8, RaySource.EYE)
    head = _sample(10.0, RaySource.HEAD)
    got = nearest_pinch_sample([a, head, b], 10.0)
    assert got is not None and got[0] is b and got[1] == pytest.approx(0.8)
    got = nearest_pinch_sample([a, head, b], 9.5)  # skew -0.5 vs +1.3
    assert got is not None and got[0] is a and got[1] == pytest.approx(-0.5)
    assert nearest_pinch_sample([a, b], 20.0) is None  # both beyond 1.5 s
    assert nearest_pinch_sample([head], 10.0) is None  # head rays are not pinch rays


def test_nearest_pinch_sample_tie_goes_to_the_earlier() -> None:
    a, b = _sample(9.5, RaySource.EYE), _sample(10.5, RaySource.EYE)
    got = nearest_pinch_sample([b, a], 10.0)
    assert got is not None and got[0] is a


def test_nearest_pinch_sample_rejects_bad_numbers() -> None:
    with pytest.raises(ValueError):
        nearest_pinch_sample([], float("nan"))
    with pytest.raises(ValueError):
        nearest_pinch_sample([], 1.0, max_skew_s=-1.0)


# --- capability table ---------------------------------------------------------


def test_eye_gaze_is_not_provided_and_says_where_that_is_evidenced() -> None:
    cap = capability("eye_gaze_ray")
    assert cap.availability is Availability.NOT_PROVIDED
    assert "wwdc2025/303" in cap.source and "forums/thread/757357" in cap.source
    assert capability("hover_state").availability is Availability.NOT_PROVIDED


def test_selection_ray_is_event_only_and_hands_are_continuous() -> None:
    assert capability("selection_ray_at_pinch").availability is Availability.AT_EVENT_ONLY
    assert capability("hand_skeleton").availability is Availability.CONTINUOUS
    assert "Full Space" in capability("hand_skeleton").conditions


def test_every_capability_cites_a_public_apple_page() -> None:
    names = [c.name for c in CAPABILITIES]
    assert len(names) == len(set(names))
    for c in CAPABILITIES:
        assert c.source.startswith("https://developer.apple.com/"), c.name
        assert c.conditions
    with pytest.raises(KeyError, match="eye_gaze_ray"):
        capability("gaze")


def test_unverified_items_are_flagged_in_the_text_not_hidden() -> None:
    assert "UNVERIFIED" in capability("device_pose").conditions
    assert "UNVERIFIED" in capability("selection_ray_at_pinch").conditions


# --- consistency with the rest of the package ---------------------------------


def test_visionos_convention_is_the_identity_in_conventions() -> None:
    v = Vec3(1.0, 2.0, -3.0)
    assert to_canonical_vec(v, Convention.VISIONOS) == v


def test_the_vision_pro_profile_never_claims_an_app_gets_gaze() -> None:
    profile = devices.get("vision-pro")
    assert profile.has_hand_tracking is True
    assert profile.has_eye_tracking is not True  # None (unknown) or False; never True


# --- docs and source hygiene --------------------------------------------------


def test_docs_page_states_the_gaze_limit_and_is_library_not_wired() -> None:
    text = (_ROOT / "docs" / "xr-visionos.md").read_text(encoding="utf-8")
    lowered = " ".join(text.lower().split())
    assert "does not expose" in lowered or "not exposed" in lowered
    assert "continuous" in lowered and "gaze" in lowered
    assert "unverified" in lowered
    assert "not yet connected" in lowered or "not wired" in lowered
    assert "synthetic" in lowered
    for url in ("wwdc2025/303", "forums/thread/757357"):
        assert url in text


def test_module_docstring_names_the_limit_and_its_evidence() -> None:
    import yazses.xr.visionos as mod

    doc = " ".join((mod.__doc__ or "").split())
    assert "does not give an app the user's gaze" in doc
    assert "UNVERIFIED" in doc
    assert "https://developer.apple.com/videos/play/wwdc2025/303/" in doc


def test_visionos_module_is_stdlib_only_and_offline() -> None:
    import yazses.xr.visionos as mod

    path = Path(mod.__file__)
    source = path.read_text(encoding="utf-8")
    assert _outbound_findings(source) == []
    import ast

    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        for n in names:
            root = n.split(".")[0]
            assert root in {"__future__", "math", "enum", "dataclasses", "collections",
                            "yazses"}, f"{n} is not stdlib-or-package"
            if root == "yazses":
                assert n.startswith("yazses.xr."), n


def test_module_has_no_clock_and_no_module_level_mutable_state() -> None:
    import ast

    import yazses.xr.visionos as mod

    tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "time.time" not in src and "monotonic" not in src and "datetime" not in src
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Set)):
            raise AssertionError("module-level mutable literal")
