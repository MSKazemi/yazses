"""The pure grounded-target resolver: geometry plus semantic evidence, or abstention.

Phase P1 of ``design/specs/eye-grounded-targets.md`` (ADR-v2-151). Given one coarse
:class:`~yazses.grounding.contracts.TargetSnapshot`, the candidates a semantic source
reported and an optional :class:`~yazses.grounding.contracts.IntentHint`, this module
answers the only question grounding asks — *which structured entity does "this" refer
to?* — and answers it with ``GROUNDED``, ``AMBIGUOUS`` or ``UNRESOLVED``.

It executes nothing. It imports no accessibility library, opens no camera, reads no
clock and touches no file: the caller passes ``now_s`` in, which is what makes every
fixture in ``tests/test_grounding_resolver.py`` reproduce exactly.

**Determinism is a requirement, not a property that happened.** The same inputs always
give the same output, candidate order never changes a result, and nothing here depends
on dict or set iteration order: the ranking key ends in a total order over the
candidate's own fields (:func:`_identity_key`), so two candidates that differ at all
have a defined order, and two that do not differ are the same value and are collapsed.

---

## Why this file holds all the policy

The vocabulary in ``contracts.py`` deliberately carries no thresholds and no weights.
Every number and every preference below is a *product* decision that the research plan
(``design/eye-control/GROUNDED_INTERACTION_RESEARCH.md`` RQ-G4) has to measure on real
desktops. So they live in one injected :class:`ResolutionPolicy`, they are all named,
and **none of their defaults is measured** — the spec forbids picking a product default
from synthetic fixtures, and a synthetic fixture is all that exists today.

## Where the weighting lives: nowhere

The spec asks the first implementation to "expose score components rather than burying
them in one opaque number", and ADR-v2-151 forbids collapsing provenance into a single
float. This resolver goes one step further and has **no weighted sum at all**. Ranking
is a lexicographic comparison of components each of which is either a boolean, a
spec-given ordering, or an exact geometric measurement:

1. **the focused/selected entity**, when it is inside the envelope — the spec's first
   ranking bullet;
2. **source reliability**, in the order ``SemanticSourceKind`` already declares
   (accessibility > application > selection > window) — the spec's order, read off the
   enum rather than re-encoded as numbers here;
3. **containment** — a candidate whose bounds contain the target beats one that merely
   overlaps it;
4. **geometry** — see :meth:`CandidateScore.geometry_key`;
5. **candidate confidence, then freshness** — ordering only. These can never *justify*
   grounding; see the ambiguity gate.

There is no weight to tune because there is no sum. A weighted sum with seven guessed
coefficients would look like measurement and be arithmetic over invented numbers: any
result it produced could be reversed by a coefficient nobody had evidence for, and
:class:`CandidateScore` would have to expose the coefficients for a reader to understand
one decision. Lexicographic order is auditable — one comparison decided it, and
:class:`CandidateScore` names which.

The two places a number is unavoidable are the *plausibility filter* (freshness budgets,
confidence floors, the optional envelope expansion) and the *ambiguity gate* tolerances.
Both are in :class:`ResolutionPolicy`.

## Where the hint acts: as a filter, once, after geometry

``design/eye-control/AGENT_TASKS.md`` is binding here: "intent hints refine the plausible
set; they never pull an off-region element into it". So a hint is applied strictly after
the spatial envelope, and within it a role or label constraint *removes* candidates
rather than nudging a score. Consequences, both deliberate:

* "click Save" cannot reach a ``Save`` button in another pane, because that button was
  never in the plausible set to be re-ranked;
* if nothing in the envelope matches what the user named, the result is ``UNRESOLVED``
  rather than the nearest thing. Naming a role or a label is a *specific, checkable*
  signal (ADR-021), and grounding a text field for "click Save" would be a confident
  wrong answer — the expensive kind.

Matching is exact, casefolded string equality on the role and whole-token containment on
the label. No stemming, no substring matching, no synonym table: a synonym map between
our grammar's "button" and a platform's "push button" is real work that needs the role
vocabularies #444 is going to measure, and inventing one here would be inventing product
policy. Until then a hint that does not match is honestly reported as not matching.

## Why abstention rests on an exact signal

ADR-021's rule is that a guard is judged on how rarely it fires, and an abstention is
user-visible. So the gate does not ask "is the winner's score high enough?" — there is no
score. It asks a checkable question: **is there a second candidate that nothing in the
ranking separates from the winner?** Two controls in the same tier whose geometry is
indistinguishable really are indistinguishable, and that is the overlapping-controls case
the ADR requires abstention for.

Candidate confidence and freshness are explicitly *not* separators. Grounding one of two
geometrically identical controls because its source reported ``0.9`` instead of ``0.7`` is
precisely the "one opaque number" the ADR forbids acting on.

The coarse-gaze consequence is worth stating plainly, because it is the whole reason this
layer exists: when a caller supplies a target *region* rather than a bare point, the
region is the sensor's uncertainty, and distance to its centre is noise. The resolver
therefore refuses to separate two candidates by distance in that case. A gaze region
covering three similar buttons is ambiguous, and it stays ambiguous until the user's own
words — a hint — narrow it. Callers that hand the resolver a bare point are asserting
that the point is precise.

## What it deliberately cannot do

* **Emit ``WINDOW_MATCH`` evidence.** Nothing in ``SemanticCandidate`` carries a window
  id, so this resolver cannot check a window match and must not claim one. The only place
  that knows is ``SemanticSource.snapshot(window_id=...)``, which filters before the
  candidates get here.
* **Resolve a target with no geometry.** A ``window_id`` alone cannot enforce an envelope,
  and ADR-v2-151 requires the existing window-level gaze/deixis behaviour to remain the
  fallback exactly there, so the honest answer is ``TARGET_GEOMETRY_MISSING``.
* **Raise.** Every input that the contracts accept produces one of the three outcomes.
  Abstention is a result; an exception would make the honest answer the error path.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from yazses.grounding.contracts import (
    CoordinateSpace,
    GroundingEvidence,
    GroundingResult,
    IntentHint,
    Point,
    Rect,
    SemanticCandidate,
    SemanticSourceKind,
    TargetSnapshot,
    UnresolvedReason,
)

#: ``SemanticSourceKind`` in declaration order is the spec's semantic-first preference
#: (accessibility, then application, then selection/focus metadata, then window
#: geometry). Reversed into "bigger is better" ranks here rather than written out as a
#: literal table: a member added to the enum gets a rank automatically instead of
#: silently ranking last, and there is no second copy of the order to fall out of sync.
_SOURCE_RANK: dict[SemanticSourceKind, int] = {
    kind: rank for rank, kind in enumerate(reversed(list(SemanticSourceKind)))
}


class _RejectionCause(Enum):
    """Why one candidate left the plausible set. Private: it exists to compute the
    ``UnresolvedReason`` a caller sees, and widening it into public API would be a
    second vocabulary for the same fact."""

    SPACE_MISMATCH = "space_mismatch"
    STALE = "stale"
    OFF_ENVELOPE = "off_envelope"
    HINT_MISMATCH = "hint_mismatch"
    LOW_CONFIDENCE = "low_confidence"
    NO_BOUNDS = "no_bounds"


#: A rejection cause that explains *every* discarded candidate is reported as itself;
#: a mixture is reported as the generic "nothing plausible". Only these two have a
#: distinct public reason — "the tree was stale" and "the tree was in another
#: coordinate space" are platform problems worth counting separately (#444), whereas
#: "the user looked between two things" is not a source failure at all.
_SPECIFIC_REASON: dict[_RejectionCause, UnresolvedReason] = {
    _RejectionCause.STALE: UnresolvedReason.SEMANTIC_ALL_STALE,
    _RejectionCause.SPACE_MISMATCH: UnresolvedReason.SEMANTIC_SPACE_MISMATCH,
}


def _check_finite_non_negative(name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be a finite value >= 0.0, got {value!r}")


def _check_unit_interval(name: str, value: float) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be a finite value in [0.0, 1.0], got {value!r}")


@dataclass(frozen=True)
class ResolutionPolicy:
    """Every number the resolver uses, in one injectable value.

    **No default here is measured.** RQ-G4 asks for the curve between grounded coverage,
    wrong-target rate and abstention rate on real desktops with real accessibility trees;
    until that exists, these are conservative starting points chosen so that the resolver
    errs towards abstaining, and ``tests/test_grounding_resolver.py`` measures what they
    do to a synthetic layout only to prove the resolver is neither blind nor paralysed.
    A synthetic fixture cannot license a product default and none is claimed.

    ``min_target_confidence`` is the one value with any provenance: it is the floor the
    shipped ``[gaze]`` section already applies to a gaze sample, reused rather than
    reinvented so the resolver does not disagree with the sensor's own gate.
    """

    #: Reject the whole resolution when the target source was this unsure of itself.
    min_target_confidence: float = 0.5
    #: How old ``target.timestamp_s`` may be at ``now_s``. Also caps a *future* target:
    #: the check is on the absolute difference, because a snapshot timestamped after the
    #: resolution is a caller bug and trusting it would ground against a stale layout.
    max_target_age_s: float = 0.5
    #: How far a candidate's capture time may sit from the target's. A semantic snapshot
    #: taken long before or after the moment the user pointed describes a different
    #: screen.
    max_candidate_skew_s: float = 0.5
    #: A floor on ``candidate.confidence``. Zero by default: a source that reports low
    #: confidence honestly is still evidence, and inventing a floor would discard it.
    min_candidate_confidence: float = 0.0
    #: Bounded slack for a coarse point target, in the target's own coordinate space.
    #: Zero by default — the strictest envelope, and the only one that cannot import a
    #: candidate the user was not looking at. A caller that knows its sensor's error
    #: (webcam gaze is documented at 3-5 cm) should prefer passing ``bounds``, which
    #: states the uncertainty instead of hiding it in a slack number.
    envelope_expansion_px: float = 0.0
    #: Two same-tier candidates are separated by specificity when the smaller one's area
    #: is at most this fraction of the larger's — i.e. the winner must be visibly more
    #: specific, not a pixel smaller. ``1.0`` would separate on any difference at all.
    tie_area_ratio: float = 0.8
    #: Two same-tier candidates are separated by proximity when their distances to the
    #: target point differ by more than this. Only ever consulted when the target is a
    #: bare point; see the module docstring.
    tie_distance_px: float = 4.0

    def __post_init__(self) -> None:
        _check_unit_interval("ResolutionPolicy.min_target_confidence", self.min_target_confidence)
        _check_unit_interval(
            "ResolutionPolicy.min_candidate_confidence", self.min_candidate_confidence
        )
        for name in ("max_target_age_s", "max_candidate_skew_s", "envelope_expansion_px",
                     "tie_distance_px"):
            _check_finite_non_negative(f"ResolutionPolicy.{name}", getattr(self, name))
        if not math.isfinite(self.tie_area_ratio) or not 0.0 < self.tie_area_ratio <= 1.0:
            raise ValueError(
                "ResolutionPolicy.tie_area_ratio must be in (0.0, 1.0] — a positive area "
                "can never be that fraction of another, so 0 would mean specificity never "
                f"separates anything and the gate abstained on every nest; got "
                f"{self.tie_area_ratio!r}"
            )


@dataclass(frozen=True)
class CandidateScore:
    """One plausible candidate and every component that ranked it.

    This is the spec's "expose score components rather than burying them in one opaque
    number", and there is no number to bury: each field below is a component of the
    lexicographic comparison, and a test (or a debug log, or #445's harness) can read
    exactly which one decided a result.

    It is safe to log: ``candidate`` is the value the source already handed over, and
    nothing derived here carries text.
    """

    candidate: SemanticCandidate
    #: The spec's first ranking bullet: an explicitly selected/focused entity inside the
    #: envelope outranks anything the tree merely happens to contain. ``SELECTION`` is the
    #: source kind the spec assigns to "selected/focused text or element metadata", so it
    #: is the signal for this, and it sits *above* source reliability — those two
    #: orderings answer different questions and the spec lists focus first.
    focus_rank: int
    #: Reliability of the source that reported it, from ``SemanticSourceKind``'s order.
    source_rank: int
    #: ``2`` when the candidate's bounds contain the target point or lie wholly inside the
    #: target region, ``1`` when they only overlap it or fall within the policy expansion.
    containment: int
    #: Area of the candidate's bounds. Always positive: a degenerate rectangle is refused
    #: by the plausibility filter, which is what lets the ambiguity gate divide by it.
    area: float
    #: Distance from the target point — or from the target region's centre when there is
    #: no point — to the candidate's bounds. Zero when inside.
    distance_px: float
    #: How far the candidate's capture time sat from the target's, absolute.
    skew_s: float
    #: Why this candidate was preferred, in a fixed order and drawn from a closed enum.
    evidence: tuple[GroundingEvidence, ...]

    @property
    def geometry_key(self) -> tuple[float, float]:
        """Geometric preference, bigger-is-better, and it swaps by containment class.

        Two candidates are only ever compared here when their ``containment`` is equal,
        because ``containment`` is a higher-priority key — so the swap is consistent.

        * **Both contain the target** (``2``): prefer the *smaller* one. This is ordinary
          hit-testing: a button inside a panel inside a window is what the user meant, and
          every toolkit delivers the event to the innermost element. Distance then breaks
          the remaining tie.
        * **Both merely overlap** (``1``): prefer the *nearer* one. Area first would pick a
          tiny distant checkbox over the large control the user was actually looking at.
        """
        if self.containment >= 2:
            return (-self.area, -self.distance_px)
        return (-self.distance_px, -self.area)

    @property
    def preference(self) -> tuple[float, ...]:
        """The full ranking key, bigger-is-better. Ends in confidence and freshness,
        which order the list but — see the module docstring — cannot ground a result."""
        return (
            float(self.focus_rank),
            float(self.source_rank),
            float(self.containment),
            *self.geometry_key,
            self.candidate.confidence,
            -self.skew_s,
        )

    @property
    def separable_tier(self) -> tuple[int, int, int]:
        """The categorical half of the key: differing here is a real, nameable reason to
        prefer one candidate, so it separates a pair outright."""
        return (self.focus_rank, self.source_rank, self.containment)


def _identity_key(candidate: SemanticCandidate) -> tuple[object, ...]:
    """A total order over a candidate's own fields, used only as the final tiebreak.

    Without it, two candidates that tie on every ranking component would come out in
    *input* order, and the ``alternatives`` list of an ambiguous result would then depend
    on the order the platform's tree walker happened to use — the arbitrary traversal
    order ADR-v2-151 forbids deciding anything by. With it, the whole ordering is a
    function of the candidate values alone.
    """
    space = candidate.space or CoordinateSpace("", 0)
    bounds = candidate.bounds or Rect(0.0, 0.0, 0.0, 0.0)
    return (
        candidate.entity_id,
        candidate.role,
        candidate.source.value,
        candidate.label or "",
        candidate.captured_at_s,
        candidate.confidence,
        space.name,
        space.version,
        bounds.x,
        bounds.y,
        bounds.width,
        bounds.height,
        candidate.actions,
    )


def _point_to_rect_distance(point: Point, rect: Rect) -> float:
    """Euclidean distance from a point to the nearest edge of a rectangle; 0 when inside."""
    dx = max(rect.x - point.x, 0.0, point.x - (rect.x + rect.width))
    dy = max(rect.y - point.y, 0.0, point.y - (rect.y + rect.height))
    return math.hypot(dx, dy)


def _rect_to_rect_distance(a: Rect, b: Rect) -> float:
    dx = max(b.x - (a.x + a.width), 0.0, a.x - (b.x + b.width))
    dy = max(b.y - (a.y + a.height), 0.0, a.y - (b.y + b.height))
    return math.hypot(dx, dy)


def _rect_inside(inner: Rect, outer: Rect) -> bool:
    return (
        inner.x >= outer.x
        and inner.y >= outer.y
        and inner.x + inner.width <= outer.x + outer.width
        and inner.y + inner.height <= outer.y + outer.height
    )


def _label_tokens(label: str | None) -> frozenset[str]:
    """Casefolded word tokens of a visible label, split on anything not alphanumeric.

    Whole tokens, never substrings: matching the hint token ``save`` against the label
    ``Savings account`` would be a guard firing on a coincidence, and ADR-021 says a
    signal has to be specific enough that firing means something.
    """
    if not label:
        return frozenset()
    tokens: list[str] = []
    current: list[str] = []
    for char in label:
        if char.isalnum():
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return frozenset(token.casefold() for token in tokens)


@dataclass(frozen=True)
class TargetResolver:
    """Resolve a coarse target onto one semantic candidate, or abstain.

    Stateless and immutable: the only thing it holds is its :class:`ResolutionPolicy`, so
    two calls with the same arguments cannot differ and #443 can construct one per config
    load and share it.

    ``now_s`` is a required keyword on both public methods. The resolver reads no clock —
    that is what keeps it testable — and freshness is the first thing the spec asks it to
    check, so the reading has to come from the caller and cannot be defaulted away.
    """

    policy: ResolutionPolicy = field(default_factory=ResolutionPolicy)

    # ----------------------------------------------------------------- public
    def resolve(
        self,
        target: TargetSnapshot,
        candidates: Sequence[SemanticCandidate],
        *,
        now_s: float,
        hint: IntentHint | None = None,
    ) -> GroundingResult:
        """Ground *target* onto one of *candidates*, or return why it could not."""
        reason = self._target_failure(target, now_s=now_s)
        if reason is not None:
            return GroundingResult.unresolved(target, reason)
        if not candidates:
            return GroundingResult.unresolved(
                target, UnresolvedReason.SEMANTIC_NO_CANDIDATES
            )

        scores, rejections = self._plausible(target, candidates, hint=hint)
        if not scores:
            return GroundingResult.unresolved(target, self._semantic_failure(rejections))

        best = scores[0]
        tied = [
            other for other in scores[1:] if self._indistinguishable(target, best, other)
        ]
        if tied:
            group = [best, *tied]
            return GroundingResult.ambiguous(
                target,
                [score.candidate for score in group],
                evidence=_shared_evidence(score.evidence for score in group),
            )
        return GroundingResult.grounded(
            target,
            best.candidate,
            # Never the product, never a boost: the weaker of the two observations. A
            # semantic tree cannot make a bad gaze sample good, and the spec's
            # integration test says so — "low-confidence gaze never gains confidence
            # from semantics".
            resolution_confidence=min(target.confidence, best.candidate.confidence),
            evidence=best.evidence,
            alternatives=[score.candidate for score in scores[1:]],
        )

    def score(
        self,
        target: TargetSnapshot,
        candidates: Sequence[SemanticCandidate],
        *,
        now_s: float,
        hint: IntentHint | None = None,
    ) -> tuple[CandidateScore, ...]:
        """The ranked plausible set with every component visible, best first.

        Public because the spec requires the components to be inspectable rather than
        buried, and because #445's harness needs to report *why* a fixture resolved the
        way it did without re-deriving it. Empty when the target itself failed policy or
        nothing survived the envelope — :meth:`resolve` is where that becomes a reason.
        """
        if self._target_failure(target, now_s=now_s) is not None:
            return ()
        return self._plausible(target, candidates, hint=hint)[0]

    # ---------------------------------------------------------------- private
    def _target_failure(
        self, target: TargetSnapshot, *, now_s: float
    ) -> UnresolvedReason | None:
        """Step 1 of the spec, in a fixed order so the reported reason is deterministic
        when a target fails more than one check."""
        if target.confidence < self.policy.min_target_confidence:
            return UnresolvedReason.TARGET_CONFIDENCE_BELOW_FLOOR
        if abs(now_s - target.timestamp_s) > self.policy.max_target_age_s:
            return UnresolvedReason.TARGET_STALE
        if not target.has_geometry:
            return UnresolvedReason.TARGET_GEOMETRY_MISSING
        return None

    def _semantic_failure(
        self, rejections: Sequence[_RejectionCause]
    ) -> UnresolvedReason:
        """One reason for an empty plausible set: the specific cause when it explains
        every rejection, the generic one when the causes are mixed.

        Reporting ``SEMANTIC_ALL_STALE`` because *one* of nine candidates was stale would
        put a platform bug in the metric that is supposed to count platform bugs.
        """
        distinct = set(rejections)
        if len(distinct) == 1:
            only = distinct.pop()
            if only in _SPECIFIC_REASON:
                return _SPECIFIC_REASON[only]
        return UnresolvedReason.SEMANTIC_NO_PLAUSIBLE_CANDIDATE

    def _plausible(
        self,
        target: TargetSnapshot,
        candidates: Sequence[SemanticCandidate],
        *,
        hint: IntentHint | None,
    ) -> tuple[tuple[CandidateScore, ...], tuple[_RejectionCause, ...]]:
        """Steps 2-3: filter to the spatially plausible set the hint allows, then rank.

        Exact duplicate values are collapsed first. A source that reports the same entity
        twice describes one control, and calling that an ambiguity would be a guard firing
        on its own input.
        """
        deduped = list(dict.fromkeys(candidates))
        kept: list[SemanticCandidate] = []
        rejections: list[_RejectionCause] = []
        for candidate in deduped:
            cause = self._reject(target, candidate, hint=hint)
            if cause is None:
                kept.append(candidate)
            else:
                rejections.append(cause)
        if not kept:
            return (), tuple(rejections)

        scored = [self._score_one(target, candidate, hint=hint) for candidate in kept]
        best_source_rank = max(score.source_rank for score in scored)
        unique_best_source = (
            sum(1 for score in scored if score.source_rank == best_source_rank) == 1
        )
        nearest = min(score.distance_px for score in scored)
        unique_nearest = sum(1 for score in scored if score.distance_px == nearest) == 1

        finished = [
            self._with_set_evidence(
                score,
                strictly_nearest=unique_nearest and score.distance_px == nearest,
                strictly_best_source=unique_best_source
                and score.source_rank == best_source_rank,
            )
            for score in scored
        ]
        finished.sort(key=lambda score: _identity_key(score.candidate))
        finished.sort(key=lambda score: score.preference, reverse=True)
        return tuple(finished), tuple(rejections)

    def _reject(
        self,
        target: TargetSnapshot,
        candidate: SemanticCandidate,
        *,
        hint: IntentHint | None,
    ) -> _RejectionCause | None:
        """Why this candidate is not plausible, or ``None`` if it is."""
        if candidate.bounds is None or candidate.space is None:
            # Without geometry the envelope cannot be enforced, and the envelope is the
            # one thing a hint is never allowed to substitute for.
            return _RejectionCause.NO_BOUNDS
        if candidate.bounds.width <= 0.0 or candidate.bounds.height <= 0.0:
            # A degenerate rectangle is not a control the user can look at. ``Rect`` is
            # half-open, so it cannot contain a point or intersect a region — but a policy
            # with an expansion measures *distance*, which is zero for a point sitting on
            # a zero-size rectangle, and the candidate would sail through the envelope
            # with no extent at all. This is also what lets the ambiguity gate divide by
            # an area; see the zero-area test in `tests/test_grounding_resolver.py`, which
            # is the one that found it. (Spelled as a file, not a test name split over two
            # lines: `tests/test_repo_hygiene_test_references.py` reads the half-name as a
            # dangling reference, and it only scans *tracked* files, so the break survives
            # every run until the file is committed.)
            return _RejectionCause.NO_BOUNDS
        if candidate.space != target.space:
            return _RejectionCause.SPACE_MISMATCH
        if abs(candidate.captured_at_s - target.timestamp_s) > self.policy.max_candidate_skew_s:
            return _RejectionCause.STALE
        if candidate.confidence < self.policy.min_candidate_confidence:
            return _RejectionCause.LOW_CONFIDENCE
        if self._containment(target, candidate.bounds) == 0:
            return _RejectionCause.OFF_ENVELOPE
        if hint is not None and not self._hint_allows(candidate, hint):
            return _RejectionCause.HINT_MISMATCH
        return None

    def _containment(self, target: TargetSnapshot, bounds: Rect) -> int:
        """``2`` inside, ``1`` overlapping or within the expansion, ``0`` off-envelope.

        The three acceptable forms are exactly the spec's Step 2 list, in an ``or``: the
        bounds contain the point, they intersect the explicit region, or they fall inside
        a bounded expansion the policy opted into.
        """
        expansion = self.policy.envelope_expansion_px
        if target.point is not None and bounds.contains(target.point):
            return 2
        if target.bounds is not None and _rect_inside(bounds, target.bounds):
            return 2
        if target.bounds is not None and bounds.intersects(target.bounds):
            return 1
        if expansion > 0.0:
            distance = self._distance(target, bounds)
            if distance <= expansion:
                return 1
        return 0

    def _distance(self, target: TargetSnapshot, bounds: Rect) -> float:
        if target.point is not None:
            return _point_to_rect_distance(target.point, bounds)
        assert target.bounds is not None  # has_geometry, and no point
        return _rect_to_rect_distance(target.bounds, bounds)

    def _hint_allows(self, candidate: SemanticCandidate, hint: IntentHint) -> bool:
        if hint.role is not None and hint.role != candidate.role.casefold():
            return False
        if hint.label_tokens and not set(hint.label_tokens) <= _label_tokens(candidate.label):
            return False
        return True

    def _score_one(
        self,
        target: TargetSnapshot,
        candidate: SemanticCandidate,
        *,
        hint: IntentHint | None,
    ) -> CandidateScore:
        bounds = candidate.bounds
        assert bounds is not None  # guaranteed by _reject
        containment = self._containment(target, bounds)
        evidence: list[GroundingEvidence] = []
        if containment == 2 or (
            target.bounds is not None and bounds.intersects(target.bounds)
        ):
            # Claimed only when the candidate really meets the target's own geometry.
            # A candidate that qualified through the policy expansion did not, and
            # saying it did would make the evidence unreadable exactly where the
            # expansion is the thing under review.
            evidence.append(GroundingEvidence.INSIDE_TARGET_REGION)
        if hint is not None and hint.role is not None:
            evidence.append(GroundingEvidence.ROLE_MATCH)
        if hint is not None and hint.label_tokens:
            evidence.append(GroundingEvidence.LABEL_HINT_MATCH)
        if candidate.source is SemanticSourceKind.SELECTION:
            evidence.append(GroundingEvidence.EXACT_ACCESSIBILITY_FOCUS)
        return CandidateScore(
            candidate=candidate,
            focus_rank=1 if candidate.source is SemanticSourceKind.SELECTION else 0,
            source_rank=_SOURCE_RANK[candidate.source],
            containment=containment,
            area=bounds.width * bounds.height,
            distance_px=self._distance(target, bounds),
            skew_s=abs(candidate.captured_at_s - target.timestamp_s),
            evidence=tuple(evidence),
        )

    def _with_set_evidence(
        self,
        score: CandidateScore,
        *,
        strictly_nearest: bool,
        strictly_best_source: bool,
    ) -> CandidateScore:
        """Add the two evidence kinds that are properties of the *set*, not the candidate.

        Both are claimed only when they are strict: "nearest" when exactly one candidate
        is nearest, "source quality" when exactly one comes from the best source present.
        Evidence that every candidate carries explains nothing.
        """
        extra: list[GroundingEvidence] = []
        if strictly_nearest:
            extra.append(GroundingEvidence.NEAREST_TO_TARGET_POINT)
        if strictly_best_source:
            extra.append(GroundingEvidence.SOURCE_QUALITY)
        if not extra:
            return score
        merged = list(score.evidence) + extra
        ordered = tuple(member for member in GroundingEvidence if member in merged)
        return CandidateScore(
            candidate=score.candidate,
            focus_rank=score.focus_rank,
            source_rank=score.source_rank,
            containment=score.containment,
            area=score.area,
            distance_px=score.distance_px,
            skew_s=score.skew_s,
            evidence=ordered,
        )

    def _indistinguishable(
        self, target: TargetSnapshot, best: CandidateScore, other: CandidateScore
    ) -> bool:
        """The ambiguity gate: is there any nameable reason to prefer *best* over *other*?

        Answered on the exact components only, and each component may only separate the
        pair **in the direction the ranking actually went** — a separator that argued for
        the runner-up would be a justification for a decision it did not make. That is why
        both helpers below test ``best`` being strictly the smaller or strictly the nearer
        rather than an absolute difference.

        Returning ``True`` costs the user an interruption (ADR-021), so what is *not* here
        matters as much: candidate confidence and freshness order the list and never reach
        this method. Grounding one of two geometrically identical controls because one
        source said ``0.9`` and the other ``0.7`` would be acting on exactly the opaque
        number ADR-v2-151 forbids.
        """
        if best.separable_tier != other.separable_tier:
            return False
        if self._area_separates(best, other):
            return False
        if self._distance_separates(target, best, other):
            return False
        return True

    def _area_separates(self, best: CandidateScore, other: CandidateScore) -> bool:
        """Whether *best* is specific enough, and enough smaller, to win on nesting.

        A button inside a panel is a large ratio apart; two same-sized siblings a pixel
        apart are not, and separating them would be a guard firing on rounding.
        """
        if other.area <= 0.0 or best.area >= other.area:
            return False
        return best.area / other.area <= self.policy.tie_area_ratio

    def _distance_separates(
        self, target: TargetSnapshot, best: CandidateScore, other: CandidateScore
    ) -> bool:
        """Whether proximity may break this tie at all.

        It may not when the caller supplied a target *region*: the region is the sensor's
        uncertainty, so which candidate sits nearer its centre is noise, and grounding on
        noise is the wrong-target failure this layer exists to avoid. With a bare point
        the caller is asserting precision, and *best* being nearer by more than the policy
        tolerance is then a real signal.
        """
        if target.bounds is not None:
            return False
        return other.distance_px - best.distance_px > self.policy.tie_distance_px


def _shared_evidence(
    groups: Iterable[tuple[GroundingEvidence, ...]],
) -> tuple[GroundingEvidence, ...]:
    """Evidence that applies to *every* tied candidate, in enum order.

    An ambiguous result explains what the tied group has in common — "all of these are
    inside the region you looked at" — and nothing more. Handing back the leader's own
    evidence would describe a preference the resolver just refused to act on.
    """
    sets = [set(group) for group in groups]
    if not sets:
        return ()
    common = set.intersection(*sets)
    return tuple(member for member in GroundingEvidence if member in common)
