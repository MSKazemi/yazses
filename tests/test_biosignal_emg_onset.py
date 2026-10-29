"""Properties of ``yazses.biosignal.emg_onset``: the one-muscle squeeze switch.

Signals are seeded white noise whose amplitude is scaled per segment (relaxed floor = 1x,
squeeze = Nx), calibrated through the detector's own ``bandlimited_rms``. Numpy only,
deterministic, offline."""

from __future__ import annotations

import math
from functools import lru_cache

import numpy as np
import pytest

from yazses.biosignal.emg_onset import (
    MIN_K_OFF,
    MIN_K_ON,
    STUCK_CLEAR_S,
    EmgOnsetDetector,
    GradedEmgDetector,
    OnsetState,
    OnsetThresholds,
    bandlimited_rms,
)
from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SampleBlock, SignalKind
from yazses.platform.emg.pressure import PressureThresholds, SqueezeLevel

SIGMA0 = 5.0  # relaxed-noise standard deviation (uV)
EMG1 = (ChannelInfo("emg0", SignalKind.EMG),)


def _noise_segments(fs: float, segs, seed: int = 0, offset: float = 0.0) -> np.ndarray:
    """Concatenate ``(seconds, amplitude_multiplier)`` segments of white noise, shape (1, n)."""
    rng = np.random.default_rng(seed)
    parts = [rng.normal(0.0, SIGMA0 * amp, int(round(dur * fs))) for dur, amp in segs]
    return np.concatenate(parts)[np.newaxis, :] + offset


@lru_cache(maxsize=None)
def _calibration(fs: float) -> tuple[float, float]:
    """(relaxed RMS, maximum-contraction RMS) measured on the detector's own band-pass."""
    rng = np.random.default_rng(1234)
    n = int(6 * fs)
    base = bandlimited_rms(rng.normal(0.0, SIGMA0, (1, n)), fs)
    mvc = bandlimited_rms(rng.normal(0.0, 10 * SIGMA0, (1, n)), fs)
    return base, mvc


def _thresholds(fs: float = 1000.0, **kw) -> OnsetThresholds:
    base, mvc = _calibration(fs)
    return OnsetThresholds.from_calibration(base, mvc, **kw)


def _feed(
    det,
    x: np.ndarray,
    fs: float = 1000.0,
    *,
    size: int | None = None,
    sizes: list[int] | None = None,
    t0: float = 0.0,
    channels=EMG1,
) -> list[BioEvent]:
    """Run ``x`` through ``det`` in blocks of ``size`` (or the explicit ``sizes``)."""
    n = x.shape[1]
    if sizes is None:
        step = size or n
        sizes = [step] * math.ceil(n / step)
    events: list[BioEvent] = []
    pos = 0
    for s in sizes:
        blk = SampleBlock(x[:, pos : pos + s], fs, channels, t0 + pos / fs)
        events.extend(det.process(blk))
        pos += s
    assert pos >= n
    return events


def _kinds(events) -> list[EventKind]:
    return [e.kind for e in events]


ON, OFF = EventKind.SQUEEZE_ON, EventKind.SQUEEZE_OFF


def _random_sizes(n: int, seed: int, max_size: int = 200) -> list[int]:
    rng = np.random.default_rng(seed)
    out: list[int] = []
    total = 0
    while total < n:
        s = min(int(rng.integers(0, max_size)), n - total)
        out.append(s)
        total += s
    return out


# ---------------------------------------------------------------------------
# OnsetThresholds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("baseline", [0.0, -1.0, float("nan"), float("inf")])
def test_thresholds_reject_bad_baseline(baseline):
    """The baseline must be positive and finite."""
    with pytest.raises(ValueError, match="baseline"):
        OnsetThresholds(baseline=baseline)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"k_off": 1.0},
        {"k_off": 0.5},
        {"k_on": 2.0, "k_off": 2.0},
        {"k_on": 1.5, "k_off": 2.0},
        {"min_burst_s": -0.1},
        {"merge_gap_s": -0.1},
        {"refractory_s": -0.1},
        {"max_hold_s": 0.04},
        {"max_hold_s": 0.01},
    ],
)
def test_thresholds_reject_inconsistent_values(kwargs):
    """Hysteresis needs k_on > k_off > 1, times are non-negative, max_hold > min_burst."""
    with pytest.raises(ValueError):
        OnsetThresholds(baseline=10.0, **kwargs)


def test_thresholds_defaults_are_valid_and_frozen():
    """Default values pass validation and the dataclass is immutable."""
    th = OnsetThresholds(baseline=10.0)
    assert th.k_on > th.k_off > 1.0
    with pytest.raises(AttributeError):
        th.baseline = 5.0  # type: ignore[misc]


def test_from_calibration_squares_rms_and_orders_levels():
    """baseline = rms^2; k_off < k_on; both respect their floors and the half-way cap."""
    th = OnsetThresholds.from_calibration(5.0, 50.0)
    assert th.baseline == pytest.approx(25.0)
    assert th.k_on >= MIN_K_ON
    assert th.k_off >= MIN_K_OFF
    assert th.k_off < th.k_on
    assert th.k_off <= 1.0 + 0.5 * (th.k_on - 1.0) + 1e-12


def test_from_calibration_passes_timing_parameters_through():
    """Timing keywords reach the thresholds unchanged."""
    th = OnsetThresholds.from_calibration(
        5.0, 50.0, min_burst_s=0.05, merge_gap_s=0.07, refractory_s=0.3, max_hold_s=9.0
    )
    assert (th.min_burst_s, th.merge_gap_s, th.refractory_s, th.max_hold_s) == (
        0.05, 0.07, 0.3, 9.0,
    )


def test_from_calibration_on_level_is_monotonic_in_mvc():
    """A stronger maximum contraction never lowers the absolute on-threshold."""
    levels = []
    for mvc in (20.0, 30.0, 50.0, 80.0, 150.0):
        th = OnsetThresholds.from_calibration(5.0, mvc)
        levels.append(th.k_on * th.baseline)
        assert th.k_on * th.baseline < mvc ** 2  # the on level is reachable
    assert levels == sorted(levels)


@pytest.mark.parametrize("mvc", [5.0, 4.0, 5.0 * 1.2, 5.0 * 1.5, 5.0 * math.sqrt(3.0)])
def test_from_calibration_refuses_mvc_not_clearly_above_baseline(mvc):
    """MVC at, below, or too close above the baseline cannot place thresholds."""
    with pytest.raises(ValueError, match="not clearly above"):
        OnsetThresholds.from_calibration(5.0, mvc)


@pytest.mark.parametrize(
    ("base", "mvc"),
    [(0.0, 10.0), (-1.0, 10.0), (float("nan"), 10.0), (5.0, 0.0), (5.0, float("inf")),
     (5.0, float("nan"))],
)
def test_from_calibration_rejects_non_positive_or_non_finite_input(base, mvc):
    """Non-positive or non-finite RMS values are refused with a ValueError."""
    with pytest.raises(ValueError):
        OnsetThresholds.from_calibration(base, mvc)


# ---------------------------------------------------------------------------
# bandlimited_rms
# ---------------------------------------------------------------------------


def test_bandlimited_rms_ignores_dc_and_scales_linearly():
    """The band-pass strips DC; RMS scales with amplitude; 1-D and 2-D agree."""
    fs = 1000.0
    x = np.random.default_rng(5).normal(0, 3.0, (1, 4000))
    r = bandlimited_rms(x, fs)
    assert bandlimited_rms(x + 5000.0, fs) == pytest.approx(r, rel=1e-3)
    assert bandlimited_rms(7.0 * x, fs) == pytest.approx(7.0 * r, rel=1e-9)
    assert bandlimited_rms(x[0], fs) == pytest.approx(r, rel=1e-12)
    assert bandlimited_rms(np.full((1, 3000), 99.0), fs) < 1e-6


def test_bandlimited_rms_edge_cases():
    """Empty input is 0.0; NaN/Inf are zeroed; band=None keeps the signal intact."""
    assert bandlimited_rms(np.empty((1, 0)), 1000.0) == 0.0
    x = np.random.default_rng(6).normal(0, 3.0, (1, 2000))
    x[0, 100] = np.nan
    x[0, 200] = np.inf
    assert math.isfinite(bandlimited_rms(x, 1000.0))
    y = np.full((1, 1000), 4.0)
    assert bandlimited_rms(y, 1000.0, band=None, skip_s=0.0) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"smooth_s": 0.0},
        {"smooth_s": -0.01},
        {"baseline_tau_s": 0.0},
        {"baseline_limits": (0.0, 4.0)},
        {"baseline_limits": (1.5, 4.0)},
        {"baseline_limits": (0.25, 0.9)},
    ],
)
def test_detector_constructor_validation(kwargs):
    """Bad smoothing, tau or baseline limits are refused at construction."""
    with pytest.raises(ValueError):
        EmgOnsetDetector(_thresholds(), **kwargs)


def test_graded_constructor_validation():
    """Negative level timing is refused."""
    levels = PressureThresholds(light=1.0, hard=2.0)
    with pytest.raises(ValueError):
        GradedEmgDetector(_thresholds(), levels, level_hold_s=-0.1)
    with pytest.raises(ValueError):
        GradedEmgDetector(_thresholds(), levels, level_settle_s=-0.1)


def test_initial_state():
    """A new detector is idle, inactive, at the calibrated baseline, with nothing rejected."""
    th = _thresholds()
    det = EmgOnsetDetector(th)
    assert det.state is OnsetState.IDLE
    assert not det.active
    assert det.baseline == th.baseline
    assert det.thresholds is th
    assert det.envelope_value == 0.0
    assert det.rejected_bursts == 0


# ---------------------------------------------------------------------------
# No phantom triggers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fs", [500.0, 1000.0, 2000.0])
def test_flatline_and_constant_offset_never_trigger(fs):
    """Constant input (zero or a large DC offset) never produces an event or leaves IDLE."""
    for level in (0.0, 1234.5, -800.0):
        det = EmgOnsetDetector(_thresholds(fs))
        events = _feed(det, np.full((1, int(10 * fs)), level), fs, size=137)
        assert events == []
        assert det.state is OnsetState.IDLE
        assert det.rejected_bursts == 0


@pytest.mark.parametrize("fs", [500.0, 1000.0, 2000.0])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_noise_at_the_calibrated_floor_never_triggers(fs, seed):
    """Relaxed noise at the calibration level, with or without a DC offset, is silent."""
    x = _noise_segments(fs, [(30.0, 1.0)], seed=seed, offset=300.0)
    det = EmgOnsetDetector(_thresholds(fs))
    assert _feed(det, x, fs, size=100) == []
    assert det.rejected_bursts == 0


def test_moderately_elevated_noise_below_the_on_level_is_silent():
    """Noise a little louder than the floor (but under the on level) stays silent."""
    fs = 1000.0
    x = _noise_segments(fs, [(20.0, 1.5)], seed=3)
    assert _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, size=64) == []


def test_modest_dc_step_does_not_trigger():
    """A 500 uV step in the electrode offset (the high-pass removes it) is not a squeeze."""
    fs = 1000.0
    x = _noise_segments(fs, [(3.0, 1.0)], seed=4)
    x = np.concatenate([x, x + 500.0], axis=1)
    det = EmgOnsetDetector(_thresholds(fs))
    assert _feed(det, x, fs, size=100) == []


def test_non_finite_samples_do_not_raise_or_trigger_on_relaxed_noise():
    """NaN/Inf in the data are neutralised: no exception and no event on relaxed noise."""
    fs = 1000.0
    x = _noise_segments(fs, [(6.0, 1.0)], seed=5)
    x[0, 2500] = np.nan
    x[0, 3000] = np.inf
    x[0, 3500] = -np.inf
    det = EmgOnsetDetector(_thresholds(fs))
    assert _feed(det, x, fs, size=250) == []


# ---------------------------------------------------------------------------
# A squeeze: ON/OFF pairing, ordering, latency window
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fs", [500.0, 1000.0, 2000.0])
def test_calibrated_burst_gives_exactly_one_ordered_on_off_pair(fs):
    """One real burst: SQUEEZE_ON then SQUEEZE_OFF, in order, around the true burst."""
    onset, dur = 2.0, 0.5
    x = _noise_segments(fs, [(onset, 1.0), (dur, 10.0), (1.5, 1.0)], seed=10)
    det = EmgOnsetDetector(_thresholds(fs))
    events = _feed(det, x, fs, size=50)
    assert _kinds(events) == [ON, OFF]
    on, off = events
    assert on.t < off.t
    # ON is confirmed after the onset but inside the burst, near the 35-125 ms window.
    assert onset + 0.03 <= on.t <= onset + 0.15
    assert onset + dur <= off.t <= onset + dur + 0.25
    assert off.detail["reason"] == "release"
    assert 0.0 <= on.confidence <= 1.0 and 0.0 <= off.confidence <= 1.0
    assert on.channel == "emg0"
    assert not det.active
    assert det.state in (OnsetState.REFRACTORY, OnsetState.IDLE)


@pytest.mark.parametrize("fs", [500.0, 1000.0, 2000.0])
def test_latency_estimate_is_inside_the_onset_window(fs):
    """detail['latency_ms'] is within the documented 35-125 ms window and matches reality."""
    onset = 2.0
    x = _noise_segments(fs, [(onset, 1.0), (0.4, 10.0), (1.0, 1.0)], seed=11)
    events = _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, size=64)
    on = events[0]
    assert 35.0 <= on.detail["latency_ms"] <= 125.0
    actual_ms = (on.t - onset) * 1000.0
    assert abs(actual_ms - on.detail["latency_ms"]) <= 40.0
    assert on.detail["onset_t"] <= on.t
    assert on.detail["peak_envelope"] >= on.detail["threshold"]


def test_event_details_are_self_consistent():
    """ON/OFF details expose thresholds, baseline, duration and the release edge."""
    fs = 1000.0
    th = _thresholds(fs)
    x = _noise_segments(fs, [(2.0, 1.0), (0.6, 10.0), (1.0, 1.0)], seed=12)
    on, off = _feed(EmgOnsetDetector(th), x, fs, size=100)
    assert on.detail["threshold"] == pytest.approx(th.k_on * on.detail["baseline"])
    assert off.detail["threshold"] == pytest.approx(th.k_off * off.detail["baseline"])
    assert off.detail["edge_t"] <= off.t
    assert off.detail["duration_s"] == pytest.approx(off.detail["edge_t"] - on.detail["onset_t"])
    assert 0.4 <= off.detail["duration_s"] <= 0.8


def test_events_are_never_emitted_during_the_settling_window():
    """Nothing is reported before settle_s has elapsed, even for a burst that starts at once."""
    fs = 1000.0
    x = _noise_segments(fs, [(0.05, 1.0), (1.5, 10.0), (1.0, 1.0)], seed=13)
    events = _feed(EmgOnsetDetector(_thresholds(fs), settle_s=0.5), x, fs, size=100)
    assert all(e.t > 0.5 for e in events)


def test_two_separated_bursts_give_two_pairs():
    """Bursts further apart than merge gap + refractory are separate squeezes."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.4, 10.0), (1.0, 1.0), (0.4, 10.0), (1.0, 1.0)], seed=14)
    events = _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, size=100)
    assert _kinds(events) == [ON, OFF, ON, OFF]
    assert [e.t for e in events] == sorted(e.t for e in events)


# ---------------------------------------------------------------------------
# Spike rejection, merge, hysteresis, refractory
# ---------------------------------------------------------------------------


def test_spike_shorter_than_the_minimum_burst_is_rejected_and_counted():
    """A 10 ms spike is not a contraction: no events, rejected_bursts counts it."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.01, 40.0), (1.5, 1.0)], seed=15)
    det = EmgOnsetDetector(_thresholds(fs))
    assert _feed(det, x, fs, size=64) == []
    assert det.rejected_bursts >= 1


def test_spike_rejection_count_accumulates_and_reset_clears_it():
    """Several spikes are each counted; reset() zeroes the counter."""
    fs = 1000.0
    segs = [(1.0, 1.0)]
    for _ in range(3):
        segs += [(0.01, 40.0), (1.0, 1.0)]
    det = EmgOnsetDetector(_thresholds(fs))
    assert _feed(det, _noise_segments(fs, segs, seed=16), fs, size=64) == []
    assert det.rejected_bursts >= 3
    det.reset()
    assert det.rejected_bursts == 0


def test_burst_just_longer_than_minimum_is_accepted_and_much_shorter_is_not():
    """Duration threshold behaves monotonically: 10 ms rejected, 150 ms accepted."""
    fs = 1000.0
    short = _noise_segments(fs, [(2.0, 1.0), (0.01, 10.0), (1.0, 1.0)], seed=17)
    longer = _noise_segments(fs, [(2.0, 1.0), (0.15, 10.0), (1.0, 1.0)], seed=17)
    assert _feed(EmgOnsetDetector(_thresholds(fs)), short, fs, size=64) == []
    assert _kinds(_feed(EmgOnsetDetector(_thresholds(fs)), longer, fs, size=64)) == [ON, OFF]


@pytest.mark.parametrize("dip", [0.02, 0.04])
def test_a_short_dip_inside_a_hold_does_not_split_the_squeeze(dip):
    """A dip shorter than merge_gap_s merges: still one ON/OFF pair."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.3, 10.0), (dip, 1.0), (0.3, 10.0), (1.0, 1.0)], seed=18)
    events = _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, size=64)
    assert _kinds(events) == [ON, OFF]
    # The merged squeeze lasts through both halves.
    assert events[1].t >= 2.0 + 0.3 + dip + 0.3


def test_a_long_dip_splits_the_squeeze_in_two():
    """A dip well beyond merge_gap_s + refractory gives two separate squeezes."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.3, 10.0), (0.3, 1.0), (0.3, 10.0), (1.0, 1.0)], seed=18)
    assert _kinds(_feed(EmgOnsetDetector(_thresholds(fs)), x, fs, size=64)) == [ON, OFF, ON, OFF]


def test_longer_merge_gap_merges_what_a_short_one_splits():
    """Raising merge_gap_s monotonically reduces the number of squeezes for a fixed dip."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.3, 10.0), (0.15, 1.0), (0.3, 10.0), (1.0, 1.0)], seed=19)
    counts = []
    for gap in (0.03, 0.06, 0.5):
        det = EmgOnsetDetector(_thresholds(fs, merge_gap_s=gap, refractory_s=0.0))
        counts.append(sum(e.kind is ON for e in _feed(det, x, fs, size=64)))
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 2 and counts[-1] == 1


def _tone_plus_floor(fs: float, segs, seed: int) -> np.ndarray:
    """A quiet noise floor plus a 100 Hz tone whose amplitude is set per ``(seconds, amplitude_uV)``.

    TKEO of ``A sin(wn)`` is the constant ``A^2 sin^2(w)``, so the envelope of a tone is
    almost deterministic, unlike that of noise (the floor is kept low so the noise-tone cross
    terms stay small). That makes "exactly between the off and on
    levels" testable without leaning on noise statistics.
    """
    rng = np.random.default_rng(seed)
    amp = np.concatenate([np.full(int(round(d * fs)), a) for d, a in segs])
    n = amp.size
    tone = amp * np.sin(2 * np.pi * 100.0 * np.arange(n) / fs)
    return (rng.normal(0.0, 0.3 * SIGMA0, n) + tone)[np.newaxis, :]


def _tone_amp_for(level_over_baseline: float, th: OnsetThresholds, fs: float) -> float:
    """Tone amplitude whose TKEO envelope is ``level_over_baseline`` x baseline (+ floor)."""
    w = 2 * np.pi * 100.0 / fs
    return math.sqrt(level_over_baseline * th.baseline / math.sin(w) ** 2)


def test_hysteresis_holds_between_the_off_and_on_levels():
    """A level between k_off and k_on does not start a squeeze, but does not end one."""
    fs = 1000.0
    th = _thresholds(fs)
    mid = 0.5 * (th.k_on + th.k_off)
    a_mid = _tone_amp_for(mid, th, fs)
    a_hi = _tone_amp_for(3 * th.k_on, th, fs)
    kw = {"adapt_baseline": False}
    mid_only = _tone_plus_floor(fs, [(2.0, 0.0), (3.0, a_mid), (1.0, 0.0)], seed=20)
    assert _feed(EmgOnsetDetector(th, **kw), mid_only, fs, size=64) == []
    held = _tone_plus_floor(fs, [(2.0, 0.0), (0.3, a_hi), (3.0, a_mid), (1.0, 0.0)], seed=20)
    events = _feed(EmgOnsetDetector(th, **kw), held, fs, size=64)
    assert _kinds(events) == [ON, OFF]
    assert events[1].t > 2.0 + 0.3 + 2.9  # held through the whole mid-level segment


def test_threshold_hugging_signal_does_not_chatter():
    """A steady level just above the on threshold gives one squeeze, not a flicker of many."""
    fs = 1000.0
    th = _thresholds(fs)
    a = _tone_amp_for(1.3 * th.k_on, th, fs)
    x = _tone_plus_floor(fs, [(2.0, 0.0), (5.0, a), (1.0, 0.0)], seed=21)
    events = _feed(EmgOnsetDetector(th, adapt_baseline=False), x, fs, size=64)
    assert _kinds(events) == [ON, OFF]


def test_refractory_delays_the_next_squeeze():
    """A second burst that begins during the hold-off only starts after refractory_s."""
    fs = 1000.0
    x = _noise_segments(
        fs, [(2.0, 1.0), (0.3, 10.0), (0.1, 1.0), (1.2, 10.0), (1.0, 1.0)], seed=21
    )
    refractory = 0.6
    with_ref = _feed(EmgOnsetDetector(_thresholds(fs, refractory_s=refractory)), x, fs, size=64)
    without = _feed(EmgOnsetDetector(_thresholds(fs, refractory_s=0.0)), x, fs, size=64)
    assert _kinds(with_ref) == [ON, OFF, ON, OFF]
    assert _kinds(without) == [ON, OFF, ON, OFF]
    assert with_ref[2].t - with_ref[1].t >= refractory - 1e-9
    assert with_ref[2].t > without[2].t


# ---------------------------------------------------------------------------
# Baseline adaptation
# ---------------------------------------------------------------------------


def test_baseline_is_frozen_during_a_hold_so_a_long_squeeze_does_not_end_itself():
    """With a fast baseline, a long squeeze still ends only when the muscle relaxes."""
    fs = 1000.0
    th = _thresholds(fs, max_hold_s=60.0)
    x = _noise_segments(fs, [(2.0, 1.0), (15.0, 10.0), (2.0, 1.0)], seed=22)
    det = EmgOnsetDetector(th, baseline_tau_s=0.2, baseline_limits=(0.25, 100.0))
    events = _feed(det, x[:, : int(10 * fs)], fs, size=100)
    assert _kinds(events) == [ON]
    assert det.active
    frozen = det.baseline
    on_baseline = events[0].detail["baseline"]
    assert frozen == pytest.approx(on_baseline, rel=1e-12)
    events += _feed(det, x[:, int(10 * fs) :], fs, size=100, t0=10.0)
    assert _kinds(events) == [ON, OFF]
    assert events[1].t >= 17.0


def test_baseline_follows_the_floor_only_while_idle_and_within_limits():
    """With adaptation on, a louder floor raises the baseline, clamped to limits * baseline."""
    fs = 1000.0
    th = _thresholds(fs)
    loud = _noise_segments(fs, [(40.0, 1.8)], seed=23)  # quiet enough to stay below k_on
    det = EmgOnsetDetector(th, baseline_tau_s=1.0)
    assert _feed(det, loud, fs, size=250) == []
    assert th.baseline * 1.5 < det.baseline <= th.baseline * 4.0
    pinned = EmgOnsetDetector(th, baseline_tau_s=1.0, baseline_limits=(0.25, 1.2))
    _feed(pinned, loud, fs, size=250)
    assert pinned.baseline == pytest.approx(1.2 * th.baseline)


def test_adapt_baseline_false_keeps_the_calibrated_baseline_exactly():
    """With adaptation off the baseline never moves; reset() restores it when it has."""
    fs = 1000.0
    th = _thresholds(fs)
    det = EmgOnsetDetector(th, adapt_baseline=False)
    _feed(det, _noise_segments(fs, [(8.0, 1.7)], seed=24), fs, size=100)
    assert det.baseline == th.baseline
    adaptive = EmgOnsetDetector(th, baseline_tau_s=0.5)
    _feed(adaptive, _noise_segments(fs, [(8.0, 1.7)], seed=24), fs, size=100)
    assert adaptive.baseline != th.baseline
    adaptive.reset()
    assert adaptive.baseline == th.baseline


# ---------------------------------------------------------------------------
# Max-hold watchdog and the stuck latch
# ---------------------------------------------------------------------------


def test_max_hold_forces_off_with_reason_then_stays_silent_while_stuck():
    """A never-releasing hold is ended by the watchdog; no re-trigger while it persists."""
    fs = 1000.0
    th = _thresholds(fs, max_hold_s=1.0)
    x = _noise_segments(fs, [(2.0, 1.0), (10.0, 10.0)], seed=25)
    det = EmgOnsetDetector(th)
    events = _feed(det, x, fs, size=128)
    assert _kinds(events) == [ON, OFF]
    on, off = events
    assert off.detail["reason"] == "max_hold"
    assert off.t - on.t == pytest.approx(th.max_hold_s, abs=0.05)
    assert off.confidence == 1.0
    assert det.state is OnsetState.STUCK
    assert not det.active


def test_stuck_latch_ignores_bursts_until_relaxed_for_stuck_clear_s():
    """After the watchdog the detector needs STUCK_CLEAR_S of relaxation before re-arming."""
    fs = 1000.0
    th = _thresholds(fs, max_hold_s=1.0)
    x = _noise_segments(
        fs,
        [
            (2.0, 1.0), (3.0, 10.0),          # stuck high: ON, then forced OFF
            (0.5 * STUCK_CLEAR_S, 1.0), (0.3, 10.0),  # relaxed too briefly: still latched
            (0.5 * STUCK_CLEAR_S, 1.0), (0.3, 10.0),  # still too brief
            (2.0 * STUCK_CLEAR_S, 1.0),               # long enough to clear
            (0.3, 10.0), (1.0, 1.0),                  # a real squeeze again
        ],
        seed=26,
    )
    events = _feed(EmgOnsetDetector(th), x, fs, size=100)
    reasons = [e.detail.get("reason") for e in events if e.kind is OFF]
    assert _kinds(events) == [ON, OFF, ON, OFF]
    assert reasons == ["max_hold", "release"]
    relaxed_until = 2.0 + 3.0 + 0.5 + 0.3 + 0.5 + 0.3 + STUCK_CLEAR_S
    assert events[2].t > relaxed_until


def test_permanently_stuck_signal_emits_a_single_pair_only():
    """A sensor that reads 'squeezed' forever produces one ON and one forced OFF, no more."""
    fs = 1000.0
    th = _thresholds(fs, max_hold_s=0.8)
    x = _noise_segments(fs, [(2.0, 1.0), (30.0, 10.0)], seed=27)
    events = _feed(EmgOnsetDetector(th), x, fs, size=500)
    assert _kinds(events) == [ON, OFF]


def test_reset_leaves_the_stuck_latch():
    """reset() returns a stuck detector to IDLE so it can trigger again."""
    fs = 1000.0
    th = _thresholds(fs, max_hold_s=0.5)
    det = EmgOnsetDetector(th)
    _feed(det, _noise_segments(fs, [(2.0, 1.0), (3.0, 10.0)], seed=28), fs, size=200)
    assert det.state is OnsetState.STUCK
    det.reset()
    assert det.state is OnsetState.IDLE
    again = _feed(det, _noise_segments(fs, [(2.0, 1.0), (0.3, 10.0), (1.0, 1.0)], seed=28), fs)
    assert _kinds(again) == [ON, OFF]


# ---------------------------------------------------------------------------
# Time gaps and reconfiguration
# ---------------------------------------------------------------------------


def test_forward_gap_in_t0_closes_an_open_squeeze():
    """Lost samples (t0 jumps forward) close the squeeze with reason 'gap'."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (1.5, 10.0)], seed=30)
    det = EmgOnsetDetector(_thresholds(fs))
    events = _feed(det, x, fs, size=100)
    assert _kinds(events) == [ON]
    assert det.active
    after = det.process(SampleBlock(_noise_segments(fs, [(0.1, 10.0)], seed=31), fs, EMG1, 3.5 + 5.0))
    assert _kinds(after) == [OFF]
    assert after[0].detail["reason"] == "gap"
    assert not det.active
    assert det.state is OnsetState.IDLE


def test_gap_makes_the_detector_wait_out_the_settle_window_again():
    """After a gap the filters restart and a continuing burst is only seen after the settle time."""
    fs = 1000.0
    det = EmgOnsetDetector(_thresholds(fs), settle_s=0.5)
    _feed(det, _noise_segments(fs, [(2.0, 1.0), (1.5, 10.0)], seed=32), fs, size=100)
    burst = _noise_segments(fs, [(0.3, 10.0)], seed=33)
    out = det.process(SampleBlock(burst, fs, EMG1, 100.0))
    assert [e.kind for e in out] == [OFF]
    out = det.process(SampleBlock(burst, fs, EMG1, 100.3))
    # The restarted stream began at t=100.0; the 0.5 s settle ends at 100.5, so the burst
    # that is still going is detected only after that, never inside the settle window.
    assert [e.kind for e in out] == [ON]
    assert out[0].t > 100.0 + 0.5


def test_contiguous_and_slightly_jittered_t0_is_not_a_gap():
    """Exactly contiguous t0, or jitter within 2.5 samples, never aborts the squeeze."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (1.2, 10.0)], seed=34)
    det = EmgOnsetDetector(_thresholds(fs))
    events: list[BioEvent] = []
    for k in range(0, x.shape[1], 100):
        jitter = 0.002 if (k // 100) % 2 else 0.0  # 2 ms = 2 samples
        events += det.process(SampleBlock(x[:, k : k + 100], fs, EMG1, k / fs + jitter))
    assert _kinds(events) == [ON]
    assert det.active


def test_changing_sampling_rate_closes_the_squeeze_with_reconfigure():
    """A different fs mid-stream is a reconfiguration: open squeeze closed, state restarted."""
    fs = 1000.0
    det = EmgOnsetDetector(_thresholds(fs))
    _feed(det, _noise_segments(fs, [(2.0, 1.0), (1.2, 10.0)], seed=35), fs, size=100)
    assert det.active
    out = det.process(
        SampleBlock(_noise_segments(500.0, [(0.5, 1.0)], seed=36), 500.0, EMG1, 3.2)
    )
    assert [e.kind for e in out] == [OFF]
    assert out[0].detail["reason"] == "reconfigure"
    assert det.state is OnsetState.IDLE


# ---------------------------------------------------------------------------
# Block-size independence, reset, channels
# ---------------------------------------------------------------------------


def _event_signature(events):
    return [(e.kind, e.detail.get("reason")) for e in events]


@pytest.mark.parametrize("fs", [500.0, 1000.0])
def test_event_times_are_block_size_independent(fs):
    """One block, 1-sample, prime and random-sized blocks (incl. empty) give the same events."""
    x = _noise_segments(
        fs, [(2.0, 1.0), (0.4, 10.0), (1.0, 1.0), (0.04, 1.0), (0.3, 10.0), (1.0, 1.0)],
        seed=40, offset=250.0,
    )
    n = x.shape[1]
    ref = _feed(EmgOnsetDetector(_thresholds(fs)), x, fs)
    assert _kinds(ref) == [ON, OFF, ON, OFF]
    variants = [
        _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, sizes=[1] * n),
        _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, size=7),
        _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, size=64),
        _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, size=997),
        _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, sizes=_random_sizes(n, 41)),
        _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, sizes=_random_sizes(n, 42, 30)),
    ]
    for got in variants:
        assert _event_signature(got) == _event_signature(ref)
        np.testing.assert_allclose([e.t for e in got], [e.t for e in ref], atol=1e-9)


def test_block_size_independence_with_a_spike_and_rejections():
    """Rejection counting and quiet output also match across splits."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.01, 40.0), (1.0, 1.0), (0.3, 10.0), (1.0, 1.0)], seed=43)
    a = EmgOnsetDetector(_thresholds(fs))
    b = EmgOnsetDetector(_thresholds(fs))
    ea = _feed(a, x, fs)
    eb = _feed(b, x, fs, sizes=_random_sizes(x.shape[1], 44))
    assert _event_signature(ea) == _event_signature(eb)
    assert a.rejected_bursts == b.rejected_bursts >= 1


def test_reset_clears_open_squeeze_and_reproduces_the_same_events():
    """After reset() the same stream yields identical events (same anchors, same baseline)."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.5, 10.0), (1.0, 1.0)], seed=45)
    det = EmgOnsetDetector(_thresholds(fs), baseline_tau_s=0.5)
    first = _feed(det, x, fs, size=100)
    _feed(det, _noise_segments(fs, [(1.0, 10.0)], seed=46), fs, size=100, t0=3.5)
    det.reset()
    assert det.state is OnsetState.IDLE and not det.active
    assert det.envelope_value == 0.0
    again = _feed(det, x, fs, size=100)
    assert _event_signature(again) == _event_signature(first)
    np.testing.assert_allclose([e.t for e in again], [e.t for e in first], atol=1e-9)


def test_empty_and_non_emg_blocks_are_ignored():
    """Empty blocks, blocks with no EMG row and blocks with fs <= 0 return nothing."""
    fs = 1000.0
    det = EmgOnsetDetector(_thresholds(fs))
    assert det.process(SampleBlock(np.empty((1, 0)), fs, EMG1, 0.0)) == []
    eeg = (ChannelInfo("f3", SignalKind.EEG),)
    burst = _noise_segments(fs, [(2.0, 1.0), (1.0, 20.0)], seed=47)
    assert _feed(det, burst, fs, size=100, channels=eeg) == []
    assert det.state is OnsetState.IDLE
    assert det.process(SampleBlock(burst[:, :10], 0.0, EMG1, 0.0)) == []


def test_only_emg_rows_are_read_in_a_mixed_block():
    """A burst on an EEG row is ignored; the same burst on the EMG row triggers."""
    fs = 1000.0
    quiet = _noise_segments(fs, [(4.0, 1.0)], seed=48)
    burst = _noise_segments(fs, [(2.0, 1.0), (0.5, 10.0), (1.5, 1.0)], seed=49)
    chans = (ChannelInfo("eeg", SignalKind.EEG), ChannelInfo("emg", SignalKind.EMG))
    loud_on_eeg = np.vstack([burst, quiet])
    loud_on_emg = np.vstack([quiet, burst])
    assert _feed(EmgOnsetDetector(_thresholds(fs)), loud_on_eeg, fs, size=100, channels=chans) == []
    events = _feed(EmgOnsetDetector(_thresholds(fs)), loud_on_emg, fs, size=100, channels=chans)
    assert _kinds(events) == [ON, OFF]
    assert events[0].channel == "emg"


def test_two_emg_channels_are_combined_and_named_together():
    """Two EMG rows are averaged: both loud triggers, and the event names both channels."""
    fs = 1000.0
    a = _noise_segments(fs, [(2.0, 1.0), (0.5, 10.0), (1.5, 1.0)], seed=50)
    b = _noise_segments(fs, [(2.0, 1.0), (0.5, 10.0), (1.5, 1.0)], seed=51)
    chans = (ChannelInfo("L", SignalKind.EMG), ChannelInfo("R", SignalKind.EMG))
    events = _feed(EmgOnsetDetector(_thresholds(fs)), np.vstack([a, b]), fs, size=100, channels=chans)
    assert _kinds(events) == [ON, OFF]
    assert events[0].channel == "L+R"


def test_no_band_runs_on_a_pre_filtered_signal():
    """band=None skips the internal band-pass (the caller already cleaned the signal)."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.5, 10.0), (1.5, 1.0)], seed=52)
    base = float(np.mean(np.abs(x[0, :2000] ** 2)))  # TKEO mean ~ variance for white noise
    th = OnsetThresholds(baseline=base, k_on=8.0, k_off=3.0)
    events = _feed(EmgOnsetDetector(th, band=None), x, fs, size=100)
    assert _kinds(events) == [ON, OFF]


# ---------------------------------------------------------------------------
# GradedEmgDetector
# ---------------------------------------------------------------------------


def _graded(fs: float = 1000.0, **kw) -> GradedEmgDetector:
    base, mvc = _calibration(fs)
    return GradedEmgDetector.from_calibration(base, mvc, **kw)


def test_graded_light_squeeze_reports_light_and_dictate_mode():
    """A burst between the light and hard levels is 'light' / 'full_text'."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.5, 5.0), (1.0, 1.0)], seed=60)
    det = _graded(fs)
    events = _feed(det, x, fs, size=100)
    assert _kinds(events) == [ON, OFF]
    assert events[0].detail["level"] == "light"
    assert events[0].detail["mode"] == "full_text"
    assert events[1].detail["level"] == "light"


def test_graded_hard_squeeze_reports_hard_and_command_mode():
    """A burst at the maximum contraction is 'hard' / 'command'."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.5, 10.0), (1.0, 1.0)], seed=61)
    events = _feed(_graded(fs), x, fs, size=100)
    assert _kinds(events) == [ON, OFF]
    assert events[0].detail["level"] == "hard"
    assert events[0].detail["mode"] == "command"
    assert events[1].detail["level"] == "hard"


def test_graded_off_reports_the_highest_level_reached():
    """A hold that starts light and escalates to hard ends with level 'hard'."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.25, 5.0), (0.5, 20.0), (1.0, 1.0)], seed=62)
    events = _feed(_graded(fs), x, fs, size=100)
    assert _kinds(events) == [ON, OFF]
    assert events[0].detail["level"] == "light"
    assert events[1].detail["level"] == "hard"


def test_graded_level_property_tracks_the_squeeze_and_returns_to_relaxed():
    """level is RELAXED at start, non-relaxed during a burst, RELAXED afterwards."""
    fs = 1000.0
    det = _graded(fs)
    assert det.level is SqueezeLevel.RELAXED
    _feed(det, _noise_segments(fs, [(2.0, 1.0), (1.0, 10.0)], seed=63), fs, size=100)
    assert det.level is SqueezeLevel.HARD
    _feed(det, _noise_segments(fs, [(1.5, 1.0)], seed=64), fs, size=100, t0=3.0)
    assert det.level is SqueezeLevel.RELAXED


def test_graded_burst_above_on_but_below_light_never_starts_dictation():
    """If the light level is out of reach, a burst that clears k_on is not confirmed."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.5, 10.0), (1.0, 1.0)], seed=65)
    plain = _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, size=100)
    assert _kinds(plain) == [ON, OFF]
    unreachable = PressureThresholds(light=1e12, hard=2e12)
    det = GradedEmgDetector(_thresholds(fs), unreachable)
    assert _feed(det, x, fs, size=100) == []
    assert det.rejected_bursts >= 1


def test_graded_squeeze_is_never_confirmed_earlier_than_the_plain_detector():
    """Waiting for the level can only delay SQUEEZE_ON, never advance it."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.5, 6.0), (1.0, 1.0)], seed=66)
    plain = _feed(EmgOnsetDetector(_thresholds(fs)), x, fs, size=100)
    graded = _feed(_graded(fs), x, fs, size=100)
    assert _kinds(graded) == _kinds(plain) == [ON, OFF]
    assert graded[0].t >= plain[0].t - 1e-9


def test_graded_level_settle_adds_latency():
    """level_settle_s delays confirmation by about that much (documented trade-off)."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.8, 10.0), (1.0, 1.0)], seed=67)
    fast = _feed(_graded(fs), x, fs, size=100)
    slow = _feed(_graded(fs, level_settle_s=0.1), x, fs, size=100)
    assert slow[0].t >= fast[0].t + 0.09
    assert slow[0].detail["latency_ms"] > fast[0].detail["latency_ms"]


def test_graded_is_block_size_independent_and_reset_restores_relaxed():
    """Level classification does not depend on the split; reset() clears the level."""
    fs = 1000.0
    x = _noise_segments(fs, [(2.0, 1.0), (0.25, 5.0), (0.5, 20.0), (1.0, 1.0)], seed=68)
    a = _feed(_graded(fs), x, fs)
    b = _feed(_graded(fs), x, fs, sizes=_random_sizes(x.shape[1], 69))
    assert [(e.kind, e.detail.get("level")) for e in a] == [
        (e.kind, e.detail.get("level")) for e in b
    ]
    np.testing.assert_allclose([e.t for e in a], [e.t for e in b], atol=1e-9)
    det = _graded(fs)
    _feed(det, _noise_segments(fs, [(2.0, 1.0), (1.0, 10.0)], seed=70), fs, size=100)
    det.reset()
    assert det.level is SqueezeLevel.RELAXED


def test_graded_flatline_is_silent():
    """No phantom trigger from a flatline in the graded detector either."""
    det = _graded(1000.0)
    assert _feed(det, np.full((1, 8000), 100.0), 1000.0, size=100) == []
    assert det.level is SqueezeLevel.RELAXED


def test_graded_from_calibration_uses_shared_units_and_forwards_kwargs():
    """Levels sit between the floor and the MVC (squared), ordered, and kwargs pass through."""
    base, mvc = 5.0, 50.0
    det = GradedEmgDetector.from_calibration(base, mvc, light_fraction=0.1, hard_fraction=0.5,
                                             smooth_s=0.05)
    th = det.thresholds
    assert th.baseline == pytest.approx(base ** 2)
    assert base ** 2 < det._levels.light < det._levels.hard < mvc ** 2
    assert det._smooth_s == 0.05
    with pytest.raises(ValueError):
        GradedEmgDetector.from_calibration(5.0, 5.0)
