"""yazses.xr.binding — demonstrative-to-panel binding and the whole-utterance grammar."""
from __future__ import annotations

import math
import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from yazses.xr.binding import (
    BindingOutcome,
    BindingResult,
    DemonstrativeAction,
    PanelObservation,
    bind_demonstrative,
    nearest_rival,
    parse_demonstrative_command,
    ray_gap_deg,
    sustained_departure,
)
from yazses.xr.types import Panel, PanelHit, Ray, Vec3

ONSET = 10.0
# Binary-exact window (0.5 / 0.25) so edge timestamps compare exactly in floats.
KW = {"lead_s": 0.5, "lag_s": 0.25}


def obs(t: float, panel: str | None, conf: float = 0.9) -> PanelObservation:
    hit = None if panel is None else PanelHit(panel, 0.5, 0.5, 1.5)
    return PanelObservation(t, hit, conf)


def dwell(panel: str | None, start: float, length: float, rate_hz: float, conf: float = 0.9) -> list[PanelObservation]:
    """Samples on ``panel`` every 1/rate_hz over ``[start, start + length)``."""
    n = max(1, round(length * rate_hz))
    return [obs(start + i / rate_hz, panel, conf) for i in range(n)]


# --- binding ---------------------------------------------------------------------------


def test_clear_bind_to_dominant_panel() -> None:
    history = [obs(9.8, "A"), obs(9.9, "A"), obs(10.0, "A"), obs(10.1, "A"), obs(9.6, "B")]
    r = bind_demonstrative(history, ONSET, **KW)
    assert r.outcome is BindingOutcome.BOUND
    assert r.panel_id == "A"
    assert 0.5 < r.margin <= 1.0


def test_two_panel_ambiguity_never_guesses() -> None:
    # A just before the word, B just after: shares ~57/43, below min_share.
    history = [obs(t, "A") for t in (9.85, 9.9, 9.95)] + [obs(t, "B") for t in (10.05, 10.1, 10.15)]
    r = bind_demonstrative(history, ONSET, **KW)
    assert r.outcome is BindingOutcome.AMBIGUOUS
    assert r.panel_id is None
    assert 0.0 <= r.margin < 0.2


def test_exact_tie_is_ambiguous_even_with_a_low_min_share() -> None:
    history = [obs(t, p) for t in (9.95, 10.0, 10.05) for p in ("A", "B")]
    r = bind_demonstrative(history, ONSET, min_share=0.4, **KW)
    assert r.outcome is BindingOutcome.AMBIGUOUS
    assert r.panel_id is None


def test_no_observations_is_none() -> None:
    r = bind_demonstrative([], ONSET, **KW)
    assert r.outcome is BindingOutcome.NONE and r.panel_id is None


def test_sparse_but_sufficient_samples_bind() -> None:
    # Three samples at ~10 Hz around the onset: enough count and covered time.
    r = bind_demonstrative([obs(9.9, "A", 0.8), obs(10.0, "A", 0.8), obs(10.1, "A", 0.8)], ONSET, **KW)
    assert (r.outcome, r.panel_id) == (BindingOutcome.BOUND, "A")


def test_regression_one_stray_sample_does_not_bind() -> None:
    # Reproducer: a single conf-0.3 sample at the onset used to BIND at 100% share,
    # because shares are relative and one sample's mass beat the old min_mass.
    r = bind_demonstrative([obs(ONSET, "A", 0.3)], ONSET)
    assert r.outcome is BindingOutcome.NONE and r.panel_id is None
    assert "insufficient evidence" in r.reason


@pytest.mark.parametrize("conf", [0.3, 0.9, 1.0])
def test_one_or_two_samples_never_bind_at_any_confidence(conf: float) -> None:
    for history in ([obs(ONSET, "A", conf)], [obs(ONSET, "A", conf), obs(ONSET + 0.05, "A", conf)]):
        r = bind_demonstrative(history, ONSET)
        assert r.outcome is BindingOutcome.NONE
        assert "insufficient evidence" in r.reason


def test_enough_samples_but_too_little_covered_time_is_insufficient() -> None:
    # Five samples 1 ms apart: count is fine, but they cover ~5 ms of a 50 ms floor.
    history = [obs(ONSET + 0.001 * i, "A") for i in range(5)]
    r = bind_demonstrative(history, ONSET, **KW)
    assert r.outcome is BindingOutcome.NONE and "insufficient evidence" in r.reason
    assert bind_demonstrative(history, ONSET, min_coverage_s=0.0, **KW).outcome is BindingOutcome.BOUND


def test_a_dropout_does_not_credit_the_stale_panel_for_the_whole_gap() -> None:
    # A is seen, then nothing for 0.5 s, then B at the onset. With a 0.1 s cap A's tail
    # is credited 0.05 s, not 0.25 s, so B (nearer the onset, heavier weight) wins.
    history = [obs(9.6, "A"), obs(9.65, "A"), obs(9.7, "A"), obs(10.0, "B"), obs(10.05, "B"), obs(10.1, "B")]
    r = bind_demonstrative(history, ONSET, **KW)
    assert (r.outcome, r.panel_id) == (BindingOutcome.BOUND, "B")


@pytest.mark.parametrize(("rate_a", "rate_b"), [(30.0, 90.0), (90.0, 30.0), (60.0, 120.0)])
def test_regression_sample_rate_does_not_bias_the_verdict(rate_a: float, rate_b: float) -> None:
    # Reproducer: A and B dwelt 0.1 s each at the same confidence, A at 30 Hz and B at 90 Hz;
    # the old per-sample weighting gave B 71%. Symmetric around the onset so only the rate differs.
    sym = {"lead_s": 0.5, "lag_s": 0.5}
    history = dwell("A", ONSET - 0.3, 0.1, rate_a) + dwell("B", ONSET + 0.2, 0.1, rate_b)
    r = bind_demonstrative(history, ONSET, **sym)
    assert r.outcome is BindingOutcome.AMBIGUOUS
    assert r.margin < 0.2


@given(
    st.sampled_from([30.0, 45.0, 60.0, 90.0, 120.0]),
    st.sampled_from([30.0, 45.0, 60.0, 90.0, 120.0]),
    st.floats(min_value=0.3, max_value=1.0),
)
def test_property_equal_dwell_at_different_rates_gives_near_equal_shares(
    rate_a: float, rate_b: float, conf: float
) -> None:
    sym = {"lead_s": 0.5, "lag_s": 0.5}
    history = dwell("A", ONSET - 0.3, 0.1, rate_a, conf) + dwell("B", ONSET + 0.2, 0.1, rate_b, conf)
    r = bind_demonstrative(history, ONSET, **sym)
    assert r.outcome is BindingOutcome.AMBIGUOUS
    assert r.margin < 0.2


def test_regression_ambiguous_carries_the_real_margin_and_share() -> None:
    # A holds ~55% of the mass, B ~5%, the rest is empty space: still AMBIGUOUS (behaviour
    # kept), but the result reports the true lead, not a placeholder.
    sym = {"lead_s": 0.5, "lag_s": 0.5}
    history = (dwell("A", ONSET - 0.05, 0.11, 100.0) + dwell("B", ONSET + 0.2, 0.0111, 100.0)
               + dwell(None, ONSET - 0.3, 0.1, 100.0))
    r = bind_demonstrative(history, ONSET, **sym)
    assert r.outcome is BindingOutcome.AMBIGUOUS
    assert r.margin > 0.3
    assert r.top_share > r.margin
    assert r.confidence == 0.0


def test_confidence_is_the_weighted_mean_of_the_winning_evidence() -> None:
    history = [obs(9.9, "A", 0.6), obs(10.0, "A", 0.6), obs(10.1, "A", 0.6)]
    r = bind_demonstrative(history, ONSET, **KW)
    assert r.outcome is BindingOutcome.BOUND
    assert r.confidence == pytest.approx(0.6)


def test_confidence_weights_by_time_and_ignores_other_panels() -> None:
    # A: high confidence at the onset (heavy), low (but usable) at the lead edge (light).
    history = [obs(10.0, "A", 1.0), obs(9.95, "A", 1.0), obs(9.55, "A", 0.3), obs(9.5625, "B", 0.4)]
    r = bind_demonstrative(history, ONSET, min_coverage_s=0.0, **KW)
    assert r.outcome is BindingOutcome.BOUND and r.panel_id == "A"
    assert 0.9 < r.confidence <= 1.0


def test_confidence_is_zero_unless_bound() -> None:
    history = [obs(t, "A") for t in (9.85, 9.9, 9.95)] + [obs(t, "B") for t in (10.05, 10.1, 10.15)]
    r = bind_demonstrative(history, ONSET, **KW)
    assert r.outcome is BindingOutcome.AMBIGUOUS and r.confidence == 0.0
    with pytest.raises(ValueError):
        BindingResult(BindingOutcome.AMBIGUOUS, None, 0.0, "x", confidence=0.5)
    with pytest.raises(ValueError):
        BindingResult(BindingOutcome.BOUND, "A", 0.5, "x", confidence=1.5)
    assert BindingResult(BindingOutcome.BOUND, "A", 0.5, "x").confidence == 0.0  # default


def test_all_low_confidence_is_none() -> None:
    r = bind_demonstrative([obs(9.9, "A", 0.1), obs(10.0, "A", 0.29)], ONSET, **KW)
    assert r.outcome is BindingOutcome.NONE
    assert "min_confidence" in r.reason


def test_low_confidence_samples_do_not_sway_a_clear_winner() -> None:
    history = [obs(9.95, "A", 0.9), obs(10.0, "A", 0.9), obs(10.05, "A", 0.9),
               obs(10.0, "B", 0.29), obs(9.9, "B", 0.29)]
    r = bind_demonstrative(history, ONSET, **KW)
    assert (r.outcome, r.panel_id) == (BindingOutcome.BOUND, "A")


def test_observations_outside_the_window_are_ignored() -> None:
    history = [obs(9.0, "B"), obs(9.4, "B"), obs(10.3, "B"), obs(11.0, "B"),
               obs(9.95, "A"), obs(10.0, "A"), obs(10.05, "A")]
    r = bind_demonstrative(history, ONSET, **KW)
    assert (r.outcome, r.panel_id) == (BindingOutcome.BOUND, "A")
    assert r.margin == pytest.approx(1.0)


def test_only_outside_the_window_is_none() -> None:
    r = bind_demonstrative([obs(9.0, "A"), obs(11.0, "A")], ONSET, **KW)
    assert r.outcome is BindingOutcome.NONE
    assert "window" in r.reason


def test_unsorted_input_gives_the_same_verdict() -> None:
    history = [obs(9.8, "A"), obs(9.9, "A"), obs(10.0, "A"), obs(10.1, "B"), obs(9.6, "B")]
    expected = bind_demonstrative(history, ONSET, **KW)
    for seed in range(10):
        shuffled = history[:]
        random.Random(seed).shuffle(shuffled)
        assert bind_demonstrative(shuffled, ONSET, **KW) == expected
    assert bind_demonstrative(list(reversed(history)), ONSET, **KW) == expected


def test_window_edges_are_inclusive_but_carry_zero_weight() -> None:
    lo, hi = ONSET - 0.5, ONSET + 0.25
    # Edge samples alone: inside the window, zero weight, so no evidence.
    r = bind_demonstrative([obs(lo, "A"), obs(hi, "A")], ONSET, **KW)
    assert r.outcome is BindingOutcome.NONE
    assert "edge" in r.reason
    # They cannot sway a real winner either.
    r = bind_demonstrative([obs(9.95, "A"), obs(10.0, "A"), obs(10.05, "A"), obs(lo, "B"), obs(hi, "B")], ONSET, **KW)
    assert (r.outcome, r.panel_id) == (BindingOutcome.BOUND, "A")
    assert r.margin == pytest.approx(1.0)


def test_sample_just_inside_an_edge_counts_and_just_outside_does_not() -> None:
    just_in = ONSET - 0.5 + 1e-3
    just_out = math.nextafter(ONSET - 0.5, 0.0)
    a = [obs(t, "A", 0.4) for t in (9.95, 10.0, 10.05)]
    r_in = bind_demonstrative([*a, obs(just_in, "B", 1.0)], ONSET, **KW)
    r_out = bind_demonstrative([*a, obs(just_out, "B", 1.0)], ONSET, **KW)
    assert r_in.margin != r_out.margin  # B's sliver of mass registers only when inside
    assert r_out.margin == pytest.approx(1.0)


def test_observation_exactly_at_the_onset_has_full_weight() -> None:
    r = bind_demonstrative([obs(ONSET, "A", 0.5), obs(ONSET - 0.05, "A", 0.5), obs(ONSET + 0.05, "A", 0.5)],
                           ONSET, **KW)
    assert r.outcome is BindingOutcome.BOUND


def test_time_weight_prefers_the_sample_at_the_onset() -> None:
    # B is held far longer, but A is at the onset and B's samples sit near the lead edge.
    history = [obs(9.5 + 0.0625 * i, "B", 0.9) for i in range(1, 4)] + [obs(10.0, "A", 0.9)]
    r = bind_demonstrative(history, ONSET, min_share=0.5, **KW)
    assert r.outcome is BindingOutcome.BOUND and r.panel_id == "A"


def test_pointing_at_empty_space_blocks_a_brief_glance() -> None:
    history = [obs(9.9, None), obs(9.8, None), obs(10.0, "A")]
    r = bind_demonstrative(history, ONSET, **KW)
    assert r.outcome is BindingOutcome.NONE
    assert r.panel_id is None


def test_all_misses_is_none() -> None:
    r = bind_demonstrative([obs(10.0, None), obs(9.9, None), obs(9.95, None)], ONSET, **KW)
    assert r.outcome is BindingOutcome.NONE
    assert "no panel" in r.reason


def test_zero_lag_window_only_sees_the_past_and_the_onset() -> None:
    history = [obs(9.9, "A"), obs(9.95, "A"), obs(10.0, "A"), obs(10.05, "B")]
    r = bind_demonstrative(history, ONSET, lead_s=0.5, lag_s=0.0)
    assert (r.outcome, r.panel_id) == (BindingOutcome.BOUND, "A")


def test_zero_width_window_holds_no_time_so_it_never_binds() -> None:
    # Formerly a single sample at the exact onset bound; a zero-width window covers no
    # time, which is insufficient evidence by definition.
    r = bind_demonstrative([obs(10.0, "A"), obs(9.99, "B")], ONSET, lead_s=0.0, lag_s=0.0)
    assert r.outcome is BindingOutcome.NONE and "insufficient evidence" in r.reason


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lead_s": -0.1},
        {"lag_s": -0.1},
        {"lead_s": math.nan},
        {"lag_s": math.inf},
        {"min_share": 0.0},
        {"min_share": 1.1},
        {"min_confidence": -0.1},
        {"min_confidence": 1.5},
        {"min_mass": -1.0},
        {"max_gap_s": 0.0},
        {"max_gap_s": math.nan},
        {"min_samples": 0},
        {"min_samples": 2.5},
        {"min_coverage_s": -0.1},
    ],
)
def test_bad_parameters_raise(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        bind_demonstrative([obs(10.0, "A")], ONSET, **kwargs)


@pytest.mark.parametrize("onset", [math.nan, math.inf, -math.inf])
def test_non_finite_onset_raises(onset: float) -> None:
    with pytest.raises(ValueError):
        bind_demonstrative([obs(10.0, "A")], onset)


def test_observation_validation() -> None:
    with pytest.raises(ValueError):
        PanelObservation(math.nan, None, 0.5)
    with pytest.raises(ValueError):
        PanelObservation(-1.0, None, 0.5)
    with pytest.raises(ValueError):
        PanelObservation(1.0, None, 1.5)
    with pytest.raises(ValueError):
        PanelObservation(1.0, None, math.nan)
    with pytest.raises(ValueError):
        PanelObservation(1.0, "A", 0.5)  # type: ignore[arg-type]


def test_result_invariant_panel_id_iff_bound() -> None:
    with pytest.raises(ValueError):
        BindingResult(BindingOutcome.BOUND, None, 0.5, "x")
    with pytest.raises(ValueError):
        BindingResult(BindingOutcome.AMBIGUOUS, "A", 0.0, "x")


_panels = st.sampled_from(["A", "B", "C", None])
_obs = st.builds(
    lambda t, p, c: obs(t, p, c),
    st.floats(min_value=9.0, max_value=11.0),
    _panels,
    st.floats(min_value=0.0, max_value=1.0),
)


@given(st.lists(_obs, max_size=12), st.randoms(use_true_random=False))
def test_property_order_invariant_and_well_formed(history: list[PanelObservation], rng) -> None:
    r = bind_demonstrative(history, ONSET, **KW)
    shuffled = history[:]
    rng.shuffle(shuffled)
    assert bind_demonstrative(shuffled, ONSET, **KW) == r
    assert (r.outcome is BindingOutcome.BOUND) == (r.panel_id is not None)
    if r.outcome is BindingOutcome.BOUND:
        assert r.panel_id in {o.hit.panel_id for o in history if o.hit is not None}
        assert 0.0 < r.margin <= 1.0


# --- evidence for the confirm policy: candidates, rival, prior panel ---------------------


def rival_obs(t: float, panel: str, rival: str | None, deg: float | None, conf: float = 0.9) -> PanelObservation:
    return PanelObservation(t, PanelHit(panel, 0.5, 0.5, 1.5), conf, rival, deg)


def test_bound_result_reports_the_top_two_candidates() -> None:
    h = dwell("A", 9.6, 0.6, 90) + dwell("B", 9.9, 0.08, 90)
    r = bind_demonstrative(h, ONSET, **KW)
    assert r.outcome is BindingOutcome.BOUND and r.candidates == ("A", "B")
    only = bind_demonstrative(dwell("A", 9.6, 0.6, 90), ONSET, **KW)
    assert only.candidates == ("A",)


def test_ambiguous_result_reports_both_candidates() -> None:
    h = dwell("A", 9.55, 0.4, 90) + dwell("B", 9.95, 0.4, 90)
    r = bind_demonstrative(h, ONSET, **KW)
    assert r.outcome is BindingOutcome.AMBIGUOUS and set(r.candidates) == {"A", "B"}


def test_the_new_evidence_never_changes_the_verdict() -> None:
    # Same pointing, with and without rival data: identical outcome, panel, margin, confidence, share.
    base = dwell("A", 9.6, 0.6, 90)
    rich = [rival_obs(o.timestamp_s, "A", "B", 1.0) for o in base]
    a, b = bind_demonstrative(base, ONSET, **KW), bind_demonstrative(rich, ONSET, **KW)
    assert (a.outcome, a.panel_id, a.margin, a.confidence, a.top_share) == (
        b.outcome, b.panel_id, b.margin, b.confidence, b.top_share)
    assert a.rival_deg is None and b.rival_deg == pytest.approx(1.0) and b.rival_id == "B"


def test_rival_is_the_evidence_weighted_mean_over_the_winning_rays_only() -> None:
    h = [rival_obs(9.7 + i / 90, "A", "B", 2.0) for i in range(54)]
    h += [rival_obs(10.0 + i / 90, "A", "C", 6.0) for i in range(5)]       # barely any weight
    h += [rival_obs(10.1 + i / 90, "B", "A", 0.1) for i in range(4)]       # loser: must not count
    r = bind_demonstrative(h, ONSET, **KW)
    assert r.panel_id == "A" and r.rival_id == "B"
    assert 2.0 <= r.rival_deg <= 2.5


def test_unmeasured_rivals_stay_none() -> None:
    r = bind_demonstrative(dwell("A", 9.6, 0.6, 90), ONSET, **KW)
    assert r.rival_id is None and r.rival_deg is None


def test_prior_panel_and_settled_time() -> None:
    # B until ~9.69, then A: the gaze left B ~0.31 s before the word.
    h = dwell("B", 9.2, 0.5, 90) + dwell("A", 9.7, 0.6, 90)
    r = bind_demonstrative(h, ONSET, **KW)
    assert r.panel_id == "A" and r.prior_panel == "B"
    assert r.settled_s == pytest.approx(0.31, abs=0.02)


def test_a_settled_gaze_reports_a_large_settle_time() -> None:
    h = dwell("B", 8.8, 0.4, 90) + dwell("A", 9.4, 1.0, 90)
    r = bind_demonstrative(h, ONSET, **KW)
    assert r.prior_panel == "B" and r.settled_s == pytest.approx(0.8, abs=0.05)


def test_no_prior_panel_when_only_the_bound_panel_was_seen() -> None:
    r = bind_demonstrative(dwell("A", 8.6, 1.8, 90), ONSET, **KW)
    assert r.prior_panel is None and r.settled_s is None


def test_a_grazing_sweep_is_not_a_prior_panel() -> None:
    h = dwell("A", 9.0, 0.7, 90) + dwell("B", 9.7, 0.04, 90) + dwell("A", 9.74, 0.6, 90)
    assert bind_demonstrative(h, ONSET, **KW).prior_panel is None


def test_history_outside_the_horizon_is_ignored() -> None:
    h = dwell("B", 7.0, 0.5, 90) + dwell("A", 9.4, 1.0, 90)
    assert bind_demonstrative(h, ONSET, history_s=1.5, **KW).prior_panel is None
    assert bind_demonstrative(h, ONSET, history_s=3.5, **KW).prior_panel == "B"


def test_low_confidence_samples_do_not_make_a_prior_panel() -> None:
    h = dwell("B", 9.2, 0.5, 90, conf=0.1) + dwell("A", 9.7, 0.6, 90)
    assert bind_demonstrative(h, ONSET, **KW).prior_panel is None


def test_samples_after_the_onset_are_not_history() -> None:
    h = dwell("A", 9.6, 0.4, 90) + dwell("B", 10.0, 0.2, 90)
    assert bind_demonstrative(h, ONSET, **KW).prior_panel is None


@pytest.mark.parametrize("kw", [{"history_s": -1.0}, {"min_prior_dwell_s": -0.1},
                                {"history_s": math.nan}, {"min_prior_dwell_s": math.inf}])
def test_bad_history_parameters_raise(kw: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        bind_demonstrative(dwell("A", 9.6, 0.6, 90), ONSET, **KW, **kw)


def test_observation_rival_validation() -> None:
    hit = PanelHit("A", 0.5, 0.5, 1.0)
    with pytest.raises(ValueError):
        PanelObservation(1.0, hit, 0.5, "B", None)
    with pytest.raises(ValueError):
        PanelObservation(1.0, hit, 0.5, None, 1.0)
    with pytest.raises(ValueError):
        PanelObservation(1.0, hit, 0.5, "B", -1.0)
    with pytest.raises(ValueError):
        PanelObservation(1.0, hit, 0.5, "B", math.nan)
    with pytest.raises(ValueError):
        PanelObservation(1.0, hit, 0.5, "A", 1.0)   # the rival must be another panel
    with pytest.raises(ValueError):
        PanelObservation(1.0, hit, 0.5, "", 1.0)


def test_result_evidence_invariants() -> None:
    with pytest.raises(ValueError):
        BindingResult(BindingOutcome.BOUND, "A", 0.5, "x", candidates=("B", "A"))
    with pytest.raises(ValueError):
        BindingResult(BindingOutcome.BOUND, "A", 0.5, "x", candidates=("A", "A"))
    with pytest.raises(ValueError):
        BindingResult(BindingOutcome.AMBIGUOUS, None, 0.0, "x", rival_id="B", rival_deg=1.0)
    with pytest.raises(ValueError):
        BindingResult(BindingOutcome.BOUND, "A", 0.5, "x", prior_panel="B")
    with pytest.raises(ValueError):
        BindingResult(BindingOutcome.BOUND, "A", 0.5, "x", rival_id="B", rival_deg=-1.0)


# --- ray_gap_deg / nearest_rival: geometry, with answers computed by hand ---------------

FACE = Vec3(0.0, 0.0, 1.0)
UP = Vec3(0.0, 1.0, 0.0)


def pan(pid: str, x: float, w: float = 1.0, h: float = 1.0) -> Panel:
    return Panel(pid, Vec3(x, 0.0, -2.0), FACE, UP, w, h)


def ray_toward(x: float, y: float = 0.0) -> Ray:
    n = math.sqrt(x * x + y * y + 4.0)
    return Ray(Vec3(0.0, 0.0, 0.0), Vec3(x / n, y / n, -2.0 / n))


def test_a_ray_on_the_panel_has_zero_gap() -> None:
    assert ray_gap_deg(ray_toward(0.0), pan("A", 0.0)) == 0.0
    assert ray_gap_deg(ray_toward(0.5), pan("A", 0.0)) == 0.0   # exactly on the edge counts as on


def test_gap_to_a_side_panel_matches_the_hand_angle() -> None:
    # Panel B spans x in [0.5, 1.5] at z=-2. A ray toward x=0.1 is atan(0.5/2)-atan(0.1/2) away.
    expected = math.degrees(math.atan2(0.5, 2.0) - math.atan2(0.1, 2.0))
    assert ray_gap_deg(ray_toward(0.1), pan("B", 1.0)) == pytest.approx(expected, abs=1e-9)


def test_gap_to_the_corner_is_a_diagonal_angle() -> None:
    # Ray toward (0,0); panel spans x in [1,2], y in [1,2]: nearest point is the corner (1,1).
    corner = Vec3(1.0, 1.0, -2.0)
    expected = math.degrees(math.acos(2.0 / math.sqrt(1 + 1 + 4)))
    assert ray_gap_deg(ray_toward(0.0), Panel("C", Vec3(1.5, 1.5, -2.0), FACE, UP, 1.0, 1.0)) == pytest.approx(
        expected, abs=1e-9)
    assert corner  # the corner the expected angle was derived from


def test_gap_is_none_when_the_panel_cannot_be_reached() -> None:
    assert ray_gap_deg(Ray(Vec3(0, 0, 0), Vec3(0, 0, 1)), pan("A", 0.0)) is None        # pointing away
    assert ray_gap_deg(Ray(Vec3(0, 0, 0), Vec3(1, 0, 0)), pan("A", 0.0)) is None        # parallel
    back = Panel("A", Vec3(0, 0, -2), Vec3(0, 0, -1), UP, 1.0, 1.0)
    assert ray_gap_deg(ray_toward(0.0), back) is None                                    # back face
    assert ray_gap_deg(ray_toward(0.0), pan("A", 0.0), max_distance_m=1.0) is None       # too far


def test_gap_decreases_as_the_ray_moves_toward_the_panel() -> None:
    gaps = [ray_gap_deg(ray_toward(x), pan("B", 2.0)) for x in (-0.5, 0.0, 0.5, 1.5)]
    assert all(g is not None for g in gaps)
    assert gaps == sorted(gaps, reverse=True) and gaps[-1] == 0.0


def test_nearest_rival_skips_the_hit_panel_and_breaks_ties_by_id() -> None:
    panels = [pan("A", 0.0), pan("C", 1.5), pan("B", -1.5)]
    r = nearest_rival(ray_toward(0.0), "A", panels)
    assert r is not None and r[0] == "B"                       # symmetric: tie goes to the smaller id
    assert nearest_rival(ray_toward(0.0), "A", [pan("A", 0.0)]) is None
    assert nearest_rival(ray_toward(0.0), None, [pan("A", 0.0)]) == ("A", 0.0)


# --- sustained_departure ----------------------------------------------------------------


def test_nothing_departed_when_the_gaze_is_still_on_the_bound_panel() -> None:
    h = dwell("A", 10.0, 0.8, 90)
    assert sustained_departure(h, "A", ONSET, 10.8) == (None, 0.0)


def test_a_rested_look_elsewhere_is_measured_first_to_last_sample() -> None:
    h = dwell("A", 9.6, 0.5, 90) + dwell("B", 10.1, 0.6, 90)
    panel, secs = sustained_departure(h, "A", ONSET, 10.7)
    assert panel == "B" and secs == pytest.approx(0.6, abs=0.02)


def test_a_glance_that_returned_does_not_count() -> None:
    h = dwell("A", 9.6, 0.5, 90) + dwell("B", 10.1, 0.3, 90) + dwell("A", 10.4, 0.3, 90)
    assert sustained_departure(h, "A", ONSET, 10.7) == (None, 0.0)


def test_a_gap_in_the_run_breaks_it() -> None:
    h = dwell("B", 10.1, 0.2, 90) + dwell("B", 10.5, 0.2, 90)       # 0.2 s hole
    panel, secs = sustained_departure(h, "A", ONSET, 10.7)
    assert panel == "B" and secs == pytest.approx(0.2, abs=0.02)


def test_empty_space_at_the_end_is_not_a_departure() -> None:
    h = dwell("B", 10.1, 0.3, 90) + dwell(None, 10.4, 0.3, 90)
    assert sustained_departure(h, "A", ONSET, 10.7) == (None, 0.0)


def test_only_the_window_after_the_onset_counts() -> None:
    h = dwell("B", 9.0, 0.9, 90)                    # all before the onset
    assert sustained_departure(h, "A", ONSET, 10.7) == (None, 0.0)
    assert sustained_departure([], "A", ONSET, 10.7) == (None, 0.0)


def test_low_confidence_samples_are_ignored_by_the_departure() -> None:
    h = dwell("B", 10.1, 0.6, 90, conf=0.1)
    assert sustained_departure(h, "A", ONSET, 10.7) == (None, 0.0)


@given(st.lists(_obs, max_size=14), st.randoms(use_true_random=False))
def test_property_departure_is_order_invariant_and_bounded(history: list[PanelObservation], rng) -> None:
    a = sustained_departure(history, "A", ONSET, 10.7)
    shuffled = history[:]
    rng.shuffle(shuffled)
    assert sustained_departure(shuffled, "A", ONSET, 10.7) == a
    assert 0.0 <= a[1] <= 0.7 + 1e-9
    assert a[0] is not None or a[1] == 0.0
    assert a[0] != "A"


@given(st.lists(_obs, max_size=14), st.randoms(use_true_random=False))
def test_property_new_evidence_is_order_invariant_and_consistent(history: list[PanelObservation], rng) -> None:
    r = bind_demonstrative(history, ONSET, **KW)
    shuffled = history[:]
    rng.shuffle(shuffled)
    assert bind_demonstrative(shuffled, ONSET, **KW) == r
    assert len(r.candidates) <= 2
    if r.outcome is BindingOutcome.BOUND:
        assert r.candidates[0] == r.panel_id and r.prior_panel != r.panel_id
        assert (r.prior_panel is None) == (r.settled_s is None)
        if r.settled_s is not None:
            assert 0.0 <= r.settled_s <= 1.5 + 1e-9


# --- grammar ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "action", "words"),
    [
        ("type here", DemonstrativeAction.DICTATE, ("here",)),
        ("Dictate here.", DemonstrativeAction.DICTATE, ("here",)),
        ("  write   there!  ", DemonstrativeAction.DICTATE, ("there",)),
        ("put it there", DemonstrativeAction.PLACE, ("there",)),
        ("Put it here.", DemonstrativeAction.PLACE, ("here",)),
        ("send this there", DemonstrativeAction.PLACE, ("this", "there")),
        ("put that there", DemonstrativeAction.PLACE, ("that", "there")),
        ("SEND THAT HERE?", DemonstrativeAction.PLACE, ("that", "here")),
    ],
)
def test_command_forms_parse(text: str, action: DemonstrativeAction, words: tuple[str, ...]) -> None:
    cmd = parse_demonstrative_command(text)
    assert cmd is not None
    assert cmd.action is action
    assert cmd.deictic_words == words
    assert cmd.raw_text == text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "this",
        "that",
        "here",
        "type",
        "this is a test",
        "I think that is right",
        "what is this",
        "please put it there",
        "put it there please",
        "type here is the thing",
        "send this to Bob",
        "send this there and then close it",
        "put the book there",
        "the meeting is here and that is fine",
        "I want you to dictate here",
        "that's here",
        "put it",
        "send there",
    ],
)
def test_ordinary_sentences_never_parse(text: str) -> None:
    assert parse_demonstrative_command(text) is None
