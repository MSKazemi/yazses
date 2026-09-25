"""Grounded target resolution — coarse pointing to an exact semantic UI entity.

ADR-v2-151 / ``design/specs/eye-grounded-targets.md``. Two modules, both pure:

* :mod:`yazses.grounding.contracts` (phase P0) — the dependency-free vocabulary of
  target snapshots, semantic candidates, intent hints and tri-state grounding results;
* :mod:`yazses.grounding.resolver` (phase P1) — the deterministic resolver that turns
  one coarse target plus a list of candidates into ``GROUNDED``, ``AMBIGUOUS`` or
  ``UNRESOLVED``, and holds every threshold and preference the vocabulary refuses to.

Nothing in here imports a platform accessibility library, captures the screen, reads a
clock, or performs an action, and nothing in the daemon imports it yet — the gaze/deixis
seam (#443) and the evaluation harness (#445) are separate changes.
"""

from __future__ import annotations

from yazses.grounding.contracts import (
    CoordinateSpace,
    GroundingEvidence,
    GroundingOutcome,
    GroundingResult,
    IntentHint,
    Point,
    Rect,
    SemanticCandidate,
    SemanticSource,
    SemanticSourceKind,
    TargetSnapshot,
    TargetSource,
    UnresolvedReason,
)
from yazses.grounding.resolver import CandidateScore, ResolutionPolicy, TargetResolver

__all__ = [
    "CandidateScore",
    "CoordinateSpace",
    "GroundingEvidence",
    "GroundingOutcome",
    "GroundingResult",
    "IntentHint",
    "Point",
    "Rect",
    "ResolutionPolicy",
    "SemanticCandidate",
    "SemanticSource",
    "SemanticSourceKind",
    "TargetResolver",
    "TargetSnapshot",
    "TargetSource",
    "UnresolvedReason",
]
