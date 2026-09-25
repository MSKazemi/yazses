"""Grounded target resolution — coarse pointing to an exact semantic UI entity.

ADR-v2-151 / ``design/specs/eye-grounded-targets.md``. This package currently holds
phase P0 only: :mod:`yazses.grounding.contracts`, the dependency-free vocabulary of
target snapshots, semantic candidates and tri-state grounding results.

Nothing in here imports a platform accessibility library, captures the screen, or
performs an action, and nothing in the daemon imports it yet — the resolver (#442),
the gaze/deixis seam (#443) and the evaluation harness (#445) are separate changes.
"""

from __future__ import annotations

from yazses.grounding.contracts import (
    CoordinateSpace,
    GroundingEvidence,
    GroundingOutcome,
    GroundingResult,
    Point,
    Rect,
    SemanticCandidate,
    SemanticSource,
    SemanticSourceKind,
    TargetSnapshot,
    TargetSource,
)

__all__ = [
    "CoordinateSpace",
    "GroundingEvidence",
    "GroundingOutcome",
    "GroundingResult",
    "Point",
    "Rect",
    "SemanticCandidate",
    "SemanticSource",
    "SemanticSourceKind",
    "TargetSnapshot",
    "TargetSource",
]
