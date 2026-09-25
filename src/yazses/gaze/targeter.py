"""Runtime look-to-pane targeting — sample gaze, pick a window, focus it.

Wires the three parts the daemon calls at hold-start: the gaze backend (one
``(yaw, pitch)`` sample), the persisted calibration map, and the desktop backend
(window list + focus). It applies the pure :mod:`~yazses.gaze.route` policy —
route to the looked-at window only when gaze is confident and lands on a window,
else leave the focused window untouched so uncertain gaze never misroutes.

Frames live only inside ``backend.estimate()`` (in-RAM, never stored — ADR-011).

An optional semantic-grounding seam (ADR-v2-151 phase P2) sits beside that policy: when
a grounder is injected, a *confident, gaze-routed* burst also asks it what the user was
looking at inside the window. It is additive in the strict sense — the route decision is
computed first and is never revisited, so with no grounder (every install today) this
file behaves exactly as it did before, and with one the worst case is an abstention.
"""
from __future__ import annotations

import logging

from yazses.gaze.grounded import RefinedTarget, refine
from yazses.gaze.route import RouteDecision, route_target
from yazses.gaze.zones import resolve_window
from yazses.grounding import GroundingResult

log = logging.getLogger(__name__)


class GazeTargeter:
    """Focus the window the user is looking at, for the next dictation."""

    def __init__(
        self,
        backend,
        calibration,
        desktop,
        confidence_min: float = 0.5,
        topology_guard=None,
        grounder=None,
    ) -> None:
        self._backend = backend
        self._calibration = calibration
        self._desktop = desktop
        self._confidence_min = confidence_min
        #: Optional :class:`~yazses.gaze.topology.SessionTopologyGuard`. When the
        #: desktop is rearranged mid-session the calibration file does not change,
        #: so the startup check cannot see it; ADR-v2-149 requires routing to stop
        #: rather than reuse coefficients (and window rectangles) from the old
        #: layout. None keeps the pre-ADR behaviour for callers that do not wire it.
        self._topology_guard = topology_guard
        self._suspension_logged = False
        #: Optional :class:`~yazses.gaze.grounded.GazeGrounder`. None on every install
        #: today — ADR-v2-151 ships no platform semantic source until its coverage
        #: study lands — and None is what keeps the window-level path untouched, so
        #: the absent case is the default rather than a configuration.
        self._grounder = grounder
        #: The decision from the most recent retarget() — the burst's gaze
        #: snapshot that deixis commands ("close this") resolve against.
        self.last_decision: RouteDecision | None = None
        #: The grounding answer for that same burst, or None when grounding did not
        #: run (no grounder, no confident gaze route) or could not answer. Cleared at
        #: the top of every retarget() so a previous burst's entity can never be read
        #: as this one's — a stale exact target is worse than no exact target.
        self.last_grounding: GroundingResult | None = None

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

        A suspended topology guard short-circuits all of that: no camera sample is
        taken and the focused window is kept, because a calibration made on the
        previous monitor arrangement would answer confidently and wrongly.

        When a semantic grounder is injected *and* the decision came from confident
        gaze, the same sample is then grounded (ADR-v2-151). That runs strictly after
        the routing decision is final and cannot change it: an exact element is an
        addition to the answer, never a correction of it.
        """
        focused = self._desktop.focused_window()
        self.last_grounding = None
        if self._topology_guard is not None and self._topology_guard.suspended():
            if not self._suspension_logged:
                # Once per suspension, not once per hold: the state is sticky until a
                # recalibration clears it, and a line per dictation would bury it.
                self._suspension_logged = True
                check = getattr(self._topology_guard, "last_check", None)
                log.warning(
                    "Gaze routing suspended — %s. Run `yazses gaze calibrate`.",
                    check.reason if check is not None else "the display layout changed",
                )
            decision = route_target(None, 0.0, focused, confidence_min=self._confidence_min)
            self.last_decision = decision
            return decision
        self._suspension_logged = False
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
        if self._grounder is not None and decision.used_gaze and decision.target is not None:
            self.last_grounding = self._ground(decision.target, yaw, pitch, confidence)
        self.last_decision = decision
        return decision

    def _ground(self, window_id, yaw: float, pitch: float, confidence: float):
        """Ask the injected grounder about this sample; never raise. Best-effort.

        Only reached for a confident, gaze-routed decision, which is the precondition
        the whole seam rests on: a low-confidence sample and a gaze point that landed
        outside every window both fall back to the focused window, and refining *into*
        a window the user was not looking at would be the wrong-target error ADR-v2-151
        is written to avoid. So the low-confidence path does not merely ignore the
        answer — it never asks, and no semantic source is touched.

        The screen point is predicted again rather than threaded out of the routing
        path above: ``predict`` is pure, so the second call returns the same pair, and
        the existing code stays character-for-character what it was.

        :class:`~yazses.gaze.grounded.GazeGrounder` already isolates a failing semantic
        source. This second catch is for the grounder *object* — a future caller can
        pass anything, and a duck-typed seam that can raise into ``retarget`` would put
        a crash between the hold and the dictation.
        """
        try:
            x, y = self._calibration.predict(yaw, pitch)
            return self._grounder.ground(
                window_id=window_id, point=(float(x), float(y)), confidence=confidence
            )
        except Exception:
            log.debug("Gaze grounding seam failed; window-level target kept.", exc_info=True)
            return None

    def refined_target(self) -> RefinedTarget:
        """The burst's target as a consumer should read it: window, plus entity if earned.

        One call so that no consumer has to reimplement the rule. The window is always
        the routing decision's, unchanged; ``is_exact`` is True only for a grounded
        result, so a deixis action, a confirm gate or a planner that asks this question
        gets today's window-level answer in every other case.
        """
        return refine(self.last_decision, self.last_grounding)

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
