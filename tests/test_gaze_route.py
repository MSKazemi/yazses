"""Gaze-Routed Dictation targeting (ADR-v2-010) — pure confidence-gated routing."""
from __future__ import annotations

from yazses.gaze.route import RouteDecision, needs_confirm, route_target


def test_confident_gaze_routes_to_looked_at_window():
    d = route_target("win_editor", 0.8, "win_focused", confidence_min=0.5)
    assert d.target == "win_editor"
    assert d.used_gaze is True
    assert d.confident is True


def test_low_confidence_falls_back_to_focus():
    d = route_target("win_editor", 0.3, "win_focused", confidence_min=0.5)
    assert d.target == "win_focused"
    assert d.used_gaze is False
    assert d.confident is False


def test_no_resolved_window_falls_back_to_focus():
    d = route_target(None, 0.9, "win_focused", confidence_min=0.5)
    assert d.target == "win_focused"
    assert d.used_gaze is False


def test_confidence_exactly_at_threshold_routes():
    d = route_target("w", 0.5, "f", confidence_min=0.5)
    assert d.used_gaze is True


def test_confirm_only_for_destructive_gaze_routes():
    gaze = RouteDecision(target="w", used_gaze=True, confident=True)
    focus = RouteDecision(target="f", used_gaze=False, confident=False)
    assert needs_confirm(gaze, is_destructive=True) is True
    assert needs_confirm(gaze, is_destructive=False) is False
    # a focus-fallback route never needs the gaze confirm
    assert needs_confirm(focus, is_destructive=True) is False
