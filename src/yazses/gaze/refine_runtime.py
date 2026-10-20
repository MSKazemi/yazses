"""Assemble implicit refinement for the daemon — or say precisely why it is not running (#398).

``gaze/clicks.py`` is the desktop boundary, ``gaze/capture.py`` pairs clicks with gaze,
``gaze/refine.py`` decides promotion and ``gaze/store.py`` persists it. Each is pure or
injected. This is the one place that wires them together, kept out of ``core/daemon.py``
so the daemon's addition is a single call, and so every precondition is a function of
plain arguments a test can vary.

The builder returns ``(runtime, reason)``. ``runtime`` is ``None`` whenever refinement
cannot honestly run, and ``reason`` says which precondition failed — the daemon logs it,
because "implicit calibration is enabled and silently does nothing" is exactly the
symptomless failure this project keeps paying for. The checks, in order:

1. ``[gaze_refine] enabled`` — off is the shipped default and is silent (no reason).
2. A gaze targeter exists — there is a live calibration to refine.
3. Gaze is on the **shared** camera source — refinement needs a continuous gaze stream to
   look back through, which only the shared source provides, and it must not open a second
   camera (ADR-v2-145). An always-on camera also needs the explicit enable it just had.
4. The platform has a click observer — none ships yet, and saying so beats a feature that
   never receives a click.
5. The stored calibration is **verified** against this desktop (ADR-v2-149): refinement may
   only refine a valid baseline in a valid context. "Unverified" is refused, not waved
   through — a map that cannot be checked is not a baseline to improve on.

Nothing is opened or started until every check passes.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from yazses.gaze.association import AssociationPolicy
from yazses.gaze.calibrate import CalibrationMap
from yazses.gaze.capture import ClickGazeCapture, ImplicitCaptureService
from yazses.gaze.clicks import ClickObserver, ClickObserverError
from yazses.gaze.refine import ImplicitRefiner, RefinementPolicy, RefinementResult
from yazses.gaze.store import RefinementInfo, promote_refinement
from yazses.perception.signals import FacePerceptionSource

__all__ = ["GuardedContext", "RefinementRuntime", "build_refinement_runtime", "policies_from_config"]

log = logging.getLogger(__name__)

_DEFAULT_FPS = 15
_MIN_FPS = 1
_MAX_FPS = 60

Spawn = Callable[[Callable[[], None]], object]


@dataclass
class RefinementRuntime:
    """The running pieces, so the daemon has one thing to ask and one thing to stop."""

    refiner: ImplicitRefiner
    service: ImplicitCaptureService
    capture: ClickGazeCapture
    stop_event: threading.Event
    worker: object | None = None

    def stop(self) -> None:
        """Stop polling, remove the click hook, give the camera back. Idempotent."""
        self.stop_event.set()
        try:
            self.service.stop()
        finally:
            join = getattr(self.worker, "join", None)
            if join is not None:
                join(timeout=2.0)


class GuardedContext:
    """Adapts a ``SessionTopologyGuard`` to what the refiner asks of a display context.

    Called, it is the cheap check (``True`` = the layout still applies) and inherits the
    guard's rate limit, which is right for the per-click intake. :meth:`confirm` is the
    unthrottled read the refiner makes immediately before it writes a calibration to disk:
    ``SessionTopologyGuard.suspended`` answers ``False`` for up to five seconds after the
    last poll no matter what happened to the monitors, so without this a layout change
    could be promoted into the stored calibration (#398). Only a *confirmed unchanged*
    layout passes: a layout that could not be read just now is not "fine".
    """

    def __init__(self, guard) -> None:
        self._guard = guard

    def __call__(self) -> bool:
        return not self._guard.suspended()

    def confirm(self) -> bool:
        from yazses.gaze.topology import Validity

        return bool(self._guard.verify_now().validity is Validity.VALID)


def policies_from_config(section) -> tuple[AssociationPolicy, RefinementPolicy]:
    """The two validated policies for a ``[gaze_refine]`` section.

    Milliseconds in the file, seconds in the code. Raises ``ValueError`` on a nonsense
    value; the builder turns that into a reason rather than a daemon that will not start.
    """
    association = AssociationPolicy(
        latency_s=int(section.click_latency_ms) / 1000.0,
        lookback_s=int(section.lookback_ms) / 1000.0,
        min_confidence=float(section.min_confidence),
    )
    refinement = RefinementPolicy(
        min_train_samples=int(section.min_train_samples),
        min_holdout_samples=int(section.min_holdout_samples),
        holdout_every=int(section.holdout_every),
        min_improvement_px=float(section.min_improvement_px),
        max_holdout_samples=int(section.max_holdout_samples),
        evaluate_every=int(section.evaluate_every),
        min_confidence=float(section.min_confidence),
    )
    return association, refinement


def build_refinement_runtime(
    section,
    *,
    targeter,
    perception,
    gaze_on_shared_source: bool,
    observer_factory: Callable[[], ClickObserver] | None,
    data_dir: Path,
    calibration_verified: bool,
    context_valid: Callable[[], bool] | None = None,
    source: str = "explicit",
    fps: int = _DEFAULT_FPS,
    spawn: Spawn | None = None,
    clock: Callable[[], float] | None = None,
) -> tuple[RefinementRuntime | None, str]:
    """Start implicit refinement, or return ``(None, why not)``. See the module docstring.

    *clock* is the clock the shared source stamps samples with (the daemon passes
    ``time.monotonic``, the source's default). Given, a click stamped on a different clock
    is refused by name instead of being counted as stale gaze.
    """
    if not getattr(section, "enabled", False):
        return None, ""
    if targeter is None:
        return None, "gaze routing is not running, so there is no calibration to refine"
    if perception is None or not gaze_on_shared_source:
        return None, (
            "it needs the shared camera: enable [perception] and keep gaze on the same "
            "camera index, so refinement can read a continuous gaze stream without opening "
            "a second camera"
        )
    if observer_factory is None:
        return None, "this platform has no click observer yet, so there is nothing to learn from"
    if not calibration_verified:
        return None, (
            "the stored calibration could not be verified against this desktop "
            "(ADR-v2-149); run `yazses gaze calibrate`, then refinement can start"
        )

    try:
        association, policy = policies_from_config(section)
    except (TypeError, ValueError) as exc:
        return None, f"[gaze_refine] has an unusable value ({exc})"

    def persist(candidate: CalibrationMap, result: RefinementResult) -> None:
        # Never turn a missing figure into 0.0 (METRICS.md): an "improvement" recorded
        # against an error of zero would read as the best map ever made.
        if result.baseline_error_px is None or result.candidate_error_px is None:
            raise ValueError("a promotion needs both held-out errors")
        promote_refinement(
            data_dir,
            candidate,
            RefinementInfo(
                train_samples=result.train_samples,
                holdout_samples=result.holdout_samples,
                baseline_error_px=float(result.baseline_error_px),
                candidate_error_px=float(result.candidate_error_px),
            ),
            # `refiner` is bound just below; at call time its baseline is still the map
            # the candidate was measured against (it only moves after this returns).
            expected_baseline=refiner.baseline,
        )

    refiner = ImplicitRefiner(
        targeter.calibration,
        policy,
        persist=persist,
        activate=targeter.set_calibration,
        context_valid=context_valid,
        source=source,
    )
    capture = ClickGazeCapture(refiner.observe, association, clock=clock)
    clamped = min(_MAX_FPS, max(_MIN_FPS, int(fps)))
    try:
        observer = observer_factory()
    except Exception as exc:
        return None, f"the click observer could not be built ({type(exc).__name__})"
    service = ImplicitCaptureService(
        capture=capture,
        observer=observer,
        lease=_named_lease(perception, "gaze-refine"),
        interval_s=1.0 / clamped,
        failure_reason=_failure_reason_of(perception),
    )
    try:
        service.start()
    except ClickObserverError as exc:
        return None, f"the click observer could not start ({exc})"
    except Exception as exc:
        return None, f"refinement could not start ({type(exc).__name__})"

    stop = threading.Event()
    runtime = RefinementRuntime(refiner, service, capture, stop)
    try:
        runtime.worker = (spawn or _spawn_thread)(lambda: service.run(stop))
    except Exception as exc:
        runtime.stop()
        return None, f"the refinement loop could not start ({type(exc).__name__})"
    return runtime, ""


def _failure_reason_of(perception) -> Callable[[], str] | None:
    """Why the shared source stopped, as a callable, or ``None`` if it cannot say."""
    status = getattr(perception, "status", None)
    if status is None:
        return None
    return lambda: str(status().failure_reason)


def _named_lease(perception, name: str) -> FacePerceptionSource:
    return perception.consumer(name)  # type: ignore[no-any-return]


def _spawn_thread(body: Callable[[], None]) -> threading.Thread:
    thread = threading.Thread(target=body, name="yazses-gaze-refine", daemon=True)
    thread.start()
    return thread
