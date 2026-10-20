"""Deterministic replay of grounding traces: coverage, wrong target, ambiguity, abstention.

Phase P4 of ``design/specs/eye-grounded-targets.md`` (ADR-v2-151), the harness the
resolver's own docstring points at. Given the validated cases of
``src/yazses/grounding/trace.py`` it replays each one through the real
``TargetResolver`` — there is no second resolver here, and no scoring of its own — and
reports the five outcome counts ``design/eye-control/METRICS.md`` names, the two rates
the ADR insists are different errors, the candidate-count distributions before and after
an intent hint, and the target-source / semantic-source split of every abstention.

It reads no clock (``now_s`` is a field of the recorded case), touches no file (the
command-line front end ``scripts/replay_grounding_trace.py`` does the reading) and
imports nothing outside the standard library and this package's own vocabulary. The same
trace therefore produces byte-identical output on any machine, which is what makes the
committed report reviewable in a diff.

---

## The two strategies, and why the comparison is honest

Both strategies run the *same* resolver with the *same* policy. The only difference is
what each is allowed to see, which is the only difference the product has:

* ``window_only`` — the behaviour that ships today. Window-level gaze/deixis knows the
  focused window's rectangle and nothing inside it, so the strategy passes the resolver
  only the candidates whose source is ``SemanticSourceKind.WINDOW``, and it passes no
  intent hint, because nothing in the current path matches a spoken label against a
  structured element.
* ``semantic_grounding`` — every candidate the trace recorded, plus the case's hint.

Implementing ``window_only`` as a *filter over the shared resolver* rather than as a
second code path is deliberate: a hand-written baseline could differ from the product for
reasons that have nothing to do with semantics, and the comparison would then measure the
baseline's bugs.

**Read the ``window_only`` column carefully.** Under the classification rule below it
scores almost everything as a wrong target, because grounding the containing window is
not grounding the control the user meant. That is a true statement about *exact-element*
grounding and a misleading one about risk: a coarse window ground is the existing
fallback, not a misclick on the wrong button. So every wrong target is additionally
broken down by the source kind of the entity it landed on — ``grounded_wrong_by_source``
— and a column whose wrongs are all ``window`` is describing coarseness, while one with
``accessibility`` wrongs is describing the failure ADR-021 actually charges for.

## Classification, stated once

For each case and strategy, exactly one of five buckets:

* ``grounded_correct`` — grounded, and the entity is ``expected_entity_id``;
* ``grounded_wrong`` — grounded to anything else, **including when
  ``expected_entity_id`` is ``null``**, which is the trace's positive statement that no
  element is the right answer and abstention was correct;
* ``ambiguous`` — the resolver named several plausible candidates;
* ``unresolved`` — the resolver abstained and said why.

``ambiguous`` and ``unresolved`` are abstentions. The ADR's rule is that a wrong target
and an abstention are not the same error, so they are never summed into one "failure"
number; the only place they are added together is ``abstention_rate``, which is what that
rate means.

## Zero denominators, decided rather than divided

1. **A trace with no cases is refused**, by ``src/yazses/grounding/trace.py`` when it is
   read and by :func:`replay` when it is handed one anyway. ``total_trials`` is therefore
   always at least one and ``wrong_target_rate`` and ``abstention_rate`` are always real
   numbers. A harness that answered ``0.0`` on nothing would report a perfect run.
2. **A derived rate whose own denominator is zero is reported as missing, never as
   zero**: ``{"value": null, "reason": ...}`` with a reason from ``METRICS.md``'s missing
   list, which is the convention ``src/yazses/eyeeval/schema.py`` already enforces on
   result documents. ``grounded_correct_share_of_grounded`` when nothing grounded is
   ``not_measured``; the after-hint candidate distribution is ``not_measured`` when no
   case carried a hint, and ``not_supported`` for ``window_only``, which by construction
   never consults one.

## No product threshold follows from any of this

Every fixture is invented. The numbers below describe five synthetic layouts and licence
nothing: RQ-G4 in ``design/eye-control/GROUNDED_INTERACTION_RESEARCH.md`` measures the
real curve on real desktops with real accessibility trees, and both the spec and
``ResolutionPolicy``'s own docstring forbid picking a product default from a fixture. The
report says so in a field, so a reader who sees only the JSON is told too.

## What is never in a report

No label, no window title, no free text from the trace. A report carries entity ids,
role-free enum members (``GroundingEvidence``, ``UnresolvedReason``), counts and rates.
The evidence and reason vocabularies are closed enums precisely so that printing them
cannot leak, and ``tests/test_grounding_replay.py`` checks that no fixture label reaches
the document.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, fields
from enum import Enum
from typing import Any

from yazses.grounding.contracts import (
    GroundingEvidence,
    GroundingOutcome,
    Rect,
    SemanticCandidate,
    SemanticSourceKind,
    UnresolvedReason,
)
from yazses.grounding.resolver import ResolutionPolicy, TargetResolver
from yazses.grounding.trace import TraceCase

#: The report envelope version. ``MAJOR.MINOR`` with the same rule the trace uses.
REPORT_VERSION = "1.0"

#: Repeated verbatim into every report so a reader of the JSON alone is told.
NO_THRESHOLD_NOTICE = (
    "Synthetic fixtures only. No product threshold, default or acceptance criterion "
    "follows from these numbers; they describe invented layouts. The real curve between "
    "grounded coverage, wrong-target rate and abstention rate is RQ-G4 in "
    "design/eye-control/GROUNDED_INTERACTION_RESEARCH.md and has to be measured on real "
    "desktops with real accessibility trees."
)

#: The zero-denominator decision, in the document rather than only in the docstring.
ZERO_DENOMINATOR_RULE = (
    "A trace with no cases is refused, so total_trials >= 1 and wrong_target_rate and "
    "abstention_rate are always defined. A derived rate whose own denominator is zero is "
    'reported as {"value": null, "reason": ...}, never as 0.0.'
)


class Strategy(Enum):
    """What the resolver is allowed to see. See the module docstring."""

    WINDOW_ONLY = "window_only"
    SEMANTIC_GROUNDING = "semantic_grounding"


class Classification(Enum):
    """The five buckets ``METRICS.md`` reports, one per case per strategy."""

    GROUNDED_CORRECT = "grounded_correct"
    GROUNDED_WRONG = "grounded_wrong"
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"

    @property
    def is_abstention(self) -> bool:
        return self in (Classification.AMBIGUOUS, Classification.UNRESOLVED)


class GroundingReplayError(ValueError):
    """The harness was asked to report on something it cannot honestly report on."""


def _missing(reason: str) -> dict[str, Any]:
    """``METRICS.md``'s missing-data marker. Missing is never zero."""
    return {"value": None, "reason": reason}


def _rate(numerator: int, denominator: int, *, reason: str) -> float | dict[str, Any]:
    """A rate, or an explicit missing marker when the denominator is zero."""
    if denominator == 0:
        return _missing(reason)
    return round(numerator / denominator, 6)


def _strictly_contains(outer: Rect | None, inner: Rect | None) -> bool:
    if outer is None or inner is None:
        return False
    if outer.width * outer.height <= inner.width * inner.height:
        return False
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and inner.x + inner.width <= outer.x + outer.width
        and inner.y + inner.height <= outer.y + outer.height
    )


def visible_candidates(
    case: TraceCase, strategy: Strategy
) -> tuple[SemanticCandidate, ...]:
    """What *strategy* is allowed to pass to the resolver for *case*."""
    if strategy is Strategy.WINDOW_ONLY:
        return tuple(
            candidate
            for candidate in case.candidates
            if candidate.source is SemanticSourceKind.WINDOW
        )
    return case.candidates


@dataclass(frozen=True)
class CaseOutcome:
    """One case replayed under one strategy, with everything a reviewer needs.

    Every field is a count, a boolean, an id the trace already declared synthetic, or a
    member of a closed enum. There is deliberately nowhere to put a label.
    """

    case_id: str
    trace_id: str
    strategy: Strategy
    classification: Classification
    outcome: GroundingOutcome
    expected_entity_id: str | None
    entity_id: str | None
    entity_source: SemanticSourceKind | None
    unresolved_reason: UnresolvedReason | None
    evidence: tuple[GroundingEvidence, ...]
    alternatives: int
    plausible_candidates: int
    plausible_candidates_after_hint: int | None
    wrong_target_contains_expected: bool

    def to_document(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "classification": self.classification.value,
            "entity_id": self.entity_id,
            "entity_source": (
                self.entity_source.value if self.entity_source is not None else None
            ),
            "unresolved_reason": (
                self.unresolved_reason.value
                if self.unresolved_reason is not None
                else None
            ),
            "evidence": [member.value for member in self.evidence],
            "alternatives": self.alternatives,
            "plausible_candidates": self.plausible_candidates,
            "plausible_candidates_after_hint": self.plausible_candidates_after_hint,
            "wrong_target_contains_expected": self.wrong_target_contains_expected,
        }


def replay_case(
    case: TraceCase, *, strategy: Strategy, resolver: TargetResolver
) -> CaseOutcome:
    """Replay one case under one strategy. Never raises: the resolver cannot."""
    candidates = visible_candidates(case, strategy)
    hint = case.hint if strategy is Strategy.SEMANTIC_GROUNDING else None

    # The plausible set *before* the hint is the spatial envelope alone, which is what
    # `METRICS.md` calls "candidates spatially plausible after coarse-target filtering".
    # It is measured with `hint=None` for both strategies so the two columns count the
    # same thing.
    before = len(resolver.score(case.target, candidates, now_s=case.now_s, hint=None))
    after = (
        len(resolver.score(case.target, candidates, now_s=case.now_s, hint=hint))
        if hint is not None
        else None
    )

    result = resolver.resolve(case.target, candidates, now_s=case.now_s, hint=hint)
    expected = case.expected_entity_id
    grounded = result.candidate

    if result.outcome is GroundingOutcome.AMBIGUOUS:
        classification = Classification.AMBIGUOUS
    elif result.outcome is GroundingOutcome.UNRESOLVED:
        classification = Classification.UNRESOLVED
    elif grounded is not None and expected is not None and grounded.entity_id == expected:
        classification = Classification.GROUNDED_CORRECT
    else:
        classification = Classification.GROUNDED_WRONG

    contains_expected = False
    if classification is Classification.GROUNDED_WRONG and expected is not None:
        wanted = case.candidate_by_id(expected)
        contains_expected = _strictly_contains(
            grounded.bounds if grounded is not None else None,
            wanted.bounds if wanted is not None else None,
        )

    return CaseOutcome(
        case_id=case.case_id,
        trace_id=case.trace_id,
        strategy=strategy,
        classification=classification,
        outcome=result.outcome,
        expected_entity_id=expected,
        entity_id=grounded.entity_id if grounded is not None else None,
        entity_source=grounded.source if grounded is not None else None,
        unresolved_reason=result.unresolved_reason,
        evidence=result.evidence,
        alternatives=len(result.alternatives),
        plausible_candidates=before,
        plausible_candidates_after_hint=after,
        wrong_target_contains_expected=contains_expected,
    )


@dataclass(frozen=True)
class StrategyReport:
    """The aggregate for one strategy over the whole trace set."""

    strategy: Strategy
    outcomes: tuple[CaseOutcome, ...]

    @property
    def total_trials(self) -> int:
        return len(self.outcomes)

    def count(self, classification: Classification) -> int:
        return sum(
            1 for outcome in self.outcomes if outcome.classification is classification
        )

    @property
    def abstentions(self) -> int:
        return sum(1 for outcome in self.outcomes if outcome.classification.is_abstention)

    def to_document(self) -> dict[str, Any]:
        total = self.total_trials
        correct = self.count(Classification.GROUNDED_CORRECT)
        wrong = self.count(Classification.GROUNDED_WRONG)
        ambiguous = self.count(Classification.AMBIGUOUS)
        unresolved = self.count(Classification.UNRESOLVED)

        wrong_by_source = Counter(
            outcome.entity_source.value
            for outcome in self.outcomes
            if outcome.classification is Classification.GROUNDED_WRONG
            and outcome.entity_source is not None
        )
        by_reason = Counter(
            outcome.unresolved_reason.value
            for outcome in self.outcomes
            if outcome.unresolved_reason is not None
        )
        target_failures = sum(
            1
            for outcome in self.outcomes
            if outcome.unresolved_reason is not None
            and outcome.unresolved_reason.is_target_source_failure
        )
        semantic_failures = sum(
            1
            for outcome in self.outcomes
            if outcome.unresolved_reason is not None
            and outcome.unresolved_reason.is_semantic_source_failure
        )

        before = Counter(outcome.plausible_candidates for outcome in self.outcomes)
        hinted = [
            outcome.plausible_candidates_after_hint
            for outcome in self.outcomes
            if outcome.plausible_candidates_after_hint is not None
        ]
        if self.strategy is Strategy.WINDOW_ONLY:
            # Not an absence of data: window-level deixis has no structured element to
            # match a spoken label against, so the number does not exist for it.
            after: dict[str, Any] = _missing("not_supported")
        elif not hinted:
            after = _missing("not_measured")
        else:
            after = {str(size): count for size, count in sorted(Counter(hinted).items())}

        return {
            "counts": {
                "total_trials": total,
                "grounded_correct": correct,
                "grounded_wrong": wrong,
                "ambiguous": ambiguous,
                "unresolved": unresolved,
                "grounded_wrong_by_source": dict(sorted(wrong_by_source.items())),
                "grounded_wrong_containing_expected": sum(
                    1
                    for outcome in self.outcomes
                    if outcome.wrong_target_contains_expected
                ),
            },
            "rates": {
                "grounded_correct_rate": _rate(correct, total, reason="not_measured"),
                "wrong_target_rate": _rate(wrong, total, reason="not_measured"),
                "ambiguity_rate": _rate(ambiguous, total, reason="not_measured"),
                "unresolved_rate": _rate(unresolved, total, reason="not_measured"),
                "abstention_rate": _rate(self.abstentions, total, reason="not_measured"),
                "grounded_correct_share_of_grounded": _rate(
                    correct, correct + wrong, reason="not_measured"
                ),
            },
            "abstention_sources": {
                "target_source_failure": target_failures,
                "semantic_source_failure": semantic_failures,
                "by_reason": dict(sorted(by_reason.items())),
            },
            "candidate_counts": {
                "cases_with_hint": len(hinted),
                "before_hint": {
                    str(size): count for size, count in sorted(before.items())
                },
                "after_hint": after,
            },
        }


@dataclass(frozen=True)
class ReplayReport:
    """Every strategy's aggregate plus the per-case rows, ready to serialise."""

    cases: tuple[TraceCase, ...]
    strategies: tuple[StrategyReport, ...]
    policy: ResolutionPolicy

    def strategy(self, strategy: Strategy) -> StrategyReport:
        for report in self.strategies:
            if report.strategy is strategy:
                return report
        raise KeyError(strategy)

    def to_document(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        by_case: dict[str, dict[str, Any]] = {}
        for case in sorted(self.cases, key=lambda item: item.case_id):
            row: dict[str, Any] = {
                "case_id": case.case_id,
                "trace_id": case.trace_id,
                "expected_entity_id": case.expected_entity_id,
                "has_hint": case.hint is not None,
                "candidates": len(case.candidates),
            }
            by_case[case.case_id] = row
            rows.append(row)
        for report in sorted(self.strategies, key=lambda item: item.strategy.value):
            for outcome in report.outcomes:
                by_case[outcome.case_id][report.strategy.value] = outcome.to_document()

        traces = Counter(case.trace_id for case in self.cases)
        return {
            "report_version": REPORT_VERSION,
            "no_threshold_notice": NO_THRESHOLD_NOTICE,
            "zero_denominator_rule": ZERO_DENOMINATOR_RULE,
            "policy": {
                item.name: getattr(self.policy, item.name)
                for item in sorted(fields(self.policy), key=lambda f: f.name)
            },
            "traces": [
                {"trace_id": trace_id, "cases": count}
                for trace_id, count in sorted(traces.items())
            ],
            "total_trials": len(self.cases),
            "strategies": {
                report.strategy.value: report.to_document()
                for report in sorted(
                    self.strategies, key=lambda item: item.strategy.value
                )
            },
            "cases": rows,
        }


def replay(
    cases: Sequence[TraceCase],
    *,
    policy: ResolutionPolicy | None = None,
    strategies: Sequence[Strategy] = tuple(Strategy),
) -> ReplayReport:
    """Replay *cases* under each strategy and aggregate.

    Raises :class:`GroundingReplayError` on an empty case list. That is the whole of the
    empty-collection decision: a report over zero trials is not a weaker report, it is a
    false one, because every rate in it would read as a perfect score.
    """
    ordered = tuple(cases)
    if not ordered:
        raise GroundingReplayError(
            "refusing to report on zero trials: every rate would be 0.0, which is "
            "indistinguishable in the output from a run with no wrong targets. Supply at "
            "least one trace case."
        )
    duplicates = [
        case_id
        for case_id, count in Counter(case.case_id for case in ordered).items()
        if count > 1
    ]
    if duplicates:
        raise GroundingReplayError(
            "case ids must be unique across the whole trace set, or a case silently "
            f"replaces another in the report: {sorted(duplicates)}"
        )
    resolver = TargetResolver(policy=policy or ResolutionPolicy())
    return ReplayReport(
        cases=ordered,
        strategies=tuple(
            StrategyReport(
                strategy=strategy,
                outcomes=tuple(
                    replay_case(case, strategy=strategy, resolver=resolver)
                    for case in ordered
                ),
            )
            for strategy in strategies
        ),
        policy=resolver.policy,
    )
