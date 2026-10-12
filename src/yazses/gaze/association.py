"""Pair a click with the gaze the user had when they aimed it (#397, pure).

A click says where the user *was* looking; the gaze sample that says where their eyes
*were pointing* has to be found in time. This module is that join and nothing else — no
camera, no desktop, no thread, no estimator. ``gaze/implicit.py`` already knows what to
do with a ``(gaze, click)`` pair; this decides whether there is a trustworthy pair at all.

The rules follow ``design/specs/eye-implicit-calibration.md`` "Sample association":

* look back in a **documented window** from the click, never forward — an eye position
  recorded after the button went down cannot be what aimed it;
* aim for the sample one **aim latency** before the click (the #101 sketch says ~100 ms:
  the eyes arrive on the target, then the hand lands the click), and take the nearest;
* **reject, never repair**: no observation, only stale ones, or a low-confidence nearest
  one all produce a named rejection. Picking a *different* sample because the nearest one
  was poor would pair the click with the eyes of another moment, which is the exact
  corruption this guard exists to stop;
* keep only derived numbers — a pair is four floats, a confidence and a lag.

## The numbers are placeholders, not findings

``DEFAULT_LATENCY_S``, ``DEFAULT_LOOKBACK_S`` and the confidence floor are conservative
starting values taken from the #101 sketch and the existing estimator default. **None of
them has been measured on real hardware**, and the spec says outright that the latency
"should be configurable/research-measurable rather than hard-coded forever" and that no
implicit calibration is recommended without longitudinal field evidence (#104). They are
parameters of :class:`AssociationPolicy` for that reason; the tests pin the *mechanism*
(boundaries, ordering, rejection) with synthetic streams and never assert that these
values are right for a person.
"""
from __future__ import annotations

import math
import threading
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from yazses.gaze.clicks import ClickEvent
from yazses.gaze.implicit import DEFAULT_MIN_CONFIDENCE
from yazses.perception.signals import GazeSignal

__all__ = [
    "DEFAULT_CAPACITY",
    "DEFAULT_LATENCY_S",
    "DEFAULT_LOOKBACK_S",
    "Association",
    "AssociationPolicy",
    "AssociationResult",
    "GazeHistory",
    "RejectReason",
    "associate",
]

#: Seconds between the eyes settling on a target and the click landing (#101 sketch).
#: **Unmeasured starting value.**
DEFAULT_LATENCY_S = 0.1

#: How far back from the click a gaze observation may be and still count. At the shared
#: source's 15 fps this admits ~7 samples. **Unmeasured starting value.**
DEFAULT_LOOKBACK_S = 0.5

#: Ring size. Bounded so that "keep the recent past" can never become "keep a session".
#: At the source's maximum 60 fps this still covers a full 0.5 s look-back with margin.
DEFAULT_CAPACITY = 64


class RejectReason(str, Enum):
    """Why a click produced no calibration pair. Each is a different thing to fix."""

    #: No gaze observation has been recorded at all — the camera has not produced a face.
    NO_GAZE = "no_gaze"
    #: Observations exist but none inside the look-back window — the face left the frame
    #: or the camera stalled. The classic stale-sample case.
    STALE = "stale"
    #: The nearest observation is below the confidence floor (the eyes disagreed).
    LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True)
class AssociationPolicy:
    """How a click is matched to gaze. Validated at construction, immutable after."""

    latency_s: float = DEFAULT_LATENCY_S
    lookback_s: float = DEFAULT_LOOKBACK_S
    min_confidence: float = DEFAULT_MIN_CONFIDENCE

    def __post_init__(self) -> None:
        for name in ("latency_s", "lookback_s", "min_confidence"):
            if not math.isfinite(float(getattr(self, name))):
                raise ValueError(f"AssociationPolicy.{name} must be finite")
        if self.latency_s < 0:
            raise ValueError("AssociationPolicy.latency_s must be >= 0")
        if self.lookback_s <= 0:
            raise ValueError("AssociationPolicy.lookback_s must be > 0")
        if self.latency_s > self.lookback_s:
            raise ValueError(
                "AssociationPolicy.latency_s must not exceed lookback_s: the sample the "
                "latency points at would lie outside the window it is chosen from"
            )
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("AssociationPolicy.min_confidence must be within 0..1")


@dataclass(frozen=True)
class Association:
    """One calibration observation: the gaze feature, the click, how sure, how far apart."""

    gaze: tuple[float, float]
    click: tuple[float, float]
    confidence: float
    #: Seconds from the chosen gaze sample to the click (>= 0).
    lag_s: float


@dataclass(frozen=True)
class AssociationResult:
    """Exactly one of ``association`` / ``reason`` is set."""

    association: Association | None = None
    reason: RejectReason | None = None

    @property
    def accepted(self) -> bool:
        return self.association is not None


class GazeHistory:
    """A bounded, thread-safe ring of the recent gaze observations (derived numbers only).

    Fed by whatever polls the shared source, read by the click handler on another thread.
    It stores :class:`~yazses.perception.signals.GazeSignal` values — a timestamp, two
    floats and a confidence — so there is no frame, landmark or image in it to leak, and a
    full ring is a few kilobytes of numbers.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("GazeHistory capacity must be >= 1")
        self._items: deque[GazeSignal] = deque(maxlen=int(capacity))
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def record(self, gaze: GazeSignal | None) -> bool:
        """Append *gaze* if it is a new observation; ``True`` when it was kept.

        ``None`` (no face this poll) is not recorded: absence is not a sample, and storing
        a placeholder would let a later click be paired with it. A timestamp not strictly
        newer than the last one is dropped — the poller reads the same latest observation
        several times between frames, and a duplicate must not outweigh a real sample.
        """
        if gaze is None:
            return False
        with self._lock:
            if self._items and gaze.timestamp_s <= self._items[-1].timestamp_s:
                return False
            self._items.append(gaze)
            return True

    def snapshot(self) -> tuple[GazeSignal, ...]:
        """The recorded observations, oldest first."""
        with self._lock:
            return tuple(self._items)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


def associate(
    click: ClickEvent,
    samples: Iterable[GazeSignal],
    policy: AssociationPolicy | None = None,
) -> AssociationResult:
    """Match *click* to one of *samples*, or say why it cannot be. Pure.

    Order of the checks is order of the failure's cause: nothing recorded at all
    (:attr:`RejectReason.NO_GAZE`), nothing recent enough (:attr:`RejectReason.STALE`),
    then the nearest-to-aim sample being too uncertain (:attr:`RejectReason.LOW_CONFIDENCE`).
    """
    chosen_policy = policy or AssociationPolicy()
    pool = tuple(samples)
    if not pool:
        return AssociationResult(reason=RejectReason.NO_GAZE)

    earliest = click.timestamp_s - chosen_policy.lookback_s
    aim = click.timestamp_s - chosen_policy.latency_s
    window = [s for s in pool if earliest <= s.timestamp_s <= click.timestamp_s]
    if not window:
        return AssociationResult(reason=RejectReason.STALE)

    # Nearest to the aim point; ties go to the earlier sample, so the answer does not
    # depend on the order the samples were handed in.
    best = min(window, key=lambda s: (abs(s.timestamp_s - aim), s.timestamp_s))
    if best.confidence < chosen_policy.min_confidence:
        return AssociationResult(reason=RejectReason.LOW_CONFIDENCE)
    return AssociationResult(
        association=Association(
            gaze=(best.raw_x, best.raw_y),
            click=(click.x, click.y),
            confidence=best.confidence,
            lag_s=click.timestamp_s - best.timestamp_s,
        )
    )
