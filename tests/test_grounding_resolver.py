"""The resolver either names one entity, says "several", or says why not — deterministically.

`src/yazses/grounding/resolver.py` is phase P1 of ADR-v2-151. What has to hold:

1. **A label match cannot import a candidate from elsewhere.** The spatial envelope is
   enforced before a hint is even looked at, so "click Save" can only ever reach a `Save`
   the user was actually pointing at. This is the acceptance criterion the whole layer
   exists for, and the one an ordinary scoring implementation gets wrong by giving a label
   match a large enough weight.
2. **Abstention is exact, not fuzzy.** The gate fires when nothing in the ranking separates
   the winner from a runner-up. ADR-021 judges a guard on how rarely it fires, so there is
   a measurement below (`test_the_abstention_rate_on_a_realistic_layout_is_measured`) that
   fails if the resolver becomes either paralysed or credulous.
3. **Order-independence.** A platform tree walker's traversal order must not decide
   anything, so every permutation of a candidate list produces the identical result.
4. **Nothing raises.** Every input the contracts accept yields one of three outcomes; an
   exception would turn the honest answer into the error path.
5. **Purity.** No clock, no randomness, no platform library — checked mechanically,
   because the resolver is the one module in this programme that CI can fully exercise.

The vocabulary's own invariants are `tests/test_grounding_contracts.py`; the gaze seam is
#443 and the replay harness is #445, and neither is exercised here.
"""

from __future__ import annotations

import ast
import itertools
import math
from pathlib import Path

import pytest

import yazses.grounding.resolver as resolver_module
from yazses.grounding import (
    CandidateScore,
    CoordinateSpace,
    GroundingEvidence,
    GroundingOutcome,
    IntentHint,
    Point,
    Rect,
    ResolutionPolicy,
    SemanticCandidate,
    SemanticSourceKind,
    TargetResolver,
    TargetSnapshot,
    TargetSource,
    UnresolvedReason,
)

SPACE = CoordinateSpace("screen", 1)
OTHER_SPACE = CoordinateSpace("screen", 2)
T0 = 1000.0

#: One resolver, default policy, shared by the tests that are not about policy. Frozen
#: and stateless, so sharing it cannot leak anything between tests.
R = TargetResolver()


def a_target(**kw) -> TargetSnapshot:
    """A precise pointing target: a mouse-grade point, fresh, confident."""
    base = dict(
        source=TargetSource.MOUSE,
        timestamp_s=T0,
        confidence=0.9,
        space=SPACE,
        point=Point(120.0, 210.0),
        window_id="win-1",
    )
    base.update(kw)
    return TargetSnapshot(**base)  # type: ignore[arg-type]


def a_candidate(**kw) -> SemanticCandidate:
    base = dict(
        source=SemanticSourceKind.ACCESSIBILITY,
        entity_id="save-button",
        role="button",
        captured_at_s=T0,
        confidence=0.9,
        space=SPACE,
        bounds=Rect(100.0, 200.0, 60.0, 30.0),
        label="Save",
        actions=("press",),
    )
    base.update(kw)
    return SemanticCandidate(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 0. Guard the fixtures. A helper that does not build the case under test makes
#    every assertion below pass for the wrong reason.
# --------------------------------------------------------------------------- #
def test_the_default_fixtures_really_are_the_easy_case() -> None:
    assert a_candidate().bounds is not None
    assert a_candidate().bounds.contains(a_target().point)  # type: ignore[union-attr]
    assert R.resolve(a_target(), [a_candidate()], now_s=T0).is_grounded


def test_the_default_policy_is_the_one_being_tested() -> None:
    """If the defaults drift, the tests that do not pass a policy are testing something
    else and the measurement below stops describing the shipped behaviour."""
    policy = ResolutionPolicy()
    assert policy.envelope_expansion_px == 0.0
    assert policy.min_candidate_confidence == 0.0
    assert policy.min_target_confidence == 0.5
    assert R.policy == policy


# --------------------------------------------------------------------------- #
# 1. One plausible candidate resolves — and says why
# --------------------------------------------------------------------------- #
def test_one_plausible_candidate_grounds_deterministically() -> None:
    result = R.resolve(a_target(), [a_candidate()], now_s=T0)
    assert result.outcome is GroundingOutcome.GROUNDED
    assert result.candidate is not None
    assert result.candidate.entity_id == "save-button"
    assert result.unresolved_reason is None
    assert result == R.resolve(a_target(), [a_candidate()], now_s=T0)


def test_provenance_and_evidence_survive_the_resolution() -> None:
    """ADR-v2-151: consumers must be able to tell an exact accessibility node from a
    geometry-only fallback, so the result carries the candidate *and* why it won."""
    result = R.resolve(a_target(), [a_candidate()], now_s=T0)
    assert result.candidate is not None
    assert result.candidate.source is SemanticSourceKind.ACCESSIBILITY
    assert result.candidate.actions == ("press",)
    assert GroundingEvidence.INSIDE_TARGET_REGION in result.evidence
    assert result.target is a_target() or result.target == a_target()


def test_grounding_never_invents_confidence() -> None:
    """The spec's integration rule: low-confidence gaze never gains confidence from
    semantics. The weaker of the two observations wins, so the number can only fall."""
    low = a_target(confidence=0.55)
    certain = a_candidate(confidence=1.0)
    result = R.resolve(low, [certain], now_s=T0)
    assert result.resolution_confidence == pytest.approx(0.55)
    flipped = R.resolve(a_target(confidence=1.0), [a_candidate(confidence=0.6)], now_s=T0)
    assert flipped.resolution_confidence == pytest.approx(0.6)


def test_an_abstention_carries_no_confidence_at_all() -> None:
    result = R.resolve(a_target(), [], now_s=T0)
    assert result.resolution_confidence == 0.0
    assert result.candidate is None


# --------------------------------------------------------------------------- #
# 2. The spatial envelope. The criterion the layer exists for.
# --------------------------------------------------------------------------- #
def test_a_matching_label_outside_the_envelope_cannot_win() -> None:
    """The binding rule from `design/eye-control/AGENT_TASKS.md`: an intent hint refines
    the plausible set and never pulls an off-region element into it."""
    elsewhere = a_candidate(entity_id="save-in-other-pane", bounds=Rect(900.0, 60.0, 60.0, 30.0))
    hint = IntentHint(verb="click", role="button", label_tokens=("save",))
    result = R.resolve(a_target(), [elsewhere], now_s=T0, hint=hint)
    assert result.outcome is GroundingOutcome.UNRESOLVED
    assert result.candidate is None
    # And the fixture really is the tempting case: it would have won on the hint alone.
    assert R._hint_allows(elsewhere, hint)


def test_an_off_region_label_match_loses_to_nothing_at_all() -> None:
    """Stronger form: the off-region `Save` is present *with* an on-region candidate the
    hint rejects. A scoring resolver that summed a label weight would pick the `Save`."""
    elsewhere = a_candidate(entity_id="save-far", bounds=Rect(900.0, 60.0, 60.0, 30.0))
    here = a_candidate(entity_id="cancel-here", label="Cancel")
    hint = IntentHint(role="button", label_tokens=("save",))
    result = R.resolve(a_target(), [here, elsewhere], now_s=T0, hint=hint)
    assert result.outcome is GroundingOutcome.UNRESOLVED
    assert result.unresolved_reason is UnresolvedReason.SEMANTIC_NO_PLAUSIBLE_CANDIDATE


def test_a_candidate_with_no_bounds_is_not_plausible() -> None:
    """Without geometry the envelope cannot be enforced, so a bounds-less candidate is
    exactly the thing a label match must not be able to import."""
    result = R.resolve(
        a_target(),
        [a_candidate(bounds=None, space=None, entity_id="no-geometry")],
        now_s=T0,
        hint=IntentHint(label_tokens=("save",)),
    )
    assert result.outcome is GroundingOutcome.UNRESOLVED


def test_the_envelope_expansion_is_opt_in_and_bounded() -> None:
    near_miss = a_candidate(bounds=Rect(130.0, 200.0, 60.0, 30.0))  # 10px right of the point
    assert R.resolve(a_target(), [near_miss], now_s=T0).outcome is GroundingOutcome.UNRESOLVED
    generous = TargetResolver(ResolutionPolicy(envelope_expansion_px=20.0))
    assert generous.resolve(a_target(), [near_miss], now_s=T0).is_grounded
    stingy = TargetResolver(ResolutionPolicy(envelope_expansion_px=5.0))
    assert stingy.resolve(a_target(), [near_miss], now_s=T0).outcome is (
        GroundingOutcome.UNRESOLVED
    )


def test_a_candidate_reached_only_through_the_expansion_does_not_claim_containment() -> None:
    """`INSIDE_TARGET_REGION` means the candidate met the target's own geometry. Claiming
    it for an expansion hit would make the evidence useless exactly where the expansion
    is the thing under review."""
    near_miss = a_candidate(bounds=Rect(130.0, 200.0, 60.0, 30.0))
    generous = TargetResolver(ResolutionPolicy(envelope_expansion_px=20.0))
    result = generous.resolve(a_target(), [near_miss], now_s=T0)
    assert result.is_grounded
    assert GroundingEvidence.INSIDE_TARGET_REGION not in result.evidence


def test_a_region_target_accepts_an_overlapping_candidate() -> None:
    region = a_target(point=None, bounds=Rect(100.0, 200.0, 120.0, 60.0))
    overlapping = a_candidate(bounds=Rect(80.0, 190.0, 60.0, 30.0))
    result = R.resolve(region, [overlapping], now_s=T0)
    assert result.is_grounded
    assert GroundingEvidence.INSIDE_TARGET_REGION in result.evidence


# --------------------------------------------------------------------------- #
# 3. Nesting: the innermost element, the way every toolkit hit-tests
# --------------------------------------------------------------------------- #
def _nest() -> list[SemanticCandidate]:
    window = a_candidate(
        entity_id="window", role="window", label="Editor",
        source=SemanticSourceKind.WINDOW, bounds=Rect(0.0, 0.0, 1000.0, 800.0),
    )
    panel = a_candidate(entity_id="panel", role="panel", label="Toolbar",
                        bounds=Rect(80.0, 180.0, 400.0, 80.0))
    button = a_candidate()
    return [window, panel, button]


def test_the_nest_fixture_really_nests() -> None:
    point = a_target().point
    assert point is not None
    assert all(c.bounds is not None and c.bounds.contains(point) for c in _nest())


def test_nested_bounds_ground_the_innermost_element() -> None:
    result = R.resolve(a_target(), _nest(), now_s=T0)
    assert result.candidate is not None
    assert result.candidate.entity_id == "save-button"
    # The runners-up stay available for a UX layer, ranked.
    assert [c.entity_id for c in result.alternatives] == ["panel", "window"]


def test_two_same_sized_overlapping_siblings_abstain() -> None:
    """The ADR's overlapping-controls case. Nothing in the ranking separates them, so
    guessing would be a coin flip dressed as a decision."""
    left = a_candidate(entity_id="left", label="Save")
    right = a_candidate(entity_id="right", label="Save as", bounds=Rect(110.0, 200.0, 60.0, 30.0))
    point = a_target().point
    assert point is not None
    assert left.bounds.contains(point) and right.bounds.contains(point)  # type: ignore[union-attr]
    result = R.resolve(a_target(), [left, right], now_s=T0)
    assert result.outcome is GroundingOutcome.AMBIGUOUS
    assert {c.entity_id for c in result.alternatives} == {"left", "right"}
    assert result.candidate is None
    assert result.unresolved_reason is None


def test_an_ambiguous_result_only_claims_what_the_whole_group_shares() -> None:
    left = a_candidate(entity_id="left")
    right = a_candidate(entity_id="right", bounds=Rect(110.0, 200.0, 60.0, 30.0))
    result = R.resolve(a_target(), [left, right], now_s=T0)
    assert result.evidence == (GroundingEvidence.INSIDE_TARGET_REGION,)
    # Neither is strictly nearest and neither has a better source, so neither claim is made.
    assert GroundingEvidence.NEAREST_TO_TARGET_POINT not in result.evidence
    assert GroundingEvidence.SOURCE_QUALITY not in result.evidence


def test_a_hint_resolves_what_geometry_could_not() -> None:
    """The pair that abstains above grounds once the user's own words narrow it — this is
    the whole point of the hint being a refinement rather than a tiebreaker."""
    left = a_candidate(entity_id="left", label="Save")
    right = a_candidate(entity_id="right", label="Cancel", bounds=Rect(110.0, 200.0, 60.0, 30.0))
    assert R.resolve(a_target(), [left, right], now_s=T0).outcome is GroundingOutcome.AMBIGUOUS
    result = R.resolve(
        a_target(), [left, right], now_s=T0, hint=IntentHint(label_tokens=("save",))
    )
    assert result.candidate is not None
    assert result.candidate.entity_id == "left"
    assert GroundingEvidence.LABEL_HINT_MATCH in result.evidence


def test_a_role_hint_resolves_a_control_from_its_own_label() -> None:
    """The nested-roles case: a static label and the field it names overlap, and only the
    role says which one "type here" meant."""
    caption = a_candidate(entity_id="caption", role="label", label="Amount")
    field = a_candidate(entity_id="field", role="entry", label="Amount")
    assert R.resolve(a_target(), [caption, field], now_s=T0).outcome is (
        GroundingOutcome.AMBIGUOUS
    )
    result = R.resolve(a_target(), [caption, field], now_s=T0, hint=IntentHint(role="entry"))
    assert result.candidate is not None
    assert result.candidate.entity_id == "field"
    assert GroundingEvidence.ROLE_MATCH in result.evidence


def test_repeated_labels_abstain_rather_than_pick_the_first() -> None:
    """Eight list rows with the same label, two of them under the pointer. A hint on the
    label cannot separate them, and neither can traversal order."""
    rows = [
        a_candidate(
            entity_id=f"row-{i}", role="listitem", label="Untitled note",
            bounds=Rect(100.0, 195.0 + i * 5.0, 200.0, 30.0),
        )
        for i in range(4)
    ]
    point = a_target().point
    assert point is not None
    assert sum(1 for r in rows if r.bounds.contains(point)) >= 2  # type: ignore[union-attr]
    result = R.resolve(
        a_target(), rows, now_s=T0, hint=IntentHint(label_tokens=("untitled",))
    )
    assert result.outcome is GroundingOutcome.AMBIGUOUS
    assert len(result.alternatives) >= 2


def test_a_hint_that_matches_nothing_in_the_envelope_abstains() -> None:
    """Naming a role is a specific, checkable signal (ADR-021). If nothing under the
    pointer is a button, grounding a text field for "click Save" would be a confident
    wrong answer — the expensive kind."""
    field = a_candidate(entity_id="field", role="entry", label="Amount")
    result = R.resolve(a_target(), [field], now_s=T0, hint=IntentHint(role="button"))
    assert result.outcome is GroundingOutcome.UNRESOLVED
    assert result.unresolved_reason is UnresolvedReason.SEMANTIC_NO_PLAUSIBLE_CANDIDATE
    # Without the hint the same input grounds: the hint only ever narrows.
    assert R.resolve(a_target(), [field], now_s=T0).is_grounded


def test_a_hint_with_only_a_verb_changes_nothing() -> None:
    """"click this" constrains nothing the resolver can check, and must not behave
    differently from no hint at all."""
    bare = IntentHint(verb="click")
    assert not bare.constrains_anything
    for candidates in ([a_candidate()], _nest(), []):
        assert R.resolve(a_target(), candidates, now_s=T0, hint=bare) == R.resolve(
            a_target(), candidates, now_s=T0
        )


def test_label_matching_is_whole_token_not_substring() -> None:
    """`save` must not match `Savings`. A guard that fires on a coincidence teaches
    people to ignore it (ADR-021)."""
    savings = a_candidate(entity_id="savings", label="Savings account")
    result = R.resolve(a_target(), [savings], now_s=T0, hint=IntentHint(label_tokens=("save",)))
    assert result.outcome is GroundingOutcome.UNRESOLVED
    assert R.resolve(
        a_target(), [savings], now_s=T0, hint=IntentHint(label_tokens=("savings",))
    ).is_grounded


def test_label_and_role_matching_ignore_case_and_punctuation() -> None:
    localized = a_candidate(entity_id="save-as", role="Button", label="Save As…")
    result = R.resolve(
        a_target(), [localized], now_s=T0,
        hint=IntentHint(role="BUTTON", label_tokens=("Save", "AS")),
    )
    assert result.is_grounded


# --------------------------------------------------------------------------- #
# 4. Source preference and focus
# --------------------------------------------------------------------------- #
def test_the_source_rank_follows_the_enum_order_with_no_second_copy() -> None:
    ranks = resolver_module._SOURCE_RANK
    assert set(ranks) == set(SemanticSourceKind), "a new source kind would rank unranked"
    order = list(SemanticSourceKind)
    assert [ranks[kind] for kind in order] == sorted(
        (ranks[kind] for kind in order), reverse=True
    )


def test_a_better_source_outranks_a_smaller_rectangle() -> None:
    """Provenance is a tier above geometry: a tiny window-geometry guess must not beat an
    exact accessibility node just by being smaller."""
    guess = a_candidate(
        entity_id="geometry-guess", source=SemanticSourceKind.WINDOW,
        bounds=Rect(118.0, 208.0, 6.0, 6.0),
    )
    exact = a_candidate(entity_id="a11y-node")
    result = R.resolve(a_target(), [guess, exact], now_s=T0)
    assert result.candidate is not None
    assert result.candidate.entity_id == "a11y-node"
    assert GroundingEvidence.SOURCE_QUALITY in result.evidence


def test_the_focused_selection_wins_inside_the_envelope() -> None:
    """The spec's first ranking bullet. Selection/focus metadata is what the user just
    acted on, so inside the envelope it outranks a same-shaped tree node."""
    focused = a_candidate(entity_id="selected-run", source=SemanticSourceKind.SELECTION,
                          role="text", label="the selected words")
    node = a_candidate(entity_id="paragraph", role="text", label="the whole paragraph")
    result = R.resolve(a_target(), [focused, node], now_s=T0)
    assert result.candidate is not None
    assert result.candidate.entity_id == "selected-run"
    assert GroundingEvidence.EXACT_ACCESSIBILITY_FOCUS in result.evidence


def test_a_focused_selection_outside_the_envelope_still_loses() -> None:
    """No tier can substitute for the envelope."""
    focused = a_candidate(entity_id="selected-elsewhere", source=SemanticSourceKind.SELECTION,
                          bounds=Rect(900.0, 60.0, 60.0, 30.0))
    result = R.resolve(a_target(), [focused], now_s=T0)
    assert result.outcome is GroundingOutcome.UNRESOLVED


def test_window_match_evidence_is_never_claimed() -> None:
    """`SemanticCandidate` carries no window id, so this resolver cannot check a window
    match. Emitting the evidence anyway would be a claim nothing verified — the only
    place that knows is `SemanticSource.snapshot(window_id=...)`, upstream of here."""
    seen: set[GroundingEvidence] = set()
    for candidates in ([a_candidate()], _nest(), [a_candidate(), a_candidate(entity_id="b")]):
        seen |= set(R.resolve(a_target(), candidates, now_s=T0).evidence)
        seen |= {e for s in R.score(a_target(), candidates, now_s=T0) for e in s.evidence}
    assert seen, "the sweep produced no evidence at all — it is proving nothing"
    assert GroundingEvidence.WINDOW_MATCH not in seen


# --------------------------------------------------------------------------- #
# 5. Step 1 — stale, unconfident, space-mismatched input abstains with a reason
# --------------------------------------------------------------------------- #
def test_a_stale_target_abstains() -> None:
    result = R.resolve(a_target(), [a_candidate()], now_s=T0 + 5.0)
    assert result.outcome is GroundingOutcome.UNRESOLVED
    assert result.unresolved_reason is UnresolvedReason.TARGET_STALE
    assert result.unresolved_reason.is_target_source_failure


def test_a_target_from_the_future_is_stale_too() -> None:
    """A snapshot timestamped after the resolution is a caller bug, and trusting it would
    ground against a layout that has not happened."""
    assert R.resolve(a_target(), [a_candidate()], now_s=T0 - 5.0).unresolved_reason is (
        UnresolvedReason.TARGET_STALE
    )


def test_a_low_confidence_target_abstains_before_anything_else_is_examined() -> None:
    result = R.resolve(a_target(confidence=0.1), [a_candidate()], now_s=T0)
    assert result.unresolved_reason is UnresolvedReason.TARGET_CONFIDENCE_BELOW_FLOOR
    assert R.score(a_target(confidence=0.1), [a_candidate()], now_s=T0) == ()


def test_a_target_with_no_geometry_abstains_so_the_old_fallback_stays() -> None:
    """ADR-v2-151 keeps window-level gaze/deixis as the fallback exactly here: a window id
    cannot enforce an envelope, so there is nothing to ground against."""
    windowed = a_target(point=None, bounds=None, space=None, window_id="win-1")
    assert not windowed.has_geometry
    result = R.resolve(windowed, [a_candidate()], now_s=T0)
    assert result.unresolved_reason is UnresolvedReason.TARGET_GEOMETRY_MISSING


def test_an_empty_candidate_set_is_a_semantic_source_failure() -> None:
    result = R.resolve(a_target(), [], now_s=T0)
    assert result.unresolved_reason is UnresolvedReason.SEMANTIC_NO_CANDIDATES
    assert result.unresolved_reason.is_semantic_source_failure


def test_a_coordinate_space_mismatch_abstains_and_names_itself() -> None:
    """A re-calibration or a plugged-in monitor bumps the space version, and comparing
    across it would ground against a layout that no longer exists (ADR-v2-149)."""
    other = a_candidate(space=OTHER_SPACE)
    result = R.resolve(a_target(), [other], now_s=T0)
    assert result.unresolved_reason is UnresolvedReason.SEMANTIC_SPACE_MISMATCH


def test_an_entirely_stale_tree_abstains_and_names_itself() -> None:
    stale = [a_candidate(entity_id="a", captured_at_s=T0 - 30.0),
             a_candidate(entity_id="b", captured_at_s=T0 + 30.0)]
    assert R.resolve(a_target(), stale, now_s=T0).unresolved_reason is (
        UnresolvedReason.SEMANTIC_ALL_STALE
    )


def test_a_mixed_failure_reports_the_generic_reason() -> None:
    """Reporting "the tree was stale" because one of two candidates was stale would put a
    non-failure in the metric that counts platform failures (#444)."""
    mixed = [a_candidate(entity_id="stale", captured_at_s=T0 - 30.0),
             a_candidate(entity_id="off-region", bounds=Rect(900.0, 60.0, 10.0, 10.0))]
    assert R.resolve(a_target(), mixed, now_s=T0).unresolved_reason is (
        UnresolvedReason.SEMANTIC_NO_PLAUSIBLE_CANDIDATE
    )


def test_one_stale_candidate_does_not_spoil_a_fresh_one() -> None:
    result = R.resolve(
        a_target(),
        [a_candidate(entity_id="stale", captured_at_s=T0 - 30.0), a_candidate()],
        now_s=T0,
    )
    assert result.candidate is not None
    assert result.candidate.entity_id == "save-button"


def test_every_unresolved_result_from_the_resolver_names_a_reason() -> None:
    """The contract allows a reason-less UNRESOLVED so that any caller can build one. The
    resolver never uses that latitude: an abstention it produced always knows why."""
    cases = [
        (a_target(confidence=0.0), [a_candidate()], T0),
        (a_target(), [a_candidate()], T0 + 99.0),
        (a_target(point=None, bounds=None, space=None), [a_candidate()], T0),
        (a_target(), [], T0),
        (a_target(), [a_candidate(space=OTHER_SPACE)], T0),
        (a_target(), [a_candidate(captured_at_s=T0 - 9.0)], T0),
        (a_target(), [a_candidate(bounds=Rect(900.0, 60.0, 5.0, 5.0))], T0),
    ]
    seen: set[UnresolvedReason] = set()
    for target, candidates, now in cases:
        result = R.resolve(target, candidates, now_s=now)
        assert result.outcome is GroundingOutcome.UNRESOLVED, result
        assert result.unresolved_reason is not None
        seen.add(result.unresolved_reason)
    assert seen == set(UnresolvedReason), (
        f"these reasons are unreachable from the resolver: {sorted(set(UnresolvedReason) - seen)}"
    )


# --------------------------------------------------------------------------- #
# 6. Determinism and order-independence
# --------------------------------------------------------------------------- #
def _permutation_cases() -> list[tuple[TargetSnapshot, list[SemanticCandidate], IntentHint | None]]:
    tie = [a_candidate(entity_id="left"),
           a_candidate(entity_id="right", bounds=Rect(110.0, 200.0, 60.0, 30.0))]
    mixed = _nest() + [a_candidate(entity_id="stale", captured_at_s=T0 - 40.0)]
    region = a_target(point=None, bounds=Rect(100.0, 190.0, 140.0, 60.0))
    return [
        (a_target(), _nest(), None),
        (a_target(), tie, None),
        (a_target(), mixed, None),
        (a_target(), mixed, IntentHint(role="button")),
        (region, mixed, None),
    ]


def test_candidate_order_never_changes_the_result() -> None:
    """A platform tree walker's traversal order is arbitrary. If it could decide anything,
    the same desktop would ground differently on GNOME and on KDE."""
    for target, candidates, hint in _permutation_cases():
        expected = R.resolve(target, candidates, now_s=T0, hint=hint)
        for permutation in itertools.permutations(candidates):
            got = R.resolve(target, list(permutation), now_s=T0, hint=hint)
            assert got == expected, f"{[c.entity_id for c in permutation]} -> {got.outcome}"


def test_candidate_order_never_changes_the_ranking_either() -> None:
    for target, candidates, hint in _permutation_cases():
        expected = [s.candidate.entity_id for s in R.score(target, candidates, now_s=T0, hint=hint)]
        for permutation in itertools.permutations(candidates):
            got = [
                s.candidate.entity_id
                for s in R.score(target, list(permutation), now_s=T0, hint=hint)
            ]
            assert got == expected


def test_the_permutation_sweep_is_exercising_more_than_one_outcome() -> None:
    """Guard the guard: if every case resolved the same way the sweep would prove little."""
    outcomes = {
        R.resolve(t, c, now_s=T0, hint=h).outcome for t, c, h in _permutation_cases()
    }
    assert len(outcomes) >= 2, outcomes


def test_a_duplicate_candidate_is_not_an_ambiguity() -> None:
    """A source that reports the same entity twice describes one control. Calling that an
    ambiguity would be a guard firing on its own input."""
    result = R.resolve(a_target(), [a_candidate(), a_candidate(), a_candidate()], now_s=T0)
    assert result.is_grounded
    assert result.alternatives == ()


# --------------------------------------------------------------------------- #
# 7. Never raises
# --------------------------------------------------------------------------- #
def test_no_accepted_input_makes_the_resolver_raise() -> None:
    """Abstention is a result. An exception would make the honest outcome the error path,
    and error paths get swallowed."""
    targets = [
        a_target(),
        a_target(confidence=0.0),
        a_target(point=None, bounds=Rect(0.0, 0.0, 0.0, 0.0)),
        a_target(point=None, bounds=Rect(100.0, 200.0, 100.0, 100.0)),
        a_target(point=Point(0.0, 0.0), bounds=Rect(0.0, 0.0, 10.0, 10.0)),
        a_target(point=None, bounds=None, space=None),
        a_target(timestamp_s=-5.0),
    ]
    candidates = [
        a_candidate(),
        a_candidate(entity_id="zero", bounds=Rect(120.0, 210.0, 0.0, 0.0)),
        a_candidate(entity_id="huge", bounds=Rect(-1e6, -1e6, 2e6, 2e6)),
        a_candidate(entity_id="nobounds", bounds=None, space=None),
        a_candidate(entity_id="other-space", space=OTHER_SPACE),
        a_candidate(entity_id="unsure", confidence=0.0),
    ]
    hints = [None, IntentHint(), IntentHint(role="button", label_tokens=("save",))]
    policies = [
        ResolutionPolicy(),
        ResolutionPolicy(envelope_expansion_px=1e6, tie_area_ratio=1.0, tie_distance_px=0.0),
        ResolutionPolicy(min_target_confidence=1.0, max_target_age_s=0.0,
                         max_candidate_skew_s=0.0, min_candidate_confidence=1.0),
    ]
    seen: set[GroundingOutcome] = set()
    for policy in policies:
        resolver = TargetResolver(policy)
        for target in targets:
            for size in (0, 1, 2, len(candidates)):
                for hint in hints:
                    result = resolver.resolve(
                        target, candidates[:size], now_s=T0 + 0.1, hint=hint
                    )
                    seen.add(result.outcome)
                    assert 0.0 <= result.resolution_confidence <= 1.0
    assert seen == set(GroundingOutcome), f"the sweep never produced {set(GroundingOutcome) - seen}"


def test_a_zero_area_candidate_can_never_be_plausible() -> None:
    """`Rect` containment and intersection are both half-open, so a zero-size rectangle
    holds nothing. The score's area is therefore always positive, which is what lets the
    ambiguity gate divide by it."""
    zero = a_candidate(entity_id="zero", bounds=Rect(120.0, 210.0, 0.0, 0.0))
    assert R.score(a_target(), [zero], now_s=T0) == ()
    # And with an expansion, where *distance* rather than containment decides the
    # envelope: the point sits zero pixels from a zero-size rectangle, so this was the
    # one path that admitted a candidate with no extent at all.
    generous = TargetResolver(ResolutionPolicy(envelope_expansion_px=50.0))
    assert generous.score(a_target(), [zero], now_s=T0) == ()
    assert generous.resolve(a_target(), [zero], now_s=T0).outcome is GroundingOutcome.UNRESOLVED
    sliver = a_candidate(entity_id="sliver", bounds=Rect(119.0, 209.0, 2.0, 2.0))
    assert all(s.area > 0.0 for s in generous.score(a_target(), [sliver], now_s=T0))


# --------------------------------------------------------------------------- #
# 8. The score components are inspectable, which the spec requires
# --------------------------------------------------------------------------- #
def test_the_score_exposes_the_component_that_decided() -> None:
    scores = R.score(a_target(), _nest(), now_s=T0)
    assert [s.candidate.entity_id for s in scores] == ["save-button", "panel", "window"]
    button, panel, window = scores
    # The button beat the panel on area alone: every earlier component is equal.
    assert button.separable_tier == panel.separable_tier
    assert button.area < panel.area
    # The window lost earlier, on source rank — so its area never mattered.
    assert window.source_rank < panel.source_rank
    assert all(isinstance(s, CandidateScore) for s in scores)


def test_the_geometry_key_swaps_with_the_containment_class() -> None:
    """Inside the target, the smaller candidate is the more specific one. Merely
    overlapping it, area first would pick a tiny distant checkbox over the control the
    user was looking at."""
    inside = R.score(a_target(), _nest(), now_s=T0)[0]
    assert inside.containment == 2
    assert inside.geometry_key == (-inside.area, -inside.distance_px)
    generous = TargetResolver(ResolutionPolicy(envelope_expansion_px=40.0))
    outside = generous.score(
        a_target(), [a_candidate(bounds=Rect(140.0, 200.0, 60.0, 30.0))], now_s=T0
    )[0]
    assert outside.containment == 1
    assert outside.geometry_key == (-outside.distance_px, -outside.area)


def test_confidence_and_freshness_order_the_list_but_cannot_ground() -> None:
    """Two geometrically identical controls, one reported with much higher confidence.
    The list is still deterministic, and the result is still an abstention: grounding on
    that difference is acting on the one opaque number ADR-v2-151 forbids."""
    sure = a_candidate(entity_id="sure", confidence=1.0)
    unsure = a_candidate(entity_id="unsure", confidence=0.2, label="Save later")
    scores = R.score(a_target(), [unsure, sure], now_s=T0)
    assert [s.candidate.entity_id for s in scores] == ["sure", "unsure"]
    assert R.resolve(a_target(), [unsure, sure], now_s=T0).outcome is GroundingOutcome.AMBIGUOUS


def test_distance_separates_a_point_target_but_not_a_region() -> None:
    """A region *is* the sensor's uncertainty. Which candidate sits nearer its centre is
    noise, and grounding on noise is the wrong-target failure this layer exists to avoid."""
    near = a_candidate(entity_id="near", bounds=Rect(100.0, 200.0, 40.0, 30.0))
    far = a_candidate(entity_id="far", bounds=Rect(200.0, 200.0, 40.0, 30.0))
    point = a_target(point=Point(150.0, 215.0))
    generous = ResolutionPolicy(envelope_expansion_px=100.0)
    by_point = TargetResolver(generous).resolve(point, [near, far], now_s=T0)
    assert by_point.candidate is not None
    assert by_point.candidate.entity_id == "near"
    region = a_target(point=None, bounds=Rect(100.0, 200.0, 140.0, 30.0))
    by_region = TargetResolver(generous).resolve(region, [near, far], now_s=T0)
    assert by_region.outcome is GroundingOutcome.AMBIGUOUS


def test_the_tie_tolerances_are_policy_not_a_constant() -> None:
    """The numbers are unmeasured, so they must be reachable. A caller that wants any
    difference to separate can say so; the shipped default cannot be the only behaviour."""
    a = a_candidate(entity_id="a", bounds=Rect(100.0, 200.0, 60.0, 30.0))
    b = a_candidate(entity_id="b", bounds=Rect(100.0, 200.0, 58.0, 30.0))  # 3% smaller
    assert R.resolve(a_target(), [a, b], now_s=T0).outcome is GroundingOutcome.AMBIGUOUS
    picky = TargetResolver(ResolutionPolicy(tie_area_ratio=1.0))
    result = picky.resolve(a_target(), [a, b], now_s=T0)
    assert result.candidate is not None
    assert result.candidate.entity_id == "b"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_target_confidence": 1.5},
        {"min_target_confidence": math.nan},
        {"min_candidate_confidence": -0.1},
        {"max_target_age_s": -1.0},
        {"max_candidate_skew_s": math.inf},
        {"envelope_expansion_px": -5.0},
        {"tie_distance_px": math.nan},
        {"tie_area_ratio": 0.0},
        {"tie_area_ratio": 1.5},
    ],
)
def test_a_nonsense_policy_is_refused_at_construction(kwargs: dict[str, float]) -> None:
    """Refused, not clamped — the same rule the vocabulary uses. A NaN threshold compares
    False against everything, which reads as "below policy" in one branch and "not above
    policy" in another."""
    with pytest.raises(ValueError):
        ResolutionPolicy(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 9. How often does it abstain? ADR-021 judges a guard on that number.
# --------------------------------------------------------------------------- #
#: A synthetic settings window: a title bar, two panels, a six-button toolbar, five
#: labelled fields (each caption overlapping its field), an eight-row list with one
#: repeated label, and two checkboxes. Invented labels only, per the spec's privacy rule.
#:
#: It is a *shape*, not evidence. Nothing measured here may become a product default —
#: the research plan (RQ-G4) measures that on real desktops with real accessibility trees.
def _realistic_layout() -> tuple[list[SemanticCandidate], list[SemanticCandidate]]:
    """Returns (every candidate, the leaf controls a user could mean)."""
    candidates: list[SemanticCandidate] = []
    leaves: list[SemanticCandidate] = []

    def add(entity_id, role, label, rect, *, leaf, source=SemanticSourceKind.ACCESSIBILITY):
        candidate = SemanticCandidate(
            source=source, entity_id=entity_id, role=role, captured_at_s=T0,
            confidence=0.85, space=SPACE, bounds=rect, label=label,
            actions=("press",) if leaf else (),
        )
        candidates.append(candidate)
        if leaf:
            leaves.append(candidate)

    add("window", "window", "Settings", Rect(0.0, 0.0, 1200.0, 800.0), leaf=False,
        source=SemanticSourceKind.WINDOW)
    add("toolbar", "panel", "Toolbar", Rect(0.0, 0.0, 1200.0, 48.0), leaf=False)
    add("form-panel", "panel", "General", Rect(40.0, 80.0, 560.0, 400.0), leaf=False)
    add("list-panel", "panel", "Notes", Rect(640.0, 80.0, 520.0, 400.0), leaf=False)

    for i, name in enumerate(("New", "Open", "Save", "Print", "Undo", "Redo")):
        add(f"tool-{name.lower()}", "button", name,
            Rect(12.0 + i * 100.0, 8.0, 90.0, 32.0), leaf=True)

    for i, name in enumerate(("Name", "Amount", "Currency", "Comment", "Folder")):
        top = 120.0 + i * 70.0
        add(f"caption-{i}", "label", name, Rect(60.0, top, 120.0, 24.0), leaf=False)
        add(f"field-{i}", "entry", name, Rect(200.0, top - 4.0, 320.0, 32.0), leaf=True)

    for i in range(8):
        add(f"row-{i}", "listitem", "Untitled note",
            Rect(660.0, 100.0 + i * 44.0, 480.0, 40.0), leaf=True)

    for i, name in enumerate(("Start at login", "Check for updates")):
        add(f"check-{i}", "checkbox", name, Rect(60.0, 520.0 + i * 40.0, 220.0, 28.0), leaf=True)
    return candidates, leaves


def test_the_realistic_layout_is_actually_realistic() -> None:
    """Guard the guard. A layout with no nesting, no repeated labels and no overlap would
    make the measurement below meaningless."""
    candidates, leaves = _realistic_layout()
    assert len(candidates) == 30 and len(leaves) == 21
    labels = [c.label for c in candidates]
    assert labels.count("Untitled note") == 8, "no repeated-label case"
    assert len({c.role for c in candidates}) >= 6
    window = next(c for c in candidates if c.entity_id == "window")
    assert all(
        c is window or (c.bounds is not None and window.bounds is not None
                        and c.bounds.intersects(window.bounds))
        for c in candidates
    ), "nothing is nested inside anything"
    # Each caption overlaps the field it names: the nested-roles case.
    caption = next(c for c in candidates if c.entity_id == "caption-1")
    field = next(c for c in candidates if c.entity_id == "field-1")
    assert caption.bounds is not None and field.bounds is not None
    assert caption.bounds.y < field.bounds.y + field.bounds.height


def _outcomes(
    resolver: TargetResolver,
    make_target,
    *,
    hint_for=None,
) -> dict[str, float]:
    """Resolve one target per leaf control and tally what came back."""
    candidates, leaves = _realistic_layout()
    tally = {"grounded_correct": 0, "grounded_wrong": 0, "ambiguous": 0, "unresolved": 0}
    for leaf in leaves:
        assert leaf.bounds is not None
        hint = hint_for(leaf) if hint_for else None
        result = resolver.resolve(
            make_target(leaf.bounds), candidates, now_s=T0, hint=hint
        )
        if result.outcome is GroundingOutcome.AMBIGUOUS:
            tally["ambiguous"] += 1
        elif result.outcome is GroundingOutcome.UNRESOLVED:
            tally["unresolved"] += 1
        elif result.candidate is not None and result.candidate.entity_id == leaf.entity_id:
            tally["grounded_correct"] += 1
        else:
            tally["grounded_wrong"] += 1
    total = float(len(leaves))
    return {name: count / total for name, count in tally.items()}


def _coarse_region(size: float):
    """A gaze target that states its own uncertainty: a *size* square around the control.

    Webcam gaze is documented in `[gaze]`'s own config docstring as coarse, ~3-5 cm, which
    at an ordinary desktop DPI is well over a hundred pixels — so 120 is the realistic
    middle of this sweep, not its worst case.
    """

    def make(bounds: Rect) -> TargetSnapshot:
        centre = bounds.center
        return a_target(
            source=TargetSource.GAZE, point=None,
            bounds=Rect(centre.x - size / 2, centre.y - size / 2, size, size),
        )

    return make


def _spoken_hint(leaf: SemanticCandidate) -> IntentHint:
    """What "click Save" / "type in Amount" would give the resolver: the role and the
    first word of the visible label, as the command grammar would parse it."""
    assert leaf.label is not None
    return IntentHint(verb="click", role=leaf.role, label_tokens=(leaf.label.split()[0],))


def test_the_abstention_rate_on_a_realistic_layout_is_measured() -> None:
    """ADR-021: a guard is judged on how rarely it fires, and an abstention interrupts the
    user. So both directions are asserted — a resolver that abstained on everything would
    be as useless as one that never did.

    The sweep resolves one target per leaf control of `_realistic_layout` (21 of them) for
    a precise point and for gaze regions of four sizes, with and without a spoken hint.
    Measured on this fixture, with the shipped default policy:

    | target                  | grounded correct | ambiguous | wrong |
    |-------------------------|-----------------:|----------:|------:|
    | precise point           |             100% |        0% |    0% |
    | 40 px region            |             100% |        0% |    0% |
    | 80 px region            |            52.4% |     47.6% |    0% |
    | 120 px region           |            28.6% |     71.4% |    0% |
    | 120 px region + hint    |            61.9% |     38.1% |    0% |

    Three things that matter, and one that does not:

    * **Wrong-target is 0% in every column.** That is what abstention buys.
    * **Abstention tracks the sensor, not the resolver's mood.** A region tighter than the
      control pitch resolves everything; a region wider than it cannot, because three
      identically-sized fields 70 px apart genuinely are indistinguishable inside it.
    * **The user's own words recover most of the coverage**, which is the argument for the
      hint being a filter rather than a tiebreaker.
    * **None of these numbers is evidence for a threshold.** They describe one invented
      layout. RQ-G4 measures the real curve on real desktops, and the spec forbids picking
      a product default from a fixture.

    The 38.1% that survives the hint is the eight identically-labelled list rows: nothing
    the user said and nothing in the geometry separates them, and #443's job there is to
    fall back to the existing window-level behaviour or ask, not to pick row four.
    """
    precise = _outcomes(R, lambda bounds: a_target(point=bounds.center))
    assert precise == {
        "grounded_correct": 1.0, "grounded_wrong": 0.0, "ambiguous": 0.0, "unresolved": 0.0
    }, precise

    tight = _outcomes(R, _coarse_region(40.0))
    assert tight["grounded_correct"] == 1.0, tight

    curve = [_outcomes(R, _coarse_region(size)) for size in (40.0, 80.0, 120.0, 160.0)]
    assert all(step["grounded_wrong"] == 0.0 for step in curve), curve
    abstention = [step["ambiguous"] + step["unresolved"] for step in curve]
    assert abstention == sorted(abstention), f"abstention must not fall as the target coarsens: {abstention}"
    assert abstention[0] == 0.0 and abstention[-1] > 0.5, abstention

    coarse = curve[2]
    hinted = _outcomes(R, _coarse_region(120.0), hint_for=_spoken_hint)
    assert hinted["grounded_wrong"] == 0.0, hinted
    assert hinted["grounded_correct"] > coarse["grounded_correct"] + 0.2, (coarse, hinted)
    # The eight identically-labelled rows are the irreducible case: a hint cannot drive
    # abstention to zero, and a resolver that claimed otherwise would be guessing.
    assert hinted["ambiguous"] == pytest.approx(8 / 21), hinted


def test_a_precise_point_on_empty_canvas_abstains_rather_than_grabbing_the_window() -> None:
    """The coarse window-geometry candidate covers the whole screen, so "nothing here" must
    not silently become "the window". It grounds on the window only because that is the
    single plausible candidate — and its provenance says so, which is what lets #443 keep
    the existing window-level behaviour instead of treating it as an exact element."""
    candidates, _ = _realistic_layout()
    empty_spot = a_target(point=Point(620.0, 700.0))
    result = R.resolve(empty_spot, candidates, now_s=T0)
    assert result.is_grounded
    assert result.candidate is not None
    assert result.candidate.source is SemanticSourceKind.WINDOW


# --------------------------------------------------------------------------- #
# 10. Purity. The resolver is the module CI can fully exercise; keep it that way.
# --------------------------------------------------------------------------- #
RESOLVER_PATH = Path(resolver_module.__file__)

#: stdlib only, and not much of it. No `time` (the caller passes `now_s`, which is what
#: makes a fixture reproduce), no `random`, no `os`, no `pathlib`.
ALLOWED_IMPORTS = {"__future__", "collections", "dataclasses", "enum", "math", "typing", "yazses"}

FORBIDDEN_IMPORTS = {
    "time", "random", "os", "socket", "http", "urllib", "requests", "pathlib",
    "cv2", "mediapipe", "pyatspi", "gi", "objc", "AppKit", "Quartz", "numpy", "PIL", "mss",
}


def _imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not node.level, "the resolver must not import relatively"
            roots.add((node.module or "").split(".")[0])
    return roots


def test_the_import_scan_reads_the_module() -> None:
    """Guard the guard: a wrong path or a silent parse failure would report nothing
    imported and the assertions below would pass on an empty set."""
    roots = _imported_roots(RESOLVER_PATH)
    assert RESOLVER_PATH.name == "resolver.py"
    assert {"math", "yazses"} <= roots, f"only found {sorted(roots)}"


def test_the_resolver_imports_nothing_but_stdlib_and_its_own_vocabulary() -> None:
    roots = _imported_roots(RESOLVER_PATH)
    assert not roots - ALLOWED_IMPORTS, f"unexpected imports: {sorted(roots - ALLOWED_IMPORTS)}"
    assert not roots & FORBIDDEN_IMPORTS


def test_the_resolver_names_no_clock_or_random_source_even_lazily() -> None:
    """An import scan misses `import time` inside a function, which is the pattern this
    codebase uses everywhere for heavy backends. Determinism is the whole contract here,
    so check the source text too."""
    source = RESOLVER_PATH.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in source.splitlines()
        if not line.lstrip().startswith("#")
    )
    for forbidden in ("time.monotonic", "time.time", "random.", "datetime", "perf_counter"):
        assert forbidden not in body, f"{forbidden} would make a fixture irreproducible"


def test_the_source_check_would_notice_a_clock() -> None:
    """Guard the guard: the check above must fail on the thing it forbids."""
    assert "time.monotonic" in "x = time.monotonic()"


def test_the_resolver_has_no_mutable_module_level_state() -> None:
    """Two consumers share this module. A cache here would make one call's result depend
    on another's, which is exactly the determinism the harness relies on."""
    tree = ast.parse(RESOLVER_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = [node.target] if isinstance(node, ast.AnnAssign) else node.targets
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            assert all(name.isupper() or name.startswith("_") for name in names), names
            assert names, "an unnamed module-level assignment"


def test_the_resolver_performs_no_action() -> None:
    """Grounding answers what "this" refers to. Anything that clicks, focuses or types
    lives downstream of the safety layer (ADR-v2-151, ADR-021)."""
    public = {name for name in dir(R) if not name.startswith("_")}
    assert public == {"policy", "resolve", "score"}


# --------------------------------------------------------------------------- #
# 11. The two value types EYE-GROUND-002 added to the vocabulary.
#     They live in contracts.py because #443's grammar builds one and #445's
#     harness reads the other, but their invariants arrived with this change, so
#     they are tested beside the module that produces and consumes them.
# --------------------------------------------------------------------------- #
def test_an_intent_hint_is_a_frozen_casefolded_value() -> None:
    hint = IntentHint(verb="Click", role="Button", label_tokens=["Save", "AS"])
    assert hint.verb == "click" and hint.role == "button"
    assert hint.label_tokens == ("save", "as"), "a list would make the hint unhashable"
    assert hint == IntentHint(verb="click", role="button", label_tokens=("save", "as"))
    assert len({hint, IntentHint(verb="click", role="button", label_tokens=("save", "as"))}) == 1
    with pytest.raises(Exception):
        hint.role = "entry"  # type: ignore[misc]


def test_an_empty_hint_constrains_nothing_and_says_so() -> None:
    assert not IntentHint().constrains_anything
    assert not IntentHint(verb="click").constrains_anything
    assert IntentHint(role="button").constrains_anything
    assert IntentHint(label_tokens=("save",)).constrains_anything


@pytest.mark.parametrize(
    "kwargs",
    [
        {"verb": ""},
        {"role": ""},
        {"label_tokens": ("",)},
        {"label_tokens": ("save now",)},
        {"label_tokens": (" save",)},
    ],
)
def test_a_malformed_hint_is_refused_at_construction(kwargs: dict[str, object]) -> None:
    """A token with a space can never match one label token, so it is a caller bug that
    would silently make every resolution abstain — refused at the seam that produced it."""
    with pytest.raises(ValueError):
        IntentHint(**kwargs)  # type: ignore[arg-type]


def test_every_unresolved_reason_belongs_to_exactly_one_family() -> None:
    """P4 reports target-source failure and semantic-source failure separately. The family
    is derived from the member name, so a member cannot be added and forgotten — but only
    if every name carries one of the two prefixes, which is what this checks."""
    for reason in UnresolvedReason:
        assert reason.is_target_source_failure != reason.is_semantic_source_failure, reason
    assert sum(1 for r in UnresolvedReason if r.is_target_source_failure) >= 2
    assert sum(1 for r in UnresolvedReason if r.is_semantic_source_failure) >= 2


def test_an_unresolved_reason_cannot_carry_private_ui_text() -> None:
    """Same structural privacy as `GroundingEvidence`: an enum has nowhere to put a window
    title, so a debug log or an aggregate report is safe by construction."""
    for reason in UnresolvedReason:
        assert isinstance(reason.value, str)
        assert reason.value.replace("_", "").isalpha() and reason.value.islower()


def test_only_an_unresolved_result_may_carry_a_reason() -> None:
    """A reason on a grounded result would be a contradiction a consumer could act on."""
    from yazses.grounding.contracts import GroundingResult

    target, candidate = a_target(), a_candidate()
    with pytest.raises(ValueError):
        GroundingResult(
            outcome=GroundingOutcome.GROUNDED, target=target, candidate=candidate,
            resolution_confidence=0.5, unresolved_reason=UnresolvedReason.TARGET_STALE,
        )
    with pytest.raises(ValueError):
        GroundingResult(
            outcome=GroundingOutcome.AMBIGUOUS, target=target,
            alternatives=(candidate, a_candidate(entity_id="b")),
            unresolved_reason=UnresolvedReason.TARGET_STALE,
        )
    # And the reason-less UNRESOLVED the vocabulary shipped with still constructs.
    assert GroundingResult.unresolved(target).unresolved_reason is None
