"""Gaze-routed dictation targeting (pure) — ADR-v2-010.

Decide which window the next dictation/command lands in, given the look-to-pane
resolution (``zones.resolve_window``) + a confidence gate, falling back to the
focused window when gaze is uncertain so it never misroutes. Destructive
gaze-routed actions are flagged for a confirm because consumer-webcam gaze is
coarse (~1–2°). The webcam backend (``gaze/l2cs``) stays lazy; this layer is pure
and testable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteDecision:
    target: object | None      # window id the dictation should land in (or None)
    used_gaze: bool            # True if gaze chose it; False if it fell back to focus
    confident: bool


def route_target(
    resolved_window, confidence: float, focused_window, *, confidence_min: float = 0.5
) -> RouteDecision:
    """Choose the dictation target window from a gaze resolution + confidence.

    When ``confidence >= confidence_min`` and a window resolved under the gaze,
    that window is the target (``used_gaze=True``). Otherwise fall back to the
    focused window (``used_gaze=False``) so uncertain gaze never misroutes. Pure.
    """
    confident = confidence >= confidence_min and resolved_window is not None
    if confident:
        return RouteDecision(target=resolved_window, used_gaze=True, confident=True)
    return RouteDecision(target=focused_window, used_gaze=False, confident=False)


def needs_confirm(decision: RouteDecision, is_destructive: bool) -> bool:
    """Whether a gaze-routed action should confirm before running.

    Only destructive actions that were actually routed by gaze confirm — focus-
    fallback routes and non-destructive actions do not, so the common case stays
    frictionless while a coarse-gaze misroute of a destructive action is guarded.
    """
    return bool(is_destructive and decision.used_gaze)
