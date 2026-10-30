"""Tests for yazses.xr.smoothing — the One-Euro ray stabiliser and dwell read-out."""
from __future__ import annotations

import math
import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from yazses.xr.geometry import angle_between, norm
from yazses.xr.smoothing import RayFilter, dwell_progress
from yazses.xr.types import Ray, RaySource, Vec3, XrSample

ORIGIN = Vec3(0.0, 1.6, 0.0)


def yaw_dir(yaw: float, pitch: float = 0.0) -> Vec3:
    """Unit direction at ``yaw`` (about +Y) and ``pitch``; yaw 0 is straight ahead (-Z)."""
    return Vec3(
        math.sin(yaw) * math.cos(pitch),
        math.sin(pitch),
        -math.cos(yaw) * math.cos(pitch),
    )


def sample(
    t: float,
    yaw: float = 0.0,
    pitch: float = 0.0,
    origin: Vec3 = ORIGIN,
    source: RaySource = RaySource.EYE,
    confidence: float = 0.9,
) -> XrSample:
    return XrSample(t, source, Ray(origin, yaw_dir(yaw, pitch)), confidence)


def err(out: XrSample, yaw: float, pitch: float = 0.0) -> float:
    return angle_between(out.ray.direction, yaw_dir(yaw, pitch))


# --- parameters ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_cutoff_hz": 0.0},
        {"min_cutoff_hz": -1.0},
        {"min_cutoff_hz": math.nan},
        {"d_cutoff_hz": 0.0},
        {"d_cutoff_hz": math.inf},
        {"beta": -0.1},
        {"beta": math.nan},
        {"reset_gap_s": 0.0},
        {"reset_gap_s": math.inf},
    ],
)
def test_bad_parameters_are_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        RayFilter(**kwargs)


def test_zero_beta_is_allowed() -> None:
    assert RayFilter(beta=0.0).beta == 0.0


# --- fixed point and pass-through ---------------------------------------------------


def test_first_sample_passes_through_unchanged() -> None:
    f = RayFilter()
    s = sample(3.0, yaw=0.4, pitch=0.1)
    assert f.update(s) == s


def test_constant_input_is_a_fixed_point() -> None:
    f = RayFilter(beta=0.5)
    origin = Vec3(0.1, 1.5, -0.2)
    out = None
    for i in range(300):
        out = f.update(sample(i / 90.0, yaw=0.3, pitch=-0.2, origin=origin))
        assert err(out, 0.3, -0.2) < 1e-12
        assert norm(Vec3(out.ray.origin.x - 0.1, out.ray.origin.y - 1.5, out.ray.origin.z + 0.2)) < 1e-12
    assert out is not None


def test_metadata_is_preserved() -> None:
    f = RayFilter()
    f.update(sample(0.0, source=RaySource.HAND, confidence=0.3))
    out = f.update(sample(0.02, yaw=0.1, source=RaySource.HAND, confidence=0.3))
    assert out.timestamp_s == 0.02
    assert out.source is RaySource.HAND
    assert out.confidence == 0.3


def test_input_sample_is_not_mutated() -> None:
    f = RayFilter()
    f.update(sample(0.0))
    s = sample(0.02, yaw=0.5)
    before = s.ray
    out = f.update(s)
    assert s.ray == before
    assert out is not s


# --- dynamics -----------------------------------------------------------------------


def test_step_response_converges_monotonically() -> None:
    f = RayFilter(beta=2.0)
    for i in range(30):
        f.update(sample(i / 90.0, yaw=0.0))
    target = 0.4
    errors = []
    for i in range(30, 400):
        errors.append(err(f.update(sample(i / 90.0, yaw=target)), target))
    # Never overshoots, never moves away from the target. (Below ~1e-6 rad the acos in
    # angle_between is noise-limited, so the check stops there.)
    resolvable = [e for e in errors if e > 1e-6]
    assert len(resolvable) > 50
    assert all(b <= a + 1e-12 for a, b in zip(resolvable, resolvable[1:], strict=False))
    assert errors[0] < target  # it did start to move
    assert errors[-1] < 1e-3


def test_fast_motion_lags_less_than_slow_motion() -> None:
    """The One-Euro property: the time lag shrinks as the ray speeds up."""

    def steady_time_lag(speed_rad_s: float, beta: float) -> float:
        f = RayFilter(beta=beta)
        hz = 120.0
        out = None
        t = 0.0
        for _ in range(int(6 * hz)):
            out = f.update(sample(t, yaw=speed_rad_s * t))
            t += 1.0 / hz
        assert out is not None
        lag_rad = err(out, speed_rad_s * (t - 1.0 / hz))
        return lag_rad / speed_rad_s

    slow = steady_time_lag(0.1, beta=2.0)
    fast = steady_time_lag(3.0, beta=2.0)
    assert fast < slow / 3
    # Without the speed term the lag does not shrink (control experiment).
    flat_slow = steady_time_lag(0.1, beta=0.0)
    flat_fast = steady_time_lag(3.0, beta=0.0)
    assert flat_fast == pytest.approx(flat_slow, rel=0.15)
    assert fast < flat_fast / 3


def test_jitter_variance_is_reduced() -> None:
    rng = random.Random(20251030)
    f = RayFilter()
    in_sq = out_sq = 0.0
    n = 0
    for i in range(900):
        jy, jp = rng.gauss(0.0, 0.01), rng.gauss(0.0, 0.01)
        s = sample(i / 90.0, yaw=0.2 + jy, pitch=0.1 + jp)
        out = f.update(s)
        if i >= 90:  # past the warm-up
            in_sq += angle_between(s.ray.direction, yaw_dir(0.2, 0.1)) ** 2
            out_sq += err(out, 0.2, 0.1) ** 2
            n += 1
    assert n > 0
    assert out_sq / n < 0.25 * (in_sq / n)


def test_origin_is_smoothed_too() -> None:
    rng = random.Random(7)
    f = RayFilter()
    raw_sq = out_sq = 0.0
    for i in range(600):
        jitter = Vec3(rng.gauss(0, 0.005), rng.gauss(0, 0.005), rng.gauss(0, 0.005))
        o = Vec3(ORIGIN.x + jitter.x, ORIGIN.y + jitter.y, ORIGIN.z + jitter.z)
        out = f.update(sample(i / 90.0, origin=o))
        if i >= 60:
            raw_sq += jitter.x**2 + jitter.y**2 + jitter.z**2
            out_sq += (out.ray.origin.x - ORIGIN.x) ** 2 + (out.ray.origin.z - ORIGIN.z) ** 2 + (
                out.ray.origin.y - ORIGIN.y
            ) ** 2
    assert out_sq < 0.25 * raw_sq


# --- time handling ------------------------------------------------------------------


def test_out_of_order_sample_is_passed_through_and_ignored() -> None:
    a, b = RayFilter(), RayFilter()
    seq = [sample(i / 60.0, yaw=0.05 * i) for i in range(10)]
    for s in seq[:5]:
        a.update(s)
        b.update(s)
    late = sample(1.0 / 60.0, yaw=1.2)  # older than the last accepted sample
    assert a.update(late) is late  # unfiltered
    for s in seq[5:]:
        assert a.update(s) == b.update(s)  # state exactly as if it never arrived


def test_duplicate_timestamp_is_passed_through_and_ignored() -> None:
    a, b = RayFilter(), RayFilter()
    for i in range(4):
        a.update(sample(i / 60.0, yaw=0.1 * i))
        b.update(sample(i / 60.0, yaw=0.1 * i))
    dup = sample(3 / 60.0, yaw=-0.9)
    assert a.update(dup) is dup
    nxt = sample(4 / 60.0, yaw=0.4)
    assert a.update(nxt) == b.update(nxt)


def test_gap_longer_than_reset_gap_resets_state() -> None:
    f = RayFilter(reset_gap_s=0.5)
    for i in range(30):
        f.update(sample(i / 60.0, yaw=0.0))
    after = sample(0.5 + 29 / 60.0 + 0.01, yaw=0.8)  # just over the gap
    assert f.update(after) == after  # treated as a fresh first sample


def test_gap_at_exactly_reset_gap_does_not_reset() -> None:
    f = RayFilter(reset_gap_s=0.5)
    f.update(sample(0.0, yaw=0.0))
    s = sample(0.5, yaw=0.8)
    out = f.update(s)
    assert out != s and err(out, 0.8) > 0.0  # smoothed, not passed through


def test_gap_reset_restarts_the_velocity_estimate() -> None:
    f = RayFilter(beta=2.0)
    for i in range(60):
        f.update(sample(i / 60.0, yaw=0.05 * i))  # fast sweep builds a speed estimate
    t = 60 / 60.0 + 2.0
    f.update(sample(t, yaw=1.0))
    out = f.update(sample(t + 1 / 60.0, yaw=1.0))
    assert err(out, 1.0) < 1e-9  # no residual velocity carried over the gap


def test_reset_makes_next_sample_a_first_sample() -> None:
    f = RayFilter()
    f.update(sample(0.0))
    f.update(sample(0.01, yaw=0.2))
    f.reset()
    s = sample(0.02, yaw=0.9)
    assert f.update(s) == s
    # And an earlier timestamp is fine after reset (clock may restart).
    s2 = sample(0.0, yaw=0.1)
    assert f.update(s2) == s2


def test_antipodal_flip_returns_last_good_direction() -> None:
    dt = 0.01
    # beta=0 and tau == dt gives alpha == 0.5: the average of a and -a cancels out.
    f = RayFilter(min_cutoff_hz=1.0 / (2.0 * math.pi * dt), beta=0.0)
    first = f.update(sample(0.0, yaw=0.0))
    flipped = XrSample(dt, RaySource.EYE, Ray(ORIGIN, Vec3(0.0, 0.0, 1.0)), 0.9)
    out = f.update(flipped)
    assert out.ray.direction == first.ray.direction
    assert abs(norm(out.ray.direction) - 1.0) < 1e-12
    # The filter keeps working afterwards.
    nxt = f.update(sample(2 * dt, yaw=0.0))
    assert abs(norm(nxt.ray.direction) - 1.0) < 1e-12


def test_tiny_dt_does_not_poison_the_state() -> None:
    f = RayFilter(beta=1.0)
    f.update(sample(1.0, yaw=0.0))
    f.update(sample(1.0 + 1e-300 + 1e-12, yaw=0.5))  # huge apparent speed
    for i in range(1, 200):
        out = f.update(sample(1.0 + i / 90.0, yaw=0.5))
    assert err(out, 0.5) < 1e-3


# --- invariants (property tests) ----------------------------------------------------

_component = st.floats(min_value=-1.0, max_value=1.0, allow_nan=False, allow_infinity=False)
_vec = st.tuples(_component, _component, _component).filter(
    lambda v: math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) > 1e-3
)


def _unit(v: tuple[float, float, float]) -> Vec3:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return Vec3(v[0] / n, v[1] / n, v[2] / n)


@settings(max_examples=200, deadline=None)
@given(
    vecs=st.lists(_vec, min_size=1, max_size=40),
    dts=st.lists(st.floats(min_value=1e-4, max_value=0.8), min_size=40, max_size=40),
    min_cutoff=st.floats(min_value=0.05, max_value=50.0),
    beta=st.floats(min_value=0.0, max_value=20.0),
)
def test_output_direction_is_always_unit_length(
    vecs: list[tuple[float, float, float]],
    dts: list[float],
    min_cutoff: float,
    beta: float,
) -> None:
    f = RayFilter(min_cutoff_hz=min_cutoff, beta=beta)
    t = 0.0
    for v, dt in zip(vecs, dts, strict=False):
        t += dt
        out = f.update(XrSample(t, RaySource.HAND, Ray(ORIGIN, _unit(v)), 1.0))
        assert abs(norm(out.ray.direction) - 1.0) < 1e-9


@settings(max_examples=100, deadline=None)
@given(
    vecs=st.lists(_vec, min_size=2, max_size=30),
    stamps=st.lists(st.floats(min_value=0.0, max_value=5.0), min_size=30, max_size=30),
)
def test_arbitrary_timestamp_order_never_breaks_the_invariant(
    vecs: list[tuple[float, float, float]], stamps: list[float]
) -> None:
    f = RayFilter()
    for v, t in zip(vecs, stamps, strict=False):
        out = f.update(XrSample(t, RaySource.EYE, Ray(ORIGIN, _unit(v)), 0.5))
        assert abs(norm(out.ray.direction) - 1.0) < 1e-6
        assert math.isfinite(out.ray.origin.x + out.ray.origin.y + out.ray.origin.z)


# --- dwell_progress -----------------------------------------------------------------

CENTRE = yaw_dir(0.0)
RADIUS = math.radians(3.0)


def stream(yaws: list[float], hz: float = 100.0, t0: float = 0.0) -> list[XrSample]:
    return [sample(t0 + i / hz, yaw=y) for i, y in enumerate(yaws)]


def test_dwell_full_window_on_target_is_one() -> None:
    s = stream([0.0] * 101)  # t = 0.00 .. 1.00
    assert dwell_progress(s, CENTRE, RADIUS, now_s=1.0) == pytest.approx(1.0)


def test_dwell_never_on_target_is_zero() -> None:
    s = stream([0.5] * 101)
    assert dwell_progress(s, CENTRE, RADIUS, now_s=1.0) == 0.0


def test_dwell_empty_is_zero() -> None:
    assert dwell_progress([], CENTRE, RADIUS, now_s=1.0) == 0.0


def test_dwell_partial_is_time_weighted() -> None:
    # Off target for the first 0.4 s, on target for the last 0.6 s of the window.
    s = stream([0.5] * 40 + [0.0] * 61)
    assert dwell_progress(s, CENTRE, RADIUS, now_s=1.0) == pytest.approx(0.6, abs=1e-9)


def test_dwell_drops_when_the_ray_leaves() -> None:
    s = stream([0.0] * 80 + [0.5] * 21)  # on target for 0.8 s, then away
    assert dwell_progress(s, CENTRE, RADIUS, now_s=1.0) == pytest.approx(0.8, abs=1e-9)
    # Once the whole window is off target nothing is left.
    assert dwell_progress(s, CENTRE, RADIUS, now_s=1.8) == 0.0


def test_dwell_window_before_first_sample_counts_as_off_target() -> None:
    s = [sample(0.5, yaw=0.0)]  # first observation half-way into the window
    assert dwell_progress(s, CENTRE, RADIUS, now_s=1.0) == pytest.approx(0.5)


def test_dwell_last_sample_holds_until_now() -> None:
    s = [sample(0.0, yaw=0.0)]
    assert dwell_progress(s, CENTRE, RADIUS, now_s=1.0) == pytest.approx(1.0)


def test_dwell_ignores_samples_in_the_future() -> None:
    s = stream([0.0] * 51) + [sample(2.0, yaw=0.5)]
    assert dwell_progress(s, CENTRE, RADIUS, now_s=0.5, window_s=0.5) == pytest.approx(1.0)


def test_dwell_ignores_samples_before_the_window_except_the_one_holding() -> None:
    s = [sample(0.0, yaw=0.5), sample(4.0, yaw=0.0)]
    # window [4.5, 5.5]: the t=4.0 sample (on target) is still the current one.
    assert dwell_progress(s, CENTRE, RADIUS, now_s=5.5) == pytest.approx(1.0)


def test_dwell_radius_is_inclusive() -> None:
    edge = sample(0.0, yaw=RADIUS)
    angle = angle_between(edge.ray.direction, CENTRE)
    assert dwell_progress([edge], CENTRE, angle, now_s=1.0) == pytest.approx(1.0)
    assert dwell_progress([edge], CENTRE, angle * 0.999, now_s=1.0) == 0.0


def test_dwell_does_not_depend_on_input_order() -> None:
    s = stream([0.5] * 30 + [0.0] * 71)
    rev = list(reversed(s))
    assert dwell_progress(rev, CENTRE, RADIUS, 1.0) == dwell_progress(s, CENTRE, RADIUS, 1.0)


def test_dwell_normalises_the_centre() -> None:
    s = stream([0.0] * 101)
    assert dwell_progress(s, Vec3(0.0, 0.0, -5.0), RADIUS, now_s=1.0) == pytest.approx(1.0)


def test_dwell_custom_window() -> None:
    s = stream([0.5] * 50 + [0.0] * 51)  # on target from t=0.5
    assert dwell_progress(s, CENTRE, RADIUS, now_s=1.0, window_s=0.5) == pytest.approx(1.0)
    assert dwell_progress(s, CENTRE, RADIUS, now_s=1.0, window_s=2.0) == pytest.approx(0.25)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"radius_rad": -0.1},
        {"radius_rad": math.nan},
        {"now_s": math.inf},
        {"window_s": 0.0},
        {"window_s": -1.0},
    ],
)
def test_dwell_bad_arguments_are_refused(kwargs: dict[str, float]) -> None:
    args = {"radius_rad": RADIUS, "now_s": 1.0, "window_s": 1.0}
    args.update(kwargs)
    with pytest.raises(ValueError):
        dwell_progress([], CENTRE, **args)


def test_dwell_zero_centre_is_refused() -> None:
    with pytest.raises(ValueError):
        dwell_progress([], Vec3(0.0, 0.0, 0.0), RADIUS, 1.0)


@settings(max_examples=150, deadline=None)
@given(
    yaws=st.lists(st.floats(min_value=-1.0, max_value=1.0), min_size=0, max_size=40),
    now=st.floats(min_value=0.0, max_value=3.0),
    window=st.floats(min_value=0.05, max_value=3.0),
    radius=st.floats(min_value=0.0, max_value=3.2),
)
def test_dwell_progress_is_always_a_fraction(
    yaws: list[float], now: float, window: float, radius: float
) -> None:
    s = [sample(i * 0.07, yaw=y) for i, y in enumerate(yaws)]
    p = dwell_progress(s, CENTRE, radius, now, window_s=window)
    assert 0.0 <= p <= 1.0


# --- regressions: pass-through observability, extreme centre_dir -----------------------


def test_pass_through_counters_make_raw_samples_observable() -> None:
    f = RayFilter()
    for i in range(5):
        f.update(sample(i / 60.0, yaw=0.05 * i))
    assert (f.filtered_count, f.passed_through_count) == (5, 0)
    late = sample(1.0 / 60.0, yaw=1.2)
    assert f.update(late) is late  # documented: returned RAW
    assert (f.filtered_count, f.passed_through_count) == (5, 1)
    f.update(sample(5 / 60.0, yaw=0.3))
    f.update(sample(5 / 60.0, yaw=0.3))  # exact duplicate
    assert (f.filtered_count, f.passed_through_count) == (6, 2)


def test_counters_survive_a_gap_reset() -> None:
    f = RayFilter(reset_gap_s=0.5)
    f.update(sample(0.0))
    f.update(sample(0.0))  # duplicate
    f.update(sample(5.0))  # gap -> reset, then filtered as a new first sample
    assert (f.filtered_count, f.passed_through_count) == (2, 1)


def test_dwell_progress_with_huge_centre_dir_matches_unit_centre() -> None:
    # Reproducer: a 1e200 centre_dir used to raise a misleading zero-length error.
    samples = [sample(i / 10.0, yaw=0.0) for i in range(11)]
    unit = Vec3(0.0, 0.0, -1.0)
    huge = Vec3(0.0, 0.0, -1e200)
    expected = dwell_progress(samples, unit, 0.1, now_s=1.0, window_s=1.0)
    assert expected > 0.0
    assert dwell_progress(samples, huge, 0.1, now_s=1.0, window_s=1.0) == expected
    tiny = Vec3(0.0, 0.0, -1e-200)
    assert dwell_progress(samples, tiny, 0.1, now_s=1.0, window_s=1.0) == expected


def test_dwell_progress_zero_centre_dir_raises_a_clear_error() -> None:
    with pytest.raises(ValueError, match="centre_dir must be a non-zero vector"):
        dwell_progress([sample(0.0)], Vec3(0.0, 0.0, 0.0), 0.1, now_s=1.0)
