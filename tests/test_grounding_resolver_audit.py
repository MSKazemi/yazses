"""Audit of EYE-GROUND-001/002 (#441/#442): the properties a hand-built fixture hides.

`tests/test_grounding_resolver.py` pins the policy with chosen fixtures. This file asks the
opposite question — what real input would those fixtures miss? — and answers it three ways:

1. **Properties over generated input** (hypothesis, already a dev dependency): the resolver
   never raises on anything the contracts accept, a result never depends on candidate
   order, a grounded candidate is always inside the spatial envelope, a hint can never pull
   a candidate in, and every abstention carries a machine-checkable reason.
2. **Defects the audit found**, each as a regression: a NaN clock read as "fresh"; labels
   in decomposed Unicode or in a script whose vowels are combining marks never matched a
   hint; one entity reported twice was called ambiguous with itself; a window-geometry
   fallback was reported to consumers as an exact element; a coarse gaze *region* grounded
   whichever neighbour its edge did not cut (29.6% wrong at 200 px).
3. **Measured behaviour**: wrong-target and abstention rates on adversarial synthetic sets
   (`test_a_coarse_gaze_region_never_grounds_the_wrong_neighbour` and its neighbours), with
   the parent/child ratio pinned as provisional policy so changing it is a visible decision.

Synthetic, invented geometry and labels only. Nothing here is evidence for a threshold.
"""

from __future__ import annotations

import itertools
import random
import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from yazses.gaze.grounded import SCREEN_SPACE, GazeGrounder, refine
from yazses.gaze.route import RouteDecision
from yazses.grounding import (
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
OTHER = CoordinateSpace("screen", 2)
T0 = 1000.0
R = TargetResolver()

fuzz = settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def a_target(**kw) -> TargetSnapshot:
    base = dict(source=TargetSource.MOUSE, timestamp_s=T0, confidence=0.9, space=SPACE,
                point=Point(120.0, 210.0), window_id="win-1")
    base.update(kw)
    return TargetSnapshot(**base)  # type: ignore[arg-type]


def a_candidate(**kw) -> SemanticCandidate:
    base = dict(source=SemanticSourceKind.ACCESSIBILITY, entity_id="save-button",
                role="button", captured_at_s=T0, confidence=0.9, space=SPACE,
                bounds=Rect(100.0, 200.0, 60.0, 30.0), label="Save", actions=("press",))
    base.update(kw)
    return SemanticCandidate(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. Generated input
# --------------------------------------------------------------------------- #
_coord = st.floats(min_value=-2000.0, max_value=4000.0, allow_nan=False, allow_infinity=False)
_size = st.floats(min_value=0.0, max_value=3000.0, allow_nan=False, allow_infinity=False)
_unit = st.floats(min_value=0.0, max_value=1.0, allow_nan=False)
_rects = st.builds(Rect, _coord, _coord, _size, _size)
_spaces = st.sampled_from([SPACE, SPACE, SPACE, OTHER])
_labels = st.one_of(st.none(), st.sampled_from(["Save", "Save as", "Savings", "OK", "Cancel", ""]))


@st.composite
def _candidates(draw):
    has_bounds = draw(st.booleans())
    return SemanticCandidate(
        source=draw(st.sampled_from(list(SemanticSourceKind))),
        entity_id=draw(st.sampled_from(["a", "b", "c", "d", "e", "f"])),
        role=draw(st.sampled_from(["button", "entry", "panel", "label"])),
        captured_at_s=draw(st.sampled_from([T0, T0 + 0.2, T0 - 0.2, T0 + 9.0])),
        confidence=draw(_unit),
        space=draw(_spaces) if has_bounds else None,
        bounds=draw(_rects) if has_bounds else None,
        label=draw(_labels),
        actions=draw(st.sampled_from([(), ("press",), ("press", "focus")])),
    )


@st.composite
def _targets(draw):
    kind = draw(st.sampled_from(["point", "region", "both", "none"]))
    point = Point(draw(_coord), draw(_coord)) if kind in ("point", "both") else None
    bounds = draw(_rects) if kind in ("region", "both") else None
    return TargetSnapshot(
        source=draw(st.sampled_from(list(TargetSource))),
        timestamp_s=T0 + draw(st.sampled_from([0.0, 0.1, -0.1, 3.0])),
        confidence=draw(_unit),
        space=SPACE if (point or bounds) else None,
        point=point,
        bounds=bounds,
        window_id=draw(st.sampled_from([None, "win-1"])),
    )


_hints = st.one_of(
    st.none(),
    st.builds(
        IntentHint,
        verb=st.sampled_from([None, "click"]),
        role=st.sampled_from([None, "button", "ENTRY"]),
        label_tokens=st.sampled_from([(), ("save",), ("Save", "as"), ("cancel",)]),
    ),
)
_policies = st.builds(
    ResolutionPolicy,
    min_target_confidence=_unit,
    max_target_age_s=st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
    max_candidate_skew_s=st.floats(min_value=0.0, max_value=5.0, allow_nan=False),
    min_candidate_confidence=_unit,
    envelope_expansion_px=st.sampled_from([0.0, 0.0, 25.0, 400.0]),
    tie_area_ratio=st.sampled_from([0.5, 0.8, 1.0]),
    tie_distance_px=st.sampled_from([0.0, 4.0, 50.0]),
)
_nows = st.sampled_from([T0, T0 + 0.3, T0 + 4.0, float("inf"), float("-inf"), float("nan")])


def _in_envelope(target: TargetSnapshot, candidate: SemanticCandidate, policy) -> bool:
    assert candidate.bounds is not None
    if target.point is not None and candidate.bounds.contains(target.point):
        return True
    if target.bounds is not None and candidate.bounds.intersects(target.bounds):
        return True
    if policy.envelope_expansion_px > 0.0:
        # Looser than the resolver on purpose: it only has to bound what may ground.
        pad = policy.envelope_expansion_px + 1e-6
        grown = Rect(candidate.bounds.x - pad, candidate.bounds.y - pad,
                     candidate.bounds.width + 2 * pad, candidate.bounds.height + 2 * pad)
        if target.point is not None and grown.contains(target.point):
            return True
        if target.bounds is not None and grown.intersects(target.bounds):
            return True
        # A region with no extent (a point or a line) is measured by distance in the resolver,
        # and `intersects` (strict: zero area never intersects) cannot see it: give it a hair of
        # extent and ask again.
        b = target.bounds
        if b is not None and (b.width <= 0.0 or b.height <= 0.0
                              or b.x + b.width <= b.x or b.y + b.height <= b.y):
            if grown.intersects(Rect(b.x - 1e-6, b.y - 1e-6, b.width + 2e-6, b.height + 2e-6)):
                return True
    return False


@fuzz
@given(_targets(), st.lists(_candidates(), max_size=7), _hints, _policies, _nows)
def test_never_raises_and_every_outcome_is_well_formed(target, candidates, hint, policy, now_s):
    result = TargetResolver(policy).resolve(target, candidates, now_s=now_s, hint=hint)
    if result.outcome is GroundingOutcome.GROUNDED:
        assert result.candidate is not None and result.unresolved_reason is None
        assert result.candidate.bounds is not None
        assert _in_envelope(target, result.candidate, policy)
        assert result.resolution_confidence <= min(target.confidence, result.candidate.confidence)
        assert result.candidate not in result.alternatives
    elif result.outcome is GroundingOutcome.AMBIGUOUS:
        assert result.candidate is None and len(set(result.alternatives)) >= 2
        assert result.resolution_confidence == 0.0
        assert all(_in_envelope(target, c, policy) for c in result.alternatives)
    else:
        # The machine-checkable reason: resolver output never leaves it blank.
        assert result.unresolved_reason in set(UnresolvedReason)
        assert result.candidate is None and result.resolution_confidence == 0.0


@fuzz
@given(_targets(), st.lists(_candidates(), max_size=6), _hints, _policies,
       st.sampled_from([T0, T0 + 0.3]), st.randoms(use_true_random=False))
def test_the_result_is_independent_of_candidate_order(
    target, candidates, hint, policy, now_s, rnd
):
    resolver = TargetResolver(policy)
    base = resolver.resolve(target, candidates, now_s=now_s, hint=hint)
    shuffled = list(candidates)
    rnd.shuffle(shuffled)
    assert resolver.resolve(target, shuffled, now_s=now_s, hint=hint) == base
    assert resolver.score(target, shuffled, now_s=now_s, hint=hint) == resolver.score(
        target, candidates, now_s=now_s, hint=hint
    )


@fuzz
@given(_targets(), st.lists(_candidates(), min_size=1, max_size=6), _policies,
       st.sampled_from([T0, T0 + 0.3]))
def test_a_hint_only_ever_removes_candidates(target, candidates, policy, now_s):
    """A hint refines; it can never add a candidate the unhinted run did not consider."""
    resolver = TargetResolver(policy)
    plain = {s.candidate for s in resolver.score(target, candidates, now_s=now_s)}
    for hint in (IntentHint(role="button"), IntentHint(label_tokens=("save",))):
        hinted = {s.candidate for s in resolver.score(target, candidates, now_s=now_s, hint=hint)}
        assert hinted <= plain


def test_full_permutation_sweep_on_a_tied_group_is_one_result() -> None:
    tied = [a_candidate(entity_id=f"b{i}", label="Same") for i in range(5)]
    outcomes = {
        R.resolve(a_target(), list(order), now_s=T0)
        for order in itertools.permutations(tied)
    }
    assert len(outcomes) == 1
    (only,) = outcomes
    assert only.outcome is GroundingOutcome.AMBIGUOUS
    assert [c.entity_id for c in only.alternatives] == sorted(c.entity_id for c in tied)


def test_nan_and_infinite_clock_readings_abstain_instead_of_reading_as_fresh() -> None:
    """`abs(nan - t) > budget` is False, so a NaN `now_s` used to pass the freshness gate
    and ground against a layout of unknown age."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        result = R.resolve(a_target(), [a_candidate()], now_s=bad)
        assert result.outcome is GroundingOutcome.UNRESOLVED
        assert result.unresolved_reason is UnresolvedReason.TARGET_STALE
        assert R.score(a_target(), [a_candidate()], now_s=bad) == ()


# --------------------------------------------------------------------------- #
# 2. Defects found by the audit
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("label", "token"),
    [
        pytest.param("Café", "café", id="decomposed-label-composed-hint"),
        pytest.param("Café", "café", id="composed-label-decomposed-hint"),
        # Devanagari: vowel signs and the virama are combining marks (not str.isalnum).
        pytest.param("हिन्दी सेव",
                     "हिन्दी", id="indic-combining-marks"),
        pytest.param("Save!", "save", id="trailing-punctuation-in-label"),
        pytest.param("E-mail", "e-mail", id="hint-token-with-an-inner-hyphen"),
        pytest.param("Save", "SAVE!", id="hint-token-with-punctuation"),
    ],
)
def test_label_hints_match_across_unicode_forms_and_punctuation(label, token) -> None:
    result = R.resolve(a_target(), [a_candidate(label=label)], now_s=T0,
                       hint=IntentHint(label_tokens=(token,)))
    assert result.is_grounded, result
    assert GroundingEvidence.LABEL_HINT_MATCH in result.evidence


@pytest.mark.parametrize(
    ("label", "token"),
    [
        pytest.param("Cafe\u0301", "cafe", id="cafe-is-not-cafe-acute"),
        pytest.param("\u0939\u093f\u0928\u094d\u0926\u0940", "\u0939\u093f",
                     id="a-fragment-of-an-indic-word-is-not-the-word"),
    ],
)
def test_combining_marks_keep_a_word_whole(label, token) -> None:
    """Splitting on a combining mark would turn one word into fragments, and a hint that
    names a fragment would then match a word the user never said."""
    result = R.resolve(a_target(), [a_candidate(label=label)], now_s=T0,
                       hint=IntentHint(label_tokens=(token,)))
    assert result.outcome is GroundingOutcome.UNRESOLVED


def test_a_hint_token_with_no_word_characters_matches_nothing() -> None:
    """Not "no constraint": a stripped-to-empty token must not silently vanish."""
    result = R.resolve(a_target(), [a_candidate()], now_s=T0,
                       hint=IntentHint(label_tokens=("&",)))
    assert result.outcome is GroundingOutcome.UNRESOLVED


def test_matching_is_still_whole_token_after_normalisation() -> None:
    result = R.resolve(a_target(), [a_candidate(label="Savings account")], now_s=T0,
                       hint=IntentHint(label_tokens=("save",)))
    assert result.outcome is GroundingOutcome.UNRESOLVED


def test_one_entity_reported_twice_is_one_entity_not_an_ambiguity() -> None:
    older = a_candidate(captured_at_s=T0 - 0.2, confidence=0.7)
    newer = a_candidate(captured_at_s=T0, confidence=0.9)
    for order in ([older, newer], [newer, older]):
        result = R.resolve(a_target(), order, now_s=T0)
        assert result.is_grounded
        assert result.candidate == newer


def test_the_same_id_at_different_bounds_stays_ambiguous() -> None:
    """A source that reports one id in two places is defective; do not hide that."""
    moved = a_candidate(bounds=Rect(105.0, 200.0, 60.0, 30.0))
    result = R.resolve(a_target(), [a_candidate(), moved], now_s=T0)
    assert result.outcome is GroundingOutcome.AMBIGUOUS


def test_a_stale_twin_does_not_veto_a_fresh_reading() -> None:
    fresh = a_candidate()
    stale = a_candidate(captured_at_s=T0 - 30.0)
    assert R.resolve(a_target(), [stale, fresh], now_s=T0).candidate == fresh


@pytest.mark.parametrize("actions", [(["press"],), ({"a": 1},), (3,)])
def test_a_candidate_cannot_smuggle_an_unhashable_or_non_string_action(actions) -> None:
    """The contract used to accept these and the resolver then raised `TypeError`."""
    with pytest.raises(ValueError, match="actions"):
        a_candidate(actions=actions)


def test_a_non_string_label_is_refused_at_the_adapter() -> None:
    with pytest.raises(ValueError, match="label"):
        a_candidate(label=7)


class _Source:
    def __init__(self, *candidates):
        self._candidates = candidates

    def snapshot(self, *, window_id, region):
        return list(self._candidates)


def _grounder(source, **kw) -> GazeGrounder:
    return GazeGrounder(source, clock=lambda: T0, **kw)


def test_a_window_geometry_fallback_is_not_reported_as_an_exact_element() -> None:
    """ADR-v2-151: "geometry-only fallback" is a provenance a consumer must be able to tell
    from an accessibility node. Grounding the window's own rectangle on empty canvas gave
    `entity_id="window"` and `is_exact=True`."""
    window = a_candidate(entity_id="window", role="window", label="Notes",
                         source=SemanticSourceKind.WINDOW, bounds=Rect(0, 0, 1000, 800),
                         space=SCREEN_SPACE)
    grounder = _grounder(_Source(window))
    result = grounder.ground(window_id="win-1", point=(500.0, 400.0), confidence=0.9)
    assert result is not None and result.is_grounded
    refined = refine(RouteDecision(target="win-1", used_gaze=True, confident=True), result)
    assert refined.window_id == "win-1"
    assert refined.is_exact is False and refined.entity_id is None and refined.role is None
    assert refined.source is SemanticSourceKind.WINDOW
    assert refined.outcome is GroundingOutcome.GROUNDED


def test_an_accessibility_entity_keeps_its_provenance_through_refine() -> None:
    button = a_candidate(bounds=Rect(450, 380, 100, 40), space=SCREEN_SPACE)
    result = _grounder(_Source(button)).ground(
        window_id="win-1", point=(500.0, 400.0), confidence=0.9
    )
    refined = refine(RouteDecision(target="win-1", used_gaze=True, confident=True), result)
    assert refined.is_exact and refined.source is SemanticSourceKind.ACCESSIBILITY


def test_a_region_states_the_sensors_uncertainty_and_makes_neighbours_ambiguous() -> None:
    """A bare gaze point asserts precision the sensor lacks: two adjacent buttons, the
    point lands on one, the resolver grounds it with no abstention. With the opt-in
    `region_px` the same sample covers both and the resolver says so."""
    left = a_candidate(entity_id="left", bounds=Rect(400, 380, 90, 40), space=SCREEN_SPACE)
    right = a_candidate(entity_id="right", bounds=Rect(510, 380, 90, 40), space=SCREEN_SPACE)
    source = _Source(left, right)
    precise = _grounder(source).ground(window_id="w", point=(470.0, 400.0), confidence=0.9)
    assert precise is not None and precise.is_grounded
    assert precise.candidate is not None and precise.candidate.entity_id == "left"

    coarse = _grounder(source, region_px=200.0).ground(
        window_id="w", point=(470.0, 400.0), confidence=0.9
    )
    assert coarse is not None and coarse.outcome is GroundingOutcome.AMBIGUOUS
    assert refine(None, coarse).is_exact is False


@pytest.mark.parametrize("bad", [0.0, -5.0, float("nan"), float("inf")])
def test_region_px_must_be_a_positive_finite_size(bad) -> None:
    with pytest.raises(ValueError, match="region_px"):
        _grounder(_Source(), region_px=bad)


# --------------------------------------------------------------------------- #
# 3. Scale, and measured behaviour that is policy
# --------------------------------------------------------------------------- #
def test_a_twenty_thousand_node_tree_resolves_quickly_and_deterministically() -> None:
    rng = random.Random(7)
    tree = [
        a_candidate(entity_id=f"n{i}", bounds=Rect(
            rng.uniform(0, 1900), rng.uniform(0, 1000), rng.uniform(1, 200), rng.uniform(1, 60)))
        for i in range(20_000)
    ]
    target = a_target(point=Point(960.0, 500.0))
    started = time.perf_counter()
    first = R.resolve(target, tree, now_s=T0)
    elapsed = time.perf_counter() - started
    rng.shuffle(tree)
    assert R.resolve(target, tree, now_s=T0) == first
    # Generous: measured at ~0.03 s. This only has to catch an accidental O(n^2).
    assert elapsed < 5.0, elapsed


def _tally(rows) -> dict[str, float]:
    """Resolve (target, candidates, truth) rows; bucket as the replay harness does."""
    tally = {"correct": 0, "wrong": 0, "ambiguous": 0, "unresolved": 0}
    for target, candidates, truth in rows:
        result = R.resolve(target, candidates, now_s=T0)
        if result.outcome is GroundingOutcome.AMBIGUOUS:
            tally["ambiguous"] += 1
        elif result.outcome is GroundingOutcome.UNRESOLVED:
            tally["unresolved"] += 1
        elif result.candidate is not None and result.candidate.entity_id == truth:
            tally["correct"] += 1
        else:
            tally["wrong"] += 1
    return {name: count / len(rows) for name, count in tally.items()}


def _gaze_region(centre_x: float, centre_y: float, size: float) -> TargetSnapshot:
    return a_target(source=TargetSource.GAZE, point=None,
                    bounds=Rect(centre_x - size / 2, centre_y - size / 2, size, size))


def test_a_coarse_gaze_region_never_grounds_the_wrong_neighbour() -> None:
    """The defect behind the region-containment rule, measured with an honest error model.

    The user looks at a true point on a control; the sensor reports a centre displaced by up
    to half the stated region on each axis, so the region always contains the true point.
    Truth is the control holding that point. Six 90x40 buttons, 10 px apart (1500 trials per
    row, seeded). Wrong-target rate, before -> after this change:

    | region | wrong before | wrong after | ambiguous after |
    |-------:|-------------:|------------:|----------------:|
    |  40 px |         0.0% |        0.0% |           19.7% |
    |  80 px |         0.0% |        0.0% |           55.1% |
    | 120 px |         2.1% |        0.0% |           84.9% |
    | 200 px |        29.6% |        0.0% |           90.9% |

    Before, "wholly inside the region" outranked "overlaps the region", so whichever
    control the region's *edge* happened to cut lost to one it did not — arbitrary, and
    wrong 3 times in 10 at 200 px. A region is the sensor's uncertainty, so it separates
    nothing. The price is abstention, stated above, which is the intended trade (a wrong
    exact-element action costs more than a question, ADR-021) and **not** a product
    threshold: the invented geometry here says nothing about real desktops (RQ-G4).
    """
    rng = random.Random(42)
    buttons = [
        a_candidate(entity_id=f"b{i}", bounds=Rect(10.0 + i * 100.0, 10.0, 90.0, 40.0))
        for i in range(6)
    ]
    for size in (40.0, 80.0, 120.0, 200.0):
        rows = []
        for _ in range(400):
            i = rng.randrange(6)
            tx, ty = 10.0 + i * 100.0 + rng.uniform(0, 90), 10.0 + rng.uniform(0, 40)
            rows.append((_gaze_region(tx + rng.uniform(-size / 2, size / 2),
                                      ty + rng.uniform(-size / 2, size / 2), size),
                         buttons, f"b{i}"))
        rates = _tally(rows)
        assert rates["wrong"] == 0.0, (size, rates)
        assert rates["correct"] + rates["ambiguous"] == pytest.approx(1.0)
    # And it is not paralysed: a region tighter than the button pitch still grounds most.
    assert _tally([
        (_gaze_region(10.0 + i * 100.0 + 45.0, 30.0, 20.0), buttons, f"b{i}") for i in range(6)
    ])["correct"] == 1.0


def test_a_small_neighbour_inside_the_region_does_not_beat_the_field_being_looked_at() -> None:
    """An entry field (400x30) with a 16 px checkbox and icon either side, gaze centre in
    the field. Wrong-target before -> after: 22% -> 0% at a 120 px region and 36% -> 0% at
    200 px. The neighbours fit wholly inside the region and the field only overlaps it, so
    the old containment tier put a control the user never looked at on top, and the old
    area rule then called the 16 px square "more specific" than a field it is not part of.
    """
    rng = random.Random(3)
    for size in (120.0, 200.0):
        rows = []
        for _ in range(300):
            candidates = [
                a_candidate(entity_id="fld", role="entry", bounds=Rect(100.0, 210.0, 400.0, 30.0)),
                a_candidate(entity_id="chk", role="checkbox", bounds=Rect(520.0, 215.0, 16.0, 16.0)),
                a_candidate(entity_id="ico", role="icon", bounds=Rect(60.0, 215.0, 16.0, 16.0)),
            ]
            rows.append((_gaze_region(rng.uniform(100, 500), rng.uniform(210, 240), size),
                         candidates, "fld"))
        assert _tally(rows)["wrong"] == 0.0, (size, _tally(rows))


def test_only_a_wholly_nested_candidate_is_more_specific_than_another() -> None:
    """Two partly-overlapping siblings of very different sizes are not nested, and the
    contract carries no z-order, so a precise point inside both is a real ambiguity."""
    big = a_candidate(entity_id="big", bounds=Rect(100.0, 200.0, 200.0, 60.0))
    popup = a_candidate(entity_id="popup", bounds=Rect(250.0, 220.0, 100.0, 20.0))
    result = R.resolve(a_target(point=Point(270.0, 230.0)), [big, popup], now_s=T0)
    assert result.outcome is GroundingOutcome.AMBIGUOUS
    nested = a_candidate(entity_id="nested", bounds=Rect(260.0, 225.0, 30.0, 10.0))
    assert R.resolve(a_target(point=Point(270.0, 230.0)), [big, nested], now_s=T0).is_grounded


def test_the_parent_child_ratio_rule_is_pinned_as_policy() -> None:
    """Characterisation, not endorsement. A point in a child nested in a parent, child area
    as a fraction of the parent's (300 random sizes per row): the default `tie_area_ratio`
    of 0.8 abstains at 0.85 and 0.95 (100% ambiguous) and grounds the child at 0.79 and
    below (100% correct). A button and its near-identical label child are one control to a
    user and two to this rule, so this is the over-eager direction of the guard. The
    default is provisional (ResolutionPolicy says so); changing it is a measurement for
    RQ-G4 to justify, so pinning it makes that a visible decision.
    """
    rng = random.Random(11)
    for fraction, expect_ambiguous in ((0.95, True), (0.85, True), (0.79, False), (0.5, False)):
        rows = []
        for _ in range(100):
            w, h = rng.uniform(60, 200), rng.uniform(24, 60)
            cw, ch = w * fraction**0.5, h * fraction**0.5
            parent = a_candidate(entity_id="parent", role="group", bounds=Rect(100.0, 100.0, w, h))
            child = a_candidate(entity_id="child", role="label", bounds=Rect(
                100.0 + (w - cw) / 2, 100.0 + (h - ch) / 2, cw, ch))
            rows.append((a_target(point=Point(100.0 + w / 2, 100.0 + h / 2)),
                         [parent, child], "child"))
        rates = _tally(rows)
        assert rates["wrong"] == 0.0
        assert (rates["ambiguous"] == 1.0) if expect_ambiguous else (rates["correct"] == 1.0)


@pytest.mark.parametrize("region", [Rect(10.0, 0.0, 0.0, 10.0), Rect(0.0, 10.0, 10.0, 0.0),
                                    Rect(10.0, 10.0, 0.0, 0.0)], ids=["vline", "hline", "point"])
@pytest.mark.parametrize("bounds", [Rect(0.0, 0.0, 20.0, 20.0), Rect(15.0, 0.0, 10.0, 10.0)],
                         ids=["covering", "beside"])
def test_the_envelope_oracle_measures_a_zero_extent_region_by_distance(region, bounds):
    """A target region with no extent (a line or a point) grounds by distance in the resolver,
    and `Rect.intersects` never sees zero area: without the oracle's own allowance the property
    test above reports a correct grounding as out of envelope. Every case failed before it."""
    target = TargetSnapshot(source=TargetSource.GAZE, timestamp_s=T0, confidence=1.0,
                            space=SPACE, point=None, bounds=region)
    cand = SemanticCandidate(source=SemanticSourceKind.ACCESSIBILITY, entity_id="a",
                             role="button", captured_at_s=T0, confidence=1.0, space=SPACE,
                             bounds=bounds)
    policy = ResolutionPolicy(envelope_expansion_px=25.0)
    result = TargetResolver(policy).resolve(target, [cand], now_s=T0)
    assert result.outcome is GroundingOutcome.GROUNDED  # the premise: the resolver grounds it
    assert _in_envelope(target, result.candidate, policy)
