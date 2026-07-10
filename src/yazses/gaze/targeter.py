"""Runtime look-to-pane targeting — sample gaze, pick a window, focus it.

Wires the three parts the daemon calls at hold-start: the gaze backend (one
``(yaw, pitch)`` sample), the persisted calibration map, and the desktop backend
(window list + focus). It applies the pure :mod:`~yazses.gaze.route` policy —
route to the looked-at window only when gaze is confident and lands on a window,
else leave the focused window untouched so uncertain gaze never misroutes.

Frames live only inside ``backend.estimate()`` (in-RAM, never stored — ADR-011).
"""
from __future__ import annotations

import logging

from yazses.gaze.route import RouteDecision, route_target
from yazses.gaze.zones import resolve_window

log = logging.getLogger(__name__)


class GazeTargeter:
    """Focus the window the user is looking at, for the next dictation."""

    def __init__(self, backend, calibration, desktop, confidence_min: float = 0.5) -> None:
        self._backend = backend
        self._calibration = calibration
        self._desktop = desktop
        self._confidence_min = confidence_min

    def retarget(self) -> RouteDecision:
        """Sample gaze and focus the looked-at window; return the decision.

        No confident gaze (no face / low confidence) or a point outside every
        window falls back to the focused window and changes nothing.
        """
        focused = self._desktop.focused_window()
        gaze = self._backend.estimate()
        if gaze is None:
            return route_target(None, 0.0, focused, confidence_min=self._confidence_min)

        yaw, pitch = gaze
        windows = self._desktop.list_windows()
        resolved = resolve_window(self._calibration, yaw, pitch, windows)
        # l2cs gates confidence internally (None below threshold), so a returned
        # sample counts as confident; the pure policy still needs a window match.
        decision = route_target(
            resolved, 1.0, focused, confidence_min=self._confidence_min
        )
        if decision.used_gaze and decision.target is not None and decision.target != focused:
            try:
                self._desktop.activate(decision.target)
                log.info("Gaze routed dictation to window %s", decision.target)
            except Exception as exc:  # focus is best-effort; never break dictation
                log.warning("Gaze re-focus failed (%s); using focused window.", exc)
                return route_target(None, 0.0, focused, confidence_min=self._confidence_min)
        return decision

    def close(self) -> None:
        """Release the camera held by the backend."""
        try:
            self._backend.close()
        except Exception:
            pass
