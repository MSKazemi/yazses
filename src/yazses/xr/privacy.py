"""Privacy guards for XR tracking data (pure, stdlib only).

Eye, head and hand rays are biometric-adjacent: a gaze trace can reveal identity,
attention and health. The interaction-kernel research note (open question 7) asks which
observations are safe to retain "for a few seconds"; this module takes the short window
as its working answer. ADR-v2-150 allows anything longer-lived only under explicit
research consent; ADR-019 requires every outbound path to be declared. This module is
the XR side of all three:

* :class:`SampleRetention` — a short, bounded, log-safe window of recent samples.
* :func:`redact_for_log` — the only form of a sample that may reach a log line.
* :class:`PersistencePolicy` / :func:`may_persist` — raw samples are never written to
  disk unless the participant explicitly consented to research capture.
* :data:`EGRESS` — this package opens zero outbound paths (pinned by a test that scans
  the package source, in the spirit of ``tests/test_egress_inventory.py``).

Time is always passed in (``now_s``); there is no clock and no global state here.
"""
from __future__ import annotations

import math
from collections import deque
from enum import Enum
from typing import NoReturn

from yazses.xr.types import XrSample

#: Outbound paths opened by ``yazses.xr``. Empty on purpose: the adapter is designed
#: to receive already-sampled numbers over a paired link (ADR-v2-013; no transport for
#: them exists yet) and sends nothing anywhere. A non-empty value here would need an ADR-019 row first.
EGRESS: frozenset[str] = frozenset()

# Coarse confidence buckets for log lines. Deliberately few: a finer figure is itself
# a (weak) tracker-quality fingerprint.
_HIGH = 0.8
_MEDIUM = 0.5


def confidence_bucket(confidence: float) -> str:
    """``"high"`` (>= 0.8), ``"medium"`` (>= 0.5) or ``"low"`` — never the raw number."""
    if confidence >= _HIGH:
        return "high"
    if confidence >= _MEDIUM:
        return "medium"
    return "low"


def redact_for_log(sample: XrSample) -> str:
    """The only log-safe rendering of a sample: source and a coarse confidence bucket.

    No position, direction or timestamp is included — a timestamp plus a source is
    enough to correlate a log with a gaze trace held elsewhere.
    """
    if not isinstance(sample, XrSample):
        raise TypeError("redact_for_log expects an XrSample")
    return f"xr-sample source={sample.source.value} confidence={confidence_bucket(sample.confidence)}"


class SampleRetention:
    """A bounded, short-lived window of recent :class:`XrSample` (oldest → newest).

    Three independent limits keep tracking data from accumulating:

    * **Age** — a sample older than ``window_s`` seconds is dropped on every
      :meth:`add`, :meth:`prune` and :meth:`snapshot`. A sample exactly ``window_s``
      old is still kept; anything older is not.
    * **Count** — at most ``max_samples`` are held; the oldest is evicted first.
    * **Explicit** — :meth:`clear` drops every reference at once.

    A sample's own timestamp is not trusted. One stamped far in the future would
    otherwise make every later, legitimate sample look stale. So a sample more than
    ``max_future_s`` (default 5 s) ahead of the reference is refused with
    :class:`ValueError`. The reference is the caller's monotonic ``now_s`` when
    :meth:`add` is given one (preferred), else the newest sample held. The very first
    sample into an empty buffer, added without ``now_s``, has no reference and is
    accepted; :meth:`prune` with the real clock drops it (and anything else stamped
    more than ``max_future_s`` ahead of that clock), which is how a poisoned buffer
    recovers without :meth:`clear`. Without ``now_s``, a pause longer than
    ``max_future_s`` since the newest held sample makes the next :meth:`add` raise
    until :meth:`prune` ages it out; pass ``now_s`` to avoid that.
    ``max_future_s=math.inf`` switches the check off.

    ``repr``/``str`` show only the count and limits, so a stray ``logger.debug(buffer)``
    cannot leak where anyone was looking. Retained gaze data must also not be serialised
    or duplicated, so pickling, ``copy.copy`` and ``copy.deepcopy`` raise
    :class:`TypeError`.
    """

    __slots__ = ("_window_s", "_max_samples", "_max_future_s", "_samples")

    def __init__(
        self, window_s: float = 2.0, max_samples: int = 240, max_future_s: float = 5.0
    ) -> None:
        if (
            isinstance(window_s, bool)
            or not isinstance(window_s, (int, float))
            or not math.isfinite(window_s)
            or window_s <= 0
        ):
            raise ValueError(f"window_s must be a finite number > 0, got {window_s!r}")
        if isinstance(max_samples, bool) or not isinstance(max_samples, int) or max_samples < 1:
            raise ValueError(f"max_samples must be an integer >= 1, got {max_samples!r}")
        if (
            isinstance(max_future_s, bool)
            or not isinstance(max_future_s, (int, float))
            or math.isnan(max_future_s)
            or max_future_s <= 0
        ):
            raise ValueError(f"max_future_s must be a number > 0 (inf allowed), got {max_future_s!r}")
        self._window_s = float(window_s)
        self._max_samples = max_samples
        self._max_future_s = float(max_future_s)
        self._samples: deque[XrSample] = deque()

    @property
    def window_s(self) -> float:
        return self._window_s

    @property
    def max_samples(self) -> int:
        return self._max_samples

    @property
    def max_future_s(self) -> float:
        return self._max_future_s

    def __len__(self) -> int:
        return len(self._samples)

    def add(self, sample: XrSample, *, now_s: float | None = None) -> None:
        """Retain ``sample``, then drop whatever is now too old or over the cap.

        The sample's own timestamp is "now" for the age check, so a sample that is
        already stale relative to the newest one held is discarded, not stored. A
        late (out-of-order) sample is slotted into place so the window stays sorted.
        A sample stamped more than ``max_future_s`` ahead of ``now_s`` (or, without
        ``now_s``, ahead of the newest sample held) raises :class:`ValueError` and
        changes nothing. When ``now_s`` is given it also drives the age check.
        """
        if not isinstance(sample, XrSample):
            raise TypeError("SampleRetention.add expects an XrSample")
        if now_s is not None and (
            isinstance(now_s, bool) or not isinstance(now_s, (int, float)) or not math.isfinite(now_s)
        ):
            raise ValueError(f"now_s must be a finite number, got {now_s!r}")
        samples = self._samples
        ts = sample.timestamp_s
        newest = samples[-1].timestamp_s if samples else ts
        reference = now_s if now_s is not None else (newest if samples else None)
        if reference is not None and ts - reference > self._max_future_s:
            raise ValueError(
                f"sample is {ts - reference:.3f}s ahead of the reference clock "
                f"(max_future_s={self._max_future_s:g}); refused"
            )
        if newest - ts > self._window_s:
            return  # arrived already outside the window: never retained
        if not samples or ts >= newest:
            samples.append(sample)
        else:
            # Late arrival: insert after the last sample that is not newer than it.
            index = len(samples)
            while index > 0 and samples[index - 1].timestamp_s > ts:
                index -= 1
            samples.insert(index, sample)
        self.prune(max(ts, newest) if now_s is None else max(ts, newest, now_s))

    def prune(self, now_s: float) -> None:
        """Drop samples older than ``window_s`` at ``now_s``, then enforce the cap.

        Samples stamped more than ``max_future_s`` *after* ``now_s`` are dropped too:
        they cannot be genuine for that clock, and left in place they would outlive
        every later prune.
        """
        if isinstance(now_s, bool) or not isinstance(now_s, (int, float)) or not math.isfinite(now_s):
            raise ValueError(f"now_s must be a finite number, got {now_s!r}")
        samples = self._samples
        if samples and samples[-1].timestamp_s - now_s > self._max_future_s:
            horizon = now_s + self._max_future_s
            kept = [s for s in samples if s.timestamp_s <= horizon]
            samples.clear()
            samples.extend(kept)
        # Oldest first, so the loop stops at the first sample still inside the window.
        while samples and now_s - samples[0].timestamp_s > self._window_s:
            samples.popleft()
        while len(samples) > self._max_samples:
            samples.popleft()

    def snapshot(self, now_s: float) -> tuple[XrSample, ...]:
        """The retained samples, oldest → newest, after pruning to ``now_s``."""
        self.prune(now_s)
        return tuple(self._samples)

    def clear(self) -> None:
        """Drop every retained reference (the samples become collectable)."""
        self._samples.clear()

    def __repr__(self) -> str:
        return (
            f"SampleRetention(count={len(self._samples)}, "
            f"window_s={self._window_s}, max_samples={self._max_samples})"
        )

    __str__ = __repr__

    # Retained gaze data must not be serialised or duplicated: a pickle would hold the
    # coordinates, and a deep copy would keep samples alive after clear().
    def _refuse_copy(self, *_: object) -> NoReturn:
        raise TypeError(
            "SampleRetention holds gaze data and must not be pickled, copied or "
            "deep-copied; build a new buffer instead"
        )

    __reduce__ = _refuse_copy
    __reduce_ex__ = _refuse_copy
    __getstate__ = _refuse_copy
    __copy__ = _refuse_copy
    __deepcopy__ = _refuse_copy


class PersistencePolicy(Enum):
    """Whether raw XR samples may ever be written to disk. Closed."""

    NEVER = "never"
    RESEARCH_CONSENT_ONLY = "research_consent_only"


def may_persist(policy: PersistencePolicy, *, research_consent: bool) -> bool:
    """May raw XR samples be persisted? Only under explicit research consent.

    Fails closed: consent must be the literal ``True`` (a truthy string or ``1`` is not
    consent) and an unrecognised policy value never permits persistence.
    """
    if policy is PersistencePolicy.RESEARCH_CONSENT_ONLY:
        return research_consent is True
    return False
