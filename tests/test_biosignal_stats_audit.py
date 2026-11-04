"""Independent-oracle audit of the biosignal switch's statistics and arithmetic.

Every expected number here comes from the stdlib (bisection on the Poisson CDF, the Wilson
score formula, published chi-square and Wilson table values), not from the code under test.
Where a mismatch is a defect the test is a regression test (it fails without the fix);
where the product claim itself needs a human decision the test is a strict xfail with the
reason stated, so the decision cannot be silently forgotten.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from yazses.biosignal import calibration as cal
from yazses.biosignal.calibration import CalibrationConfig, CalibrationSession
from yazses.biosignal.conformance import check_source
from yazses.biosignal.evaluate import (
    KindStats,
    _poisson_upper,
    evaluate_idle,
)
from yazses.biosignal.fprate import (
    LedgerStats,
    poisson_rate_lower_bound,
    summary,
    wilson_interval,
)
from yazses.biosignal.sources import SyntheticSource
from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind

# ---------------------------------------------------------------- independent oracles


def _pois_cdf(k: int, lam: float) -> float:
    return sum(math.exp(-lam + i * math.log(lam) - math.lgamma(i + 1)) for i in range(k + 1))


def _exact_upper_oracle(k: int, alpha: float = 0.05) -> float:
    """lam with P(X <= k | lam) = alpha: the one-sided 95% upper Poisson limit."""
    lo, hi = 0.0, k + 50.0 + 20.0 * math.sqrt(k + 1.0)
    for _ in range(300):
        mid = (lo + hi) / 2.0
        if _pois_cdf(k, mid) > alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _exact_lower_oracle(k: int, alpha: float = 0.05) -> float:
    """lam with P(X >= k | lam) = alpha: the one-sided 95% lower Poisson limit (k >= 1)."""
    lo, hi = 0.0, 3.0 * k + 50.0
    for _ in range(300):
        mid = (lo + hi) / 2.0
        if 1.0 - _pois_cdf(k - 1, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _wilson_oracle(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    # z = 1.96 is the constant fprate.py uses (exact 1.959964 differs by ~2e-6 in the bounds).
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return centre - half, centre + half


# Published chi-square 0.95 quantiles, halved: the exact one-sided 95% Poisson upper limit
# after k events is chi2_{0.95}(2k + 2) / 2. df=2,4,6,12,22 -> 5.9915, 9.4877, 12.5916,
# 21.0261, 33.9244 (standard chi-square table).
_CHI2_TABLE_UPPER = {0: 5.9915 / 2, 1: 9.4877 / 2, 2: 12.5916 / 2, 5: 21.0261 / 2, 10: 33.9244 / 2}


# ----------------------------------------------- oracles agree with each other (sanity)


@pytest.mark.parametrize("k", [0, 1, 2, 5, 10])
def test_oracle_matches_published_chi_square_table(k: int) -> None:
    assert _exact_upper_oracle(k) == pytest.approx(_CHI2_TABLE_UPPER[k], abs=2e-4)


# ------------------------------------------------ Poisson upper bound (evaluate.py) ----


def test_zero_events_upper_limit_is_the_chi_square_value_not_a_rule_of_three_approximation() -> None:
    # Regression: the Wilson-Hilferty form gave 2.9687 here (0.9% low, anti-conservative).
    # Per-hour form at exposure 1 h is the event limit itself.
    assert _poisson_upper(0, 1.0) == pytest.approx(2.9957323, rel=1e-6)


@pytest.mark.parametrize("k", [1, 2, 5, 10, 100])
def test_upper_limit_matches_exact_oracle(k: int) -> None:
    assert _poisson_upper(k, 1.0) == pytest.approx(_exact_upper_oracle(k), rel=1e-6)


def test_upper_limit_per_hour_at_default_idle_length_is_30_per_hour() -> None:
    # 0.1 h of silence with zero phantoms: the exact bound is 29.957 per hour, printed "30.0".
    assert _poisson_upper(0, 0.1) == pytest.approx(_exact_upper_oracle(0) / 0.1, rel=1e-6)
    assert f"{_poisson_upper(0, 0.1):.1f}" == "30.0"


@pytest.mark.parametrize("hours", [0.0, -1.0])
def test_zero_or_negative_exposure_claims_nothing(hours: float) -> None:
    # "0 events in 0 s" has no rate, so there is no upper bound to quote and no safety claim.
    assert _poisson_upper(0, hours) is None
    assert _poisson_upper(3, hours) is None


def test_idle_run_with_zero_phantoms_reports_the_exact_upper_bound() -> None:
    class Silent:
        def process(self, block: SampleBlock) -> list:
            return []

    report = evaluate_idle(None, Silent(), hours_simulated=0.1, seed=0)
    assert report.phantom_activations == 0
    assert report.phantom_per_hour == 0.0
    assert report.phantom_upper_per_hour == pytest.approx(_exact_upper_oracle(0) / report.hours,
                                                          rel=1e-6)


# ------------------------------------------------------ per-hour rate conversions -------


def test_kind_stats_false_positives_per_hour_is_count_over_hours() -> None:
    row = KindStats(kind=None, true_positives=0, false_positives=3, false_negatives=0,
                    latency_median_ms=None, latency_p95_ms=None, duration_s=1800.0)
    assert row.false_positives_per_hour == pytest.approx(6.0)


def test_kind_stats_zero_duration_has_no_rate() -> None:
    row = KindStats(kind=None, true_positives=0, false_positives=3, false_negatives=0,
                    latency_median_ms=None, latency_p95_ms=None, duration_s=0.0)
    assert row.false_positives_per_hour is None


def test_ledger_per_hour_and_per_minute_match_hand_arithmetic() -> None:
    stats = LedgerStats(activations=3, cancelled=1, active_seconds=1800.0)
    assert stats.per_hour == pytest.approx(6.0)
    assert stats.per_minute == pytest.approx(0.1)
    assert stats.cancelled_per_hour == pytest.approx(2.0)
    assert stats.cancelled_fraction == pytest.approx(1 / 3)


def test_ledger_no_activations_has_no_cancelled_fraction() -> None:
    assert LedgerStats(activations=0, active_seconds=600.0).cancelled_fraction is None


def test_summary_with_zero_activations_states_the_count_and_no_safety_word() -> None:
    text = summary(LedgerStats(activations=0, active_seconds=2520.0))
    assert text == "0 activations over 42 min"
    assert "safe" not in text.lower()


def test_summary_with_no_session_time_claims_nothing() -> None:
    assert summary(LedgerStats()) == "no active session time recorded yet"


# ------------------------------------------------------------- Wilson intervals (fprate) --


def test_wilson_zero_of_ten_matches_published_table() -> None:
    low, high = wilson_interval(0, 10)
    assert low == 0.0
    assert high == pytest.approx(0.2775, abs=1e-4)      # published table: 0.2775


def test_wilson_five_of_ten_matches_published_table() -> None:
    low, high = wilson_interval(5, 10)
    assert low == pytest.approx(0.2366, abs=1e-4)
    assert high == pytest.approx(0.7634, abs=1e-4)


@pytest.mark.parametrize(("k", "n"), [(1, 3), (3, 30), (1, 20), (7, 9), (50, 100)])
def test_wilson_matches_independent_formula(k: int, n: int) -> None:
    got = wilson_interval(k, n)
    want = _wilson_oracle(k, n)
    assert got[0] == pytest.approx(want[0], abs=1e-12)
    assert got[1] == pytest.approx(want[1], abs=1e-12)


def test_wilson_with_no_trials_is_the_whole_range_not_a_zero() -> None:
    assert wilson_interval(0, 0) == (0.0, 1.0)


# --------------------------------------------- governor's lower bound (conservative) ----


@pytest.mark.parametrize("count", range(1, 21))
def test_governor_lower_bound_never_exceeds_the_exact_lower_limit(count: int) -> None:
    # The governor must act only on evidence: its lower bound may be below the exact limit
    # (conservative) but must not be above it.
    z = 1.6448536269514722  # one-sided 95%
    assert poisson_rate_lower_bound(count, 1.0, z) <= _exact_lower_oracle(count) + 1e-9


@pytest.mark.parametrize("count", [5, 10, 20])
def test_governor_lower_bound_is_within_one_percent_for_useful_counts(count: int) -> None:
    z = 1.6448536269514722
    got = poisson_rate_lower_bound(count, 1.0, z)
    assert got == pytest.approx(_exact_lower_oracle(count), rel=1e-2)


# ---------------------------------------------------------- window / segment arithmetic --


def test_window_rms_drops_the_partial_tail_window() -> None:
    from yazses.biosignal.calibration import _window_rms

    assert _window_rms(np.ones((1, 10)), 4).size == 2       # 10 // 4 whole windows
    assert _window_rms(np.ones((1, 3)), 4).size == 0        # shorter than one window


def test_segments_bridge_gaps_up_to_merge_gap_and_keep_min_length_inclusive() -> None:
    from yazses.biosignal.calibration import _segments

    m = np.array([1, 1, 1, 0, 0, 1], dtype=bool)
    assert _segments(m, min_len=3, merge_gap=0) == [(0, 3)]          # (3,6) too short
    assert _segments(m, min_len=1, merge_gap=0) == [(0, 3), (5, 6)]
    gap1 = np.array([1, 1, 0, 1, 1], dtype=bool)
    assert _segments(gap1, min_len=1, merge_gap=0) == [(0, 2), (3, 5)]
    assert _segments(gap1, min_len=1, merge_gap=1) == [(0, 5)]       # one False bridged


# ------------------------------------------------------- calibration: short baseline -----


def test_too_short_rest_is_not_reported_as_flat_electrodes() -> None:
    # Regression: 0.5 s of rest at 0.25 s windows gives 2 windows (< 4). The old message
    # said the electrodes were flat, which the data contradicts: the signal is there.
    fs = 250.0
    chans = (ChannelInfo("Fp1", SignalKind.EEG),)
    cfg = CalibrationConfig(relax_s=0.5, window_s=0.25)
    session = CalibrationSession("oracle", chans, fs, config=cfg)
    rng = np.random.default_rng(3)
    n = round((cfg.settle_s + cfg.relax_s) * fs)
    issue = session.feed(SampleBlock(rng.normal(0.0, 20.0, size=(1, n)), fs, chans, 0.0))
    assert issue is not None
    assert issue.code is cal.IssueCode.NO_SIGNAL
    assert "flat" not in issue.message.lower()
    assert "not enough" in issue.message.lower()


# ------------------------------------------------- idle-run overshoot (documented bound) --


def test_default_idle_source_is_capped_at_exactly_the_requested_length() -> None:
    # The default SyntheticSource is capped at the request, so the consumed time equals it
    # (the one-block overshoot the docstring allows is for a caller's own source).
    class Silent:
        def process(self, block: SampleBlock) -> list:
            return []

    target = 0.00001 * 3600.0          # 0.036 s, not a whole number of 0.04 s blocks
    report = evaluate_idle(None, Silent(), hours_simulated=0.00001, seed=0)
    assert report.duration_s == pytest.approx(target, abs=1e-9)


# ------------------------------------------- verdicts that need a human (strict xfail) ---


@pytest.mark.xfail(strict=True, reason=(
    "LedgerStats.per_hour returns 0.0 when activations exist but no active time was recorded,"
    " so 'N events in 0 s' reads as a zero rate. cli_impl serialises that 0.0 as"
    " activations_per_hour. Fixing it changes a public JSON value (float -> None), which is a"
    " CLI-interface decision for the owner."
))
def test_events_in_zero_active_time_do_not_read_as_a_zero_rate() -> None:
    stats = LedgerStats(activations=3, active_seconds=0.0)
    assert stats.per_hour != 0.0


@pytest.mark.xfail(strict=True, reason=(
    "check_source says 'PASS' whenever no clause failed, even when both rate clauses were"
    " skipped because the run was shorter than 2 s (so the sample rate was never measured)."
    " Changing what PASS means changes the CLI verdict and exit status; that is an owner"
    " decision (for example a separate 'INCOMPLETE' verdict)."
))
def test_a_run_too_short_to_measure_the_rate_is_not_a_full_pass() -> None:
    class Clock:
        t = 0.0

        def __call__(self) -> float:
            return self.t

        def sleep(self, dt: float) -> None:
            self.t += dt

    clock = Clock()
    report = check_source(SyntheticSource("eeg", duration=0.2), clock=clock, sleep=clock.sleep,
                          seconds=0.2)
    rate_skipped = {report.clause("rate_t0").status, report.clause("rate_arrival").status} == {
        "skip"
    }
    assert rate_skipped
    assert not report.passed
