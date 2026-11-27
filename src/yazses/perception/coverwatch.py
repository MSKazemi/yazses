"""Release a covered camera and take it back when the cover is gone (#923).

The lifecycle half of ``perception/cover.py``. Three inputs decide whether a camera is
covered: a hardware privacy signal where the platform has one
(``platform.base.CameraCoverSignal``), the frames the camera features are already reading,
and -- once the camera has been released -- a short, infrequent probe. The one output is
``CameraSwitch.cover`` / ``uncover``, so a covered camera is released by exactly the path
``yazses camera off`` uses, and the user's own switch always wins: while it is off nothing
here touches a camera, and any ``camera on`` / ``off`` / ``use`` forgets the verdict.

Frames arrive on capture threads (:meth:`CoverWatch.observe`), which only count them. The
switch is driven from this object's own thread (:meth:`CoverWatch.tick`), because
releasing a camera joins the very loop that delivered the frame.

Pure apart from that thread: the probe, the signal and the clock are injected.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from yazses.perception.cover import (
    PROBE_CLEAR,
    PROBE_UNKNOWN,
    CoverDetector,
    FrameStats,
    frame_stats,
    probe_delay,
)
from yazses.perception.switch import CameraSwitch

__all__ = ["SAMPLE_INTERVAL_S", "TICK_S", "CoverWatch"]

log = logging.getLogger(__name__)

#: Seconds between two frames that are actually measured; the rest are ignored.
SAMPLE_INTERVAL_S = 0.25
#: How often the hardware signal is read, verdicts applied and a due probe run.
TICK_S = 1.0
#: Longest ``camera off`` waits for a probe in progress to let the camera go.
_PROBE_YIELD_S = 5.0

#: ``(camera index, cancelled)`` -> one of the ``PROBE_*`` verdicts.
Probe = Callable[[int, Callable[[], bool]], str]
#: Camera index -> ``True`` covered, ``False`` the hardware says open, ``None`` no signal.
Signal = Callable[[int], "bool | None"]


class CoverWatch:
    """Watch the cameras a :class:`CameraSwitch` drives, and cover or uncover them."""

    def __init__(
        self,
        switch: CameraSwitch,
        *,
        probe: Probe,
        signal: Signal | None = None,
        clock: Callable[[], float] = time.monotonic,
        tick_s: float = TICK_S,
    ) -> None:
        self._switch = switch
        self._probe = probe
        self._signal = signal
        self._clock = clock
        self._tick_s = float(tick_s)
        self._lock = threading.Lock()
        self._probe_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._generation = switch.generation
        self._detectors: dict[int, CoverDetector] = {}
        self._measured_at: dict[int, float] = {}
        self._pending: dict[int, FrameStats] = {}
        #: Covered cameras whose hardware signal said so: its "open" uncovers them.
        self._by_signal: set[int] = set()
        self._next_probe: dict[int, float] = {}
        self._attempts: dict[int, int] = {}
        switch.add_guard(self._yield_probe)

    # -- capture threads ---------------------------------------------------- #

    def observe(self, index: int, frame: object) -> None:
        """Count one frame from camera *index*. Never raises, never keeps the frame."""
        try:
            if not self._switch.is_on or index in self._switch.covered:
                return
            now = self._clock()
            with self._lock:
                self._sync_locked()
                last = self._measured_at.get(index)
                if index in self._pending or (
                    last is not None and now - last < SAMPLE_INTERVAL_S
                ):
                    return
                stats = frame_stats(frame)
                if stats is None:
                    return
                self._measured_at[index] = now
                detector = self._detectors.setdefault(index, CoverDetector())
                if detector.observe(stats, now):
                    self._pending[index] = stats
        except Exception as exc:  # the type only: nothing about a frame reaches a log
            log.debug("camera cover: %s while measuring a frame", type(exc).__name__)

    # -- the watch ---------------------------------------------------------- #

    def tick(self) -> None:
        """One pass: hardware signals, then frame verdicts, then any probe that is due."""
        with self._lock:
            generation = self._sync_locked()
        if not self._switch.is_on:
            return
        covered = set(self._switch.covered)
        closed: set[int] = set()
        for index in sorted(covered | set(self._switch.held_indices())):
            reading = self._read_signal(index)
            if reading is True:
                if index in covered or self._cover(
                    index, generation, "its privacy shutter or switch reports closed"
                ):
                    closed.add(index)
                    self._by_signal.add(index)
            elif reading is False and index in self._by_signal:
                self._uncover(index, generation)
        with self._lock:
            pending, self._pending = self._pending, {}
        for index, stats in sorted(pending.items()):
            self._cover(
                index, generation,
                f"blank frames: mean {stats.mean:.0f}, spread {stats.spread:.1f}",
            )
        for index in self._switch.covered:
            if index not in closed:
                self._probe_if_due(index, generation)

    def start(self) -> None:
        """Run :meth:`tick` on a daemon thread until :meth:`stop`."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="yazses-camera-cover", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """End the watch and cancel a probe in progress. Idempotent."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(_PROBE_YIELD_S)

    # -- internals ---------------------------------------------------------- #

    def _run(self) -> None:
        while not self._stop.wait(self._tick_s):
            try:
                self.tick()
            except Exception:
                log.debug("camera cover: a check failed", exc_info=True)

    def _sync_locked(self) -> int:
        """Forget everything after a user transition (``camera on`` / ``off`` / ``use``)."""
        generation = self._switch.generation
        if generation != self._generation:
            self._generation = generation
            self._detectors.clear()
            self._measured_at.clear()
            self._pending.clear()
            self._by_signal.clear()
            self._next_probe.clear()
            self._attempts.clear()
        return generation

    def _forget(self, index: int) -> None:
        with self._lock:
            self._detectors.pop(index, None)
            self._measured_at.pop(index, None)
            self._pending.pop(index, None)
            self._by_signal.discard(index)
            self._next_probe.pop(index, None)
            self._attempts.pop(index, None)

    def _read_signal(self, index: int) -> bool | None:
        if self._signal is None:
            return None
        try:
            return self._signal(index)
        except Exception:
            log.debug("camera cover: the privacy signal could not be read", exc_info=True)
            return None

    def _cover(self, index: int, generation: int, why: str) -> bool:
        if not self._switch.cover(index, generation):
            return False
        self._forget(index)
        self._next_probe[index] = self._clock() + probe_delay(0)
        log.info(
            "Camera %d looks covered (%s). YazSes released it and resumes when it is "
            "uncovered; `yazses camera on` checks now.", index, why,
        )
        return True

    def _uncover(self, index: int, generation: int) -> None:
        # Forget first: a resumed camera delivers frames before `uncover` returns, and
        # they must start a new run rather than extend the old one.
        self._forget(index)
        if self._switch.uncover(index, generation):
            log.info("Camera %d is no longer covered; camera features resume.", index)

    def _probe_if_due(self, index: int, generation: int) -> None:
        due = self._next_probe.setdefault(index, self._clock() + probe_delay(0))
        if self._clock() < due:
            return

        def cancelled() -> bool:
            return self._stop.is_set() or self._switch.generation != generation

        with self._probe_lock:
            if cancelled():
                return
            try:
                verdict = self._probe(index, cancelled)
            except Exception:
                log.debug("camera cover: probing camera %d failed", index, exc_info=True)
                verdict = PROBE_UNKNOWN
        if cancelled():
            return
        if verdict == PROBE_CLEAR:
            self._uncover(index, generation)
            return
        attempts = self._attempts.get(index, 0) + 1
        self._attempts[index] = attempts
        self._next_probe[index] = self._clock() + probe_delay(attempts)

    def _yield_probe(self) -> None:
        """Wait for a probe to release the camera: ``camera off`` means free *now*."""
        if self._probe_lock.acquire(timeout=_PROBE_YIELD_S):
            self._probe_lock.release()
        else:
            log.warning("A camera check is still holding the camera; it is released as "
                        "soon as the device returns.")
