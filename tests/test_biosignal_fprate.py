"""Tests for ``yazses.biosignal.fprate``: the false-activation ledger and budget governor.

Everything runs on an injected fake clock, so the tests are deterministic and never sleep.
"""

from __future__ import annotations

import dataclasses
import json
import math

import pytest

from yazses.biosignal.fprate import (
    ACTIVATING_KINDS,
    PROXY_NOTE,
    ActivationLedger,
    BudgetGovernor,
    FalsePositiveBudget,
    GovernorAction,
    GovernorKind,
    LedgerStats,
    poisson_rate_lower_bound,
    summary,
    wilson_interval,
)
from yazses.biosignal.types import BioEvent, EventKind

HOUR = 3600.0
CLOCK_ORIGIN = 7_654_321.5


class FakeClock:
    """A manually advanced monotonic clock."""

    def __init__(self, start: float = CLOCK_ORIGIN) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def ev(kind: EventKind = EventKind.BLINK, t: float = 0.0) -> BioEvent:
    return BioEvent(kind=kind, t=t)


def make_ledger(**kwargs) -> tuple[FakeClock, ActivationLedger]:
    clock = FakeClock()
    return clock, ActivationLedger(clock, **kwargs)


# --------------------------------------------------------------------------- statistics


@pytest.mark.parametrize(
    "k, n, low, high",
    [
        (1, 3, 0.0615, 0.7923),    # the worked example in summary()'s docstring (6-79 %)
        (3, 3, 0.4385, 1.0),
        (50, 100, 0.4038, 0.5962),
        (0, 10, 0.0, 0.2775),
        (10, 10, 0.7225, 1.0),
    ],
)
def test_wilson_known_values(k, n, low, high) -> None:
    """Wilson 95 % interval matches hand-computed values."""
    got_low, got_high = wilson_interval(k, n)
    assert got_low == pytest.approx(low, abs=1e-3)
    assert got_high == pytest.approx(high, abs=1e-3)


def test_wilson_no_trials_is_the_whole_range() -> None:
    """With nothing observed, nothing is known."""
    assert wilson_interval(0, 0) == (0.0, 1.0)
    assert wilson_interval(5, -1) == (0.0, 1.0)


def test_wilson_bounds_contain_the_estimate_and_stay_in_unit_interval() -> None:
    """0 <= low <= k/n <= high <= 1 for every k, n; edges do not collapse to a point."""
    for n in range(1, 61):
        for k in range(n + 1):
            low, high = wilson_interval(k, n)
            assert 0.0 <= low <= high <= 1.0
            assert low <= k / n + 1e-12 and k / n <= high + 1e-12
            assert high > low  # unlike the textbook interval, never zero-width
    assert wilson_interval(0, 5)[0] == 0.0
    assert wilson_interval(5, 5)[1] == 1.0


def test_wilson_symmetry_monotonicity_and_shrinking() -> None:
    """Mirrored counts mirror the interval; more successes raise it; more data narrows it."""
    low, high = wilson_interval(2, 17)
    m_low, m_high = wilson_interval(15, 17)
    assert (m_low, m_high) == pytest.approx((1 - high, 1 - low))
    lows = [wilson_interval(k, 20)[0] for k in range(21)]
    highs = [wilson_interval(k, 20)[1] for k in range(21)]
    assert lows == sorted(lows) and highs == sorted(highs)
    widths = [wilson_interval(n // 2, n)[1] - wilson_interval(n // 2, n)[0] for n in (4, 16, 64)]
    assert widths == sorted(widths, reverse=True)
    wide = wilson_interval(5, 10, z=2.58)
    narrow = wilson_interval(5, 10, z=1.0)
    assert wide[0] < narrow[0] and wide[1] > narrow[1]


def test_wilson_clamps_out_of_range_successes() -> None:
    """Nonsense counts are clamped to [0, n] instead of producing NaN or out-of-range."""
    assert wilson_interval(-5, 10) == wilson_interval(0, 10)
    assert wilson_interval(15, 10) == wilson_interval(10, 10)


def test_poisson_lower_bound_basics() -> None:
    """Zero events or zero exposure -> 0; the bound never exceeds the plain rate."""
    assert poisson_rate_lower_bound(0, 1.0, 1.28) == 0.0
    assert poisson_rate_lower_bound(5, 0.0, 1.28) == 0.0
    assert poisson_rate_lower_bound(-1, 1.0, 1.28) == 0.0
    for count in (1, 3, 10, 100, 1000):
        bound = poisson_rate_lower_bound(count, 2.0, 1.28)
        assert 0.0 <= bound <= count / 2.0


def test_poisson_lower_bound_is_conservative_with_little_evidence() -> None:
    """Three events are worth far less than their face rate; many events approach it."""
    few = poisson_rate_lower_bound(3, 1.0, 1.28) / 3.0
    many = poisson_rate_lower_bound(300, 1.0, 1.28) / 300.0
    assert few < 0.5 < many < 1.0
    # Larger z (more confidence demanded) lowers the bound; z = 0 is the closest to the rate.
    assert (
        poisson_rate_lower_bound(10, 1.0, 2.5)
        < poisson_rate_lower_bound(10, 1.0, 1.28)
        < poisson_rate_lower_bound(10, 1.0, 0.0)
    )
    assert poisson_rate_lower_bound(1, 1.0, 5.0) == 0.0  # not enough to say anything


def test_poisson_lower_bound_matches_exact_quantile_for_large_counts() -> None:
    """For 100 events the approximation agrees with the exact 95 % lower limit (84.14)."""
    assert poisson_rate_lower_bound(100, 1.0, 1.645) == pytest.approx(84.14, abs=0.5)


# --------------------------------------------------------------------------- ledger: counting


def test_activating_kinds_exclude_only_squeeze_off() -> None:
    """SQUEEZE_OFF is the release of a squeeze, not a new activation."""
    assert EventKind.SQUEEZE_OFF not in ACTIVATING_KINDS
    assert ACTIVATING_KINDS == frozenset(EventKind) - {EventKind.SQUEEZE_OFF}


def test_squeeze_off_is_not_an_activation() -> None:
    """Recording SQUEEZE_OFF returns None and changes no counter."""
    clock, ledger = make_ledger()
    ledger.start()
    assert ledger.record(ev(EventKind.SQUEEZE_ON)) == 1
    clock.advance(1.0)
    assert ledger.record(ev(EventKind.SQUEEZE_OFF)) is None
    assert ledger.session_stats().activations == 1
    assert ledger.counts_by_kind() == {EventKind.SQUEEZE_ON: (1, 0)}


@pytest.mark.parametrize("kind", sorted(ACTIVATING_KINDS, key=lambda k: k.value))
def test_every_activating_kind_is_counted(kind) -> None:
    """Each kind other than SQUEEZE_OFF counts once and gets an id."""
    _, ledger = make_ledger()
    event_id = ledger.record(ev(kind))
    assert isinstance(event_id, int)
    assert ledger.counts_by_kind() == {kind: (1, 0)}


def test_ids_are_unique_and_increasing() -> None:
    """Event ids increase so a caller can hold on to one."""
    _, ledger = make_ledger()
    ids = [ledger.record(ev()) for _ in range(5)]
    assert ids == sorted(set(ids))


def test_record_starts_the_session_if_needed() -> None:
    """A first activation without start() begins accruing active time."""
    clock, ledger = make_ledger()
    assert not ledger.is_active
    ledger.record(ev())
    assert ledger.is_active and ledger.sessions == 1
    clock.advance(60.0)
    assert ledger.session_stats().active_seconds == pytest.approx(60.0)


def test_counts_activations_per_active_hour() -> None:
    """Rate is activations divided by *active* hours."""
    clock, ledger = make_ledger()
    ledger.start()
    for _ in range(6):
        ledger.record(ev())
    clock.advance(1800.0)
    stats = ledger.total_stats()
    assert stats.activations == 6
    assert stats.active_hours == pytest.approx(0.5)
    assert stats.per_hour == pytest.approx(12.0)
    assert stats.per_minute == pytest.approx(0.2)
    assert ledger.activations_per_hour == pytest.approx(12.0)
    assert ledger.activations_per_minute == pytest.approx(0.2)


def test_rates_are_zero_without_active_time() -> None:
    """No active time means no rate (never a ZeroDivisionError)."""
    stats = LedgerStats(activations=4, cancelled=1, active_seconds=0.0)
    assert stats.per_minute == stats.per_hour == stats.cancelled_per_hour == 0.0
    clock, ledger = make_ledger()
    assert ledger.activations_per_hour == 0.0
    assert ledger.recent_rate_per_hour() == 0.0


def test_pause_and_resume_exclude_paused_time() -> None:
    """Time between pause() and resume() is not active time."""
    clock, ledger = make_ledger()
    ledger.start()
    clock.advance(1800.0)
    ledger.pause()
    assert not ledger.is_active
    clock.advance(7200.0)   # laptop open overnight, or the quality gate suppressing
    assert ledger.session_stats().active_seconds == pytest.approx(1800.0)
    ledger.resume()
    clock.advance(1800.0)
    assert ledger.session_stats().active_seconds == pytest.approx(3600.0)
    ledger.record(ev())
    assert ledger.activations_per_hour == pytest.approx(1.0)


def test_pause_and_start_are_idempotent() -> None:
    """Double start/pause neither double counts time nor sessions."""
    clock, ledger = make_ledger()
    ledger.start()
    ledger.start()
    clock.advance(10.0)
    ledger.pause()
    clock.advance(5.0)
    ledger.pause()
    assert ledger.session_stats().active_seconds == pytest.approx(10.0)
    assert ledger.sessions == 1


def test_stop_folds_session_into_carried_totals() -> None:
    """stop() keeps the totals but starts the next session fresh."""
    clock, ledger = make_ledger()
    ledger.start()
    event_id = ledger.record(ev())
    ledger.mark_cancelled(event_id)
    clock.advance(600.0)
    ledger.stop()
    assert ledger.session_stats() == LedgerStats(0, 0, 0.0)
    total = ledger.total_stats()
    assert (total.activations, total.cancelled) == (1, 1)
    assert total.active_seconds == pytest.approx(600.0)
    assert not ledger.is_active
    clock.advance(1000.0)  # stopped: this must not count
    ledger.start()
    clock.advance(60.0)
    ledger.record(ev())
    assert ledger.sessions == 2
    assert ledger.total_stats().activations == 2
    assert ledger.total_stats().active_seconds == pytest.approx(660.0)
    assert ledger.session_stats().activations == 1
    assert ledger.mark_cancelled(event_id) is False  # the old id no longer resolves


def test_ledger_ignores_event_time_and_uses_its_own_clock() -> None:
    """BioEvent.t is on the source's clock and must not influence the ledger."""
    clock, ledger = make_ledger()
    event_id = ledger.record(ev(t=1e12))
    clock.advance(1.0)
    assert ledger.mark_cancelled(event_id) is True
    assert ledger.session_stats().active_seconds == pytest.approx(1.0)


@pytest.mark.parametrize(
    "kwargs",
    [{"grace_s": -1.0}, {"ewma_halflife_s": 0.0}, {"ewma_halflife_s": -5.0}, {"max_records": 0}],
)
def test_ledger_rejects_invalid_parameters(kwargs) -> None:
    """Impossible ledger settings fail at construction."""
    with pytest.raises(ValueError):
        ActivationLedger(FakeClock(), **kwargs)


# --------------------------------------------------------------------------- ledger: cancellation


def test_mark_cancelled_only_inside_grace_window() -> None:
    """A cancellation counts within grace_s of the activation and not after."""
    clock, ledger = make_ledger(grace_s=3.0)
    early = ledger.record(ev())
    clock.advance(2.9)
    assert ledger.mark_cancelled(early) is True
    late = ledger.record(ev())
    clock.advance(3.01)
    assert ledger.mark_cancelled(late) is False
    assert ledger.session_stats().cancelled == 1
    assert ledger.session_stats().activations == 2


def test_mark_cancelled_boundary_is_inclusive() -> None:
    """Exactly grace_s after the activation is still inside the window."""
    clock, ledger = make_ledger(grace_s=3.0)
    event_id = ledger.record(ev())
    clock.advance(3.0)
    assert ledger.mark_cancelled(event_id) is True


def test_mark_cancelled_twice_unknown_and_aged_out() -> None:
    """A second cancel, an unknown id and an id that aged out of the record all return False."""
    clock, ledger = make_ledger(max_records=2)
    first = ledger.record(ev())
    assert ledger.mark_cancelled(first) is True
    assert ledger.mark_cancelled(first) is False
    assert ledger.mark_cancelled(9999) is False
    a = ledger.record(ev())
    ledger.record(ev())
    ledger.record(ev())  # pushes `a` out of the bounded record
    assert ledger.mark_cancelled(a) is False
    assert ledger.session_stats().cancelled == 1


def test_cancelled_never_exceeds_activations() -> None:
    """However many cancellations are attempted, cancelled <= activations."""
    clock, ledger = make_ledger()
    ids = [ledger.record(ev()) for _ in range(4)]
    for event_id in ids * 3:
        ledger.mark_cancelled(event_id)
    stats = ledger.session_stats()
    assert stats.cancelled == stats.activations == 4
    assert stats.kept == 0


def test_mark_cancelled_latest_picks_most_recent_uncancelled() -> None:
    """'Undo' without an id cancels the newest eligible activation, then the next older."""
    clock, ledger = make_ledger(grace_s=3.0)
    first = ledger.record(ev())
    clock.advance(1.0)
    second = ledger.record(ev())
    clock.advance(0.5)
    assert ledger.mark_cancelled_latest() == second
    assert ledger.mark_cancelled_latest() == first
    assert ledger.mark_cancelled_latest() is None  # nothing left to cancel


def test_mark_cancelled_latest_respects_window_and_kind() -> None:
    """Only activations inside the grace window, of the requested kind, are eligible."""
    clock, ledger = make_ledger(grace_s=3.0)
    blink = ledger.record(ev(EventKind.BLINK))
    clock.advance(1.0)
    squeeze = ledger.record(ev(EventKind.SQUEEZE_ON))
    assert ledger.mark_cancelled_latest(EventKind.BLINK) == blink
    assert ledger.mark_cancelled_latest(EventKind.BLINK) is None
    assert ledger.mark_cancelled_latest(EventKind.JAW_CLENCH) is None
    clock.advance(10.0)
    assert ledger.mark_cancelled_latest() is None  # squeeze is now outside the window
    assert ledger.mark_cancelled(squeeze) is False
    assert ledger.session_stats().cancelled == 1


def test_mark_cancelled_latest_on_empty_ledger() -> None:
    """No activations -> nothing to cancel."""
    _, ledger = make_ledger()
    assert ledger.mark_cancelled_latest() is None


def test_cancelled_fraction_is_none_when_empty() -> None:
    """With no activations the cancelled fraction is undefined, not 0 or NaN."""
    clock, ledger = make_ledger()
    assert ledger.cancelled_fraction is None
    assert LedgerStats().cancelled_fraction is None
    ledger.start()
    clock.advance(60.0)
    assert ledger.cancelled_fraction is None
    event_id = ledger.record(ev())
    ledger.record(ev())
    ledger.mark_cancelled(event_id)
    assert ledger.cancelled_fraction == pytest.approx(0.5)


def test_ledger_wilson_interval_uses_totals() -> None:
    """The ledger's interval is the Wilson interval of (cancelled, activations)."""
    _, ledger = make_ledger()
    assert ledger.wilson_interval() == (0.0, 1.0)
    ids = [ledger.record(ev()) for _ in range(3)]
    ledger.mark_cancelled(ids[0])
    assert ledger.wilson_interval() == wilson_interval(1, 3)


def test_recent_counts_decay_with_half_life() -> None:
    """An activation fades by half every ewma_halflife_s of active time."""
    clock, ledger = make_ledger(ewma_halflife_s=100.0)
    ledger.start()
    event_id = ledger.record(ev())
    ledger.mark_cancelled(event_id)
    clock.advance(100.0)
    acts, canc, window = ledger.recent_counts()
    assert acts == pytest.approx(0.5)
    assert canc == pytest.approx(0.5)
    assert window == pytest.approx(100.0 / math.log(2.0) * 0.5)
    assert ledger.recent_rate_per_hour() == pytest.approx(acts / window * HOUR)
    assert ledger.recent_rate_per_hour(cancelled_only=True) == pytest.approx(canc / window * HOUR)


def test_paused_time_does_not_decay_recent_counts() -> None:
    """The recent-rate estimate runs on active time, so a pause freezes it."""
    clock, ledger = make_ledger(ewma_halflife_s=100.0)
    ledger.start()
    ledger.record(ev())
    ledger.pause()
    before = ledger.recent_counts()
    clock.advance(10_000.0)
    assert ledger.recent_counts() == before


# --------------------------------------------------------------------------- ledger: persistence


def test_to_dict_has_only_aggregate_counters() -> None:
    """No timestamps, no per-event records, only counters keyed by kind."""
    clock, ledger = make_ledger()
    ledger.start()
    a = ledger.record(ev(EventKind.BLINK, t=123456.0))
    ledger.record(ev(EventKind.SQUEEZE_ON))
    ledger.mark_cancelled(a)
    clock.advance(90.0)
    data = ledger.to_dict()
    assert set(data) == {"schema", "sessions", "active_seconds", "activations", "cancelled"}
    assert data["activations"] == {"blink": 1, "squeeze_on": 1}
    assert data["cancelled"] == {"blink": 1, "squeeze_on": 0}
    assert data["active_seconds"] == 90
    assert data["sessions"] == 1
    text = json.dumps(data)  # plain JSON
    assert "7654321" not in text and "123456" not in text  # neither clock nor event time
    for value in (data["schema"], data["sessions"], data["active_seconds"]):
        assert isinstance(value, int)
    for group in (data["activations"], data["cancelled"]):
        assert all(isinstance(v, int) for v in group.values())


def test_to_dict_from_dict_round_trip() -> None:
    """Rebuilding from the dict reproduces the totals and the dict itself."""
    clock, ledger = make_ledger()
    ledger.start()
    ids = [ledger.record(ev(EventKind.BLINK)) for _ in range(3)]
    ledger.record(ev(EventKind.JAW_CLENCH))
    ledger.mark_cancelled(ids[0])
    clock.advance(1234.0)
    ledger.stop()
    data = ledger.to_dict()

    clock2 = FakeClock()
    again = ActivationLedger.from_dict(data, clock2)
    assert again.to_dict() == data
    total = again.total_stats()
    assert (total.activations, total.cancelled) == (4, 1)
    assert total.active_seconds == pytest.approx(1234.0)
    assert again.sessions == 1
    assert again.session_stats() == LedgerStats(0, 0, 0.0)  # carried, not "this session"
    again.start()
    again.record(ev())
    assert again.total_stats().activations == 5
    assert again.sessions == 2


@pytest.mark.parametrize(
    "junk",
    [
        None,
        5,
        "text",
        [],
        [1, 2],
        {},
        {"activations": "bad", "cancelled": 7, "sessions": "x", "active_seconds": None},
        {"activations": [1, 2], "cancelled": [3]},
        {"activations": {"blink": "many"}},
        {"activations": {"blink": -4}, "active_seconds": -10, "sessions": -1},
        {"activations": {"blink": float("nan")}, "active_seconds": float("inf")},
        {"activations": {"blink": True}, "sessions": True},
        {"activations": {"no_such_kind": 9}},
    ],
)
def test_from_dict_tolerates_junk(junk) -> None:
    """A corrupt file never raises: unreadable parts count as zero."""
    ledger = ActivationLedger.from_dict(junk, FakeClock())
    total = ledger.total_stats()
    assert total.activations == 0 and total.cancelled == 0
    assert total.active_seconds >= 0.0 and ledger.sessions >= 0
    assert ledger.cancelled_fraction is None


def test_from_dict_clamps_and_filters() -> None:
    """Cancelled is clamped to activations; SQUEEZE_OFF and unknown kinds are ignored;
    a good key survives next to a bad one."""
    data = {
        "activations": {"blink": 5, "squeeze_off": 99, "bogus": 3, "jaw_clench": "x"},
        "cancelled": {"blink": 50, "jaw_clench": 7},
        "active_seconds": 3600.7,
        "sessions": 2.9,
    }
    ledger = ActivationLedger.from_dict(data, FakeClock())
    assert ledger.counts_by_kind() == {EventKind.BLINK: (5, 5)}
    assert ledger.total_stats().active_seconds == pytest.approx(3600.0)
    assert ledger.sessions == 2


def test_from_dict_passes_ledger_options() -> None:
    """Extra keyword arguments reach the constructor."""
    ledger = ActivationLedger.from_dict({}, FakeClock(), grace_s=9.0, ewma_halflife_s=42.0)
    assert ledger.grace_s == 9.0 and ledger.ewma_halflife_s == 42.0


# --------------------------------------------------------------------------- summary


def test_summary_exact_format() -> None:
    """The one-line report: rate, cancelled count, fraction, Wilson CI, active span."""
    stats = LedgerStats(activations=3, cancelled=1, active_seconds=HOUR)
    assert summary(stats) == "3 activations/h, 1 cancelled (33%, 95% CI 6–79%) over 60 min"


def test_summary_with_note_appends_proxy_caveat() -> None:
    """with_note adds PROXY_NOTE in parentheses, on every branch."""
    stats = LedgerStats(activations=3, cancelled=1, active_seconds=HOUR)
    assert summary(stats, with_note=True) == summary(stats) + f" ({PROXY_NOTE})"
    assert "proxy" in PROXY_NOTE and "not ground truth" in PROXY_NOTE
    for odd in (LedgerStats(2, 0, 0.0), LedgerStats(0, 0, 600.0)):
        assert summary(odd, with_note=True) == summary(odd) + f" ({PROXY_NOTE})"


def test_summary_edge_cases() -> None:
    """No time, no activations and activations-without-time are all worded sensibly."""
    assert summary(LedgerStats()) == "no active session time recorded yet"
    assert summary(LedgerStats(2, 0, 0.0)) == "2 activations, no active session time recorded"
    assert summary(LedgerStats(0, 0, 600.0)) == "0 activations over 10 min"
    assert summary(LedgerStats(1, 0, 45.0)).endswith("over 45 s")
    assert summary(LedgerStats(1, 0, 9000.0)).endswith("over 2.5 h")


def test_summary_rate_formatting() -> None:
    """Rates print without trailing zeros, with one decimal under 10."""
    assert summary(LedgerStats(5, 0, 2 * HOUR)).startswith("2.5 activations/h")
    assert summary(LedgerStats(40, 0, 2 * HOUR)).startswith("20 activations/h")
    assert summary(LedgerStats(37, 0, 3 * HOUR)).startswith("12 activations/h")


def test_summary_accepts_a_ledger() -> None:
    """A ledger summarises as its totals (carried plus current session)."""
    clock, ledger = make_ledger()
    ledger.start()
    event_id = ledger.record(ev())
    ledger.record(ev())
    ledger.mark_cancelled(event_id)
    clock.advance(HOUR)
    assert summary(ledger) == summary(ledger.total_stats())
    assert "1 cancelled (50%" in summary(ledger)


# --------------------------------------------------------------------------- budget validation


def test_default_budget_is_valid_and_disabled() -> None:
    """The governor is opt-in: the default budget is valid and enabled=False."""
    budget = FalsePositiveBudget()
    assert budget.enabled is False
    assert budget.max_cancelled_per_hour > 0


def test_budget_is_frozen() -> None:
    """A budget cannot be mutated behind the governor's back."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        FalsePositiveBudget().enabled = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_cancelled_per_hour": 0.0},
        {"max_cancelled_per_hour": -1.0},
        {"min_session_minutes": -1.0},
        {"min_cancelled": 0},
        {"desensitize_factor": 0.9},
        {"suspend_multiple": 0.5},
        {"hysteresis": 0.0},
        {"hysteresis": 1.0},
        {"hysteresis": 1.5},
        {"dwell_minutes": -1.0},
        {"suspend_s": 0.0},
        {"suspend_s": 100.0, "max_suspend_s": 50.0},
        {"suspend_backoff": 0.5},
        {"confidence_z": -0.1},
    ],
)
def test_budget_validation_rejects(kwargs) -> None:
    """Each impossible setting raises ValueError."""
    with pytest.raises(ValueError):
        FalsePositiveBudget(**kwargs)


def test_budget_validation_accepts_boundaries() -> None:
    """The inclusive edges of the valid ranges are accepted."""
    FalsePositiveBudget(
        min_session_minutes=0, min_cancelled=1, desensitize_factor=1.0, suspend_multiple=1.0,
        dwell_minutes=0, suspend_s=10, max_suspend_s=10, suspend_backoff=1.0, confidence_z=0.0,
    )


def test_governor_action_constructors() -> None:
    """Factory helpers set the right kind and a no-op factor where applicable."""
    assert GovernorAction.ok() == GovernorAction(GovernorKind.OK, 1.0, "")
    assert GovernorAction.suspend("why").factor == 1.0
    desens = GovernorAction.desensitize(1.5, "why")
    assert desens.kind is GovernorKind.DESENSITIZE and desens.factor == 1.5
    assert desens.reason == "why"


# --------------------------------------------------------------------------- governor


class Rig:
    """A governor on a fake clock with helpers to generate cancelled activations."""

    def __init__(self, *, halflife_s: float = 600.0, enabled: bool = True, **budget) -> None:
        self.clock = FakeClock()
        self.ledger = ActivationLedger(self.clock, ewma_halflife_s=halflife_s)
        self.ledger.start()
        self.gov = BudgetGovernor(
            self.ledger, FalsePositiveBudget(enabled=enabled, **budget), release_word="carry on"
        )

    def cancelled(self, count: int = 1, every_s: float = 60.0) -> GovernorAction:
        """``count`` activations, each cancelled at once, ``every_s`` apart."""
        action = self.gov.action
        for _ in range(count):
            self.clock.advance(every_s)
            event_id = self.ledger.record(ev())
            assert self.ledger.mark_cancelled(event_id)
            action = self.gov.update()
        return action

    def kept(self, count: int = 1, every_s: float = 60.0) -> GovernorAction:
        action = self.gov.action
        for _ in range(count):
            self.clock.advance(every_s)
            self.ledger.record(ev())
            action = self.gov.update()
        return action

    def idle(self, seconds: float, step_s: float = 60.0) -> GovernorAction:
        action = self.gov.action
        elapsed = 0.0
        while elapsed < seconds:
            self.clock.advance(step_s)
            elapsed += step_s
            action = self.gov.update()
        return action

    def drive_to(self, kind: GovernorKind, every_s: float = 60.0, limit: int = 500) -> None:
        for _ in range(limit):
            self.cancelled(1, every_s)
            if self.gov.state is kind:
                return
        raise AssertionError(f"never reached {kind}; stuck in {self.gov.state}")

    def suspension_length(self, step_s: float = 1.0) -> float:
        """Idle in 1 s steps until the governor leaves SUSPEND; return how long it took."""
        assert self.gov.state is GovernorKind.SUSPEND
        elapsed = 0.0
        while self.gov.state is GovernorKind.SUSPEND:
            self.clock.advance(step_s)
            elapsed += step_s
            self.gov.update()
            assert elapsed < 10_000
        return elapsed


def test_default_governor_is_disabled_and_always_ok() -> None:
    """With the default (enabled=False) budget even a storm of cancellations reports OK."""
    clock = FakeClock()
    ledger = ActivationLedger(clock)
    ledger.start()
    gov = BudgetGovernor(ledger)
    assert gov.budget.enabled is False
    for _ in range(200):
        clock.advance(5.0)
        ledger.mark_cancelled(ledger.record(ev()))
        action = gov.update()
        assert action == GovernorAction.ok()
    assert gov.state is GovernorKind.OK
    assert gov.action == GovernorAction.ok()
    assert "off" in gov.explain()
    assert ledger.session_stats().cancelled == 200  # still measured


def test_enabled_governor_starts_ok() -> None:
    """A fresh enabled governor with no evidence is OK with a neutral factor."""
    rig = Rig()
    action = rig.gov.update()
    assert action.kind is GovernorKind.OK and action.factor == 1.0 and action.reason == ""


def test_few_early_cancellations_never_fire() -> None:
    """Rule 9: a handful of early cancellations is noise, not a signal."""
    rig = Rig()
    # Fewer than min_cancelled, however fast.
    assert rig.cancelled(2, every_s=1.0).kind is GovernorKind.OK
    # Plenty of cancellations but too little active time (< min_session_minutes).
    rig = Rig()
    assert rig.cancelled(10, every_s=10.0).kind is GovernorKind.OK
    assert rig.gov.state is GovernorKind.OK
    # Few cancellations spread over a long time: enough time, not enough evidence.
    rig = Rig()
    rig.idle(30 * 60)
    assert rig.cancelled(2, every_s=300.0).kind is GovernorKind.OK


def test_cancellations_mixed_with_kept_activations_stay_ok() -> None:
    """A low cancelled rate (1 per 20 min = 3/h, under budget) never trips the governor."""
    rig = Rig()
    for _ in range(12):
        rig.kept(19, every_s=60.0)
        assert rig.cancelled(1, every_s=60.0).kind is GovernorKind.OK
    assert rig.gov.state is GovernorKind.OK


def test_escalates_ok_to_desensitize_to_suspend() -> None:
    """A sustained high cancelled rate goes OK -> DESENSITIZE -> SUSPEND, in that order."""
    rig = Rig()
    seen = [rig.gov.state]
    for _ in range(40):
        rig.cancelled(1, every_s=60.0)
        if rig.gov.state is not seen[-1]:
            seen.append(rig.gov.state)
        if rig.gov.state is GovernorKind.SUSPEND:
            break
    assert seen == [GovernorKind.OK, GovernorKind.DESENSITIZE, GovernorKind.SUSPEND]


def test_desensitize_action_carries_factor_and_reason() -> None:
    """DESENSITIZE reports the budget's factor (> 1) and a plain-language reason."""
    rig = Rig(desensitize_factor=1.7)
    rig.drive_to(GovernorKind.DESENSITIZE)
    action = rig.gov.action
    assert action.kind is GovernorKind.DESENSITIZE
    assert action.factor == pytest.approx(1.7)
    assert "cancelled" in action.reason and "an hour" in action.reason
    assert rig.gov.update().kind is GovernorKind.DESENSITIZE  # stable while nothing changes


def test_suspend_action_has_unit_factor_and_reason() -> None:
    """SUSPEND turns the trigger off, so there is no threshold factor to apply."""
    rig = Rig()
    rig.drive_to(GovernorKind.SUSPEND)
    action = rig.gov.action
    assert action.kind is GovernorKind.SUSPEND
    assert action.factor == 1.0 and action.reason


def test_moderate_overage_desensitizes_but_does_not_suspend() -> None:
    """At 8/h (over the 6/h budget, under twice that) the gentle fix is all it does."""
    rig = Rig(halflife_s=1e9)  # near-uniform average, so the rate is the plain rate
    seen = set()
    for _ in range(100):
        rig.cancelled(1, every_s=450.0)  # 8 per hour
        seen.add(rig.gov.state)
    assert GovernorKind.DESENSITIZE in seen
    assert GovernorKind.SUSPEND not in seen
    assert rig.gov.state is GovernorKind.DESENSITIZE


def test_suspend_auto_recovers_into_desensitize_not_ok() -> None:
    """After suspend_s the suspension ends by itself, into the gentle state."""
    rig = Rig(suspend_s=300.0)
    rig.drive_to(GovernorKind.SUSPEND)
    rig.clock.advance(299.0)
    assert rig.gov.update().kind is GovernorKind.SUSPEND
    rig.clock.advance(2.0)
    action = rig.gov.update()
    assert action.kind is GovernorKind.DESENSITIZE
    assert action.factor == rig.gov.budget.desensitize_factor
    assert "on its own" in action.reason


def test_recovery_from_suspend_needs_fresh_evidence_to_suspend_again() -> None:
    """Right after auto-recovery, old cancellations do not instantly re-suspend."""
    rig = Rig()
    rig.drive_to(GovernorKind.SUSPEND)
    rig.suspension_length()
    assert rig.gov.state is GovernorKind.DESENSITIZE
    assert rig.gov.update().kind is GovernorKind.DESENSITIZE
    rig.cancelled(2, every_s=10.0)  # under min_cancelled / min_session_minutes
    assert rig.gov.state is GovernorKind.DESENSITIZE


def test_suspension_backoff_doubles_up_to_the_cap() -> None:
    """Repeated suspensions last suspend_s, then x backoff each time, capped."""
    rig = Rig(suspend_s=100.0, suspend_backoff=2.0, max_suspend_s=350.0, min_session_minutes=1.0)
    lengths = []
    for _ in range(5):
        rig.drive_to(GovernorKind.SUSPEND, every_s=10.0)
        lengths.append(rig.suspension_length())
    assert lengths[0] == pytest.approx(100.0, abs=2)
    assert lengths[1] == pytest.approx(200.0, abs=2)
    assert lengths[2] == pytest.approx(350.0, abs=2)   # 400 capped to max_suspend_s
    assert lengths[3] == pytest.approx(350.0, abs=2)
    assert lengths[4] == pytest.approx(350.0, abs=2)


def test_backoff_factor_of_one_keeps_suspensions_constant() -> None:
    """suspend_backoff = 1 means every suspension is suspend_s long."""
    rig = Rig(suspend_s=120.0, suspend_backoff=1.0, min_session_minutes=1.0)
    lengths = []
    for _ in range(3):
        rig.drive_to(GovernorKind.SUSPEND, every_s=10.0)
        lengths.append(rig.suspension_length())
    assert all(length == pytest.approx(120.0, abs=2) for length in lengths)


def test_release_returns_to_ok_in_one_call_from_suspend() -> None:
    """One release() undoes a suspension immediately and reports OK."""
    rig = Rig()
    rig.drive_to(GovernorKind.SUSPEND)
    action = rig.gov.release()
    assert action == GovernorAction.ok()
    assert rig.gov.state is GovernorKind.OK
    assert rig.gov.action == GovernorAction.ok()
    assert rig.gov.update().kind is GovernorKind.OK  # and it stays released


def test_release_returns_to_ok_in_one_call_from_desensitize() -> None:
    """release() also undoes the gentle state."""
    rig = Rig()
    rig.drive_to(GovernorKind.DESENSITIZE)
    assert rig.gov.release() == GovernorAction.ok()
    assert rig.gov.state is GovernorKind.OK


def test_release_when_already_ok_is_harmless() -> None:
    """release() on a healthy governor is a no-op that reports OK."""
    rig = Rig()
    assert rig.gov.release() == GovernorAction.ok()
    assert rig.gov.update() == GovernorAction.ok()


def test_release_starts_a_fresh_evidence_window() -> None:
    """After release the old cancellations are forgiven; new evidence is needed to re-fire."""
    rig = Rig()
    rig.drive_to(GovernorKind.SUSPEND)
    rig.gov.release()
    assert rig.cancelled(2, every_s=10.0).kind is GovernorKind.OK
    # Genuinely continuing trouble does bring it back.
    rig.drive_to(GovernorKind.DESENSITIZE)
    assert rig.gov.state is GovernorKind.DESENSITIZE


def test_release_resets_the_suspension_backoff() -> None:
    """A user release means the next suspension is the base length again."""
    rig = Rig(suspend_s=100.0, suspend_backoff=2.0, max_suspend_s=1000.0, min_session_minutes=1.0)
    rig.drive_to(GovernorKind.SUSPEND, every_s=10.0)
    assert rig.suspension_length() == pytest.approx(100.0, abs=2)
    rig.drive_to(GovernorKind.SUSPEND, every_s=10.0)
    rig.gov.release()
    rig.drive_to(GovernorKind.DESENSITIZE, every_s=10.0)
    rig.drive_to(GovernorKind.SUSPEND, every_s=10.0)
    assert rig.suspension_length() == pytest.approx(100.0, abs=2)


def test_hysteresis_prevents_flapping_at_the_boundary() -> None:
    """Dropping just under budget does not restore sensitivity; well under it does."""
    rig = Rig(halflife_s=1e9, dwell_minutes=1.0, min_session_minutes=1.0)
    rig.drive_to(GovernorKind.SUSPEND, every_s=36.0)  # 100 per hour
    rig.suspension_length()  # let the suspension lapse into DESENSITIZE
    assert rig.gov.state is GovernorKind.DESENSITIZE
    budget = rig.gov.budget
    recovered_at = None
    states = []
    for _ in range(2000):
        rig.idle(120.0)
        rate = rig.ledger.recent_rate_per_hour(cancelled_only=True)
        states.append((rate, rig.gov.state))
        if rig.gov.state is GovernorKind.OK:
            recovered_at = rate
            break
    assert recovered_at is not None, "never recovered"
    # Between hysteresis*budget and budget it stayed desensitized (no flapping at the edge)...
    in_band = [s for r, s in states if budget.max_cancelled_per_hour * budget.hysteresis < r
               <= budget.max_cancelled_per_hour]
    assert in_band and all(s is GovernorKind.DESENSITIZE for s in in_band)
    # ... and recovery happened only once the rate was under the hysteresis level.
    assert recovered_at < budget.max_cancelled_per_hour * budget.hysteresis


def test_recovery_requires_the_dwell_time() -> None:
    """Even at zero rate the governor stays desensitized until dwell_minutes have passed."""
    rig = Rig(dwell_minutes=30.0, min_session_minutes=1.0, halflife_s=60.0)
    rig.drive_to(GovernorKind.DESENSITIZE, every_s=10.0)
    rig.idle(10 * 60)
    assert rig.gov.state is GovernorKind.DESENSITIZE
    rig.idle(30 * 60)
    assert rig.gov.state is GovernorKind.OK


def test_recovery_from_desensitize_resets_the_evidence_window() -> None:
    """After a full recovery a couple of new cancellations are not enough to re-fire."""
    rig = Rig(dwell_minutes=1.0, min_session_minutes=1.0, halflife_s=60.0)
    rig.drive_to(GovernorKind.DESENSITIZE, every_s=10.0)
    rig.idle(60 * 60)
    assert rig.gov.state is GovernorKind.OK
    assert rig.cancelled(2, every_s=5.0).kind is GovernorKind.OK


def test_governor_judges_the_session_not_carried_history() -> None:
    """Carried totals from earlier sessions do not count toward this session's evidence."""
    clock = FakeClock()
    carried = ActivationLedger.from_dict(
        {"activations": {"blink": 500}, "cancelled": {"blink": 500}, "active_seconds": 3600,
         "sessions": 9},
        clock,
    )
    carried.start()
    gov = BudgetGovernor(carried, FalsePositiveBudget(enabled=True))
    assert gov.update().kind is GovernorKind.OK


# --------------------------------------------------------------------------- explain


def test_explain_disabled_and_ok() -> None:
    """Off and healthy states each get one plain sentence."""
    assert "off" in Rig(enabled=False).gov.explain()
    rig = Rig()
    assert "normally" in rig.gov.explain()
    assert "carry on" not in rig.gov.explain()


def test_explain_desensitized_mentions_release_word_and_factor() -> None:
    """The user is told what changed and how to undo it."""
    rig = Rig(desensitize_factor=1.5)
    rig.drive_to(GovernorKind.DESENSITIZE)
    text = rig.gov.explain()
    assert '"carry on"' in text
    assert "1.5x" in text
    assert rig.gov.action.reason in text


def test_explain_suspended_mentions_release_word_and_time_left() -> None:
    """While suspended, explain() says why, when it ends, and the one-word way out."""
    rig = Rig(suspend_s=300.0)
    rig.drive_to(GovernorKind.SUSPEND)
    text = rig.gov.explain()
    assert '"carry on"' in text
    assert "paused" in text and ("min" in text or " s" in text)
    assert rig.gov.action.reason in text
    rig.clock.advance(100.0)
    later = rig.gov.explain()
    assert later != text  # the countdown moves


def test_default_release_word_is_resume() -> None:
    """Without an integrator-supplied word, explain() offers 'resume'."""
    clock = FakeClock()
    ledger = ActivationLedger(clock)
    ledger.start()
    gov = BudgetGovernor(ledger, FalsePositiveBudget(enabled=True, min_session_minutes=0.0))
    assert gov.release_word == "resume"
    for _ in range(60):
        clock.advance(30.0)
        ledger.mark_cancelled(ledger.record(ev()))
        gov.update()
        if gov.state is GovernorKind.DESENSITIZE:
            break
    assert gov.state is GovernorKind.DESENSITIZE
    assert '"resume"' in gov.explain()
