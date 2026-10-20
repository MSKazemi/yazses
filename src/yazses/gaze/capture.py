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

A ring of recent ``GazeSignal`` values (see ``GazeHistory``), bounded in count
(``DEFAULT_CAPACITY``) **and in age** (``DEFAULT_MAX_AGE_S``, widened to the look-back),
plus integer counters and one context fingerprint string. A click is reduced to its
coordinates and dropped. Nothing is written to disk by this module -- the spec's
persistence section stores the map and its context, never samples -- nothing is logged
per click, and no pair outlives the sink call. The sink — the estimator — keeps its own
bounded state in RAM and nothing else (#398).

## A changed layout empties the ring

A pair joins a click, in the canonical desktop coordinates of the layout that exists
*now*, with eye features recorded a moment ago. If the display layout or the camera
changed in between (ADR-v2-149), the ring may hold eye positions aimed at a desktop that
no longer exists, and no sample says which side of the change it was taken on. So when an
injected ``fingerprint`` reads differently from the one the ring was filled under, the
ring and the reuse memory are dropped and the click that noticed is refused as
``topology_changed``. Later clicks pair only with gaze recorded after that. An unreadable
layout (``None``) is not a change: a failed read is never evidence of one.

The fingerprint is read on a click, never per gaze poll -- the real reader runs ``xrandr``
-- and :class:`ThrottledFingerprint` bounds even that to one read per interval. A change is
therefore seen up to one interval late; ``ImplicitRefiner``'s own context check and its
unthrottled confirmation before a write (#398) are what keep such a pair out of the
stored map.

## Non-goal

This does **not** replace a stored calibration. Producing pairs is #397; deciding that a
refinement earned promotion is #398 (``gaze/refine.py``).
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from yazses.gaze.association import (
    DEFAULT_CAPACITY,
    DEFAULT_MAX_AGE_S,
    Association,
    AssociationPolicy,
    AssociationResult,
    GazeHistory,
    RejectReason,
    associate,
)
from yazses.gaze.clicks import ClickEvent, ClickObserver
from yazses.perception.signals import FacePerceptionSource, GazeSignal

__all__ = [
    "DEFAULT_FINGERPRINT_INTERVAL_S",
    "MAX_CLICK_CLOCK_SKEW_S",
    "CaptureStats",
    "ClickGazeCapture",
    "ImplicitCaptureService",
    "ThrottledFingerprint",
]

log = logging.getLogger(__name__)

#: How far a click's timestamp may sit from "now" on the perception clock before it is
#: called a clock mismatch rather than a click. The failures this exists for are not
#: subtle -- a wall-clock reading is ~1.7e9 s against a monotonic clock that counts from
#: boot, a boot-time clock is off by however long the laptop slept -- so the value only has
#: to sit above delivery jitter and below those. **Provisional; not measured on any
#: platform's input stack**, and the tests pin the mechanism, not this number.
MAX_CLICK_CLOCK_SKEW_S = 5.0

#: Minimum seconds between two real reads of the context fingerprint. Clicks are seconds
#: apart, so this rarely delays detection; it exists so a click burst cannot spawn one
#: ``xrandr`` per click on the input hook's thread. **Provisional; unmeasured.**
DEFAULT_FINGERPRINT_INTERVAL_S = 1.0


class ThrottledFingerprint:
    """A context-fingerprint reader that reads for real at most once per interval.

    Pure: *read* and *clock* are injected. *read* returns the current fingerprint, or
    ``None`` when the layout cannot be read. A read that fails or returns ``None`` keeps the
    last known value -- "could not tell" is not "changed" -- so a flaky display server
    cannot flush the ring on every click. *seed* is a fingerprint already known to hold
    right now (the context the calibration was just verified against), which saves the
    first read and makes it the baseline a change is measured from.
    """

    def __init__(
        self,
        read: Callable[[], str | None],
        *,
        min_interval_s: float = DEFAULT_FINGERPRINT_INTERVAL_S,
        clock: Callable[[], float] | None = None,
        seed: str | None = None,
    ) -> None:
        if not (math.isfinite(float(min_interval_s)) and min_interval_s >= 0):
            raise ValueError("ThrottledFingerprint.min_interval_s must be finite and >= 0")
        self._read = read
        self._min_interval_s = float(min_interval_s)
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._value: str | None = seed
        self._last_read: float | None = self._clock() if seed is not None else None
        #: How many real reads were made (a count, for tests and nothing else).
        self.reads = 0

    def __call__(self) -> str | None:
        with self._lock:
            now = self._clock()
            if self._last_read is not None and now - self._last_read < self._min_interval_s:
                return self._value
            self._last_read = now
            self.reads += 1
            try:
                value = self._read()
            except Exception as exc:
                log.debug(
                    "context fingerprint read raised %s; keeping the last", type(exc).__name__
                )
                return self._value
            if value is not None:
                self._value = str(value)
            return self._value


@dataclass(frozen=True)
class CaptureStats:
    """Counts only — nothing in here can identify a click, a place or a person."""

    clicks: int = 0
    accepted: int = 0
    no_gaze: int = 0
    stale: int = 0
    low_confidence: int = 0
    clock_mismatch: int = 0
    sample_reused: int = 0
    topology_changed: int = 0

    @property
    def rejected(self) -> int:
        return (
            self.no_gaze + self.stale + self.low_confidence
            + self.clock_mismatch + self.sample_reused + self.topology_changed
        )


class ClickGazeCapture:
    """Click events in, accepted ``(gaze, click)`` pairs out. Pure; thread-safe."""

    def __init__(
        self,
        sink: Callable[[Association], object],
        policy: AssociationPolicy | None = None,
        history: GazeHistory | None = None,
        clock: Callable[[], float] | None = None,
        fingerprint: Callable[[], str | None] | None = None,
    ) -> None:
        """*clock* is the clock gaze samples are stamped with (``time.monotonic`` for the
        shared source). Given, a click stamped far from it is refused by name and the ring
        is aged against it even while no face arrives; omitted, that check is off,
        association trusts the timestamps it is handed, and the ring ages only as new
        samples arrive.

        *fingerprint* returns the ADR-v2-149 context fingerprint of the current display
        layout and camera (``None`` = cannot tell). Given, a change between clicks drops
        the ring; omitted, the capture does not watch the layout (the refiner still does).

        The default ring is bounded in age to ``max(DEFAULT_MAX_AGE_S, lookback)``. An
        injected ring may have no age bound, but not one shorter than the look-back: that
        would discard samples the policy says a click may use.
        """
        self._sink = sink
        self._policy = policy or AssociationPolicy()
        if history is None:
            history = GazeHistory(max_age_s=max(DEFAULT_MAX_AGE_S, self._policy.lookback_s))
        elif history.max_age_s is not None and history.max_age_s < self._policy.lookback_s:
            raise ValueError(
                "the gaze ring's max_age_s is shorter than the association look-back; it "
                "would drop samples a click is allowed to use"
            )
        self._history = history
        self._clock = clock
        self._fingerprint = fingerprint
        self._seen_fingerprint: str | None = None
        self._lock = threading.Lock()
        self._counts = {
            "clicks": 0, "accepted": 0, "no_gaze": 0, "stale": 0, "low_confidence": 0,
            "clock_mismatch": 0, "sample_reused": 0, "topology_changed": 0,
        }
        # Bounded to the gaze ring: an observation older than the ring cannot be chosen
        # again anyway, so remembering more would only be a slow leak.
        self._used: deque[float] = deque(maxlen=DEFAULT_CAPACITY)
        self._warned_clock = False

    @property
    def history(self) -> GazeHistory:
        return self._history

    def record_gaze(self, gaze: GazeSignal | None) -> bool:
        """Offer one gaze observation (``None`` = no face this poll). ``True`` if kept.

        Also ages the ring: against the clock when there is one, otherwise against the
        observation just offered.
        """
        kept = self._history.record(gaze)
        if self._clock is not None:
            self._history.prune(self._clock())
        elif gaze is not None:
            self._history.prune(gaze.timestamp_s)
        return kept

    def observe_topology(self) -> bool:
        """Read the fingerprint; on a change drop the ring and return ``True``.

        The first readable value is adopted as the baseline, not reported as a change.
        Without a fingerprint, or when it reads ``None`` or raises, nothing changes.
        """
        if self._fingerprint is None:
            return False
        try:
            current = self._fingerprint()
        except Exception as exc:  # runs on the input hook's thread
            log.debug("context fingerprint raised %s; treated as unknown", type(exc).__name__)
            return False
        if current is None:
            return False
        with self._lock:
            previous = self._seen_fingerprint
            self._seen_fingerprint = current
            if previous is None or previous == current:
                return False
            self._used.clear()
        self._history.clear()
        log.info(
            "Implicit gaze calibration: the display layout or camera changed; recent gaze "
            "dropped, clicks pair only with gaze seen after the change."
        )
        return True

    def handle_click(self, click: ClickEvent) -> AssociationResult:
        """Associate *click* with recent gaze; give an accepted pair to the sink.

        Never raises: this runs on the observer's thread, and an exception escaping into
        an OS input hook is the kind of failure that takes the hook down. A sink that
        raises is contained and logged by exception *type* only.
        """
        result = self._decide(click)
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

    def _decide(self, click: ClickEvent) -> AssociationResult:
        """Accept or name the rejection. Order: layout, clock, association, then reuse."""
        if self.observe_topology():
            return AssociationResult(reason=RejectReason.TOPOLOGY_CHANGED)
        if self._clock is not None and self._skewed(click):
            return AssociationResult(reason=RejectReason.CLOCK_MISMATCH)
        if self._clock is not None:
            self._history.prune(self._clock())
        result = associate(click, self._history.snapshot(), self._policy)
        if result.reason is RejectReason.NO_GAZE and self._history.aged_out:
            # The ring is empty because its samples grew old, not because no face was ever
            # seen: that is the face-left-the-frame case, and it keeps its own name.
            return AssociationResult(reason=RejectReason.STALE)
        pair = result.association
        if pair is None or pair.gaze_timestamp_s is None:
            return result
        # Check-and-claim in one step, so two clicks racing on two threads cannot both win
        # the same observation. A pair that is not accepted never reaches this line, so a
        # rejected click does not use the sample up.
        with self._lock:
            if pair.gaze_timestamp_s in self._used:
                return AssociationResult(reason=RejectReason.SAMPLE_REUSED)
            self._used.append(pair.gaze_timestamp_s)
        return result

    def _skewed(self, click: ClickEvent) -> bool:
        if self._clock is None or abs(self._clock() - click.timestamp_s) <= MAX_CLICK_CLOCK_SKEW_S:
            return False
        if not self._warned_clock:
            self._warned_clock = True
            # Said once and in words: every click would otherwise be counted as "stale",
            # which blames a camera that is fine. No timestamp or coordinate is logged.
            log.warning(
                "Implicit gaze calibration: click timestamps are not on the camera's "
                "monotonic clock (off by more than %.0f s), so no click can be paired with "
                "gaze. The click observer must stamp with time.monotonic().",
                MAX_CLICK_CLOCK_SKEW_S,
            )
        return True

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
        failure_reason: Callable[[], str] | None = None,
    ) -> None:
        """*failure_reason* returns why the shared source stopped, or ``""``. It is read
        only to explain, once, why clicks are arriving and gaze is not: a camera that dies
        after it opened leaves this service ``running`` and every click ``no_gaze``."""
        self._capture = capture
        self._observer = observer
        self._lease = lease
        self._interval_s = max(0.001, float(interval_s))
        self._failure_reason = failure_reason
        self._explained = False
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
            # The layout at start is the baseline a later change is measured from.
            self._capture.observe_topology()
            self._explained = False
            self._running = True

    def _on_click(self, click: ClickEvent) -> None:
        """The observer's callback: the pairing result is counted inside the capture.

        Reads the source first. The ring is fed by a poller on its own cadence, so at the
        instant of a click it can be up to one poll interval behind a source that already
        holds the sample the click should use -- and at a low frame rate that interval is
        longer than the look-back window, which would call every click stale.
        """
        try:
            self.poll()
        except Exception as exc:  # an exception must not reach the OS input hook
            log.debug("implicit calibration poll raised %s on a click", type(exc).__name__)
        self._capture.handle_click(click)

    def poll(self) -> bool:
        """Copy the shared source's newest gaze observation into the ring; ``True`` if new.

        Returns ``False`` when the lease is down, there is no face, or the observation is
        one already recorded.
        """
        sample = self._lease.latest()
        if sample is None:
            self._explain_if_failed()
        return self._capture.record_gaze(None if sample is None else sample.gaze)

    def _explain_if_failed(self) -> None:
        """Say once, with the real reason, why this service will never see gaze."""
        if self._explained or self._failure_reason is None:
            return
        try:
            reason = self._failure_reason()
        except Exception:
            return
        if not reason:
            return
        self._explained = True
        log.warning(
            "Implicit gaze calibration is on but the shared camera is not running: %s. "
            "Clicks cannot be paired with gaze until it is.",
            reason,
        )

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
