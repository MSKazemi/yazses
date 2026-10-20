"""Shared-camera samples to chord tokens (pure) -- EYE-GESTURE-001.

The sensor half of ADR-v2-043. One :class:`~yazses.perception.signals.PerceptionSample` per
tick goes in; ``press`` / ``release`` / ``pulse`` calls on a
:class:`~yazses.gesture.engine.ChordEngine` come out. Two token families, both built from
detectors that already exist and are already tested:

* **Face tokens** (``jaw_open``, ``brow_raise`` ...): one
  :class:`~yazses.facegesture.detector.GestureSwitch` per token a bound chord uses, fed by
  ``gesture_reading`` -- so the thresholds, hysteresis, debounce, confidence floor and
  freshness rules are the face switch's own, not a second copy.
* **Head tokens** (``nod``, ``shake``, ``tilt``): :class:`~yazses.gesture.headmotion.HeadGestureDetector`.

Only the tokens some bound chord uses are watched. With an empty mapping no detector exists and
a tick does nothing at all.

**A sample is acted on once.** The runner polls faster than the camera delivers, so the same
observation arrives several times; a switch counts *frames*, and counting one frame twice would
halve the hold the user is asked for. The face channel is de-duplicated by its own timestamp.

**Loss of signal is quiet at once.** A channel that is missing, stale or has no reading
releases its held tokens in that tick and its detector forgets its history; when *no* channel
is usable the engine drops its engagement and the pointer freeze as well. Nothing is stitched
across the gap and nothing is replayed after it.

**The pointer onset.** A face gesture moves the head before a detector has seen enough frames
to call it a token, so a face token is also reported to the engine as *engaged* from the first
frame at or above the switch's release threshold -- the engine uses that for the pointer freeze
and for nothing else. The camera frame's own timestamp travels with it (``at_s``), so the freeze
can name the frame that began it and take back what the pointer did for that frame.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from yazses.facegesture.calibration import Reading
from yazses.facegesture.detector import GESTURES, GestureSwitch, gesture_reading, min_hold_s_for
from yazses.gesture.engine import ChordEngine
from yazses.gesture.headmotion import (
    HEAD_TOKENS,
    PRESS,
    PULSE,
    RELEASE,
    HeadGestureDetector,
    HeadMotionSettings,
)
from yazses.perception.signals import PerceptionSample

__all__ = ["FaceSwitchSettings", "SensorSettings", "SensorTokens"]


@dataclass(frozen=True)
class FaceSwitchSettings:
    """The face switch's own tuning, taken from ``[facegesture]`` by the caller."""

    hold_threshold: float = 0.5
    release_threshold: float = 0.35
    min_hold_frames: int = 3
    min_release_frames: int = 2
    confidence_floor: float = 0.0
    refractory_frames: int = 0


@dataclass(frozen=True)
class SensorSettings:
    freshness_s: float = 0.5
    face: FaceSwitchSettings = field(default_factory=FaceSwitchSettings)
    head: HeadMotionSettings = field(default_factory=HeadMotionSettings)


class SensorTokens:
    """Drives a :class:`ChordEngine` from perception samples. Never raises."""

    def __init__(self, engine: ChordEngine, settings: SensorSettings | None = None) -> None:
        self._engine = engine
        self._s = settings or SensorSettings()
        wanted = engine.vocabulary
        f = self._s.face
        self._faces: dict[str, GestureSwitch] = {
            name: GestureSwitch(
                f.hold_threshold, f.release_threshold, f.min_hold_frames, f.min_release_frames,
                confidence_floor=f.confidence_floor, refractory_frames=f.refractory_frames,
                min_hold_s=min_hold_s_for(name),  # eyes_closed: 0.8 s of time, any frame rate
            )
            for name in GESTURES
            if name in wanted
        }
        self._head: HeadGestureDetector | None = (
            HeadGestureDetector(self._s.head) if any(t in wanted for t in HEAD_TOKENS) else None
        )
        self._last_face_ts = -math.inf

    @property
    def watching(self) -> tuple[str, ...]:
        """The tokens being derived, for status and tests."""
        head = tuple(t for t in HEAD_TOKENS if t in self._engine.vocabulary) if self._head else ()
        return (*self._faces, *head)

    def update(self, sample: PerceptionSample | None, now_s: float) -> None:
        """Advance one runner tick."""
        if not (self._faces or self._head):
            return
        try:
            self._update(sample, now_s)
        except Exception:
            # Derived numbers are validated at the boundary, so this is a defect; a tick that
            # raised must not leave a token held.
            self.reset(now_s)
            raise

    def reset(self, now_s: float = 0.0) -> None:
        """Release everything and forget (shutdown, suppression). Idempotent."""
        for name, switch in self._faces.items():
            if switch.reset() == "end":
                self._engine.release(name, now_s)
        self._last_face_ts = -math.inf
        if self._head is not None:
            self._apply_head(self._head.reset(), now_s)
        self._engine.reset(now_s)

    # ------------------------------------------------------------------ internals

    def _update(self, sample: PerceptionSample | None, now_s: float) -> None:
        if not math.isfinite(now_s):
            self.reset(0.0)
            return
        face = sample.face if sample is not None else None
        head_pose = sample.head_pose if sample is not None else None
        fresh = self._s.freshness_s
        # "Is there a usable face / head this tick" asked of the same readers that will use it.
        face_live = any(
            gesture_reading(face, name, now_s=now_s, max_age_s=fresh).score is not None
            for name in self._faces
        )
        head_events = self._head.update(head_pose, now_s) if self._head is not None else []
        head_live = head_pose is not None and 0.0 <= now_s - head_pose.timestamp_s <= fresh
        has_signal = face_live or (head_live and self._head is not None)

        # Liveness first: the gate must have seen this tick's signal before an action asks it.
        self._engine.frame(has_signal, now_s)
        if not has_signal:
            for name, switch in self._faces.items():
                if switch.reset() == "end":
                    self._engine.release(name, now_s)
            self._last_face_ts = -math.inf
            self._apply_head(head_events, now_s)
            self._engine.reset(now_s)
            return

        self._apply_faces(face, now_s, face_live)
        self._apply_head(head_events, now_s)
        self._engine.tick(now_s)

    def _apply_faces(self, face: object, now_s: float, live: bool) -> None:
        fresh = self._s.freshness_s
        if live and getattr(face, "timestamp_s", None) == self._last_face_ts:
            return  # the same observation again
        if live:
            self._last_face_ts = face.timestamp_s  # type: ignore[attr-defined]
        frame_s: float | None = self._last_face_ts if live else None
        for name, switch in self._faces.items():
            reading: Reading = gesture_reading(face, name, now_s=now_s, max_age_s=fresh)  # type: ignore[arg-type]
            # now_s is the runner tick; each observation reaches here once (deduplicated by its
            # timestamp above), so a timed hold measures real elapsed time.
            event = switch.update(reading.score, reading.confidence, now_s=now_s)
            if event == "start":
                self._engine.press(name, now_s, frame_s)
            elif event == "end":
                self._engine.release(name, now_s)
            elif not switch.held:
                engaged = (
                    reading.score is not None
                    and switch.last_frame == "reading"
                    and reading.score >= switch.thresholds[1]
                )
                self._engine.onset(name, engaged, now_s, frame_s)

    def _apply_head(self, events: list[tuple[str, str]], now_s: float) -> None:
        for token, phase in events:
            if phase == PULSE:
                self._engine.pulse(token, now_s)
            elif phase == PRESS:
                self._engine.press(token, now_s)
            elif phase == RELEASE:
                self._engine.release(token, now_s)

