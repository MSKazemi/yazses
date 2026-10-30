"""Synthetic XR trajectories: determinism, counts, geometry, noise, dropout, scenarios."""
from __future__ import annotations

import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from yazses.xr.geometry import angle_between, norm
from yazses.xr.raycast import nearest_hit
from yazses.xr.synth import (
    DEFAULT_EYE,
    Scenario,
    dropout,
    fixation,
    make_scenarios,
    panel_point,
    saccade,
    sweep_between,
    with_confidence_ramp,
)
from yazses.xr.types import Panel, RaySource, Vec3

# A panel 2 m ahead of the default eye, facing the user: right = +X, up = +Y.
FRONT = Panel("front", Vec3(0.0, 1.6, -2.0), Vec3(0.0, 0.0, 1.0), Vec3(0.0, 1.0, 0.0), 1.0, 0.5)
LEFT = Panel("left", Vec3(-2.0, 1.6, -2.0), Vec3(0.0, 0.0, 1.0), Vec3(0.0, 1.0, 0.0), 1.0, 0.5)
RIGHT = Panel("right", Vec3(2.0, 1.6, -2.0), Vec3(0.0, 0.0, 1.0), Vec3(0.0, 1.0, 0.0), 1.0, 0.5)


def _dirs(samples):
    return [s.ray.direction for s in samples]


def _strictly_increasing(samples) -> bool:
    return all(b.timestamp_s > a.timestamp_s for a, b in zip(samples, samples[1:]))


# --- panel_point / exact aim -------------------------------------------------


def test_panel_point_hand_computed_corners():
    assert panel_point(FRONT, 0.5, 0.5) == Vec3(0.0, 1.6, -2.0)
    p = panel_point(FRONT, 1.0, 1.0)  # right edge, top edge
    assert (p.x, p.y, p.z) == pytest.approx((0.5, 1.85, -2.0))
    p = panel_point(FRONT, 0.0, 0.0)  # left edge, bottom edge
    assert (p.x, p.y, p.z) == pytest.approx((-0.5, 1.35, -2.0))


def test_zero_noise_aims_exactly_at_the_target_point():
    # Centre: straight down -Z.
    (s,) = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=1 / 90)
    d = s.ray.direction
    assert (d.x, d.y, d.z) == pytest.approx((0.0, 0.0, -1.0), abs=1e-12)
    # Top-right corner: (0.5, 0.25, -2) normalised; |.| = sqrt(4.3125).
    (s,) = fixation(FRONT, 1.0, 1.0, start_s=0.0, duration_s=1 / 90)
    n = math.sqrt(4.3125)
    d = s.ray.direction
    assert (d.x, d.y, d.z) == pytest.approx((0.5 / n, 0.25 / n, -2.0 / n), abs=1e-12)
    assert s.ray.origin == DEFAULT_EYE


def test_zero_noise_samples_are_all_identical_in_direction():
    samples = fixation(LEFT, 0.3, 0.7, start_s=1.0, duration_s=0.5)
    assert len(set(_dirs(samples))) == 1


def test_custom_eye_and_source_and_confidence_propagate():
    eye = Vec3(0.0, 1.6, -1.0)
    (s,) = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=1 / 90, eye=eye,
                    source=RaySource.HEAD, confidence=0.4)
    assert s.ray.origin == eye
    assert s.source is RaySource.HEAD
    assert s.confidence == 0.4
    assert (s.ray.direction.z) == pytest.approx(-1.0)


# --- determinism -------------------------------------------------------------


def test_same_seed_identical_different_seed_different():
    kw = {"start_s": 0.5, "duration_s": 1.0, "noise_rad": 0.02}
    a = fixation(FRONT, 0.4, 0.6, seed=7, **kw)
    b = fixation(FRONT, 0.4, 0.6, seed=7, **kw)
    c = fixation(FRONT, 0.4, 0.6, seed=8, **kw)
    assert a == b
    assert a != c


def test_module_level_random_is_never_used():
    import random

    random.seed(1)
    a = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=0.5, noise_rad=0.05, seed=3)
    random.seed(999)
    b = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=0.5, noise_rad=0.05, seed=3)
    assert a == b


def test_scenarios_deterministic_per_seed():
    a = make_scenarios([FRONT, LEFT, RIGHT], 10, seed=5, noise_rad=0.01)
    b = make_scenarios([FRONT, LEFT, RIGHT], 10, seed=5, noise_rad=0.01)
    c = make_scenarios([FRONT, LEFT, RIGHT], 10, seed=6, noise_rad=0.01)
    assert a == b
    assert a != c


def test_sweep_deterministic_per_seed():
    kw = {"start_s": 0.0, "dwell_a_s": 0.4, "dwell_b_s": 0.4, "noise_rad": 0.01}
    assert sweep_between(LEFT, RIGHT, seed=1, **kw) == sweep_between(LEFT, RIGHT, seed=1, **kw)
    assert sweep_between(LEFT, RIGHT, seed=1, **kw) != sweep_between(LEFT, RIGHT, seed=2, **kw)


# --- counts, timestamps, unit rays ------------------------------------------


@pytest.mark.parametrize(("hz", "dur", "expected"), [(90, 1.0, 90), (60, 0.5, 30), (30, 2.0, 60), (90, 0.0, 0)])
def test_count_matches_hz_times_duration(hz, dur, expected):
    assert len(fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=dur, hz=hz)) == expected


def test_timestamps_start_at_start_s_on_the_hz_grid():
    s = fixation(FRONT, 0.5, 0.5, start_s=2.0, duration_s=0.1, hz=50)
    assert [x.timestamp_s for x in s] == pytest.approx([2.0, 2.02, 2.04, 2.06, 2.08])


@settings(max_examples=60, deadline=None)
@given(
    u=st.floats(0, 1),
    v=st.floats(0, 1),
    start=st.floats(0, 1e4),
    dur=st.floats(0, 3),
    hz=st.floats(1, 240),
    noise=st.floats(0, 0.5),
    seed=st.integers(0, 2**32),
)
def test_fixation_rays_unit_timestamps_increasing_count_exact(u, v, start, dur, hz, noise, seed):
    samples = fixation(FRONT, u, v, start_s=start, duration_s=dur, hz=hz, noise_rad=noise, seed=seed)
    assert len(samples) == math.floor(dur * hz + 0.5)
    assert _strictly_increasing(samples)
    for s in samples:
        assert s.timestamp_s >= 0
        assert norm(s.ray.direction) == pytest.approx(1.0, abs=1e-9)


@settings(max_examples=60, deadline=None)
@given(
    a=st.tuples(st.floats(-1, 1), st.floats(-1, 1), st.floats(-1, 1)).filter(lambda t: math.hypot(*t) > 1e-3),
    b=st.tuples(st.floats(-1, 1), st.floats(-1, 1), st.floats(-1, 1)).filter(lambda t: math.hypot(*t) > 1e-3),
    noise=st.floats(0, 0.3),
    seed=st.integers(0, 2**32),
)
def test_saccade_rays_are_unit_and_stay_between_endpoints(a, b, noise, seed):
    va, vb = Vec3(*a), Vec3(*b)
    samples = saccade(va, vb, start_s=0.0, duration_s=0.1, noise_rad=0.0 if noise < 0.01 else noise, seed=seed)
    assert len(samples) == 9
    assert _strictly_increasing(samples)
    total = angle_between(va, vb)
    for s in samples:
        assert norm(s.ray.direction) == pytest.approx(1.0, abs=1e-9)
    if noise < 0.01:  # noiseless: every point lies on the arc, within its span
        for s in samples:
            da = angle_between(va, s.ray.direction)
            db = angle_between(s.ray.direction, vb)
            assert da + db == pytest.approx(total, abs=1e-6)


def test_saccade_handles_identical_and_antiparallel_endpoints():
    same = saccade(Vec3(0, 0, -1), Vec3(0, 0, -2), start_s=0.0, duration_s=0.1)
    assert all(s.ray.direction == Vec3(0, 0, -1) for s in same)
    flip = saccade(Vec3(0, 0, -1), Vec3(0, 0, 1), start_s=0.0, duration_s=0.1)
    for s in flip:
        assert norm(s.ray.direction) == pytest.approx(1.0)
    mid = flip[len(flip) // 2].ray.direction  # halfway through an eased half-turn
    assert angle_between(Vec3(0, 0, -1), mid) == pytest.approx(math.pi / 2, abs=1e-6)


def test_saccade_moves_monotonically_from_start_to_end():
    start, end = Vec3(-1, 0, -1), Vec3(1, 0, -1)
    s = saccade(start, end, start_s=0.0, duration_s=0.1)
    angles = [angle_between(start, x.ray.direction) for x in s]
    assert angles == sorted(angles)
    assert 0 < angles[0] and angles[-1] < angle_between(start, end)


def test_sweep_between_is_gapless_and_visits_both_panels():
    s = sweep_between(LEFT, RIGHT, start_s=1.0, dwell_a_s=0.5, dwell_b_s=0.5, saccade_s=0.1)
    assert len(s) == 45 + 9 + 45
    assert _strictly_increasing(s)
    assert s[0].timestamp_s == 1.0
    # Every sample sits on the 1/90 grid: no gap or overlap between segments.
    steps = [b.timestamp_s - a.timestamp_s for a, b in zip(s, s[1:])]
    assert steps == pytest.approx([1 / 90] * len(steps), abs=1e-9)
    assert s[0].ray.direction.x < 0 < s[-1].ray.direction.x
    # Saccade samples lie strictly between the two fixation directions.
    mid = s[45 + 4].ray.direction
    assert s[0].ray.direction.x < mid.x < s[-1].ray.direction.x


# --- noise statistics --------------------------------------------------------


def test_mean_angular_error_matches_noise_rad():
    noise = 0.02
    samples = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=250.0, hz=90.0,
                       noise_rad=noise, seed=2024)
    ideal = Vec3(0.0, 0.0, -1.0)
    errs = [angle_between(ideal, s.ray.direction) for s in samples]
    assert len(errs) == 22500
    assert sum(errs) / len(errs) == pytest.approx(noise, rel=0.03)


def test_noise_is_isotropic_about_the_aim():
    # No bias: the mean of the jittered directions leans toward the aim, not off to a side.
    samples = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=100.0, noise_rad=0.05, seed=11)
    mx = sum(s.ray.direction.x for s in samples) / len(samples)
    my = sum(s.ray.direction.y for s in samples) / len(samples)
    assert abs(mx) < 2e-3 and abs(my) < 2e-3


# --- dropout / confidence ramp ----------------------------------------------


def test_dropout_removes_exactly_the_window():
    s = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=2.0, hz=10)
    out = dropout(s, 0.5, 1.0)
    removed = [x for x in s if x not in out]
    assert [x.timestamp_s for x in removed] == pytest.approx([0.5, 0.6, 0.7, 0.8, 0.9])
    assert len(out) == len(s) - 5
    assert all(x in s for x in out)  # survivors are untouched, order preserved
    assert out == [x for x in s if not 0.5 <= x.timestamp_s < 1.0]


def test_dropout_edge_cases():
    s = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=1.0, hz=10)
    assert dropout(s, 5.0, 6.0) == s
    assert dropout(s, 0.3, 0.3) == s  # empty window removes nothing
    assert dropout(s, 0.0, 100.0) == []
    assert dropout([], 0.0, 1.0) == []
    with pytest.raises(ValueError):
        dropout(s, 1.0, 0.5)
    with pytest.raises(ValueError):
        dropout(s, float("nan"), 1.0)


@settings(max_examples=50, deadline=None)
@given(a=st.floats(0, 3), width=st.floats(0, 3))
def test_dropout_property_survivors_are_exactly_outside_window(a, width):
    s = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=3.0, hz=30)
    out = dropout(s, a, a + width)
    assert all(not a <= x.timestamp_s < a + width for x in out)
    assert len(out) + sum(1 for x in s if a <= x.timestamp_s < a + width) == len(s)


def test_confidence_ramp_linear_inside_untouched_outside():
    s = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=2.0, hz=10, confidence=0.9)
    out = with_confidence_ramp(s, 0.5, 1.5, 1.0, 0.0)
    assert len(out) == len(s)
    for before, after in zip(s, out):
        t = before.timestamp_s
        assert after.timestamp_s == t and after.ray == before.ray
        if 0.5 <= t <= 1.5:
            assert after.confidence == pytest.approx(1.0 - (t - 0.5))
        else:
            assert after.confidence == 0.9


def test_confidence_ramp_validation():
    s = fixation(FRONT, 0.5, 0.5, start_s=0.0, duration_s=1.0)
    with pytest.raises(ValueError):
        with_confidence_ramp(s, 1.0, 1.0, 1.0, 0.0)
    with pytest.raises(ValueError):
        with_confidence_ramp(s, 0.0, 1.0, 1.5, 0.0)


# --- scenarios --------------------------------------------------------------


def test_scenarios_are_labelled_and_well_formed():
    panels = [FRONT, LEFT, RIGHT]
    scenarios = make_scenarios(panels, 40, seed=3, noise_rad=0.01)
    assert len(scenarios) == 40
    ids = {p.panel_id for p in panels}
    for sc in scenarios:
        assert isinstance(sc, Scenario)
        assert sc.truth_panel_id in ids
        assert _strictly_increasing(sc.samples)
        assert sc.samples[0].timestamp_s >= 0
        assert sc.samples[0].timestamp_s <= sc.word_onset_s <= sc.samples[-1].timestamp_s
        for s in sc.samples:
            assert norm(s.ray.direction) == pytest.approx(1.0, abs=1e-9)
    assert len({sc.truth_panel_id for sc in scenarios}) > 1  # truth varies


def test_scenario_lead_is_measured_from_look_onset():
    for sc in make_scenarios([FRONT, LEFT], 20, seed=1, lead_s_range=(0.25, 0.25)):
        assert sc.word_onset_s - sc.samples[0].timestamp_s == pytest.approx(0.25)


def test_zero_lead_means_eyes_are_on_the_truth_panel_at_onset():
    panels = {p.panel_id: p for p in (LEFT, RIGHT)}
    for sc in make_scenarios(list(panels.values()), 20, seed=2, lead_s_range=(0.0, 0.0)):
        first = sc.samples[0].ray.direction
        assert (first.x < 0) == (sc.truth_panel_id == "left")


def test_long_lead_means_eyes_have_moved_to_the_other_panel():
    # ADJUSTED for the label fix: a long lead no longer makes the eyes move on by itself
    # (the fixation stretches to cover the lead). Looking away is now the explicit
    # ``look_away_prob`` knob; with it at 1 the gaze at the word is on the distractor.
    for sc in make_scenarios(
        [LEFT, RIGHT], 20, seed=4, lead_s_range=(1.5, 1.5), look_away_prob=1.0
    ):
        at_word = min(sc.samples, key=lambda s: abs(s.timestamp_s - sc.word_onset_s))
        gaze_left = at_word.ray.direction.x < 0
        assert gaze_left == (sc.truth_panel_id == "right")


def test_single_panel_scenarios_keep_gaze_on_the_truth():
    for sc in make_scenarios([FRONT], 5, seed=9, lead_s_range=(0.0, 2.0)):
        assert sc.truth_panel_id == "front"
        assert sc.samples[0].timestamp_s <= sc.word_onset_s <= sc.samples[-1].timestamp_s
        assert all(s.ray.direction.z < 0 for s in sc.samples)


def test_scenario_validation():
    with pytest.raises(ValueError):
        Scenario((), -1.0, "x")
    with pytest.raises(ValueError):
        Scenario((), 0.0, "")
    assert isinstance(Scenario([], 0.0, "x").samples, tuple)
    with pytest.raises(ValueError):
        make_scenarios([], 1)
    with pytest.raises(ValueError):
        make_scenarios([FRONT, FRONT], 1)
    with pytest.raises(ValueError):
        make_scenarios([FRONT], 1, lead_s_range=(0.5, 0.1))
    with pytest.raises(ValueError):
        make_scenarios([FRONT], 1, lead_s_range=(-0.1, 0.1))
    with pytest.raises(ValueError):
        make_scenarios([FRONT], -1)
    assert make_scenarios([FRONT], 0) == []


# --- argument validation ----------------------------------------------------


@pytest.mark.parametrize(
    "kw",
    [
        {"start_s": -0.1, "duration_s": 1.0},
        {"start_s": 0.0, "duration_s": -1.0},
        {"start_s": 0.0, "duration_s": 1.0, "hz": 0},
        {"start_s": 0.0, "duration_s": 1.0, "hz": float("inf")},
        {"start_s": 0.0, "duration_s": 1.0, "noise_rad": -0.1},
        {"start_s": float("nan"), "duration_s": 1.0},
        {"start_s": 0.0, "duration_s": 1.0, "confidence": 1.5},
    ],
)
def test_fixation_rejects_bad_arguments(kw):
    with pytest.raises(ValueError):
        fixation(FRONT, 0.5, 0.5, **kw)


@pytest.mark.parametrize(("u", "v"), [(-0.1, 0.5), (0.5, 1.1), (float("nan"), 0.5)])
def test_fixation_rejects_off_panel_or_nan_target(u, v):
    with pytest.raises(ValueError):
        fixation(FRONT, u, v, start_s=0.0, duration_s=1.0)


def test_timestamp_grid_that_float_precision_collapses_is_refused():
    with pytest.raises(ValueError):
        fixation(FRONT, 0.5, 0.5, start_s=1e17, duration_s=1.0)


# --- label honesty: intent (truth_panel_id) versus measured gaze --------------

PANEL_SETS = {
    "three": [FRONT, LEFT, RIGHT],
    "two": [LEFT, RIGHT],
    "one": [FRONT],
}


def _ray_at_onset_hit(sc, panels):
    prior = [s for s in sc.samples if s.timestamp_s <= sc.word_onset_s]
    hit = nearest_hit(prior[-1].ray, panels)
    return hit.panel_id if hit is not None else None


@pytest.mark.parametrize("name", ["three", "two", "one"])
@pytest.mark.parametrize("lead", [(0.0, 0.0), (0.2, 0.8), (0.0, 2.0), (1.5, 3.0)])
def test_default_gaze_at_onset_is_the_intended_panel_noise_free(name, lead):
    panels = PANEL_SETS[name]
    scenarios = make_scenarios(panels, 2000, seed=11, lead_s_range=lead)
    assert len(scenarios) == 2000
    bad = [sc for sc in scenarios if sc.gaze_panel_at_onset != sc.truth_panel_id]
    assert bad == []
    # The field is a measurement, reproducible from the samples alone.
    for sc in scenarios[:200]:
        assert sc.gaze_panel_at_onset == _ray_at_onset_hit(sc, panels)
        assert sc.samples[-1].timestamp_s >= sc.word_onset_s


@pytest.mark.parametrize("name", ["three", "two", "one"])
def test_look_away_differs_exactly_when_the_eyes_moved_on(name):
    panels = PANEL_SETS[name]
    scenarios = make_scenarios(
        panels, 2000, seed=12, lead_s_range=(0.0, 1.0), look_away_prob=1.0
    )
    assert all(sc.gaze_panel_at_onset != sc.truth_panel_id for sc in scenarios)
    # Probability 0.5: both strata present, and the label is measured, not assumed.
    mixed = make_scenarios(panels, 2000, seed=13, look_away_prob=0.5)
    away = sum(sc.gaze_panel_at_onset != sc.truth_panel_id for sc in mixed)
    assert 800 < away < 1200
    for sc in mixed[:200]:
        assert sc.gaze_panel_at_onset == _ray_at_onset_hit(sc, panels)
        assert sc.samples[-1].timestamp_s >= sc.word_onset_s


def test_look_away_lone_panel_gazes_at_nothing():
    for sc in make_scenarios([FRONT], 50, seed=2, look_away_prob=1.0):
        assert sc.gaze_panel_at_onset is None
        assert sc.truth_panel_id == "front"


def test_look_away_prob_validation_and_determinism():
    for bad in (-0.1, 1.1, float("nan")):
        with pytest.raises(ValueError):
            make_scenarios([FRONT, LEFT], 1, look_away_prob=bad)
    a = make_scenarios([FRONT, LEFT], 10, seed=5, noise_rad=0.01, look_away_prob=0.5)
    assert a == make_scenarios([FRONT, LEFT], 10, seed=5, noise_rad=0.01, look_away_prob=0.5)


def test_gaze_label_under_noise_is_still_what_the_rays_hit():
    panels = [FRONT, LEFT, RIGHT]
    for sc in make_scenarios(panels, 300, seed=21, noise_rad=0.05, look_away_prob=0.3):
        assert sc.gaze_panel_at_onset == _ray_at_onset_hit(sc, panels)


def test_scenario_backwards_compatible_positional_use():
    sc = Scenario((), 0.5, "x")
    assert sc.gaze_panel_at_onset is None
    assert Scenario((), 0.5, "x", "y").gaze_panel_at_onset == "y"
    with pytest.raises(ValueError):
        Scenario((), 0.5, "x", "")


def test_saccade_between_equal_nonunit_directions_does_not_crash():
    # Hypothesis found this: rounding makes angle_between(a, a) ~1e-8 while the
    # perpendicular residual is exactly zero.
    d = Vec3(0.1402908948744861, 0.3125, 0.1402908948744861)
    out = saccade(d, d, start_s=0.0, duration_s=0.1)
    assert out and all(norm(s.ray.direction) == pytest.approx(1.0, abs=1e-9) for s in out)
