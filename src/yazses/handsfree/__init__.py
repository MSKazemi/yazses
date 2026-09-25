"""Hands-free composition — one global safety state for every camera-driven input (ADR-v2-148).

`handsfree` is a composition of ordinary capabilities, not a second pipeline. What lives here is
the part the components must *share*: a single ACTIVE / PAUSED / FAULTED state plus a
stale-signal watchdog that every continuous input source (gaze, Head-Pointer, face switch) asks
before it moves a cursor or commits a click.

``safety`` is pure — no camera, no thread, no backend, a caller-supplied clock. OFF by default
(``[handsfree_safety] enabled``); ``gate_from_config`` returns None until the user opts in, so an
existing install behaves exactly as it did before.

``observability`` is the other half of that share: one set of privacy-safe health rows —
names, states, ages, counts and capability flags, never a sample value — that both `doctor`
and `status` render, so the two surfaces cannot describe the same machine differently. It is
pure too; ``probe`` is the impure gatherer beside it.
"""
from yazses.handsfree.observability import (
    HandsFreeFacts,
    Health,
    HealthRow,
    as_payload,
    doctor_rows,
    facts_from_payload,
    health_rows,
    render_status_lines,
)
from yazses.handsfree.safety import (
    DEFAULT_STALE_AFTER_MS,
    Decision,
    HandsFreeSafety,
    RearmResult,
    SafetyLimits,
    SafetyState,
    SafetyStatus,
    SourceHealth,
    gate_from_config,
    monotonic_ms,
)

__all__ = [
    "DEFAULT_STALE_AFTER_MS",
    "Decision",
    "HandsFreeFacts",
    "HandsFreeSafety",
    "Health",
    "HealthRow",
    "RearmResult",
    "SafetyLimits",
    "SafetyState",
    "SafetyStatus",
    "SourceHealth",
    "as_payload",
    "doctor_rows",
    "facts_from_payload",
    "gate_from_config",
    "health_rows",
    "monotonic_ms",
    "render_status_lines",
]
