"""Hands-free composition — one global safety state for every camera-driven input (ADR-v2-148).

`handsfree` is a composition of ordinary capabilities, not a second pipeline. What lives here is
the part the components must *share*: a single ACTIVE / PAUSED / FAULTED state plus a
stale-signal watchdog that every continuous input source (gaze, Head-Pointer, face switch) asks
before it moves a cursor or commits a click.

``safety`` is pure — no camera, no thread, no backend, a caller-supplied clock. OFF by default
(``[handsfree_safety] enabled``); ``gate_from_config`` returns None until the user opts in, so an
existing install behaves exactly as it did before.
"""
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
    "HandsFreeSafety",
    "RearmResult",
    "SafetyLimits",
    "SafetyState",
    "SafetyStatus",
    "SourceHealth",
    "gate_from_config",
    "monotonic_ms",
]
