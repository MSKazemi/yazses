"""Signal-quality gate (``yazses.biosignal.quality``): pure checks and the streaming monitor.

Everything is synthetic, seeded numpy; nothing here needs hardware, a network or a clock.
The tests state *properties* (a flat channel is flagged as flat, a hum-swamped one as
mains, a blink only degrades) rather than pinning threshold arithmetic.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from yazses.biosignal.quality import (
    ChannelQuality,
    QualityReport,
    QualityStatus,
    QualityThresholds,
    Reason,
    SignalQualityMonitor,
    assess_channel,
    burst_fraction,
    drift_metrics,
    excess_kurtosis,
    explain,
    flatline_std,
    mains_ratio,
    nonfinite_fraction,
    robust_sigma,
    saturation_fraction,
    suppress_events,
)
from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind

FS = 250.0


def _rng(seed: int = 0) -> np.random.Generator:
    return np.random.default_rng(seed)


def _noise(n: int, sigma: float = 10.0, seed: int = 0) -> np.ndarray:
    return _rng(seed).normal(0.0, sigma, n)


def _tone(n: int, fs: float, hz: float, amp: float) -> np.ndarray:
    return amp * np.sin(2 * np.pi * hz * np.arange(n) / fs)


def _chans(*specs: tuple[str, SignalKind]) -> tuple[ChannelInfo, ...]:
    return tuple(ChannelInfo(name, kind) for name, kind in specs)


EEG1 = _chans(("Fp1", SignalKind.EEG))
EMG1 = _chans(("emg", SignalKind.EMG))


def _feed(
    mon: SignalQualityMonitor,
    data: np.ndarray,
    fs: float,
    channels: tuple[ChannelInfo, ...],
    *,
    block: int | None = None,
    t_start: float = 0.0,
) -> list[QualityReport]:
    """Feed ``data`` (n_ch, N) in contiguous blocks with correct ``t0``; return all reports."""
    block = block or int(round(fs * 0.25))
    reports = []
    for i in range(0, data.shape[1], block):
        chunk = data[:, i : i + block]
        reports.append(
            mon.update(SampleBlock(chunk, fs, channels, t0=t_start + i / fs))
        )
    return reports


def _clean(seconds: float, fs: float = FS, n_ch: int = 1, seed: int = 0) -> np.ndarray:
    return np.vstack([_noise(int(seconds * fs), 10.0, seed + k) for k in range(n_ch)])


def _good_monitor(
    thr: QualityThresholds | None = None,
    channels: tuple[ChannelInfo, ...] = EEG1,
    seconds: float = 6.0,
) -> tuple[SignalQualityMonitor, float]:
    """A monitor already past warm-up and recovery on clean noise; returns it and next t0."""
    mon = SignalQualityMonitor(thr)
    _feed(mon, _clean(seconds, n_ch=len(channels)), FS, channels)
    assert mon.report is not None
    assert mon.report.overall is QualityStatus.GOOD
    return mon, seconds


# --------------------------------------------------------------------------------------
# Pure metrics
# --------------------------------------------------------------------------------------


def test_nonfinite_fraction_counts_nan_and_inf_and_handles_empty():
    x = np.ones(100)
    x[:5] = np.nan
    x[5:8] = np.inf
    x[8:10] = -np.inf
    assert nonfinite_fraction(x) == pytest.approx(0.10)
    assert nonfinite_fraction(np.ones(10)) == 0.0
    assert nonfinite_fraction(np.full(10, np.nan)) == 1.0
    assert nonfinite_fraction(np.array([])) == 0.0


def test_flatline_std_is_zero_for_constant_and_matches_sine_rms():
    assert flatline_std(np.full(500, 123.4)) == pytest.approx(0.0, abs=1e-9)   # offset is not signal
    assert flatline_std(_tone(1000, FS, 10.0, 20.0)) == pytest.approx(20.0 / math.sqrt(2), rel=0.02)
    assert flatline_std(np.array([])) == 0.0


def test_robust_sigma_recovers_gaussian_sigma_and_ignores_outliers():
    x = _noise(20000, 7.0, seed=1)
    assert robust_sigma(x) == pytest.approx(7.0, rel=0.05)
    spiky = x.copy()
    spiky[:20] = 1e5   # a few huge outliers
    assert robust_sigma(spiky) == pytest.approx(robust_sigma(x), rel=0.02)
    assert np.std(spiky) > 100 * robust_sigma(spiky)   # whereas the plain std explodes
    assert robust_sigma(np.array([])) == 0.0
    assert robust_sigma(np.full(50, 3.0)) == 0.0


def test_excess_kurtosis_is_near_zero_for_gaussian_and_large_for_spiky():
    assert excess_kurtosis(_noise(50000, 1.0, seed=2)) == pytest.approx(0.0, abs=0.15)
    spiky = _noise(2000, 1.0, seed=3)
    spiky[::200] = 80.0
    assert excess_kurtosis(spiky) > 20.0
    uniform = _rng(4).uniform(-1, 1, 50000)
    assert excess_kurtosis(uniform) == pytest.approx(-1.2, abs=0.1)


def test_excess_kurtosis_degenerate_inputs_are_zero():
    assert excess_kurtosis(np.full(100, 5.0)) == 0.0
    assert excess_kurtosis(np.array([1.0, 2.0, 3.0])) == 0.0   # fewer than 4 samples
    assert excess_kurtosis(np.array([])) == 0.0


def test_saturation_fraction_is_zero_for_ordinary_noise():
    assert saturation_fraction(_noise(1000, 10.0), limit_uv=500.0) == 0.0
    assert saturation_fraction(np.array([]), limit_uv=500.0) == 0.0


def test_saturation_fraction_counts_samples_beyond_the_limit():
    x = _noise(1000, 5.0)
    x[:100] = 900.0
    assert saturation_fraction(x, limit_uv=500.0) >= 0.10


def test_saturation_fraction_ignores_a_static_electrode_offset():
    """The limit applies to the median-centred window: a big DC offset is normal."""
    assert saturation_fraction(_noise(1000, 5.0) + 50000.0, limit_uv=500.0) == 0.0


def test_saturation_fraction_counts_samples_near_the_adc_rail():
    """Samples within 0.1 % of full scale count, even when no plateau shape reveals them."""
    rail = 187500.0
    x = _noise(1000, 5.0)
    x[:50] = rail * (1.0 - 0.0005 * np.linspace(0.0, 1.0, 50))   # distinct values near +rail
    assert saturation_fraction(x, limit_uv=1e9) == 0.0
    assert saturation_fraction(x, limit_uv=1e9, adc_limit_uv=rail) >= 0.05
    x[50:100] = -rail * (1.0 - 0.0005 * np.linspace(0.0, 1.0, 50))
    assert saturation_fraction(x, limit_uv=1e9, adc_limit_uv=rail) >= 0.10


def test_saturation_fraction_detects_flat_topped_clipping_below_the_limit():
    clipped = np.clip(_tone(1000, FS, 7.0, 300.0) + _noise(1000, 0.5, seed=5), -150.0, 150.0)
    # Nothing exceeds the 5 000 µV limit; only the plateau shape reveals the clipping.
    assert saturation_fraction(clipped, limit_uv=5000.0) > 0.10
    unclipped = _tone(1000, FS, 7.0, 300.0) + _noise(1000, 0.5, seed=5)
    assert saturation_fraction(unclipped, limit_uv=5000.0) == 0.0


def test_saturation_fraction_is_a_share_between_zero_and_one():
    assert saturation_fraction(np.full(100, 1e6), limit_uv=10.0) <= 1.0
    x = np.concatenate([np.zeros(50), np.full(50, 1e6)])
    assert 0.0 <= saturation_fraction(x, limit_uv=10.0) <= 1.0


def test_mains_ratio_high_for_50_hz_hum_low_for_noise_and_other_line():
    n = 1000
    hum = _tone(n, FS, 50.0, 30.0) + _noise(n, 2.0, seed=6)
    assert mains_ratio(hum, FS, 50.0) > 0.9
    assert mains_ratio(hum, FS, 60.0) < 0.05   # the other line sees nothing
    assert mains_ratio(_noise(n, 10.0, seed=7), FS, 50.0) < 0.1


def test_mains_ratio_60_hz_and_scale_invariance():
    n = 1000
    hum = _tone(n, FS, 60.0, 30.0) + _noise(n, 2.0, seed=8)
    assert mains_ratio(hum, FS, 60.0) > 0.9
    assert mains_ratio(5.0 * hum, FS, 60.0) == pytest.approx(mains_ratio(hum, FS, 60.0), rel=1e-6)


def test_mains_ratio_ignores_dc_offset_and_slow_content():
    x = _noise(1000, 5.0, seed=9) + 40000.0
    assert mains_ratio(x, FS, 50.0) < 0.1


def test_mains_ratio_zero_when_line_is_unobservable():
    hum = _tone(512, 100.0, 40.0, 30.0)
    assert mains_ratio(hum, 100.0, 50.0) == 0.0     # 50 Hz is at Nyquist for fs = 100
    assert mains_ratio(np.ones(4), FS, 50.0) == 0.0   # too short
    assert mains_ratio(_noise(100), 0.0, 50.0) == 0.0   # non-positive fs
    assert mains_ratio(np.zeros(500), FS, 50.0) == 0.0   # no power at all


def test_mains_ratio_stays_in_unit_interval():
    r = mains_ratio(_tone(1000, FS, 50.0, 1000.0), FS, 50.0)
    assert 0.0 <= r <= 1.0


def test_drift_metrics_large_for_slow_wander_small_for_white_noise():
    n = 1000
    t = np.linspace(0, 1, n)
    wander = 200.0 * (t - 0.5) + _noise(n, 2.0, seed=10)
    ratio, p2p = drift_metrics(wander)
    assert ratio > 0.99
    assert p2p == pytest.approx(200.0, rel=0.05)
    ratio_n, _ = drift_metrics(_noise(n, 10.0, seed=11))
    assert ratio_n < 0.05


def test_drift_metrics_degenerate_inputs():
    assert drift_metrics(np.full(100, 7.0)) == (0.0, 0.0)
    assert drift_metrics(np.arange(10.0)) == (0.0, 0.0)   # fewer than 16 samples
    assert drift_metrics(np.array([])) == (0.0, 0.0)


def test_drift_metrics_ratio_in_unit_interval_and_offset_invariant():
    x = np.linspace(0, 80, 400) ** 1.0 + _noise(400, 1.0, seed=12)
    r1, p1 = drift_metrics(x)
    r2, p2 = drift_metrics(x + 12345.0)
    assert 0.0 <= r1 <= 1.0
    assert r2 == pytest.approx(r1, abs=1e-6)
    assert p2 == pytest.approx(p1, rel=1e-6)


def test_burst_fraction_zero_for_stationary_noise():
    assert burst_fraction(_noise(1000, 10.0, seed=13)) == 0.0


def test_burst_fraction_single_blink_touches_at_most_one_segment():
    x = _noise(1000, 5.0, seed=14)
    x[400:430] += 300.0 * np.hanning(30)
    assert burst_fraction(x) <= 2 / 8


def test_burst_fraction_sway_touches_many_segments():
    x = _noise(1000, 3.0, seed=15)
    seg = 1000 // 8
    for k in (1, 4, 6):   # three loud segments; the quiet majority keeps the median std low
        x[k * seg : (k + 1) * seg] *= 40.0
    assert burst_fraction(x) == pytest.approx(3 / 8)


def test_burst_fraction_short_window_returns_zero():
    assert burst_fraction(_noise(16)) == 0.0   # fewer than 3 usable segments
    assert burst_fraction(np.array([])) == 0.0


# --------------------------------------------------------------------------------------
# assess_channel: one window, one verdict
# --------------------------------------------------------------------------------------


def test_clean_noise_is_trusted_with_a_high_score_and_no_reasons():
    cq = assess_channel("Fp1", SignalKind.EEG, _noise(1000, 10.0), FS)
    assert cq.status is QualityStatus.GOOD
    assert cq.reasons == ()
    assert cq.score >= 0.75
    assert cq.name == "Fp1"


def test_constant_input_is_flagged_flatline_not_quiet_but_fine():
    for value in (0.0, 123.0, -50000.0):
        cq = assess_channel("c", SignalKind.EEG, np.full(1000, value), FS)
        assert cq.status is QualityStatus.BAD
        assert Reason.FLATLINE in cq.reasons
        assert cq.score < 0.25


def test_quiet_but_alive_channel_is_not_flatline():
    cq = assess_channel("c", SignalKind.EEG, _noise(1000, 3.0), FS)
    assert Reason.FLATLINE not in cq.reasons
    assert cq.status is QualityStatus.GOOD


def test_flatline_bad_has_no_spectral_metrics_but_reports_std():
    cq = assess_channel("c", SignalKind.EEG, np.zeros(1000), FS)
    assert "mains_ratio" not in cq.metrics
    assert cq.metrics["std_uv"] == 0.0


def test_mains_hum_raises_its_own_reason_at_50_and_60_hz():
    for hz in (50.0, 60.0):
        x = _tone(1000, FS, hz, 30.0) + _noise(1000, 3.0, seed=16)
        cq = assess_channel("c", SignalKind.EEG, x, FS)
        assert cq.status is QualityStatus.BAD
        assert Reason.MAINS in cq.reasons
        assert Reason.FLATLINE not in cq.reasons
        assert cq.metrics["mains_hz"] == hz


def test_moderate_hum_is_degraded_not_bad():
    # ~half the power in the line: between the degraded and bad ratios.
    x = _tone(1000, FS, 50.0, 14.0) + _noise(1000, 10.0, seed=17)
    cq = assess_channel("c", SignalKind.EEG, x, FS)
    assert cq.status is QualityStatus.DEGRADED
    assert Reason.MAINS in cq.reasons


def test_clipping_raises_saturation_reason():
    clipped = np.clip(_tone(1000, FS, 5.0, 1500.0) + _noise(1000, 1.0, seed=18), -500.0, 500.0)
    cq = assess_channel("emg", SignalKind.EMG, clipped, FS)
    assert cq.status is QualityStatus.BAD
    assert Reason.SATURATION in cq.reasons
    assert cq.metrics["saturation_frac"] >= 0.05


def test_adc_rail_raises_saturation_only_when_the_limit_is_configured():
    x = _noise(1000, 10.0, seed=19)
    x[:100] = 187500.0
    thr_off = QualityThresholds()
    thr_on = QualityThresholds(adc_limit_uv=187500.0, saturation_uv={})
    assert Reason.SATURATION in assess_channel("c", SignalKind.EEG, x, FS, thr_on).reasons
    # With the rail unknown the 500 µV limit still catches a 187 mV excursion.
    assert Reason.SATURATION in assess_channel("c", SignalKind.EEG, x, FS, thr_off).reasons


def test_slow_drift_raises_drift_reason():
    t = np.linspace(0, 1, 1000)
    x = 150.0 * np.sin(np.pi * t) + _noise(1000, 1.0, seed=20)   # one slow arch, EMG so noise is exempt
    cq = assess_channel("emg", SignalKind.EMG, x, FS)
    assert cq.status is QualityStatus.BAD
    assert Reason.DRIFT in cq.reasons


def test_small_slow_trend_cannot_trip_drift_on_a_quiet_channel():
    """The minimum peak-to-peak guard: a near-flat channel with a tiny trend is not drift."""
    t = np.linspace(0, 1, 1000)
    x = 10.0 * t + _noise(1000, 0.05, seed=21)   # trend explains ~all variance, but spans 10 µV
    ratio, p2p = drift_metrics(x)
    assert ratio > 0.97 and p2p < 50.0
    cq = assess_channel("emg", SignalKind.EMG, x, FS)
    assert Reason.DRIFT not in cq.reasons


def test_few_nans_degrade_many_nans_are_bad_and_all_nan_cannot_be_judged():
    x = _noise(1000, 10.0, seed=22)
    few = x.copy()
    few[:20] = np.nan   # 2 %
    cq = assess_channel("c", SignalKind.EEG, few, FS)
    assert cq.status is QualityStatus.DEGRADED and Reason.NONFINITE in cq.reasons
    many = x.copy()
    many[:200] = np.nan   # 20 %
    cq = assess_channel("c", SignalKind.EEG, many, FS)
    assert cq.status is QualityStatus.BAD and Reason.NONFINITE in cq.reasons
    cq = assess_channel("c", SignalKind.EEG, np.full(1000, np.nan), FS)
    assert cq.status is QualityStatus.BAD and Reason.NONFINITE in cq.reasons
    assert cq.score < 0.25


def test_infinite_samples_are_treated_like_nan_and_do_not_crash():
    x = _noise(1000, 10.0, seed=23)
    x[:300] = np.inf
    cq = assess_channel("c", SignalKind.EEG, x, FS)
    assert cq.status is QualityStatus.BAD
    assert Reason.NONFINITE in cq.reasons


def test_too_few_finite_samples_cannot_be_judged_and_is_bad():
    x = np.full(1000, np.nan)
    x[:5] = 1.0
    cq = assess_channel("c", SignalKind.EEG, x, FS)
    assert cq.status is QualityStatus.BAD
    assert Reason.NONFINITE in cq.reasons


def test_gap_fraction_maps_to_dropout_reason_by_severity():
    x = _noise(1000, 10.0, seed=24)
    assert Reason.DROPOUT not in assess_channel("c", SignalKind.EEG, x, FS, gap_fraction=0.0).reasons
    deg = assess_channel("c", SignalKind.EEG, x, FS, gap_fraction=0.05)
    assert deg.status is QualityStatus.DEGRADED and Reason.DROPOUT in deg.reasons
    bad = assess_channel("c", SignalKind.EEG, x, FS, gap_fraction=0.5)
    assert bad.status is QualityStatus.BAD and Reason.DROPOUT in bad.reasons


def test_blink_like_transients_are_not_a_quality_fault():
    """Blinks are what the detectors look for: heavy tails alone must not condemn a channel."""
    n = int(4 * FS)
    x = _noise(n, 5.0, seed=25)
    for centre in (int(0.8 * FS), int(2.0 * FS), int(3.2 * FS)):
        x += 250.0 * np.exp(-0.5 * ((np.arange(n) - centre) / (0.06 * FS)) ** 2)
    cq = assess_channel("Fp1", SignalKind.EEG, x, FS)
    assert cq.metrics["kurtosis"] > 3.0   # the transients really are heavy-tailed
    assert cq.status is not QualityStatus.BAD


def test_sustained_bursts_degrade_a_channel_but_never_make_it_bad():
    """Cable sway (bursts in many segments) is DEGRADED at worst: bursts overlap real events."""
    thr = QualityThresholds(burst_frac_degraded=0.3)
    x = _noise(1000, 3.0, seed=26)
    seg = 1000 // 8
    for k in (1, 4, 6):
        x[k * seg : (k + 1) * seg] *= 40.0   # sway in three of eight segments
    cq = assess_channel("c", SignalKind.EEG, x, FS, thr)
    assert cq.metrics["burst_frac"] >= 0.3
    assert cq.status is QualityStatus.DEGRADED
    assert cq.reasons == (Reason.NOISE,)
    # Even a window that is almost nothing but loud bursts cannot be condemned by bursts alone
    # while its robust (MAD) amplitude stays below the BAD limit.
    assert cq.metrics["noise_sigma_uv"] < thr.noise_sigma_uv[SignalKind.EEG][1]


def test_loud_broadband_noise_on_eeg_is_bad_but_exempt_on_emg():
    loud = _noise(1000, 300.0, seed=27)
    assert assess_channel("c", SignalKind.EEG, loud, FS).status is QualityStatus.BAD
    assert Reason.NOISE in assess_channel("c", SignalKind.EEG, loud, FS).reasons
    emg = assess_channel("c", SignalKind.EMG, loud, FS)
    assert Reason.NOISE not in emg.reasons
    assert "noise_sigma_uv" not in emg.metrics


def test_a_sustained_emg_burst_is_not_a_quality_problem():
    """A squeeze *is* a broadband burst, so EMG must stay trusted while the user squeezes."""
    x = _noise(1000, 5.0, seed=28)
    x[300:700] += _noise(400, 400.0, seed=29)
    cq = assess_channel("emg", SignalKind.EMG, x, FS)
    assert cq.status is QualityStatus.GOOD


def test_score_is_bounded_and_bands_match_status():
    cases = [
        _noise(1000, 10.0, seed=30),
        np.zeros(1000),
        _tone(1000, FS, 50.0, 14.0) + _noise(1000, 10.0, seed=17),
        _tone(1000, FS, 50.0, 30.0) + _noise(1000, 3.0, seed=16),
    ]
    for x in cases:
        cq = assess_channel("c", SignalKind.EEG, x, FS)
        assert 0.0 <= cq.score <= 1.0
        if cq.status is QualityStatus.GOOD:
            assert cq.score >= 0.75
        elif cq.status is QualityStatus.DEGRADED:
            assert 0.25 <= cq.score < 0.75
        else:
            assert cq.score < 0.25


def test_assess_channel_is_deterministic_and_does_not_mutate_input():
    x = _noise(1000, 10.0, seed=31)
    x[3] = np.nan
    before = x.copy()
    a = assess_channel("c", SignalKind.EEG, x, FS)
    b = assess_channel("c", SignalKind.EEG, x, FS)
    assert a == b
    np.testing.assert_array_equal(x, before)


def test_worst_reasons_are_listed_before_milder_ones():
    x = _noise(1000, 10.0, seed=32)
    x[:30] = np.nan   # 3 % -> degraded nonfinite
    cq = assess_channel("c", SignalKind.EEG, x, FS, gap_fraction=0.5)   # bad dropout
    assert cq.reasons[0] == Reason.DROPOUT
    assert Reason.NONFINITE in cq.reasons


def test_thresholds_validate_their_invariants():
    with pytest.raises(ValueError):
        QualityThresholds(window_s=0)
    with pytest.raises(ValueError):
        QualityThresholds(hop_s=-1)
    with pytest.raises(ValueError):
        QualityThresholds(window_s=2.0, min_fill_s=3.0)
    with pytest.raises(ValueError):
        QualityThresholds(recover_windows=0)
    with pytest.raises(ValueError):
        QualityThresholds(enter_windows=0)
    with pytest.raises(ValueError):
        QualityThresholds(flat_bad_uv=1.0, flat_degraded_uv=0.5)


def test_saturation_limit_is_infinite_for_a_kind_without_one():
    thr = QualityThresholds(saturation_uv={SignalKind.EEG: 100.0})
    assert thr.saturation_limit(SignalKind.EEG) == 100.0
    assert math.isinf(thr.saturation_limit(SignalKind.EMG))


# --------------------------------------------------------------------------------------
# suppress_events
# --------------------------------------------------------------------------------------


def test_suppress_events_is_true_for_none_and_for_bad_only():
    def rep(overall: QualityStatus) -> QualityReport:
        return QualityReport((), overall, ())

    assert suppress_events(None) is True
    assert suppress_events(rep(QualityStatus.BAD)) is True
    assert suppress_events(rep(QualityStatus.DEGRADED)) is False
    assert suppress_events(rep(QualityStatus.GOOD)) is False
    assert rep(QualityStatus.BAD).suppress_events is True
    assert rep(QualityStatus.GOOD).suppress_events is False


def test_report_score_is_mean_of_channels_and_zero_when_empty():
    assert QualityReport((), QualityStatus.BAD, ()).score == 0.0
    chans = (
        ChannelQuality("a", QualityStatus.GOOD, score=1.0),
        ChannelQuality("b", QualityStatus.DEGRADED, score=0.5),
    )
    rep = QualityReport(chans, QualityStatus.DEGRADED, ("a", "b"))
    assert rep.score == pytest.approx(0.75)
    assert rep.channel("b") is chans[1]
    assert rep.channel("zzz") is None


# --------------------------------------------------------------------------------------
# SignalQualityMonitor: warm-up and recovery
# --------------------------------------------------------------------------------------


def test_new_monitor_has_no_report_and_suppresses_events():
    mon = SignalQualityMonitor()
    assert mon.report is None
    assert mon.suppress_events is True
    assert suppress_events(mon.report) is True


def test_monitor_starts_bad_warming_up_and_suppresses_events():
    mon = SignalQualityMonitor()
    rep = mon.update(SampleBlock(_clean(0.5), FS, EEG1, t0=0.0))
    assert rep.overall is QualityStatus.BAD
    assert Reason.WARMING_UP in rep.reasons
    assert rep.channels[0].reasons == (Reason.WARMING_UP,)
    assert rep.usable_channels == ()
    assert rep.suppress_events is True
    assert mon.suppress_events is True


def test_warming_up_explain_says_collecting_not_a_fault():
    mon = SignalQualityMonitor()
    rep = mon.update(SampleBlock(_clean(0.5), FS, EEG1, t0=0.0))
    lines = explain(rep)
    assert len(lines) == 1
    assert "Collecting signal" in lines[0]


def test_warm_up_lasts_at_least_min_fill_then_good_noise_becomes_good():
    thr = QualityThresholds()
    mon = SignalQualityMonitor(thr)
    reports = _feed(mon, _clean(8.0), FS, EEG1)
    first_good = next(i for i, r in enumerate(reports) if r.overall is QualityStatus.GOOD)
    t_good = (first_good + 1) * 0.25   # end time of the block that produced it
    # Cannot be trusted before the window has filled and recover_windows clean checks passed.
    assert t_good >= thr.min_fill_s + (thr.recover_windows - 1) * thr.hop_s - 1e-9
    assert all(r.overall is QualityStatus.GOOD for r in reports[first_good:])
    assert reports[-1].usable_channels == ("Fp1",)
    assert reports[-1].suppress_events is False
    assert mon.suppress_events is False


def test_every_report_before_the_first_good_one_suppresses_events():
    reports = _feed(SignalQualityMonitor(), _clean(8.0), FS, EEG1)
    seen_good = False
    for r in reports:
        if r.overall is QualityStatus.GOOD:
            seen_good = True
        if not seen_good:
            assert r.suppress_events


def test_recovering_reason_and_explain_while_clean_windows_accumulate():
    mon = SignalQualityMonitor()
    reports = _feed(mon, _clean(2.3), FS, EEG1)   # just past min_fill: judged, not yet released
    rec = reports[-1]
    assert rec.overall is QualityStatus.BAD
    assert Reason.RECOVERING in rec.channels[0].reasons
    assert any("held back" in line for line in explain(rec))


def test_report_time_tracks_the_newest_sample():
    mon = SignalQualityMonitor()
    rep = mon.update(SampleBlock(_clean(1.0), FS, EEG1, t0=12.0))
    assert rep.t == pytest.approx(13.0)


def test_multichannel_good_noise_is_good_per_channel():
    chans = _chans(("Fp1", SignalKind.EEG), ("Fp2", SignalKind.EEG))
    mon = SignalQualityMonitor()
    reports = _feed(mon, _clean(8.0, n_ch=2), FS, chans)
    rep = reports[-1]
    assert rep.overall is QualityStatus.GOOD
    assert {c.name for c in rep.channels} == {"Fp1", "Fp2"}
    assert set(rep.usable_channels) == {"Fp1", "Fp2"}
    assert rep.score >= 0.75


def test_single_channel_1d_block_is_accepted():
    mon = SignalQualityMonitor()
    rep = None
    for i in range(32):
        chunk = _noise(62, 10.0, seed=100 + i)
        rep = mon.update(SampleBlock(chunk, FS, EEG1, t0=i * 62 / FS))
    assert rep is not None and rep.overall is QualityStatus.GOOD


def test_empty_block_does_not_change_the_verdict():
    mon, _ = _good_monitor()
    before = mon.report
    rep = mon.update(SampleBlock(np.empty((1, 0)), FS, EEG1, t0=6.0))
    assert rep is before
    # And on a brand-new monitor it yields a warm-up report rather than raising.
    fresh = SignalQualityMonitor().update(SampleBlock(np.empty((1, 0)), FS, EEG1, t0=0.0))
    assert fresh.overall is QualityStatus.BAD


def test_calls_between_hops_return_the_previous_report_object():
    mon, _ = _good_monitor()
    first = mon.update(SampleBlock(_noise(10, 10.0, seed=40)[None, :], FS, EEG1, t0=6.0))
    second = mon.update(SampleBlock(_noise(10, 10.0, seed=41)[None, :], FS, EEG1, t0=6.04))
    assert second is first   # 20 samples < one 0.25 s hop


def test_invalid_blocks_raise_value_error():
    mon = SignalQualityMonitor()
    with pytest.raises(ValueError):
        mon.update(SampleBlock(np.zeros((2, 100)), FS, EEG1))   # rows != channels
    with pytest.raises(ValueError):
        mon.update(SampleBlock(np.zeros((1, 100)), 0.0, EEG1))
    with pytest.raises(ValueError):
        mon.update(SampleBlock(np.zeros((1, 2, 100)), FS, EEG1))


# --------------------------------------------------------------------------------------
# SignalQualityMonitor: each fault is flagged
# --------------------------------------------------------------------------------------


def test_flatline_channel_goes_bad_with_plain_explanation():
    mon = SignalQualityMonitor()
    reports = _feed(mon, np.zeros((1, int(8 * FS))), FS, EEG1)
    rep = reports[-1]
    assert rep.overall is QualityStatus.BAD
    assert rep.channels[0].status is QualityStatus.BAD
    assert Reason.FLATLINE in rep.channels[0].reasons
    assert rep.suppress_events is True
    lines = explain(rep)
    text = " ".join(lines)
    assert "Fp1" in text and "flat" in text
    assert "not usable" in lines[0]
    # Plain language: machine reason codes must not leak into the sentences.
    for code in (Reason.FLATLINE, Reason.MAINS, Reason.NONFINITE, Reason.REQUIRED_MISSING):
        assert code not in text


def test_mains_hum_is_flagged_in_the_monitor_and_explained():
    x = _tone(int(8 * FS), FS, 50.0, 30.0)[None, :] + _clean(8.0, seed=3) * 0.3
    rep = _feed(SignalQualityMonitor(), x, FS, EEG1)[-1]
    assert rep.overall is QualityStatus.BAD
    assert Reason.MAINS in rep.channels[0].reasons
    assert any("50 Hz mains hum" in line for line in explain(rep))


def test_clipping_is_flagged_in_the_monitor():
    x = np.clip(_tone(int(8 * FS), FS, 5.0, 1500.0) + _noise(int(8 * FS), 1.0, seed=50), -500, 500)
    rep = _feed(SignalQualityMonitor(), x[None, :], FS, EMG1)[-1]
    assert rep.overall is QualityStatus.BAD
    assert Reason.SATURATION in rep.channels[0].reasons
    assert any("clipped" in line for line in explain(rep))


def test_drift_is_flagged_in_the_monitor():
    n = int(8 * FS)
    t = np.arange(n) / FS
    x = 150.0 * np.sin(2 * np.pi * 0.1 * t) + _noise(n, 1.0, seed=51)   # 0.1 Hz wander
    rep = _feed(SignalQualityMonitor(), x[None, :], FS, EMG1)[-1]
    assert Reason.DRIFT in rep.channels[0].reasons
    assert rep.overall is not QualityStatus.GOOD
    assert any("baseline" in line for line in explain(rep))


def test_nan_is_flagged_in_the_monitor_and_explained():
    x = _clean(8.0, seed=4)
    x[0, int(5 * FS) :] = np.nan
    rep = _feed(SignalQualityMonitor(), x, FS, EEG1)[-1]
    assert rep.overall is QualityStatus.BAD
    assert Reason.NONFINITE in rep.channels[0].reasons
    assert any("NaN" in line for line in explain(rep))


def test_dropout_gap_in_t0_is_flagged_and_reported_as_a_link_problem():
    mon, t = _good_monitor()
    # Lose 1 s of a 4 s window (25 %), above the 20 % "bad" fraction.
    rep = mon.update(SampleBlock(_clean(0.25, seed=60), FS, EEG1, t0=t + 1.0))
    assert rep.dropout_fraction == pytest.approx(0.25, abs=0.02)
    assert Reason.DROPOUT in rep.channels[0].reasons
    assert rep.overall is QualityStatus.BAD
    assert rep.suppress_events is True
    lines = explain(rep)
    assert any("data link is losing samples" in line for line in lines)


def test_short_dropout_degrades_but_does_not_condemn():
    mon, t = _good_monitor()
    rep = mon.update(SampleBlock(_clean(0.25, seed=61), FS, EEG1, t0=t + 0.25))   # 0.25 s of 4 s
    assert rep.channels[0].status is QualityStatus.DEGRADED
    assert Reason.DROPOUT in rep.channels[0].reasons
    assert rep.overall is QualityStatus.DEGRADED
    assert rep.suppress_events is False


def test_t0_jitter_below_tolerance_is_not_packet_loss():
    mon = SignalQualityMonitor()
    sig = _clean(8.0)
    reports = []
    for i in range(32):
        jitter = 0.005 * (1 if i % 2 else -1) if i else 0.0
        chunk = sig[:, i * 62 : (i + 1) * 62]
        reports.append(mon.update(SampleBlock(chunk, FS, EEG1, t0=i * 62 / FS + jitter)))
    assert reports[-1].dropout_fraction == 0.0
    assert reports[-1].overall is QualityStatus.GOOD


def test_gap_longer_than_the_window_makes_everything_stale_and_restarts_warm_up():
    mon, t = _good_monitor()
    rep = mon.update(SampleBlock(_clean(0.25, seed=62), FS, EEG1, t0=t + 30.0))
    assert rep.overall is QualityStatus.BAD
    assert rep.suppress_events is True
    # It then needs the full warm-up again before it trusts anything.
    reports = _feed(mon, _clean(6.0, seed=63), FS, EEG1, t_start=t + 30.25)
    assert reports[0].overall is QualityStatus.BAD
    assert reports[-1].overall is QualityStatus.GOOD


def test_t0_always_zero_disables_dropout_detection():
    """A source that never stamps t0 is treated as gap-free, not as one endless jump."""
    mon = SignalQualityMonitor()
    sig = _clean(8.0)
    reports = [
        mon.update(SampleBlock(sig[:, i : i + 62], FS, EEG1, t0=0.0))
        for i in range(0, sig.shape[1], 62)
    ]
    assert all(r.dropout_fraction == 0.0 for r in reports)
    assert all(Reason.DROPOUT not in r.channels[0].reasons for r in reports)
    assert reports[-1].overall is QualityStatus.GOOD


def test_overlapping_or_replayed_t0_is_not_counted_as_packet_loss():
    mon, t = _good_monitor()
    rep = mon.update(SampleBlock(_clean(0.25, seed=64), FS, EEG1, t0=t - 1.0))   # goes backwards
    assert rep.dropout_fraction == 0.0


def test_old_gaps_age_out_of_the_window():
    mon, t = _good_monitor()
    mon.update(SampleBlock(_clean(0.25, seed=65), FS, EEG1, t0=t + 0.25))   # one short gap
    t += 0.5
    reports = _feed(mon, _clean(8.0, seed=66), FS, EEG1, t_start=t)
    assert reports[0].dropout_fraction > 0.0
    assert reports[-1].dropout_fraction == 0.0
    assert reports[-1].overall is QualityStatus.GOOD


# --------------------------------------------------------------------------------------
# Montage-level rules
# --------------------------------------------------------------------------------------

TWO = _chans(("A", SignalKind.EEG), ("B", SignalKind.EEG))


def _two_channel_one_flat(seconds: float = 8.0) -> np.ndarray:
    data = _clean(seconds, n_ch=2)
    data[0, :] = 0.0   # channel A dead
    return data


def test_one_dead_channel_degrades_the_montage_but_keeps_the_good_one_usable():
    rep = _feed(SignalQualityMonitor(), _two_channel_one_flat(), FS, TWO)[-1]
    assert rep.overall is QualityStatus.DEGRADED
    assert rep.usable_channels == ("B",)
    assert rep.suppress_events is False
    assert rep.channel("A").status is QualityStatus.BAD
    assert rep.channel("B").status is QualityStatus.GOOD


def test_required_channel_unusable_forces_bad_and_is_explained():
    thr = QualityThresholds(required_channels=("A",))
    rep = _feed(SignalQualityMonitor(thr), _two_channel_one_flat(), FS, TWO)[-1]
    assert rep.overall is QualityStatus.BAD
    assert Reason.REQUIRED_MISSING in rep.reasons
    assert rep.missing_required == ("A",)
    assert rep.suppress_events is True
    assert any(line.startswith("Required channel(s) unusable: A") for line in explain(rep))


def test_required_channel_that_is_good_does_not_force_bad():
    thr = QualityThresholds(required_channels=("B",))
    rep = _feed(SignalQualityMonitor(thr), _two_channel_one_flat(), FS, TWO)[-1]
    assert rep.overall is QualityStatus.DEGRADED
    assert rep.missing_required == ()


def test_required_channel_absent_from_the_montage_forces_bad():
    thr = QualityThresholds(required_channels=("nonexistent",))
    rep = _feed(SignalQualityMonitor(thr), _clean(8.0), FS, EEG1)[-1]
    assert rep.overall is QualityStatus.BAD
    assert rep.missing_required == ("nonexistent",)


def test_too_few_usable_channels_forces_bad():
    thr = QualityThresholds(min_usable_channels=2)
    rep = _feed(SignalQualityMonitor(thr), _two_channel_one_flat(), FS, TWO)[-1]
    assert rep.overall is QualityStatus.BAD
    assert Reason.TOO_FEW_CHANNELS in rep.reasons
    assert any("Only 1 of 2 channel(s) are usable" in line for line in explain(rep))


def test_all_channels_bad_is_bad_by_default_min_usable():
    rep = _feed(SignalQualityMonitor(), np.zeros((2, int(8 * FS))), FS, TWO)[-1]
    assert rep.overall is QualityStatus.BAD
    assert rep.usable_channels == ()
    assert Reason.TOO_FEW_CHANNELS in rep.reasons


# --------------------------------------------------------------------------------------
# Hysteresis
# --------------------------------------------------------------------------------------


def test_entering_bad_needs_no_streak_but_does_not_trigger_on_a_tiny_glitch():
    mon, t = _good_monitor()
    nan_block = np.full((1, 62), np.nan)
    r1 = mon.update(SampleBlock(nan_block, FS, EEG1, t0=t))
    assert r1.overall is not QualityStatus.BAD   # 62/1000 samples: only degraded
    r2 = mon.update(SampleBlock(nan_block, FS, EEG1, t0=t + 62 / FS))
    # 124/1000 > 10 %: the very first evaluation past the bad limit enters BAD.
    assert r2.overall is QualityStatus.BAD
    assert r2.suppress_events is True


def test_leaving_bad_needs_recover_windows_extra_clean_evaluations():
    """A monitor that must see 3 clean checks releases exactly 2 hops after one that needs 1."""
    fs, block = 100.0, 25   # one block per 0.25 s hop

    def run(recover: int) -> int:
        thr = QualityThresholds(
            window_s=1.0, min_fill_s=1.0, hop_s=0.25, recover_windows=recover
        )
        mon = SignalQualityMonitor(thr)
        sig = np.concatenate(
            [_noise(200, 10.0, 70), np.zeros(200), _noise(400, 10.0, 71)]
        )[None, :]
        reports = _feed(mon, sig, fs, EEG1, block=block)
        flat_i = next(i for i, r in enumerate(reports) if Reason.FLATLINE in r.channels[0].reasons)
        assert reports[flat_i].overall is QualityStatus.BAD
        return next(i for i, r in enumerate(reports) if i > flat_i and r.overall is QualityStatus.GOOD)

    assert run(3) - run(1) == 2


def test_one_lucky_clean_window_does_not_release_a_bad_channel():
    """Period-5 pattern: four clean blocks then one NaN block leaves exactly one clean window."""
    fs, block = 100.0, 25

    def pattern() -> np.ndarray:
        blocks = []
        for k in range(30):
            b = _noise(block, 10.0, seed=200 + k)
            if k % 5 == 4:
                b = np.full(block, np.nan)
            blocks.append(b)
        return np.concatenate(blocks)[None, :]

    def ever_usable(recover: int) -> bool:
        thr = QualityThresholds(
            window_s=1.0, min_fill_s=1.0, hop_s=0.25, recover_windows=recover
        )
        reports = _feed(SignalQualityMonitor(thr), pattern(), fs, EEG1, block=block)
        return any(not r.suppress_events for r in reports)

    assert ever_usable(1) is True    # without hysteresis the lucky window releases it ...
    assert ever_usable(4) is False   # ... with it, the channel stays suppressed throughout


def test_good_channel_does_not_flap_on_a_borderline_window_when_enter_windows_is_two():
    thr = QualityThresholds(window_s=1.0, min_fill_s=1.0, hop_s=0.25, enter_windows=2)
    fs, block = 100.0, 25
    mon = SignalQualityMonitor(thr)
    _feed(mon, _clean(3.0, fs=fs, seed=80), fs, EEG1, block=block)
    assert mon.report is not None and mon.report.overall is QualityStatus.GOOD
    # One NaN block makes a single BAD window (25 % non-finite); with enter_windows=2 it is
    # held at DEGRADED instead of flipping to BAD.
    rep = mon.update(SampleBlock(np.full((1, block), np.nan), fs, EEG1, t0=3.0))
    assert rep.overall is QualityStatus.DEGRADED
    assert rep.suppress_events is False


def test_blink_in_a_running_stream_never_suppresses_events():
    mon = SignalQualityMonitor()
    n = int(10 * FS)
    x = _noise(n, 5.0, seed=90)
    for centre in (6.0, 7.5, 9.0):
        x += 250.0 * np.exp(-0.5 * ((np.arange(n) - centre * FS) / (0.06 * FS)) ** 2)
    reports = _feed(mon, x[None, :], FS, EEG1)
    tail = reports[int(6.0 / 0.25) :]   # after the monitor has released from warm-up
    assert all(r.overall is not QualityStatus.BAD for r in tail)


# --------------------------------------------------------------------------------------
# Resets, layout changes, block-size independence
# --------------------------------------------------------------------------------------


def test_changed_sampling_rate_resets_to_warm_up():
    mon, t = _good_monitor()
    rep = mon.update(SampleBlock(_clean(0.5, fs=500.0), 500.0, EEG1, t0=t))
    assert rep.overall is QualityStatus.BAD
    assert Reason.WARMING_UP in rep.reasons
    assert rep.suppress_events is True


def test_changed_channel_layout_resets_to_warm_up():
    mon, t = _good_monitor()
    for chans in (_chans(("Other", SignalKind.EEG)), _chans(("Fp1", SignalKind.EMG))):
        mon2, t = _good_monitor()
        rep = mon2.update(SampleBlock(_clean(0.5), FS, chans, t0=t))
        assert rep.overall is QualityStatus.BAD
        assert Reason.WARMING_UP in rep.reasons
        assert rep.channels[0].name == chans[0].name


def test_reset_forgets_everything():
    mon, _ = _good_monitor()
    mon.reset()
    assert mon.report is None
    assert mon.suppress_events is True
    rep = mon.update(SampleBlock(_clean(0.5), FS, EEG1, t0=0.0))
    assert Reason.WARMING_UP in rep.reasons


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda: _clean(12.0), id="clean"),
        pytest.param(lambda: np.zeros((1, int(12 * FS))), id="flatline"),
        pytest.param(
            lambda: _tone(int(12 * FS), FS, 50.0, 30.0)[None, :] + 0.3 * _clean(12.0, seed=5),
            id="mains",
        ),
    ],
)
def test_final_verdict_is_independent_of_block_size(make):
    data = make()
    finals = set()
    for block in (7, 62, 125, 250):   # at most one evaluation per call: keep blocks <= 1 s
        rep = _feed(SignalQualityMonitor(), data, FS, EEG1, block=block)[-1]
        finals.add((rep.overall, rep.channels[0].status, rep.channels[0].reasons))
    assert len(finals) == 1


def test_monitor_is_deterministic():
    data = _clean(8.0, seed=7)
    a = _feed(SignalQualityMonitor(), data, FS, EEG1)[-1]
    b = _feed(SignalQualityMonitor(), data, FS, EEG1)[-1]
    assert a == b


# --------------------------------------------------------------------------------------
# explain()
# --------------------------------------------------------------------------------------


def test_explain_good_report_is_one_reassuring_line():
    mon, _ = _good_monitor()
    lines = explain(mon.report)
    assert len(lines) == 1
    assert "good" in lines[0] and "1 channel" in lines[0]


def test_explain_degraded_report_says_degraded_not_unusable():
    mon, t = _good_monitor()
    rep = mon.update(SampleBlock(_clean(0.25, seed=61), FS, EEG1, t0=t + 0.25))
    lines = explain(rep)
    assert "degraded" in lines[0]
    assert "not usable" not in lines[0]


def test_explain_orders_the_worst_channel_first():
    chans = _chans(("ok_but_noisy", SignalKind.EEG), ("dead", SignalKind.EEG))
    data = _clean(8.0, n_ch=2)
    data[1, :] = 0.0
    x = np.zeros((2, data.shape[1]))
    x[0] = _tone(data.shape[1], FS, 50.0, 14.0) + _noise(data.shape[1], 10.0, seed=17)  # degraded
    x[1] = 0.0   # bad
    rep = _feed(SignalQualityMonitor(), x, FS, chans)[-1]
    lines = [ln for ln in explain(rep) if ln.startswith("channel ")]
    assert lines[0].startswith("channel dead")


def test_explain_never_raises_on_any_reason_combination():
    reasons = [
        Reason.FLATLINE, Reason.SATURATION, Reason.MAINS, Reason.DRIFT, Reason.NOISE,
        Reason.DROPOUT, Reason.NONFINITE, Reason.RECOVERING, Reason.WARMING_UP,
    ]
    chans = tuple(
        ChannelQuality(f"c{i}", QualityStatus.BAD, (r,), 0.1, {}) for i, r in enumerate(reasons)
    )
    rep = QualityReport(chans, QualityStatus.BAD, (), (Reason.TOO_FEW_CHANNELS,), ("c0",), 0.5)
    lines = explain(rep)
    assert all(isinstance(ln, str) and ln for ln in lines)
