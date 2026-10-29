"""Measuring false activations, and backing off when they are too many.

A hands-free trigger lives or dies on one number: how often it fires when the user did
not mean it. `docs/research/muscle-brain-control.md` records that the best published
blink switch reaches 0.10 false positives/min (about 50 phantom activations per
workday), that a breath-hold switch reached 0.02, and that Meta's *Nature* paper reports
no false-activation rate at all. Nobody can tune what they cannot measure, so this module
measures it on the user's own machine, locally, and lets the pipeline act on it.

## What is measured, and what is NOT

The only thing a running system can observe is *what the user did next*. An activation
the user cancels or undoes within a short grace window is the observable proxy for a
false positive. **It is a proxy, not ground truth**: a user may cancel a correct
activation (changed their mind) or leave a wrong one uncorrected (did not notice). The
`cancelled_fraction` and every rate derived from it carry that caveat, and `summary`
can print it (`PROXY_NOTE`). Ground truth needs a labelled session, which is the
benchmark's job, not the daemon's.

## Rates are per *active* time

Wall time is the wrong denominator: a laptop left open overnight, a paused session or a
period where the signal-quality gate suppressed the detector would dilute the rate and
flatter the trigger. The ledger accrues time only between `start()/resume()` and
`pause()/stop()`; the pipeline calls `pause()` while the quality gate suppresses output.

## Uncertainty is part of the number

Three cancellations out of three activations is not "100%": it is 3 samples. The
cancelled *fraction* therefore comes with a Wilson score interval (it behaves at small n
and at the 0 and 1 edges, where the textbook normal interval collapses), and the
*governor* acts on a conservative lower confidence bound of the cancelled *rate*, not on
the point estimate. That is AGENTS.md rule 9 / ADR-021 applied: a guard is judged on how
rarely it fires, so it holds only on a specific, checkable signal and only once there is
enough evidence for the signal to mean something.

## The governor

`BudgetGovernor` watches the ledger against a `FalsePositiveBudget` and moves through
three states, with hysteresis and a way out at every step:

* OK, then **DESENSITIZE** when the cancelled rate is credibly over budget. The pipeline
  multiplies its detector thresholds by `GovernorAction.factor`. This is the gentle fix,
  and always tried first.
* then **SUSPEND** when, after desensitizing and fresh evidence, it is still credibly over
  twice the budget. The trigger turns itself off rather than keep interrupting.
* Suspension ends by itself after a timer (growing on repeated suspensions, capped), and
  by one action at any time: `release()`. The integrator binds that to a single word or
  gesture. A guard the user cannot dismiss in one move teaches them to disable the
  feature, so the release is not optional.

The governor is off by default (`FalsePositiveBudget.enabled = False`): it still
reports `OK` and the ledger still measures, so the numbers exist before anything is ever
allowed to change behaviour.

## Persistence

`ActivationLedger.to_dict()` emits aggregate counters only: session count, total active
seconds, activation and cancellation counts per event kind. No raw signal, no
per-event record, and no timestamp at all (so certainly none finer than the hour).
`from_dict` reads the same shape back leniently, so `yazses biosignal report` can show
the user their own long-run rate. The module itself does no I/O; the caller stores the
dict.

Everything here is pure stdlib: the clock is injected, so the whole thing runs on a fake
clock.
"""

from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from yazses.biosignal.types import BioEvent, EventKind

__all__ = [
    "ACTIVATING_KINDS",
    "PROXY_NOTE",
    "ActivationLedger",
    "BudgetGovernor",
    "FalsePositiveBudget",
    "GovernorAction",
    "GovernorKind",
    "LedgerStats",
    "poisson_rate_lower_bound",
    "summary",
    "wilson_interval",
]

Clock = Callable[[], float]

# SQUEEZE_OFF is the release of a squeeze, not a new activation; counting it would double
# every squeeze.
ACTIVATING_KINDS: frozenset[EventKind] = frozenset(EventKind) - {EventKind.SQUEEZE_OFF}

PROXY_NOTE = (
    "cancelled = the user undid or cancelled it within a few seconds; this is a proxy "
    "for false positives, not ground truth"
)

_SCHEMA = 1
_Z95 = 1.96


# ---------------------------------------------------------------------------
# Statistics (pure functions)
# ---------------------------------------------------------------------------


def wilson_interval(successes: int, n: int, z: float = _Z95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion, as (low, high) in [0, 1].

    With no trials nothing is known, so the interval is the whole range (0, 1).
    """
    if n <= 0:
        return (0.0, 1.0)
    k = min(max(successes, 0), n)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def poisson_rate_lower_bound(count: float, exposure_hours: float, z: float) -> float:
    """One-sided lower confidence bound for an event rate, in events per hour.

    Uses the cube-root (Wilson-Hilferty) approximation to the Poisson lower quantile.
    The choice of approximation and of ``z`` is a design choice, not a measured
    constant: it exists so the governor does not act on a handful of events. A count of
    zero, or no exposure, gives 0.
    """
    if count <= 0.0 or exposure_hours <= 0.0:
        return 0.0
    t = 1.0 - 1.0 / (9.0 * count) - z / (3.0 * math.sqrt(count))
    if t <= 0.0:
        return 0.0
    return count * t**3 / exposure_hours


# ---------------------------------------------------------------------------
# Snapshot of counters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerStats:
    """Aggregate counters and the rates derived from them. Immutable snapshot."""

    activations: int = 0
    cancelled: int = 0
    active_seconds: float = 0.0

    @property
    def kept(self) -> int:
        return self.activations - self.cancelled

    @property
    def active_minutes(self) -> float:
        return self.active_seconds / 60.0

    @property
    def active_hours(self) -> float:
        return self.active_seconds / 3600.0

    @property
    def per_minute(self) -> float:
        """Activations per minute of active time (0.0 with no active time)."""
        return self.activations / self.active_minutes if self.active_seconds > 0 else 0.0

    @property
    def per_hour(self) -> float:
        """Activations per hour of active time (0.0 with no active time)."""
        return self.activations / self.active_hours if self.active_seconds > 0 else 0.0

    @property
    def cancelled_per_hour(self) -> float:
        """Cancelled activations per hour of active time (a proxy rate; see module doc)."""
        return self.cancelled / self.active_hours if self.active_seconds > 0 else 0.0

    @property
    def cancelled_fraction(self) -> float | None:
        """Share of activations that were cancelled; None when there were none."""
        return self.cancelled / self.activations if self.activations else None

    def wilson_interval(self, z: float = _Z95) -> tuple[float, float]:
        """Wilson interval for the cancelled fraction (default 95%)."""
        return wilson_interval(self.cancelled, self.activations, z)


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


class _Decayed:
    """A count whose events fade exponentially in *active* time (half-life in seconds)."""

    __slots__ = ("count", "halflife_s", "stamp")

    def __init__(self, halflife_s: float) -> None:
        self.halflife_s = halflife_s
        self.count = 0.0
        self.stamp = 0.0

    def _factor(self, active_s: float) -> float:
        return 2.0 ** (-max(0.0, active_s - self.stamp) / self.halflife_s)

    def add(self, active_s: float) -> None:
        self.count = self.count * self._factor(active_s) + 1.0
        self.stamp = max(self.stamp, active_s)

    def value(self, active_s: float) -> float:
        return self.count * self._factor(active_s)


@dataclass
class _Record:
    kind: EventKind
    t: float
    cancelled: bool = False


class ActivationLedger:
    """Counts activations and cancellations against *active session time*.

    Parameters
    ----------
    clock:
        Monotonic seconds. Injected so tests and replays are deterministic. The ledger
        stamps activations with its own clock, never with ``BioEvent.t`` (which is on
        the data source's clock).
    grace_s:
        How long after an activation a cancellation still counts as "this activation
        was a mistake". Later undos are the user editing, not the trigger misfiring.
    ewma_halflife_s:
        Half-life, in seconds of active time, of the recent-rate estimate.
    max_records:
        Bound on remembered recent activations (only needed to resolve ids inside
        the grace window).

    Activations recorded while paused are still counted (they happened) but add no time,
    which raises the measured rate; the pipeline should not emit while suppressed.
    """

    def __init__(
        self,
        clock: Clock = time.monotonic,
        *,
        grace_s: float = 3.0,
        ewma_halflife_s: float = 600.0,
        max_records: int = 256,
    ) -> None:
        if grace_s < 0 or ewma_halflife_s <= 0 or max_records < 1:
            raise ValueError("grace_s >= 0, ewma_halflife_s > 0 and max_records >= 1 required")
        self._clock = clock
        self.grace_s = float(grace_s)
        self.ewma_halflife_s = float(ewma_halflife_s)
        self._max_records = max_records
        self._lock = threading.RLock()

        # Session counters (reset by stop()).
        self._active_total = 0.0
        self._active_since: float | None = None
        self._started = False
        self._by_kind: dict[EventKind, list[int]] = {}  # kind -> [activations, cancelled]
        self._ew_all = _Decayed(ewma_halflife_s)
        self._ew_cancelled = _Decayed(ewma_halflife_s)
        self._records: OrderedDict[int, _Record] = OrderedDict()
        self._next_id = 1

        # Aggregates carried over from earlier sessions (from_dict / stop()).
        self._carried_by_kind: dict[EventKind, list[int]] = {}
        self._carried_active_s = 0.0
        self._carried_sessions = 0

    # -- session time ----------------------------------------------------

    def _active_now(self) -> float:
        if self._active_since is None:
            return self._active_total
        return self._active_total + max(0.0, self._clock() - self._active_since)

    def start(self) -> None:
        """Begin (or continue) accruing active time. Idempotent."""
        with self._lock:
            if not self._started:
                self._started = True
                self._carried_sessions += 1
            if self._active_since is None:
                self._active_since = self._clock()

    resume = start

    def pause(self) -> None:
        """Stop accruing time (paused or quality-suppressed). Idempotent."""
        with self._lock:
            if self._active_since is not None:
                self._active_total += max(0.0, self._clock() - self._active_since)
                self._active_since = None

    def stop(self) -> None:
        """End the session: fold its counters into the carried totals and start fresh."""
        with self._lock:
            self.pause()
            for kind, (a, c) in self._by_kind.items():
                row = self._carried_by_kind.setdefault(kind, [0, 0])
                row[0] += a
                row[1] += c
            self._carried_active_s += self._active_total
            self._by_kind = {}
            self._active_total = 0.0
            self._started = False
            self._ew_all = _Decayed(self.ewma_halflife_s)
            self._ew_cancelled = _Decayed(self.ewma_halflife_s)
            self._records.clear()

    @property
    def is_active(self) -> bool:
        return self._active_since is not None

    # -- recording -------------------------------------------------------

    def record(self, event: BioEvent) -> int | None:
        """Count one activation and return its id, or None if the kind is not an activation.

        Starts the session if it was never started.
        """
        if event.kind not in ACTIVATING_KINDS:
            return None
        with self._lock:
            if not self._started:
                self.start()
            event_id = self._next_id
            self._next_id += 1
            self._by_kind.setdefault(event.kind, [0, 0])[0] += 1
            self._ew_all.add(self._active_now())
            self._records[event_id] = _Record(event.kind, self._clock())
            while len(self._records) > self._max_records:
                self._records.popitem(last=False)
            return event_id

    def mark_cancelled(self, event_id: int) -> bool:
        """The user cancelled or undid this activation.

        True if it was counted as a cancellation. False if the id is unknown or has
        aged out, the grace window has passed, or it was already cancelled.
        """
        with self._lock:
            rec = self._records.get(event_id)
            if rec is None or rec.cancelled:
                return False
            if self._clock() - rec.t > self.grace_s:
                return False
            rec.cancelled = True
            self._by_kind[rec.kind][1] += 1
            self._ew_cancelled.add(self._active_now())
            return True

    def mark_cancelled_latest(self, kind: EventKind | None = None) -> int | None:
        """Cancel the most recent still-uncancelled activation inside the grace window.

        For an "undo" the integrator cannot tie to an id. Returns the id cancelled, or
        None if there was nothing eligible.
        """
        with self._lock:
            now = self._clock()
            for event_id in reversed(self._records):
                rec = self._records[event_id]
                if now - rec.t > self.grace_s:
                    break  # records are time-ordered; everything older is too old
                if rec.cancelled or (kind is not None and rec.kind is not kind):
                    continue
                return event_id if self.mark_cancelled(event_id) else None
            return None

    # -- reading ---------------------------------------------------------

    def session_stats(self) -> LedgerStats:
        """Counters for the current session only (what the governor judges)."""
        with self._lock:
            acts = sum(a for a, _ in self._by_kind.values())
            canc = sum(c for _, c in self._by_kind.values())
            return LedgerStats(acts, canc, self._active_now())

    def total_stats(self) -> LedgerStats:
        """Carried totals plus the current session (what the user report shows)."""
        with self._lock:
            s = self.session_stats()
            acts = s.activations + sum(a for a, _ in self._carried_by_kind.values())
            canc = s.cancelled + sum(c for _, c in self._carried_by_kind.values())
            return LedgerStats(acts, canc, s.active_seconds + self._carried_active_s)

    def counts_by_kind(self) -> dict[EventKind, tuple[int, int]]:
        """``{kind: (activations, cancelled)}`` over carried totals plus this session."""
        with self._lock:
            out: dict[EventKind, tuple[int, int]] = {}
            for source in (self._carried_by_kind, self._by_kind):
                for kind, (a, c) in source.items():
                    pa, pc = out.get(kind, (0, 0))
                    out[kind] = (pa + a, pc + c)
            return out

    @property
    def sessions(self) -> int:
        return self._carried_sessions

    # Convenience delegates over the totals.

    @property
    def activations_per_minute(self) -> float:
        return self.total_stats().per_minute

    @property
    def activations_per_hour(self) -> float:
        return self.total_stats().per_hour

    @property
    def cancelled_fraction(self) -> float | None:
        """Cancelled share of activations: an observable PROXY for false positives."""
        return self.total_stats().cancelled_fraction

    def wilson_interval(self, z: float = _Z95) -> tuple[float, float]:
        return self.total_stats().wilson_interval(z)

    def recent_counts(self) -> tuple[float, float, float]:
        """``(decayed activations, decayed cancelled, effective window seconds)``.

        Session-only. Events fade with the half-life; the window is the matching
        exposure, ``(h / ln 2) * (1 - 2**(-A / h))`` for ``A`` active seconds so far,
        so count / window is an unbiased exponentially weighted rate.
        """
        with self._lock:
            a = self._active_now()
            h = self.ewma_halflife_s
            window = (h / math.log(2.0)) * (1.0 - 2.0 ** (-a / h))
            return (self._ew_all.value(a), self._ew_cancelled.value(a), window)

    def recent_rate_per_hour(self, *, cancelled_only: bool = False) -> float:
        """Exponentially weighted recent rate per active hour (activations or cancellations)."""
        acts, canc, window = self.recent_counts()
        if window <= 0.0:
            return 0.0
        return (canc if cancelled_only else acts) / window * 3600.0

    # -- persistence (aggregates only) -----------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Aggregate counters only: no raw signal, no per-event data, no timestamps."""
        with self._lock:
            by_kind = self.counts_by_kind()
            return {
                "schema": _SCHEMA,
                "sessions": self._carried_sessions,
                "active_seconds": int(round(self.total_stats().active_seconds)),
                "activations": {k.value: a for k, (a, _) in sorted(
                    by_kind.items(), key=lambda kv: kv[0].value)},
                "cancelled": {k.value: c for k, (_, c) in sorted(
                    by_kind.items(), key=lambda kv: kv[0].value)},
            }

    @classmethod
    def from_dict(
        cls,
        data: object,
        clock: Clock = time.monotonic,
        **kwargs: Any,
    ) -> ActivationLedger:
        """Rebuild a ledger whose *carried* totals are the stored aggregates.

        Lenient by design: a missing or corrupt file must never stop the pipeline, so
        anything unreadable is dropped and counted as zero. Cancelled counts are
        clamped to the activations they belong to.
        """
        ledger = cls(clock, **kwargs)
        if not isinstance(data, Mapping):
            return ledger
        acts = data.get("activations")
        canc = data.get("cancelled")
        acts = acts if isinstance(acts, Mapping) else {}
        canc = canc if isinstance(canc, Mapping) else {}
        for kind in ACTIVATING_KINDS:
            a = _count(acts.get(kind.value))
            if a:
                c = min(_count(canc.get(kind.value)), a)
                ledger._carried_by_kind[kind] = [a, c]
        ledger._carried_active_s = float(_count(data.get("active_seconds")))
        ledger._carried_sessions = _count(data.get("sessions"))
        return ledger


def _count(value: object) -> int:
    """A non-negative int from untrusted input, else 0."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if not math.isfinite(value) or value < 0:
        return 0
    return int(value)


# ---------------------------------------------------------------------------
# Budget and governor
# ---------------------------------------------------------------------------


class GovernorKind(Enum):
    OK = "ok"
    DESENSITIZE = "desensitize"
    SUSPEND = "suspend"


@dataclass(frozen=True)
class GovernorAction:
    """What the pipeline should do now.

    ``factor`` is a *threshold multiplier* (>= 1.0; 1.0 means unchanged). ``reason`` is
    plain language, set for DESENSITIZE and SUSPEND.
    """

    kind: GovernorKind
    factor: float = 1.0
    reason: str = ""

    @classmethod
    def ok(cls) -> GovernorAction:
        return cls(GovernorKind.OK)

    @classmethod
    def desensitize(cls, factor: float, reason: str = "") -> GovernorAction:
        return cls(GovernorKind.DESENSITIZE, factor, reason)

    @classmethod
    def suspend(cls, reason: str = "") -> GovernorAction:
        return cls(GovernorKind.SUSPEND, 1.0, reason)


@dataclass(frozen=True)
class FalsePositiveBudget:
    """How many cancelled activations per hour the user is asked to put up with.

    Every number is a design choice, not a measured constant; change them with data.

    max_cancelled_per_hour
        The budget. The default of 6 per hour is the best published blink switch
        (0.10 false positives/min) expressed per hour; a trigger worse than the best
        published artifact switch is not livable.
    min_session_minutes
        Minimum active time before the governor will act at all, and again after each
        change of state.
    min_cancelled
        Minimum cancellations since the last change of state. Below this there is no
        signal, only noise.
    desensitize_factor
        Threshold multiplier the pipeline applies while desensitized.
    suspend_multiple
        Suspend only if still credibly over ``max_cancelled_per_hour * suspend_multiple``.
    hysteresis
        Recover only when the recent rate is below ``max_cancelled_per_hour * hysteresis``
        (< 1), so it does not flap at the boundary.
    dwell_minutes
        Minimum active time spent desensitized before returning to normal.
    suspend_s, suspend_backoff, max_suspend_s
        Auto-recovery timer: a suspension lasts ``suspend_s`` seconds, longer by
        ``suspend_backoff`` for each repeat (until it recovers to OK), capped.
    confidence_z
        One-sided z for the lower bound the governor compares to the budget. 1.28 is
        about 90%: act when we are 90% sure the rate is over budget.
    enabled
        Off by default: the governor only reports OK until this is set.
    """

    max_cancelled_per_hour: float = 6.0
    min_session_minutes: float = 5.0
    min_cancelled: int = 3
    desensitize_factor: float = 1.5
    suspend_multiple: float = 2.0
    hysteresis: float = 0.5
    dwell_minutes: float = 20.0
    suspend_s: float = 300.0
    suspend_backoff: float = 2.0
    max_suspend_s: float = 3600.0
    confidence_z: float = 1.28
    enabled: bool = False

    def __post_init__(self) -> None:
        if self.max_cancelled_per_hour <= 0 or self.min_session_minutes < 0:
            raise ValueError("max_cancelled_per_hour must be > 0 and min_session_minutes >= 0")
        if self.min_cancelled < 1:
            raise ValueError("min_cancelled must be >= 1")
        if self.desensitize_factor < 1.0 or self.suspend_multiple < 1.0:
            raise ValueError("desensitize_factor and suspend_multiple must be >= 1")
        if not 0.0 < self.hysteresis < 1.0:
            raise ValueError("hysteresis must be in (0, 1)")
        if self.dwell_minutes < 0 or self.suspend_s <= 0 or self.max_suspend_s < self.suspend_s:
            raise ValueError("dwell_minutes >= 0 and 0 < suspend_s <= max_suspend_s required")
        if self.suspend_backoff < 1.0 or self.confidence_z < 0:
            raise ValueError("suspend_backoff must be >= 1 and confidence_z >= 0")


class BudgetGovernor:
    """Watches a ledger and tells the pipeline to desensitize, then suspend, then recover.

    Call `update()` after each recorded activation or cancellation (or on a timer;
    it is cheap). It returns the action the pipeline should apply *now*. One governor
    judges one ledger; to govern each trigger separately, give each its own ledger.

    ``release_word`` is only the text shown by `explain()`: binding a word or gesture
    to `release()` is the integrator's job.
    """

    def __init__(
        self,
        ledger: ActivationLedger,
        budget: FalsePositiveBudget | None = None,
        *,
        release_word: str = "resume",
    ) -> None:
        self.ledger = ledger
        self.budget = budget or FalsePositiveBudget()
        self.release_word = release_word
        self._clock = ledger._clock
        self._state = GovernorKind.OK
        self._epoch_cancelled = 0
        self._epoch_active_s = 0.0
        self._suspend_len_s = self.budget.suspend_s
        self._recover_at = 0.0
        self._last_reason = ""
        self._released_by_user = False
        self._rate = 0.0
        self._lower = 0.0

    # -- state -----------------------------------------------------------

    @property
    def state(self) -> GovernorKind:
        return self._state

    @property
    def action(self) -> GovernorAction:
        """The current action, without re-evaluating."""
        if self._state is GovernorKind.DESENSITIZE:
            return GovernorAction.desensitize(self.budget.desensitize_factor, self._last_reason)
        if self._state is GovernorKind.SUSPEND:
            return GovernorAction.suspend(self._last_reason)
        return GovernorAction.ok()

    def _new_epoch(self) -> None:
        s = self.ledger.session_stats()
        self._epoch_cancelled = s.cancelled
        self._epoch_active_s = s.active_seconds

    def release(self) -> GovernorAction:
        """The user says "carry on": back to normal sensitivity immediately.

        Starts a fresh evidence window, so it cannot re-fire until enough new
        cancellations have been seen.
        """
        self._state = GovernorKind.OK
        self._suspend_len_s = self.budget.suspend_s
        self._released_by_user = True
        self._last_reason = ""
        self._new_epoch()
        return self.action

    def update(self) -> GovernorAction:
        """Re-evaluate against the ledger and return the action to apply now."""
        b = self.budget
        if not b.enabled:
            return GovernorAction.ok()

        now = self._clock()
        s = self.ledger.session_stats()
        acts, canc, window_s = self.ledger.recent_counts()
        exposure_h = window_s / 3600.0
        self._rate = canc / exposure_h if exposure_h > 0 else 0.0
        self._lower = poisson_rate_lower_bound(canc, exposure_h, b.confidence_z)

        # Auto-recovery: a suspension ends by itself, into the gentle state (not OK),
        # with fresh evidence required before it can suspend again.
        if self._state is GovernorKind.SUSPEND:
            if now >= self._recover_at:
                self._state = GovernorKind.DESENSITIZE
                self._last_reason = "resumed on its own after a pause; staying less sensitive for now"
                self._new_epoch()
            return self.action

        epoch_cancelled = s.cancelled - self._epoch_cancelled
        epoch_minutes = (s.active_seconds - self._epoch_active_s) / 60.0
        enough = epoch_cancelled >= b.min_cancelled and epoch_minutes >= b.min_session_minutes

        if self._state is GovernorKind.OK:
            if enough and self._lower > b.max_cancelled_per_hour:
                self._state = GovernorKind.DESENSITIZE
                self._released_by_user = False
                self._last_reason = (
                    f"you cancelled {epoch_cancelled} activations in "
                    f"{epoch_minutes:.0f} min, over your limit of "
                    f"{b.max_cancelled_per_hour:g} an hour"
                )
                self._new_epoch()
            return self.action

        # DESENSITIZE
        if enough and self._lower > b.max_cancelled_per_hour * b.suspend_multiple:
            self._state = GovernorKind.SUSPEND
            self._last_reason = (
                f"still too many cancellations ({epoch_cancelled} in {epoch_minutes:.0f} min) "
                "even with a less sensitive setting"
            )
            self._recover_at = now + self._suspend_len_s
            self._suspend_len_s = min(self._suspend_len_s * b.suspend_backoff, b.max_suspend_s)
        elif (
            epoch_minutes >= b.dwell_minutes
            and self._rate < b.max_cancelled_per_hour * b.hysteresis
        ):
            self._state = GovernorKind.OK
            self._suspend_len_s = b.suspend_s
            self._last_reason = ""
            self._new_epoch()
        return self.action

    # -- plain language --------------------------------------------------

    def explain(self) -> str:
        """One or two plain sentences: what is happening, why, and how to undo it."""
        b = self.budget
        if not b.enabled:
            return "The false-activation guard is off; activations are only being measured."
        if self._state is GovernorKind.OK:
            return "Hands-free triggers are running normally."
        if self._state is GovernorKind.DESENSITIZE:
            return (
                f"Hands-free triggers are set {b.desensitize_factor:g}x less sensitive: "
                f"{self._last_reason}. Say or do \"{self.release_word}\" to put sensitivity "
                "back; otherwise it returns to normal by itself once things settle."
            )
        left = max(0.0, self._recover_at - self._clock())
        return (
            f"Hands-free triggers are paused: {self._last_reason}. They restart by "
            f"themselves in about {_fmt_duration(left)}, or right now if you say or do "
            f"\"{self.release_word}\"."
        )


# ---------------------------------------------------------------------------
# CLI-ready summary
# ---------------------------------------------------------------------------


def _fmt_rate(x: float) -> str:
    r = round(x, 1)
    return f"{r:.0f}" if r >= 10 or r == int(r) else f"{r:.1f}"


def _fmt_duration(seconds: float) -> str:
    if seconds < 90:
        return f"{max(1, round(seconds))} s"
    minutes = seconds / 60.0
    if minutes < 120:
        return f"{round(minutes)} min"
    return f"{minutes / 60.0:.1f} h"


def summary(source: ActivationLedger | LedgerStats, *, with_note: bool = False) -> str:
    """A one-line, human-readable report, e.g.
    ``3 activations/h, 1 cancelled (33%, 95% CI 6-79%) over 42 min``.

    Uses carried totals plus the current session. ``with_note`` appends `PROXY_NOTE`
    in parentheses, as the cancelled count is a proxy rather than ground truth.
    """
    stats = source.total_stats() if isinstance(source, ActivationLedger) else source
    note = f" ({PROXY_NOTE})" if with_note else ""
    if stats.active_seconds <= 0:
        if stats.activations:
            return f"{stats.activations} activations, no active session time recorded{note}"
        return "no active session time recorded yet"
    span = _fmt_duration(stats.active_seconds)
    if stats.activations == 0:
        return f"0 activations over {span}{note}"
    low, high = stats.wilson_interval()
    frac = stats.cancelled_fraction or 0.0
    return (
        f"{_fmt_rate(stats.per_hour)} activations/h, {stats.cancelled} cancelled "
        f"({frac * 100:.0f}%, 95% CI {low * 100:.0f}–{high * 100:.0f}%) over {span}{note}"
    )
