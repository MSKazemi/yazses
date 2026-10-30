"""Tests for ``yazses.xr.confirm`` — the guard must be silent on the common path."""
from __future__ import annotations

import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from yazses.xr.confirm import (
    ConfirmDecision,
    ConfirmPolicy,
    ConfirmReason,
    Evidence,
    decide,
    expected_prompt_rate,
)


def clean(**over):
    """A bound, confident, non-destructive target on an unchanged panel."""
    kw = dict(outcome="bound", margin=0.6, confidence=0.9, destructive=False,
              panel_at_onset="a", panel_at_end="a")
    kw.update(over)
    return decide(**kw)


# ── the silent common path ────────────────────────────────────────────────────

def test_clean_bind_is_silent():
    d = clean()
    assert d == ConfirmDecision(False, ConfirmReason.NONE)
    assert d.release_word == "yes"


def test_missing_panel_observations_are_not_a_change():
    for onset, end in ((None, None), ("a", None), (None, "a")):
        assert clean(panel_at_onset=onset, panel_at_end=end).confirm is False


# ── each reason ───────────────────────────────────────────────────────────────

def test_ambiguous_confirms():
    d = clean(outcome="ambiguous")
    assert (d.confirm, d.reason) == (True, ConfirmReason.AMBIGUOUS_PANELS)


def test_target_changed_confirms():
    d = clean(panel_at_end="b")
    assert (d.confirm, d.reason) == (True, ConfirmReason.TARGET_CHANGED_DURING_UTTERANCE)


def test_destructive_from_ray_confirms():
    d = clean(destructive=True)
    assert (d.confirm, d.reason) == (True, ConfirmReason.DESTRUCTIVE_ACTION)


def test_low_confidence_confirms():
    d = clean(confidence=0.1)
    assert (d.confirm, d.reason) == (True, ConfirmReason.LOW_CONFIDENCE)


def test_low_margin_confirms():
    d = clean(margin=0.05)
    assert (d.confirm, d.reason) == (True, ConfirmReason.LOW_CONFIDENCE)


def test_none_outcome_is_no_target_not_a_prompt():
    d = clean(outcome="none", margin=0.0, confidence=0.0, panel_at_onset=None, panel_at_end=None)
    assert d == ConfirmDecision(False, ConfirmReason.NO_TARGET)
    assert d.reason is not ConfirmReason.NONE


def test_destructive_with_no_target_does_not_prompt():
    # No ray chose the target, so a ray cannot have misrouted it (needs_confirm parity).
    assert clean(outcome="none", destructive=True).confirm is False


def test_none_outcome_beats_every_other_signal():
    d = clean(outcome="none", destructive=True, confidence=0.0, margin=0.0,
              panel_at_onset="a", panel_at_end="b")
    assert d.reason is ConfirmReason.NO_TARGET


# ── precedence (only the reported reason, never whether to hold) ──────────────

def test_ambiguous_outranks_change_destructive_and_low_confidence():
    d = clean(outcome="ambiguous", panel_at_end="b", destructive=True, confidence=0.0)
    assert d.reason is ConfirmReason.AMBIGUOUS_PANELS


def test_change_outranks_destructive_and_low_confidence():
    d = clean(panel_at_end="b", destructive=True, confidence=0.0)
    assert d.reason is ConfirmReason.TARGET_CHANGED_DURING_UTTERANCE


def test_destructive_outranks_low_confidence():
    assert clean(destructive=True, confidence=0.0).reason is ConfirmReason.DESTRUCTIVE_ACTION


# ── threshold boundaries ──────────────────────────────────────────────────────

def test_confidence_boundary_is_inclusive_on_the_passing_side():
    assert clean(confidence=0.35).confirm is False
    assert clean(confidence=0.3499999).confirm is True


def test_margin_boundary_is_inclusive_on_the_passing_side():
    assert clean(margin=0.25).confirm is False
    assert clean(margin=0.2499999).confirm is True


def test_custom_thresholds_are_honoured():
    assert clean(confidence=0.5, min_confidence=0.6).confirm is True
    assert clean(confidence=0.6, min_confidence=0.6).confirm is False
    assert clean(margin=0.4, min_margin=0.5).confirm is True
    assert clean(margin=0.5, min_margin=0.5).confirm is False


def test_zero_thresholds_never_hold_on_confidence():
    assert clean(confidence=0.0, margin=0.0, min_confidence=0.0, min_margin=0.0).confirm is False


def test_extreme_confidence_values_accepted():
    assert clean(confidence=0.0).reason is ConfirmReason.LOW_CONFIDENCE
    assert clean(confidence=1.0).reason is ConfirmReason.NONE


def test_margin_may_exceed_one():
    assert clean(margin=7.5).confirm is False


# ── input validation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("kw", [
    {"outcome": "bounded"},
    {"outcome": ""},
    {"outcome": "BOUND"},
    {"confidence": -0.01},
    {"confidence": 1.01},
    {"confidence": float("nan")},
    {"confidence": float("inf")},
    {"margin": -0.01},
    {"margin": float("nan")},
    {"margin": float("-inf")},
    {"min_confidence": float("nan")},
    {"min_margin": -0.1},
    {"min_confidence": -0.1},
    {"confidence": True},
    {"margin": "0.5"},
])
def test_bad_input_raises(kw):
    with pytest.raises(ValueError):
        clean(**kw)


def test_decide_is_keyword_only():
    with pytest.raises(TypeError):
        decide("bound", 0.5, 0.9, False, "a", "a")  # type: ignore[misc]


# ── ConfirmDecision invariants ────────────────────────────────────────────────

def test_decision_is_frozen():
    d = clean()
    with pytest.raises(AttributeError):
        d.confirm = True  # type: ignore[misc]


@pytest.mark.parametrize("confirm,reason", [
    (True, ConfirmReason.NONE),
    (True, ConfirmReason.NO_TARGET),
    (False, ConfirmReason.AMBIGUOUS_PANELS),
    (False, ConfirmReason.LOW_CONFIDENCE),
    (False, ConfirmReason.DESTRUCTIVE_ACTION),
    (False, ConfirmReason.TARGET_CHANGED_DURING_UTTERANCE),
    (False, ConfirmReason.NEAR_PANEL_EDGE),
    (False, ConfirmReason.RECENT_PANEL_SWITCH),
])
def test_decision_rejects_contradictory_pairs(confirm, reason):
    with pytest.raises(ValueError):
        ConfirmDecision(confirm, reason)


@pytest.mark.parametrize("word", ["", "yes please", " ", "ye\ns", "ok\t"])
def test_release_must_be_one_word(word):
    with pytest.raises(ValueError):
        ConfirmDecision(True, ConfirmReason.LOW_CONFIDENCE, release_word=word)


def test_custom_one_word_release_allowed():
    assert ConfirmDecision(True, ConfirmReason.LOW_CONFIDENCE, "confirm").release_word == "confirm"


def test_every_reason_is_reachable_and_consistent():
    seen = {
        clean().reason, clean(outcome="none").reason, clean(outcome="ambiguous").reason,
        clean(confidence=0.0).reason, clean(destructive=True).reason, clean(panel_at_end="b").reason,
        clean(evidence=Evidence(rival_id="b", rival_deg=1.0)).reason,
        clean(evidence=Evidence(prior_panel="b", settled_s=0.1)).reason,
    }
    assert seen == set(ConfirmReason)


# ── properties ────────────────────────────────────────────────────────────────

_panel = st.one_of(st.none(), st.sampled_from(["a", "b", "c"]))


@given(
    margin=st.floats(0.25, 5.0),
    confidence=st.floats(0.35, 1.0),
    panel=st.sampled_from(["a", "b", "c"]),
)
def test_any_clean_bound_target_is_silent(margin, confidence, panel):
    d = decide(outcome="bound", margin=margin, confidence=confidence, destructive=False,
               panel_at_onset=panel, panel_at_end=panel)
    assert d == ConfirmDecision(False, ConfirmReason.NONE)


@given(
    outcome=st.sampled_from(["bound", "ambiguous", "none"]),
    margin=st.floats(0.0, 5.0),
    confidence=st.floats(0.0, 1.0),
    destructive=st.booleans(),
    onset=_panel,
    end=_panel,
)
def test_confirm_flag_always_matches_reason(outcome, margin, confidence, destructive, onset, end):
    d = decide(outcome=outcome, margin=margin, confidence=confidence, destructive=destructive,
               panel_at_onset=onset, panel_at_end=end)
    assert d.confirm == (d.reason not in (ConfirmReason.NONE, ConfirmReason.NO_TARGET))
    if outcome == "none":
        assert d.reason is ConfirmReason.NO_TARGET
    if outcome == "ambiguous":
        assert d.confirm


@given(confidence=st.floats(0.0, 1.0), margin=st.floats(0.0, 5.0))
def test_raising_a_threshold_never_removes_a_hold(confidence, margin):
    kw = dict(outcome="bound", margin=margin, confidence=confidence, destructive=False,
              panel_at_onset="a", panel_at_end="a")
    loose = decide(**kw, min_confidence=0.2, min_margin=0.1)
    strict = decide(**kw, min_confidence=0.6, min_margin=0.5)
    assert strict.confirm or not loose.confirm


# ── evidence rules: specific, checkable, and silent when the evidence is absent ───────────

def ev(**over):
    kw = dict(panel_id="a", top_share=0.95, runner_up="b")
    kw.update(over)
    return Evidence(**kw)


def test_evidence_with_nothing_alarming_is_silent():
    d = clean(evidence=ev(rival_id="b", rival_deg=25.0, prior_panel="b", settled_s=2.0,
                          departure_s=0.0, departure_panel=None))
    assert d == ConfirmDecision(False, ConfirmReason.NONE)


def test_unmeasured_evidence_can_never_fire_a_rule():
    # Absence of data is not a signal: every field None means every evidence rule is off.
    assert clean(evidence=Evidence()).confirm is False
    assert clean(evidence=ev()).confirm is False


def test_a_neighbour_inside_the_error_budget_holds_and_names_it():
    d = clean(evidence=ev(rival_id="b", rival_deg=2.0))
    assert (d.confirm, d.reason) == (True, ConfirmReason.NEAR_PANEL_EDGE)
    assert d.candidates == ("a", "b")


def test_a_neighbour_outside_the_error_budget_is_silent():
    assert clean(evidence=ev(rival_id="b", rival_deg=3.0)).confirm is False   # inclusive on the passing side
    assert clean(evidence=ev(rival_id="b", rival_deg=2.999)).confirm is True


def test_error_budget_zero_turns_the_edge_rule_off():
    pol = ConfirmPolicy(error_budget_deg=0.0)
    assert clean(evidence=ev(rival_id="b", rival_deg=0.0), policy=pol).confirm is False


def test_a_fresh_arrival_from_another_panel_holds_and_offers_both():
    d = clean(evidence=ev(prior_panel="c", settled_s=0.1))
    assert (d.confirm, d.reason) == (True, ConfirmReason.RECENT_PANEL_SWITCH)
    assert d.candidates == ("a", "c")


def test_a_settled_gaze_is_silent_even_with_a_prior_panel():
    assert clean(evidence=ev(prior_panel="c", settled_s=0.3)).confirm is False
    assert clean(evidence=ev(prior_panel="c", settled_s=0.2999)).confirm is True


def test_settle_zero_turns_the_switch_rule_off():
    assert clean(evidence=ev(prior_panel="c", settled_s=0.0), policy=ConfirmPolicy(settle_s=0.0)).confirm is False


def test_a_glance_away_is_not_a_changed_target_but_a_rested_look_is():
    glance = clean(panel_at_end="b", evidence=ev(departure_s=0.2, departure_panel="b"))
    assert glance.confirm is False   # the instantaneous comparison alone no longer holds
    rested = clean(panel_at_end="b", evidence=ev(departure_s=0.5, departure_panel="b"))
    assert (rested.confirm, rested.reason) == (True, ConfirmReason.TARGET_CHANGED_DURING_UTTERANCE)
    assert rested.candidates == ("a", "b")


def test_without_a_measured_departure_the_instantaneous_comparison_still_applies():
    assert clean(panel_at_end="b", evidence=ev()).reason is ConfirmReason.TARGET_CHANGED_DURING_UTTERANCE


def test_zero_departure_never_counts_even_with_a_zero_threshold():
    assert clean(evidence=ev(departure_s=0.0), policy=ConfirmPolicy(min_departure_s=0.0)).confirm is False


def test_top_share_under_the_floor_holds():
    d = clean(evidence=ev(top_share=0.55))
    assert (d.confirm, d.reason) == (True, ConfirmReason.LOW_CONFIDENCE)
    assert d.candidates == ("a", "b")
    assert clean(evidence=ev(top_share=0.6)).confirm is False


def test_ambiguous_offers_the_two_candidates():
    d = clean(outcome="ambiguous", evidence=ev(runner_up="b"))
    assert d.reason is ConfirmReason.AMBIGUOUS_PANELS and d.candidates == ("a", "b")
    assert clean(outcome="ambiguous").candidates == ()


def test_destructive_offers_only_the_bound_panel():
    assert clean(destructive=True, evidence=ev()).candidates == ("a",)


def test_precedence_among_the_new_reasons_is_fixed():
    both = ev(rival_id="b", rival_deg=1.0, prior_panel="c", settled_s=0.0, departure_s=2.0, departure_panel="d")
    assert clean(evidence=both, destructive=True, confidence=0.0).reason is ConfirmReason.RECENT_PANEL_SWITCH
    no_switch = ev(rival_id="b", rival_deg=1.0, departure_s=2.0, departure_panel="d")
    assert clean(evidence=no_switch).reason is ConfirmReason.NEAR_PANEL_EDGE
    assert clean(evidence=ev(departure_s=2.0, departure_panel="d")).reason is ConfirmReason.TARGET_CHANGED_DURING_UTTERANCE


def test_none_and_ambiguous_still_beat_the_evidence_rules():
    loud = ev(rival_id="b", rival_deg=0.0, prior_panel="c", settled_s=0.0)
    assert clean(outcome="none", evidence=loud).reason is ConfirmReason.NO_TARGET
    assert clean(outcome="ambiguous", evidence=loud).reason is ConfirmReason.AMBIGUOUS_PANELS


@pytest.mark.parametrize("kw", [
    {"top_share": -0.1}, {"top_share": 1.1}, {"top_share": float("nan")},
    {"rival_deg": -1.0}, {"rival_deg": float("inf")}, {"settled_s": -0.1},
    {"departure_s": -0.1}, {"departure_s": True},
])
def test_evidence_rejects_bad_numbers(kw):
    with pytest.raises(ValueError):
        Evidence(**kw)


@pytest.mark.parametrize("kw", [
    {"min_top_share": 1.5}, {"error_budget_deg": -1.0}, {"settle_s": float("nan")},
    {"min_departure_s": -0.5}, {"settle_s": True},
])
def test_policy_rejects_bad_numbers(kw):
    with pytest.raises(ValueError):
        ConfirmPolicy(**kw)


def test_decision_candidates_are_bounded_distinct_and_only_on_a_hold():
    with pytest.raises(ValueError):
        ConfirmDecision(True, ConfirmReason.NEAR_PANEL_EDGE, candidates=("a", "b", "c"))
    with pytest.raises(ValueError):
        ConfirmDecision(True, ConfirmReason.NEAR_PANEL_EDGE, candidates=("a", "a"))
    with pytest.raises(ValueError):
        ConfirmDecision(False, ConfirmReason.NONE, candidates=("a",))
    with pytest.raises(ValueError):
        ConfirmDecision(True, ConfirmReason.NEAR_PANEL_EDGE, candidates=("",))


# adversarial hand-built cases (not drawn from the synthetic generator) ------------------

def test_a_rested_look_of_exactly_the_threshold_holds_and_a_hair_less_does_not():
    assert clean(evidence=ev(departure_s=0.5)).confirm is True
    assert clean(evidence=ev(departure_s=0.4999)).confirm is False


def test_edge_rule_fires_on_the_neighbour_not_on_distance_to_the_own_edge():
    # A ray 0.5 deg inside its own panel's edge with NO neighbour near is not a hold.
    assert clean(evidence=ev(rival_id=None, rival_deg=None)).confirm is False


def test_a_strong_clean_bind_with_every_signal_at_its_boundary_stays_silent():
    boundary = ev(top_share=0.6, rival_id="b", rival_deg=3.0, prior_panel="c", settled_s=0.3, departure_s=0.4999)
    assert clean(margin=0.25, confidence=0.35, evidence=boundary).confirm is False


def test_the_evidence_prompt_rate_on_a_clean_stream_is_zero():
    rng = random.Random(3)
    stream = [
        decide(outcome="bound", margin=rng.uniform(0.3, 1), confidence=rng.uniform(0.4, 1), destructive=False,
               panel_at_onset="a", panel_at_end="a",
               evidence=ev(top_share=rng.uniform(0.7, 1), rival_id="b", rival_deg=rng.uniform(3.5, 40),
                           prior_panel="c", settled_s=rng.uniform(0.35, 2.0), departure_s=rng.uniform(0, 0.45)))
        for _ in range(500)
    ]
    assert expected_prompt_rate(stream) == 0.0


# ── properties: monotone, and no silent bind under the share floor ──────────────────────────

_ev_strategy = st.builds(
    Evidence,
    panel_id=st.just("a"),
    top_share=st.one_of(st.none(), st.floats(0.0, 1.0)),
    runner_up=st.sampled_from([None, "b"]),
    rival_id=st.sampled_from([None, "b"]),
    rival_deg=st.one_of(st.none(), st.floats(0.0, 30.0)),
    prior_panel=st.sampled_from([None, "c"]),
    settled_s=st.one_of(st.none(), st.floats(0.0, 3.0)),
    departure_s=st.one_of(st.none(), st.floats(0.0, 3.0)),
    departure_panel=st.sampled_from([None, "d"]),
)


def _held(e: Evidence, pol: ConfirmPolicy = ConfirmPolicy(), **over) -> bool:
    kw = dict(outcome="bound", margin=0.6, confidence=0.9, destructive=False,
              panel_at_onset="a", panel_at_end="a")
    kw.update(over)
    return decide(**kw, evidence=e, policy=pol).confirm


@given(e=_ev_strategy, floor=st.floats(0.0, 1.0))
def test_no_silent_bind_when_top_share_is_under_the_floor(e, floor):
    if e.top_share is not None and e.top_share < floor:
        assert _held(e, ConfirmPolicy(min_top_share=floor)), "a bind under min_top_share must never be silent"


@given(e=_ev_strategy, delta=st.floats(0.0, 5.0))
def test_more_evidence_never_lowers_a_hold(e, delta):
    """Each signal is monotone: moving it toward 'riskier' can only keep or add a hold."""
    from dataclasses import replace
    base = _held(e)
    riskier = []
    if e.top_share is not None:
        riskier.append(replace(e, top_share=max(0.0, e.top_share - delta / 5)))
    if e.rival_deg is not None:
        riskier.append(replace(e, rival_deg=max(0.0, e.rival_deg - delta)))
    if e.settled_s is not None:
        riskier.append(replace(e, settled_s=max(0.0, e.settled_s - delta)))
    if e.departure_s is not None:
        riskier.append(replace(e, departure_s=e.departure_s + delta))
    for r in riskier:
        assert _held(r) or not base


@given(e=_ev_strategy,
       a=st.floats(0.0, 10.0), b=st.floats(0.0, 10.0),
       s1=st.floats(0.0, 2.0), s2=st.floats(0.0, 2.0),
       d1=st.floats(0.0, 2.0), d2=st.floats(0.0, 2.0))
def test_a_stricter_policy_never_removes_a_hold(e, a, b, s1, s2, d1, d2):
    loose = ConfirmPolicy(error_budget_deg=min(a, b), settle_s=min(s1, s2), min_departure_s=max(d1, d2))
    strict = ConfirmPolicy(error_budget_deg=max(a, b), settle_s=max(s1, s2), min_departure_s=min(d1, d2))
    assert _held(e, strict) or not _held(e, loose)


@given(e=_ev_strategy, outcome=st.sampled_from(["bound", "ambiguous", "none"]),
       destructive=st.booleans(), conf=st.floats(0.0, 1.0), margin=st.floats(0.0, 1.0))
def test_candidates_only_on_a_hold_and_always_valid(e, outcome, destructive, conf, margin):
    d = decide(outcome=outcome, margin=margin, confidence=conf, destructive=destructive,
               panel_at_onset="a", panel_at_end="a", evidence=e)
    assert len(d.candidates) <= 2 and len(set(d.candidates)) == len(d.candidates)
    if not d.confirm:
        assert d.candidates == ()


# ── firing rate (SYNTHETIC data; re-measure on real sessions) ─────────────────

def _decisions(n: int, rng: random.Random, *, noisy: bool = True) -> list[ConfirmDecision]:
    """A realistic-looking mix: mostly clean binds, a thin tail of each hold condition."""
    out: list[ConfirmDecision] = []
    for i in range(n):
        slot = i % 100 if noisy else 99
        p = rng.choice(["a", "b", "c"])
        if slot < 1:        # 1% ambiguous
            out.append(decide(outcome="ambiguous", margin=rng.uniform(0, 0.2), confidence=0.8,
                              destructive=False, panel_at_onset=p, panel_at_end=p))
        elif slot < 2:      # 1% gaze moved mid-utterance
            q = "b" if p != "b" else "c"
            out.append(decide(outcome="bound", margin=0.6, confidence=0.9, destructive=False,
                              panel_at_onset=p, panel_at_end=q))
        elif slot < 3:      # 1% destructive command ("close this")
            out.append(decide(outcome="bound", margin=0.7, confidence=0.9, destructive=True,
                              panel_at_onset=p, panel_at_end=p))
        elif slot < 4:      # 1% weak bind
            out.append(decide(outcome="bound", margin=rng.uniform(0, 0.2), confidence=0.2,
                              destructive=False, panel_at_onset=p, panel_at_end=p))
        elif slot < 9:      # 5% no ray target at all (looking at the room)
            out.append(decide(outcome="none", margin=0.0, confidence=0.0, destructive=False,
                              panel_at_onset=None, panel_at_end=None))
        else:               # 91% clean: the whole passing range of both thresholds
            out.append(decide(outcome="bound", margin=rng.uniform(0.25, 1.0),
                              confidence=rng.uniform(0.35, 1.0), destructive=False,
                              panel_at_onset=p, panel_at_end=p))
    return out


def test_prompt_rate_on_realistic_synthetic_mix_is_under_five_percent():
    # A property of these thresholds on INVENTED data — not a measurement of real users.
    mix = _decisions(1000, random.Random(20261030))
    assert len(mix) == 1000
    rate = expected_prompt_rate(mix)
    assert rate < 0.05
    assert rate == pytest.approx(0.04)  # 4 of every 100 slots hold; guards against a vacuous mix


def test_prompt_rate_on_all_clean_binds_is_zero():
    assert expected_prompt_rate(_decisions(1000, random.Random(1), noisy=False)) == 0.0


def test_prompt_rate_counts_only_holds():
    holds = [clean(outcome="ambiguous")] * 3
    silent = [clean(), clean(outcome="none")]
    assert expected_prompt_rate(holds + silent) == pytest.approx(0.6)
    assert expected_prompt_rate(silent) == 0.0
    assert expected_prompt_rate(holds) == 1.0


def test_prompt_rate_empty_is_zero_and_accepts_iterators():
    assert expected_prompt_rate([]) == 0.0
    assert expected_prompt_rate(iter([clean(outcome="ambiguous"), clean()])) == 0.5
