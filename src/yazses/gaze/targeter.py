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
        #: The decision from the most recent retarget() — the burst's gaze
        #: snapshot that deixis commands ("close this") resolve against.
        self.last_decision: RouteDecision | None = None

    def _sample(self) -> tuple[tuple[float, float] | None, float]:
        """One gaze sample as ``(point, confidence)``.

        Backends exposing ``estimate_sample`` (mediapipe) report a real per-frame
        confidence, so ``[gaze] confidence_min`` gates routing on frame quality.
        Backends with only ``estimate`` (l2cs) gate confidence internally and
        return None below threshold, so a returned sample counts as confident.
        """
        sampler = getattr(self._backend, "estimate_sample", None)
        if sampler is not None:
            sample = sampler()
            if sample is None:
                return None, 0.0
            return sample.point, sample.confidence
        gaze = self._backend.estimate()
        return (None, 0.0) if gaze is None else (gaze, 1.0)

    def retarget(self, activate: bool = True) -> RouteDecision:
        """Sample gaze, remember the decision, and (optionally) focus the target.

        No confident gaze (no face / low confidence) or a point outside every
        window falls back to the focused window and changes nothing.
        ``activate=False`` snapshots the decision without focusing — used when
        only deixis is enabled (``[gaze] route_dictation`` off), so "close this"
        still knows the looked-at window but dictation stays put.
        """
        focused = self._desktop.focused_window()
        gaze, confidence = self._sample()
        if gaze is None:
            decision = route_target(None, 0.0, focused, confidence_min=self._confidence_min)
            self.last_decision = decision
            return decision

        yaw, pitch = gaze
        windows = self._desktop.list_windows()
        resolved = resolve_window(self._calibration, yaw, pitch, windows)
        decision = route_target(
            resolved, confidence, focused, confidence_min=self._confidence_min
        )
        if (
            activate
            and decision.used_gaze
            and decision.target is not None
            and decision.target != focused
        ):
            try:
                self._desktop.activate(decision.target)
                log.info("Gaze routed dictation to window %s", decision.target)
            except Exception as exc:  # focus is best-effort; never break dictation
                log.warning("Gaze re-focus failed (%s); using focused window.", exc)
                decision = route_target(None, 0.0, focused, confidence_min=self._confidence_min)
        self.last_decision = decision
        return decision

    def window_action(self, action: str, window_id) -> bool:
        """Perform a deixis window action ("focus"/"close"/"minimize") on the desktop.

        Returns False when the desktop backend lacks the operation, so callers
        can report honestly instead of silently doing nothing.
        """
        method = {"focus": "activate", "close": "close", "minimize": "minimize"}.get(action)
        if method is None:
            return False
        op = getattr(self._desktop, method, None)
        if op is None:
            return False
        op(window_id)
        return True

    def close(self) -> None:
        """Release the camera held by the backend."""
        try:
            self._backend.close()
        except Exception:
            pass
