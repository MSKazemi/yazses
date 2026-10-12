"""Runtime capture of click + gaze pairs for implicit calibration (#397).

``gaze/association.py`` decides whether a click and a gaze sample belong together;
``gaze/clicks.py`` is the desktop boundary; ``gaze/implicit.py`` is the estimator. This
module is the thin runtime between them, and it is where "opt-in" becomes a property of
the code: nothing here starts unless :meth:`ImplicitCaptureService.start` is called, and
the daemon calls that only when ``[gaze_refine] enabled`` is set.

Two parts, split the way the house pattern splits pure logic from the thing that listens:

* :class:`ClickGazeCapture` is pure. It owns the gaze ring, turns each click into an
  accept/reject through the association policy, hands accepted pairs to a sink and counts
  rejections by reason. It is driven by a fake click stream and a fake gaze stream in CI,
  with no desktop and no camera.
* :class:`ImplicitCaptureService` binds it to a :class:`~yazses.gaze.clicks.ClickObserver`
  and a lease on the shared perception source. It holds the camera lease only while
  started — that is the "always-on camera needs explicit enable" rule of ADR-v2-145
  invariant 9 — and it spawns no thread of its own: the daemon runs :meth:`run` on one.

## What is retained

A bounded ring of recent ``GazeSignal`` values (see ``GazeHistory``) and integer counters.
A click is reduced to its coordinates and dropped. Nothing is written to disk by this
module, nothing is logged per click, and no pair outlives the sink call. The sink — the
estimator — keeps its own bounded state in RAM and nothing else (#398).

## Non-goal

This does **not** replace a stored calibration. Producing pairs is #397; deciding that a
refinement earned promotion is #398 (``gaze/refine.py``).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from yazses.gaze.association import (
    Association,
    AssociationPolicy,
    AssociationResult,
    GazeHistory,
    associate,
)
from yazses.gaze.clicks import ClickEvent, ClickObserver
from yazses.perception.signals import FacePerceptionSource, GazeSignal

__all__ = ["CaptureStats", "ClickGazeCapture", "ImplicitCaptureService"]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaptureStats:
    """Counts only — nothing in here can identify a click, a place or a person."""

    clicks: int = 0
    accepted: int = 0
    no_gaze: int = 0
    stale: int = 0
    low_confidence: int = 0

    @property
    def rejected(self) -> int:
        return self.no_gaze + self.stale + self.low_confidence


class ClickGazeCapture:
    """Click events in, accepted ``(gaze, click)`` pairs out. Pure; thread-safe."""

    def __init__(
        self,
        sink: Callable[[Association], None],
        policy: AssociationPolicy | None = None,
        history: GazeHistory | None = None,
    ) -> None:
        self._sink = sink
        self._policy = policy or AssociationPolicy()
        self._history = history if history is not None else GazeHistory()
        self._lock = threading.Lock()
        self._counts = {"clicks": 0, "accepted": 0, "no_gaze": 0, "stale": 0, "low_confidence": 0}

    @property
    def history(self) -> GazeHistory:
        return self._history

    def record_gaze(self, gaze: GazeSignal | None) -> bool:
        """Offer one gaze observation (``None`` = no face this poll). ``True`` if kept."""
        return self._history.record(gaze)

    def handle_click(self, click: ClickEvent) -> AssociationResult:
        """Associate *click* with recent gaze; give an accepted pair to the sink.

        Never raises: this runs on the observer's thread, and an exception escaping into
        an OS input hook is the kind of failure that takes the hook down. A sink that
        raises is contained and logged by exception *type* only.
        """
        result = associate(click, self._history.snapshot(), self._policy)
        with self._lock:
            self._counts["clicks"] += 1
            if result.association is not None:
                self._counts["accepted"] += 1
            elif result.reason is not None:
                self._counts[result.reason.value] += 1
        if result.association is not None:
            try:
                self._sink(result.association)
            except Exception as exc:
                log.debug("implicit calibration sink raised %s; pair dropped", type(exc).__name__)
        return result

    def stats(self) -> CaptureStats:
        with self._lock:
            return CaptureStats(**self._counts)


class ImplicitCaptureService:
    """Binds capture to a click observer and a lease on the shared camera source.

    Dormant until :meth:`start`. ``start`` takes the camera lease first and the click hook
    second, and gives the lease back if the hook cannot be installed: a camera held for a
    feature that can never receive a click is the silent webcam-light failure ADR-v2-145
    exists to prevent.
    """

    def __init__(
        self,
        *,
        capture: ClickGazeCapture,
        observer: ClickObserver,
        lease: FacePerceptionSource,
        interval_s: float = 1.0 / 15.0,
    ) -> None:
        self._capture = capture
        self._observer = observer
        self._lease = lease
        self._interval_s = max(0.001, float(interval_s))
        self._running = False
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def interval_s(self) -> float:
        return self._interval_s

    def start(self) -> None:
        """Take the lease and install the click hook. Raises ``ClickObserverError``.

        On failure nothing stays held. Starting twice is a no-op.
        """
        with self._lock:
            if self._running:
                return
            self._lease.start()
            try:
                self._observer.start(self._on_click)
            except BaseException:
                self._lease.stop()
                raise
            self._running = True

    def _on_click(self, click: ClickEvent) -> None:
        """The observer's callback: the pairing result is counted inside the capture."""
        self._capture.handle_click(click)

    def poll(self) -> bool:
        """Copy the shared source's newest gaze observation into the ring; ``True`` if new.

        Returns ``False`` when the lease is down, there is no face, or the observation is
        one already recorded.
        """
        sample = self._lease.latest()
        return self._capture.record_gaze(None if sample is None else sample.gaze)

    def run(self, stop: threading.Event) -> None:
        """Poll until *stop* is set. The daemon runs this on a daemon thread."""
        while not stop.is_set():
            self.poll()
            stop.wait(self._interval_s)

    def stop(self) -> None:
        """Remove the click hook, give the lease back, forget the recent gaze. Idempotent."""
        with self._lock:
            if not self._running:
                return
            self._running = False
            try:
                self._observer.stop()
            finally:
                self._lease.stop()
                self._capture.history.clear()
