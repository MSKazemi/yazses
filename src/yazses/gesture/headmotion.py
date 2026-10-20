"""Discrete head gestures from a short window of head pose (pure) -- EYE-GESTURE-001.

``HeadPoseSignal`` is a continuous stream of angles. A chord needs *tokens*: a nod, a shake,
a tilt. This module is the one place that turns the first into the second, and it knows
nothing about chords, actions, cameras or threads -- numbers in, ``(token, phase)`` out, so the
whole policy is testable with a list of fabricated poses.

.. code-block:: text

    HeadPoseSignal --> HeadGestureDetector --> ("nod", "pulse") | ("tilt", "press"/"release")

Two kinds of token, because a head does two different things:

* **Pulses** (``nod``, ``shake``) are over almost as soon as they are recognised. One is
  recognised from a rolling window of poses as ``swings`` monotone legs of at least
  ``amplitude_rad`` each on one axis (pitch for a nod, yaw for a shake), with the *other*
  axis moving less than ``cross_ratio`` as far. The cross-axis rule is what separates a nod
  from "looked around", and the leg count is what separates a deliberate gesture from a
  glance at the keyboard (one down-and-back is two legs). After a pulse the window is
  emptied and a refractory period starts, so one motion is one pulse, never two.
* **Held** (``tilt``): ``|roll|`` beyond ``tilt_rad`` for ``tilt_hold_s`` is a press; back
  inside ``tilt_rad * RELEASE_FRACTION`` is the release. The gap between the two is the
  hysteresis. Direction is deliberately not distinguished: the sign convention of roll has
  not been verified on hardware, and guessing it would bind the wrong ear.

**Doubt is silence.** A missing sample, a stale one, a low-confidence one, a non-finite angle
and a timestamp that did not advance all produce *no token*, and the first four also empty the
window, so two halves of a nod seen either side of a dropout are never stitched together. A
held tilt is released the moment the signal goes, not when it returns -- the same rule
``facegesture/detector.py`` follows for the microphone.

No default here is measured. They are placeholders chosen to ask for something deliberate
(design/eye-control/GOVERNANCE.md; the false-activation study is P5.4), and ``[gesture]``
exposes every one.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

from yazses.perception.signals import HeadPoseSignal

__all__ = [
    "HEAD_TOKENS",
    "PRESS",
    "PULSE",
    "RELEASE",
    "HeadGestureDetector",
    "HeadMotionSettings",
    "count_swings",
]

NOD = "nod"
SHAKE = "shake"
TILT = "tilt"

#: Every token this module can emit, in a stable order.
HEAD_TOKENS: tuple[str, ...] = (NOD, SHAKE, TILT)

PULSE = "pulse"
PRESS = "press"
RELEASE = "release"

#: A tilt releases when |roll| falls below this fraction of the press threshold.
RELEASE_FRACTION = 0.7


@dataclass(frozen=True)
class HeadMotionSettings:
    """Tuning for :class:`HeadGestureDetector`. Radians and seconds; all unmeasured."""

    amplitude_rad: float = math.radians(10.0)
    swings: int = 4
    window_s: float = 1.5
    cross_ratio: float = 0.6
    tilt_rad: float = math.radians(20.0)
    tilt_hold_s: float = 0.4
    refractory_s: float = 1.0
    freshness_s: float = 0.5
    min_confidence: float = 0.5


def count_swings(values: list[float], threshold: float) -> int:
    """Monotone legs of at least ``threshold`` in ``values`` (a zig-zag count). Pure.

    ``[0, 0.2, 0]`` with ``threshold=0.15`` is two legs (out, back); a wobble smaller than
    the threshold adds none, however long it goes on. Non-finite values are skipped, and a
    non-positive threshold is no threshold at all, so it counts nothing rather than every
    jitter.
    """
    if not (threshold > 0.0 and math.isfinite(threshold)):
        return 0
    series = [v for v in values if math.isfinite(v)]
    if len(series) < 2:
        return 0
    swings = 0
    direction = 0  # 0 = not yet left the start, +1 rising, -1 falling
    start = extreme = series[0]
    for value in series[1:]:
        if direction == 0:
            if value - start >= threshold:
                direction, extreme, swings = 1, value, 1
            elif start - value >= threshold:
                direction, extreme, swings = -1, value, 1
        elif direction == 1:
            if value > extreme:
                extreme = value
            elif extreme - value >= threshold:
                direction, extreme, swings = -1, value, swings + 1
        else:
            if value < extreme:
                extreme = value
            elif value - extreme >= threshold:
                direction, extreme, swings = 1, value, swings + 1
    return swings


def _span(values: list[float]) -> float:
    return (max(values) - min(values)) if values else 0.0


class HeadGestureDetector:
    """Feed it one pose per tick; it returns the tokens that tick completed. Pure state.

    ``update(sample, now_s)`` is called every runner tick whether or not the camera produced
    anything new, because staleness is a fact about *now*. A sample is acted on once: the same
    timestamp seen again returns nothing.
    """

    def __init__(self, settings: HeadMotionSettings | None = None) -> None:
        s = settings or HeadMotionSettings()
        self._amp = s.amplitude_rad if math.isfinite(s.amplitude_rad) else 0.0
        self._swings = max(2, int(s.swings))
        self._window_s = max(0.1, s.window_s) if math.isfinite(s.window_s) else 1.5
        self._cross = min(1.0, max(0.0, s.cross_ratio)) if math.isfinite(s.cross_ratio) else 0.6
        self._tilt = s.tilt_rad if math.isfinite(s.tilt_rad) else math.inf
        self._tilt_hold = max(0.0, s.tilt_hold_s) if math.isfinite(s.tilt_hold_s) else 0.4
        self._refractory = max(0.0, s.refractory_s) if math.isfinite(s.refractory_s) else 1.0
        self._fresh = max(0.0, s.freshness_s) if math.isfinite(s.freshness_s) else 0.5
        self._min_conf = s.min_confidence if math.isfinite(s.min_confidence) else 1.0
        self._poses: deque[tuple[float, float, float]] = deque()  # (t, yaw, pitch)
        self._last_ts = -math.inf
        self._quiet_until = -math.inf
        self._tilt_since: float | None = None
        self._tilt_held = False

    @property
    def tilt_held(self) -> bool:
        """True while a ``tilt`` press is open."""
        return self._tilt_held

    def update(self, sample: HeadPoseSignal | None, now_s: float) -> list[tuple[str, str]]:
        """Advance one tick. Returns ``(token, phase)`` pairs, usually none. Never raises."""
        if not self._usable(sample, now_s):
            return self._lose()
        assert sample is not None
        if sample.timestamp_s <= self._last_ts:
            return []  # the same observation again: acted on once
        self._last_ts = sample.timestamp_s
        events: list[tuple[str, str]] = []
        events.extend(self._tilt_events(sample))
        if sample.timestamp_s < self._quiet_until:
            return events
        events.extend(self._pulse_events(sample))
        return events

    def reset(self) -> list[tuple[str, str]]:
        """Forget everything (shutdown, suppression); release a held tilt."""
        self._last_ts = -math.inf
        return self._lose()

    def discard_pending(self) -> None:
        """Forget a half-made gesture; leave a held tilt, its release and the clock alone.

        Called when the hands-free gate stops or re-arms the chord source (#417, ADR-v2-148),
        the head-side twin of ``GestureSwitch.discard_pending``: the legs of a nod or shake seen
        before that moment, and the time a tilt has been building towards ``tilt_hold_s``, cannot
        complete a token after it. A held tilt is *not* released here -- it has already been
        kept from acting, and staying held means a head still tilted across a Resume must come
        back and tilt again before it can press. The pulse refractory and the last timestamp
        are kept, so nothing already seen is counted twice. Pure state; emits nothing.
        """
        self._poses.clear()
        if not self._tilt_held:
            self._tilt_since = None

    # ------------------------------------------------------------------ internals

    def _usable(self, sample: HeadPoseSignal | None, now_s: float) -> bool:
        """Fresh, confident, finite, on a sane clock. Anything doubtful is *no signal*."""
        if sample is None or not math.isfinite(now_s):
            return False
        try:
            angles = (sample.yaw, sample.pitch, sample.roll, sample.timestamp_s, sample.confidence)
        except AttributeError:
            return False
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in angles):
            return False
        age = now_s - sample.timestamp_s
        if age < 0.0 or age > self._fresh:
            return False
        return sample.confidence >= self._min_conf

    def _lose(self) -> list[tuple[str, str]]:
        """No usable signal: drop the window, release a tilt, never stitch across the gap."""
        self._poses.clear()
        self._tilt_since = None
        if self._tilt_held:
            self._tilt_held = False
            return [(TILT, RELEASE)]
        return []

    def _tilt_events(self, sample: HeadPoseSignal) -> list[tuple[str, str]]:
        roll = abs(sample.roll)
        if self._tilt_held:
            if roll < self._tilt * RELEASE_FRACTION:
                self._tilt_held = False
                self._tilt_since = None
                return [(TILT, RELEASE)]
            return []
        if roll >= self._tilt:
            if self._tilt_since is None:
                self._tilt_since = sample.timestamp_s
            if sample.timestamp_s - self._tilt_since >= self._tilt_hold:
                self._tilt_held = True
                return [(TILT, PRESS)]
        else:
            self._tilt_since = None
        return []

    def _pulse_events(self, sample: HeadPoseSignal) -> list[tuple[str, str]]:
        t = sample.timestamp_s
        self._poses.append((t, sample.yaw, sample.pitch))
        while self._poses and t - self._poses[0][0] > self._window_s:
            self._poses.popleft()
        yaw = [p[1] for p in self._poses]
        pitch = [p[2] for p in self._poses]
        token = None
        if count_swings(pitch, self._amp) >= self._swings and _span(yaw) < self._cross * _span(pitch):
            token = NOD
        elif count_swings(yaw, self._amp) >= self._swings and _span(pitch) < self._cross * _span(yaw):
            token = SHAKE
        if token is None:
            return []
        self._poses.clear()
        self._quiet_until = t + self._refractory
        return [(token, PULSE)]
