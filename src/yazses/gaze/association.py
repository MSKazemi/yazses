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
    "DEFAULT_MAX_AGE_S",
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

#: Oldest gaze observation the capture keeps at all, in seconds. The count bound above
#: only ages samples out while new ones keep arriving; when the face leaves the frame the
#: last 64 would otherwise sit in RAM until the service stops. This bounds *retention*, not
#: pairing (the look-back window does that), so it is always widened to at least the
#: look-back. **Unmeasured starting value**: four default look-backs, nothing more.
DEFAULT_MAX_AGE_S = 2.0


class RejectReason(str, Enum):
    """Why a click produced no calibration pair. Each is a different thing to fix."""

    #: No gaze observation has been recorded at all — the camera has not produced a face.
    NO_GAZE = "no_gaze"
    #: Observations exist but none inside the look-back window — the face left the frame
    #: or the camera stalled. The classic stale-sample case.
    STALE = "stale"
    #: The nearest observation is below the confidence floor (the eyes disagreed).
    LOW_CONFIDENCE = "low_confidence"
    #: The click's timestamp is not on the perception clock at all (a wall-clock reading
    #: from an input stack, a boot-time clock that includes suspend). Decided by the
    #: capture, not by :func:`associate`, because only the capture knows "now". Without a
    #: name of its own this reads as ``STALE`` -- "the face left the frame" -- and sends
    #: the user to a camera that is fine.
    CLOCK_MISMATCH = "clock_mismatch"
    #: The gaze observation this click would use already backed an earlier click. One eye
    #: observation is one piece of evidence: a double-click or a burst must not count it
    #: twice, and the copy that lands in the held-out set would be graded against the
    #: copy it trained on. Decided by the capture, which remembers what it used.
    SAMPLE_REUSED = "sample_reused"
    #: The display layout or camera fingerprint (ADR-v2-149) changed since the recent gaze
    #: was recorded. The click is in the new layout's coordinates and the ring may hold
    #: eye positions aimed at the old one, and nothing says which sample is which -- so
    #: the ring is dropped and this click is refused. Decided by the capture, which is the
    #: only part that holds samples across the change.
    TOPOLOGY_CHANGED = "topology_changed"


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
    #: The chosen sample's own timestamp (the perception clock). A derived number, kept so
    #: the capture can tell that two clicks drew on the same observation; ``None`` only for
    #: a pair built by hand.
    gaze_timestamp_s: float | None = None


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

    Bounded in count always, and in age when *max_age_s* is given: :meth:`prune` drops
    every observation older than ``now - max_age_s``. ``None`` (the default for a ring
    built directly) keeps the count bound only, which is what this class always did.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY, max_age_s: float | None = None) -> None:
        if capacity < 1:
            raise ValueError("GazeHistory capacity must be >= 1")
        if max_age_s is not None and not (math.isfinite(float(max_age_s)) and max_age_s > 0):
            raise ValueError("GazeHistory max_age_s must be a finite number > 0, or None")
        self._items: deque[GazeSignal] = deque(maxlen=int(capacity))
        self._max_age_s = None if max_age_s is None else float(max_age_s)
        self._aged_out = False
        self._lock = threading.Lock()

    @property
    def max_age_s(self) -> float | None:
        return self._max_age_s

    @property
    def aged_out(self) -> bool:
        """Whether :meth:`prune` has dropped an observation since the last :meth:`clear`.

        An empty ring is two different situations: the camera has never produced a face
        (``NO_GAZE``), or it did and the samples grew too old (``STALE`` -- the face left
        the frame). Pruning must not turn the second into the first.
        """
        with self._lock:
            return self._aged_out

    def prune(self, now: float) -> int:
        """Drop observations older than ``now - max_age_s``; return how many went.

        A no-op without an age bound or for a non-finite *now*. The ring is in timestamp
        order (:meth:`record` refuses anything older than its newest), so the oldest are
        at the left and the loop stops at the first one young enough.
        """
        if self._max_age_s is None or not math.isfinite(now):
            return 0
        oldest_kept = now - self._max_age_s
        dropped = 0
        with self._lock:
            while self._items and self._items[0].timestamp_s < oldest_kept:
                self._items.popleft()
                dropped += 1
            if dropped:
                self._aged_out = True
        return dropped

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
            self._aged_out = False


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
            gaze_timestamp_s=best.timestamp_s,
        )
    )
