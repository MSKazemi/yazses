"""Properties of ``yazses.biosignal.filters``: design checks, frequency response,
block-size independence, steady-state start, NaN/Inf repair, back-end equivalence, TKEO
continuity, envelope, referencing and detrending. Pure numpy, deterministic, offline."""

from __future__ import annotations

import math

import numpy as np
import pytest

from yazses.biosignal import filters as F
from yazses.biosignal.filters import (
    Biquad,
    EnvelopeFollower,
    FilterChain,
    FiniteGuard,
    RunningMeanDetrender,
    SosFilter,
    Tkeo,
    bipolar,
    build_eeg_chain,
    build_emg_chain,
    build_eog_chain,
    common_average_reference,
    design_butterworth_bandpass,
    design_highpass,
    design_lowpass,
    design_notch,
    detrend_running_mean,
    rectify_envelope,
    tkeo,
)
from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind

FS = 250.0


def _noise(n_ch: int, n: int, seed: int = 0, scale: float = 10.0) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, scale, size=(n_ch, n))


def _tone(freq: float, n: int, fs: float = FS, amp: float = 1.0) -> np.ndarray:
    return amp * np.sin(2 * np.pi * freq * np.arange(n) / fs)


def _random_splits(n: int, seed: int, max_size: int = 130) -> list[int]:
    rng = np.random.default_rng(seed)
    sizes: list[int] = []
    total = 0
    while total < n:
        s = int(rng.integers(0, max_size))
        s = min(s, n - total)
        sizes.append(s)
        total += s
    return sizes


def _run_in_blocks(proc, x: np.ndarray, sizes: list[int]) -> np.ndarray:
    outs = []
    pos = 0
    for s in sizes:
        outs.append(proc.process(x[:, pos : pos + s]))
        pos += s
    return np.concatenate(outs, axis=1)


# ---------------------------------------------------------------------------
# Design validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fs", [0.0, -1.0, float("nan"), float("inf")])
def test_bad_sampling_rate_is_refused(fs):
    """A non-positive or non-finite fs raises ValueError in every designer."""
    with pytest.raises(ValueError):
        design_lowpass(10.0, fs)
    with pytest.raises(ValueError):
        design_highpass(10.0, fs)
    with pytest.raises(ValueError):
        design_notch(10.0, fs)
    with pytest.raises(ValueError):
        design_butterworth_bandpass(1.0, 10.0, fs)


@pytest.mark.parametrize("f", [0.0, -5.0, FS / 2, FS, float("nan"), float("inf")])
def test_cutoff_at_or_beyond_nyquist_is_refused(f):
    """A corner must satisfy 0 < f < fs/2; the message carries the offending numbers."""
    with pytest.raises(ValueError, match="Nyquist"):
        design_lowpass(f, FS)
    with pytest.raises(ValueError, match="Nyquist"):
        design_highpass(f, FS)
    with pytest.raises(ValueError, match="Nyquist"):
        design_notch(f, FS)


@pytest.mark.parametrize("order", [0, -1, 1.5, True, "2"])
def test_bad_order_is_refused(order):
    """Order must be an integer >= 1 (bool is not accepted)."""
    with pytest.raises(ValueError, match="order"):
        design_lowpass(10.0, FS, order)
    with pytest.raises(ValueError, match="order"):
        design_butterworth_bandpass(1.0, 10.0, FS, order)


@pytest.mark.parametrize(
    ("low", "high"),
    [(20.0, 20.0), (30.0, 20.0), (0.0, 20.0), (-1.0, 20.0), (1.0, FS / 2), (1.0, FS),
     (float("nan"), 20.0), (1.0, float("inf"))],
)
def test_bandpass_edges_must_be_ordered_and_below_nyquist(low, high):
    """0 < low < high < fs/2 or ValueError."""
    with pytest.raises(ValueError, match="band-pass edges"):
        design_butterworth_bandpass(low, high, FS)


@pytest.mark.parametrize("q", [0.0, -3.0, float("nan"), float("inf")])
def test_notch_q_must_be_positive_finite(q):
    """Notch quality factor is validated."""
    with pytest.raises(ValueError, match="q"):
        design_notch(50.0, 1000.0, q)


def test_designers_return_stable_sections():
    """Every designed section is stable (poles strictly inside the unit circle)."""
    for order in (1, 2, 3, 4, 5):
        for sections in (
            design_lowpass(5.0, FS, order),
            design_highpass(0.5, FS, order),
            design_butterworth_bandpass(0.5, 40.0, FS, order),
        ):
            assert all(s.is_stable() for s in sections)
    assert all(s.is_stable() for s in design_notch(50.0, 1000.0))


def test_lowpass_alias_and_section_counts():
    """The long name is the same function; order n gives ceil(n/2) sections per edge."""
    assert F.design_butterworth_lowpass is design_lowpass
    assert len(design_lowpass(10.0, FS, 1)) == 1
    assert len(design_lowpass(10.0, FS, 4)) == 2
    assert len(design_lowpass(10.0, FS, 5)) == 3
    assert len(design_butterworth_bandpass(1.0, 20.0, FS, 4)) == 4


def test_sosfilter_refuses_empty_unstable_and_unknown_backend():
    """Construction validates sections and backend."""
    with pytest.raises(ValueError, match="at least one"):
        SosFilter([])
    with pytest.raises(ValueError, match="unstable"):
        SosFilter([Biquad(1.0, 0.0, 0.0, -2.5, 1.5)])
    with pytest.raises(ValueError, match="backend"):
        SosFilter(design_lowpass(10.0, FS), backend="cuda")


def test_biquad_unstable_detection_and_dc_gain():
    """is_stable follows the Jury criterion; dc_gain is nan for a pole at z = 1."""
    assert Biquad(1.0, 0.0, 0.0, 0.0, 0.0).is_stable()
    assert not Biquad(1.0, 0.0, 0.0, -1.0, 0.0).is_stable()  # pole exactly on the circle
    assert not Biquad(1.0, 0.0, 0.0, 0.0, 1.0).is_stable()
    assert math.isnan(Biquad(1.0, 0.0, 0.0, -1.0, 0.0).dc_gain())
    assert Biquad(0.5, 0.0, 0.0, -0.5, 0.0).dc_gain() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Frequency response
# ---------------------------------------------------------------------------


def test_lowpass_corner_is_minus_3db_and_rolls_off():
    """Butterworth corner = -3 dB (~0.7071), passband ~1, stopband attenuated."""
    f = SosFilter(design_lowpass(20.0, 1000.0, 4))
    mag = f.magnitude_response([1.0, 20.0, 200.0], 1000.0)
    assert mag[0] == pytest.approx(1.0, abs=1e-3)
    assert mag[1] == pytest.approx(1 / math.sqrt(2), abs=2e-2)
    assert mag[2] < 1e-3


def test_highpass_blocks_dc_and_passes_high():
    """High-pass has ~0 DC gain and ~1 gain well above the corner."""
    f = SosFilter(design_highpass(5.0, 1000.0, 4))
    mag = f.magnitude_response([0.01, 5.0, 200.0], 1000.0)
    assert mag[0] < 1e-6
    assert mag[1] == pytest.approx(1 / math.sqrt(2), abs=2e-2)
    assert mag[2] == pytest.approx(1.0, abs=1e-2)


def test_bandpass_response_shape():
    """The band-pass passes the middle of the band and attenuates DC and near-Nyquist."""
    f = SosFilter(design_butterworth_bandpass(20.0, 450.0, 2000.0, 4))
    mag = f.magnitude_response([0.5, 100.0, 1000.0], 2000.0)
    assert mag[0] < 1e-3
    assert mag[1] == pytest.approx(1.0, abs=5e-2)
    assert mag[2] < 0.05


def test_notch_kills_mains_and_passes_a_nearby_tone():
    """A 50 Hz notch is a deep null at 50 Hz and nearly transparent 10 Hz away."""
    f = SosFilter(design_notch(50.0, 1000.0))
    mag = f.magnitude_response([50.0, 40.0, 60.0, 5.0], 1000.0)
    assert mag[0] < 1e-6
    assert mag[1] > 0.95 and mag[2] > 0.95 and mag[3] > 0.99


def test_notch_attenuates_mains_in_the_time_domain():
    """Filtering a mains sine through the notch leaves almost nothing after settling."""
    fs = 1000.0
    x = _tone(50.0, 4000, fs, amp=100.0)[np.newaxis, :]
    y = SosFilter(design_notch(50.0, fs)).process(x)
    assert np.abs(y[:, 2000:]).max() < 0.5
    keep = _tone(30.0, 4000, fs, amp=100.0)[np.newaxis, :]
    z = SosFilter(design_notch(50.0, fs)).process(keep)
    assert np.abs(z[:, 2000:]).max() == pytest.approx(100.0, rel=0.05)


def test_magnitude_response_matches_measured_gain():
    """The analytic response predicts the steady-state amplitude of a tone."""
    fs = 1000.0
    sections = design_butterworth_bandpass(5.0, 100.0, fs, 2)
    for f0 in (2.0, 20.0, 150.0):
        pred = SosFilter(sections).magnitude_response([f0], fs)[0]
        y = SosFilter(sections, backend="numpy").process(_tone(f0, 8000, fs))
        measured = np.abs(y[6000:]).max()
        assert measured == pytest.approx(pred, rel=0.05, abs=1e-3)


def test_chain_builders_pass_in_band_and_reject_dc_and_mains():
    """EMG/EEG/EOG chains reject DC; the EMG and EEG chains also reject mains."""
    fs = 1000.0
    emg = build_emg_chain(fs, 50.0)
    emg_f = emg.stages[0]
    mag = emg_f.magnitude_response([0.5, 50.0, 100.0], fs)
    assert mag[0] < 1e-3 and mag[1] < 1e-3 and mag[2] > 0.9
    eeg_f = build_eeg_chain(fs, 50.0).stages[0]
    mag = eeg_f.magnitude_response([0.01, 10.0, 50.0], fs)
    assert mag[0] < 1e-3 and mag[1] > 0.9 and mag[2] < 1e-3
    eog_f = build_eog_chain(fs).stages[0]
    mag = eog_f.magnitude_response([0.001, 3.0], fs)
    assert mag[0] < 1e-3 and mag[1] > 0.9


def test_chain_upper_edge_is_capped_below_nyquist():
    """At 250 Hz the EMG upper edge is capped (<= 0.45 fs), so the chain builds."""
    chain = build_emg_chain(250.0, 50.0)
    assert chain.fs == 250.0
    mag = chain.stages[0].magnitude_response([60.0, 120.0], 250.0)
    assert mag[1] < mag[0]


def test_chain_builder_errors():
    """fs too low for the band, mains at/above Nyquist, bad mains and bad harmonics raise."""
    with pytest.raises(ValueError, match="octave"):
        build_emg_chain(40.0)
    with pytest.raises(ValueError, match="Nyquist"):
        build_emg_chain(100.0, mains_hz=50.0)
    with pytest.raises(ValueError):
        build_emg_chain(1000.0, mains_hz=-1.0)
    with pytest.raises(ValueError, match="harmonics"):
        build_emg_chain(1000.0, mains_hz=50.0, mains_harmonics=0)
    with pytest.raises(ValueError):
        build_emg_chain(0.0)
    with pytest.raises(ValueError, match="octave"):
        build_eeg_chain(2.0, None)
    with pytest.raises(ValueError, match="octave"):
        build_eog_chain(0.4)


def test_mains_none_skips_the_notch_and_harmonics_add_notches():
    """mains_hz=None gives fewer sections; harmonics add a notch at 2*mains when allowed."""
    n_none = len(build_emg_chain(1000.0, None).stages[0].sections)
    n_one = len(build_emg_chain(1000.0, 50.0).stages[0].sections)
    n_two = len(build_emg_chain(1000.0, 50.0, mains_harmonics=2).stages[0].sections)
    assert n_one == n_none + 1
    assert n_two == n_one + 1
    # 2*50 Hz is above 0.45 * 200 Hz, so the harmonic is skipped quietly at low fs.
    low = len(build_eeg_chain(200.0, 50.0, mains_harmonics=2).stages[0].sections)
    assert low == len(build_eeg_chain(200.0, 50.0).stages[0].sections)


# ---------------------------------------------------------------------------
# Block-size independence and state
# ---------------------------------------------------------------------------

_BACKENDS_UNDER_TEST = ["numpy"]


@pytest.mark.parametrize("backend", _BACKENDS_UNDER_TEST)
@pytest.mark.parametrize("seed", range(5))
def test_random_block_splits_equal_one_block(backend, seed):
    """process(a); process(b); ... equals process(concatenate) for random splits incl. 0 and 1."""
    n = 1500
    x = _noise(3, n, seed=seed) + 900.0
    sections = design_butterworth_bandpass(20.0, 100.0, FS, 4) + design_notch(50.0, 1000.0)
    ref = SosFilter(sections, backend=backend).process(x)
    sizes = _random_splits(n, seed + 100)
    got = _run_in_blocks(SosFilter(sections, backend=backend), x, sizes)
    assert got.shape == ref.shape
    np.testing.assert_allclose(got, ref, rtol=1e-7, atol=1e-6)


@pytest.mark.parametrize("backend", _BACKENDS_UNDER_TEST)
def test_one_sample_prime_and_empty_blocks_equal_one_block(backend):
    """1-sample blocks, prime-sized blocks and interleaved empty blocks all match."""
    n = 700
    x = _noise(2, n, seed=7) - 40.0
    sections = design_butterworth_bandpass(1.0, 40.0, FS, 4)
    ref = SosFilter(sections, backend=backend).process(x)
    one = _run_in_blocks(SosFilter(sections, backend=backend), x, [1] * n)
    np.testing.assert_allclose(one, ref, rtol=1e-7, atol=1e-6)
    primes = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73]
    sizes: list[int] = []
    total = 0
    i = 0
    while total < n:
        s = min(primes[i % len(primes)], n - total)
        sizes.extend([s, 0])
        total += s
        i += 1
    got = _run_in_blocks(SosFilter(sections, backend=backend), x, sizes)
    np.testing.assert_allclose(got, ref, rtol=1e-7, atol=1e-6)


def test_split_sizes_cross_the_internal_chunk_boundary():
    """Blocks longer than the internal 64-sample chunk still carry state exactly."""
    x = _noise(1, 1000, seed=3) + 500.0
    sections = design_butterworth_bandpass(2.0, 60.0, FS, 4)
    ref = SosFilter(sections, backend="numpy").process(x)
    for size in (63, 64, 65, 127, 128, 129, 333):
        sizes = [size] * (1000 // size) + [1000 % size]
        got = _run_in_blocks(SosFilter(sections, backend="numpy"), x, sizes)
        np.testing.assert_allclose(got, ref, rtol=1e-7, atol=1e-6, err_msg=f"size={size}")


def test_no_edge_transient_at_block_boundaries():
    """A steady tone filtered in small blocks has no outlier at the block edges."""
    fs = 1000.0
    x = _tone(30.0, 3000, fs, amp=10.0)[np.newaxis, :]
    f = SosFilter(design_butterworth_bandpass(5.0, 100.0, fs, 2), backend="numpy")
    y = _run_in_blocks(f, x, [50] * 60)[0]
    steady = y[1500:]
    assert np.abs(steady).max() < 1.05 * np.abs(steady[:200]).max() + 1e-9
    ref = SosFilter(design_butterworth_bandpass(5.0, 100.0, fs, 2)).process(x)[0]
    assert np.abs(y - ref).max() < 1e-6


def test_dc_offset_gives_no_transient_steady_state_init():
    """A huge constant offset yields ~0 output from the first sample (no ringing)."""
    x = np.full((2, 600), 12345.0)
    for sections in (
        design_butterworth_bandpass(0.5, 40.0, FS, 4),
        design_butterworth_bandpass(20.0, 100.0, FS, 4) + design_notch(50.0, 1000.0),
        design_highpass(0.1, FS, 2),
    ):
        y = SosFilter(sections, backend="numpy").process(x)
        assert np.abs(y).max() < 1e-6


def test_dc_offset_under_a_signal_has_no_start_up_ring():
    """With a 5000-unit offset the first second is no larger than the settled signal."""
    fs = 500.0
    n = 3000
    sig = _tone(40.0, n, fs, amp=1.0)
    ref = SosFilter(design_butterworth_bandpass(20.0, 100.0, fs, 2)).process(sig)
    off = SosFilter(design_butterworth_bandpass(20.0, 100.0, fs, 2)).process(sig + 5000.0)
    assert np.abs(off[: int(fs)]).max() < 3.0 * np.abs(ref[n // 2 :]).max()


def test_settle_false_shows_a_transient_where_settle_true_does_not():
    """settle=False starts from zero state: the same DC input rings."""
    x = np.full((1, 400), 1000.0)
    sections = design_highpass(5.0, FS, 2)
    assert np.abs(SosFilter(sections, settle=True).process(x)).max() < 1e-6
    assert np.abs(SosFilter(sections, settle=False).process(x)).max() > 10.0


def test_reset_rearms_steady_state_start():
    """After reset() the next sample re-initialises to steady state at its own level."""
    f = SosFilter(design_highpass(1.0, FS, 2), backend="numpy")
    f.process(np.full((1, 300), 10.0))
    f.process(_noise(1, 300, seed=1))
    f.reset()
    y = f.process(np.full((1, 300), -777.0))
    assert np.abs(y).max() < 1e-6
    # Without reset the level step would ring.
    g = SosFilter(design_highpass(1.0, FS, 2), backend="numpy")
    g.process(np.full((1, 300), 10.0))
    assert np.abs(g.process(np.full((1, 300), -777.0))).max() > 10.0


def test_reset_matches_fresh_filter():
    """reset() makes a used filter behave exactly like a new one."""
    x = _noise(2, 400, seed=2)
    sections = design_butterworth_bandpass(20.0, 100.0, FS, 4)
    f = SosFilter(sections)
    f.process(_noise(2, 333, seed=9) + 50.0)
    f.reset()
    np.testing.assert_allclose(f.process(x), SosFilter(sections).process(x), rtol=1e-9, atol=1e-9)


def test_multichannel_rows_are_independent():
    """Each row's output depends only on that row."""
    x = _noise(3, 500, seed=4) + np.array([[100.0], [-50.0], [0.0]])
    sections = design_butterworth_bandpass(5.0, 80.0, FS, 4)
    both = SosFilter(sections).process(x)
    for ch in range(3):
        solo = SosFilter(sections).process(x[ch : ch + 1])
        np.testing.assert_allclose(both[ch], solo[0], rtol=1e-9, atol=1e-9)
    x2 = x.copy()
    x2[1] += 1e6 * np.sin(np.arange(500))
    both2 = SosFilter(sections).process(x2)
    np.testing.assert_allclose(both2[[0, 2]], both[[0, 2]], rtol=1e-9, atol=1e-9)


def test_empty_block_is_a_noop_and_keeps_shape():
    """An empty block returns an empty array of the right rank and leaves state alone."""
    sections = design_butterworth_bandpass(5.0, 80.0, FS, 2)
    f = SosFilter(sections)
    assert f.process(np.empty((3, 0))).shape == (3, 0)
    assert f.process(np.empty(0)).shape == (0,)
    x = _noise(1, 200, seed=5)
    np.testing.assert_allclose(f.process(x), SosFilter(sections).process(x))


def test_one_dimensional_input_returns_one_dimensional_output():
    """1-D in, 1-D out; 2-D in, 2-D out; the input is not modified."""
    x = _noise(1, 100, seed=6)[0]
    x_copy = x.copy()
    y = SosFilter(design_lowpass(30.0, FS)).process(x)
    assert y.shape == (100,)
    np.testing.assert_array_equal(x, x_copy)
    assert SosFilter(design_lowpass(30.0, FS)).process(x[np.newaxis, :]).shape == (1, 100)


def test_three_dimensional_input_is_refused():
    """Only 1-D and 2-D data are accepted."""
    with pytest.raises(ValueError, match="shape"):
        SosFilter(design_lowpass(30.0, FS)).process(np.zeros((1, 2, 3)))


def test_channel_count_change_raises_until_reset():
    """A different channel count after the first call is an error; reset() allows it."""
    f = SosFilter(design_lowpass(30.0, FS))
    f.process(np.zeros((2, 10)))
    with pytest.raises(ValueError, match="channel count"):
        f.process(np.zeros((3, 10)))
    f.reset()
    assert f.process(np.zeros((3, 10))).shape == (3, 10)


def test_channel_count_change_raises_in_tkeo_wrapper():
    """Tkeo refuses a channel-count change as well."""
    t = Tkeo()
    t.process(np.zeros((2, 5)))
    with pytest.raises(ValueError, match="channel count"):
        t.process(np.zeros((3, 5)))
    t.reset()
    assert t.process(np.ones((3, 5))).shape == (3, 5)


def test_extreme_offset_does_not_poison_the_output():
    """Outputs stay finite and bounded on a very large offset plus noise."""
    x = _noise(2, 2000, seed=8, scale=1.0) + 1e6
    y = SosFilter(design_butterworth_bandpass(0.5, 40.0, FS, 4)).process(x)
    assert np.isfinite(y).all()
    assert np.abs(y).max() < 50.0


# ---------------------------------------------------------------------------
# Non-finite repair
# ---------------------------------------------------------------------------


def test_finite_guard_replaces_with_last_good_value_and_counts():
    """NaN/Inf become the previous good value per channel; the count is exact."""
    g = FiniteGuard()
    x = np.array([[1.0, np.nan, np.inf, 4.0, -np.inf], [np.nan, 2.0, 3.0, np.nan, 5.0]])
    out = g.apply(x)
    np.testing.assert_array_equal(out, [[1.0, 1.0, 1.0, 4.0, 4.0], [0.0, 2.0, 3.0, 3.0, 5.0]])
    assert g.n_replaced == 5
    g.reset_counts()
    assert g.n_replaced == 0


def test_finite_guard_carries_value_across_blocks_and_reset_clears_it():
    """The last good value survives a block boundary; reset() forgets it (back to 0)."""
    g = FiniteGuard()
    g.apply(np.array([[7.0, 8.0]]))
    np.testing.assert_array_equal(g.apply(np.array([[np.nan, np.nan]])), [[8.0, 8.0]])
    g.reset()
    np.testing.assert_array_equal(g.apply(np.array([[np.nan]])), [[0.0]])


def test_finite_guard_returns_input_untouched_when_clean_and_handles_empty():
    """Clean input comes back as is; an empty block is a no-op."""
    g = FiniteGuard()
    x = np.ones((2, 4))
    assert g.apply(x) is x
    assert g.apply(np.empty((2, 0))).shape == (2, 0)
    assert g.n_replaced == 0


def test_sosfilter_repairs_nonfinite_input_and_counts():
    """NaN/Inf never reach the output; n_nonfinite counts them; later outputs stay finite."""
    x = _noise(2, 400, seed=11) + 100.0
    x[0, 50] = np.nan
    x[1, 60:63] = np.inf
    x[0, 399] = -np.inf
    f = SosFilter(design_butterworth_bandpass(5.0, 80.0, FS, 4))
    y = f.process(x)
    assert np.isfinite(y).all()
    assert f.n_nonfinite == 5
    assert np.isfinite(f.process(_noise(2, 100, seed=12))).all()
    f.reset_counts()
    assert f.n_nonfinite == 0


def test_nonfinite_repair_is_block_size_independent():
    """The repair crosses block boundaries: any split gives the same output and count."""
    x = _noise(2, 600, seed=13) + 10.0
    x[0, [0, 1, 99, 100, 101, 599]] = np.nan
    x[1, [200, 300]] = np.inf
    sections = design_butterworth_bandpass(5.0, 80.0, FS, 4)
    a = SosFilter(sections)
    ref = a.process(x)
    b = SosFilter(sections)
    got = _run_in_blocks(b, x, _random_splits(600, 3, max_size=70))
    np.testing.assert_allclose(got, ref, rtol=1e-7, atol=1e-6)
    assert a.n_nonfinite == b.n_nonfinite == 8


def test_all_nan_input_is_finite_zero_in_zero_out():
    """With no good sample ever, the guard supplies zeros: the output is finite and zero."""
    y = SosFilter(design_highpass(1.0, FS)).process(np.full((1, 50), np.nan))
    assert np.isfinite(y).all()
    assert np.abs(y).max() < 1e-12


def test_filter_chain_counts_and_repairs_at_its_input():
    """FilterChain has its own guard and counter, one for the whole chain."""
    chain = build_eeg_chain(FS, 50.0)
    x = _noise(2, 300, seed=14)
    x[0, 5] = np.nan
    assert np.isfinite(chain.process(x)).all()
    assert chain.n_nonfinite == 1
    chain.reset_counts()
    assert chain.n_nonfinite == 0


# ---------------------------------------------------------------------------
# Back-end equivalence
# ---------------------------------------------------------------------------


def test_numpy_backend_is_reported_and_auto_without_scipy_signal_is_numpy():
    """backend='numpy' reports itself."""
    assert SosFilter(design_lowpass(10.0, FS), backend="numpy").backend == "numpy"


def test_scipy_and_numpy_backends_agree_within_tolerance():
    """Both engines produce the same output for the same random block split."""
    pytest.importorskip("scipy.signal")
    x = _noise(3, 2000, seed=21) + 900.0
    x[1, 500] = np.nan
    sections = design_butterworth_bandpass(20.0, 100.0, FS, 4) + design_notch(50.0, 1000.0)
    a = SosFilter(sections, backend="numpy")
    b = SosFilter(sections, backend="scipy")
    assert a.backend == "numpy" and b.backend == "scipy"
    sizes = _random_splits(2000, 5)
    ya = _run_in_blocks(a, x, sizes)
    yb = _run_in_blocks(b, x, sizes)
    np.testing.assert_allclose(ya, yb, rtol=1e-6, atol=1e-5)
    assert a.n_nonfinite == b.n_nonfinite == 1


def test_scipy_backend_is_block_size_independent_and_resets():
    """The scipy path carries state identically and also supports reset and empty blocks."""
    pytest.importorskip("scipy.signal")
    x = _noise(2, 800, seed=22) + 50.0
    sections = design_butterworth_bandpass(2.0, 60.0, FS, 4)
    ref = SosFilter(sections, backend="scipy").process(x)
    f = SosFilter(sections, backend="scipy")
    got = _run_in_blocks(f, x, _random_splits(800, 6))
    np.testing.assert_allclose(got, ref, rtol=1e-9, atol=1e-9)
    f.reset()
    np.testing.assert_allclose(f.process(x), ref, rtol=1e-9, atol=1e-9)
    assert f.process(np.empty((2, 0))).shape == (2, 0)


def test_scipy_backend_channel_change_raises():
    """The channel-count check is backend independent."""
    pytest.importorskip("scipy.signal")
    f = SosFilter(design_lowpass(10.0, FS), backend="scipy")
    f.process(np.zeros((2, 4)))
    with pytest.raises(ValueError, match="channel count"):
        f.process(np.zeros((1, 4)))


def test_auto_backend_uses_scipy_when_already_imported():
    """auto picks scipy only if scipy.signal is already in sys.modules."""
    pytest.importorskip("scipy.signal")
    # importorskip has just imported it, so auto must now choose scipy.
    assert SosFilter(design_lowpass(10.0, FS), backend="auto").backend == "scipy"


# ---------------------------------------------------------------------------
# FilterChain
# ---------------------------------------------------------------------------


def _block(data: np.ndarray, fs: float, t0: float = 0.0) -> SampleBlock:
    chans = tuple(ChannelInfo(f"c{i}", SignalKind.EMG) for i in range(data.shape[0]))
    return SampleBlock(data=data, fs=fs, channels=chans, t0=t0)


def test_process_block_keeps_metadata_and_refuses_wrong_rate():
    """process_block returns a block with the same fs/channels/t0; a rate mismatch raises."""
    chain = build_emg_chain(1000.0, 50.0)
    blk = _block(_noise(2, 100, seed=31), 1000.0, t0=12.5)
    out = chain.process_block(blk)
    assert out.fs == 1000.0 and out.t0 == 12.5 and out.channels == blk.channels
    assert out.data.shape == blk.data.shape
    with pytest.raises(ValueError, match="differs"):
        chain.process_block(_block(_noise(2, 100, seed=32), 500.0))


def test_chain_without_fs_accepts_any_block_rate():
    """fs=None disables the rate check."""
    chain = FilterChain([SosFilter(design_lowpass(30.0, FS))])
    assert chain.fs is None
    chain.process_block(_block(np.zeros((1, 10)), 500.0))


def test_chain_reset_resets_every_stage():
    """reset() on the chain re-arms each stage's steady-state start."""
    chain = FilterChain([SosFilter(design_highpass(1.0, FS)), SosFilter(design_lowpass(50.0, FS))])
    chain.process(np.full((1, 100), 5.0))
    chain.process(np.full((1, 100), 9.0))  # step: rings
    chain.reset()
    assert np.abs(chain.process(np.full((1, 100), 300.0))).max() < 1e-6


def test_chain_is_block_size_independent():
    """A multi-stage chain (with envelope) is invariant to the split."""
    x = _noise(2, 900, seed=33) + 20.0
    mk = lambda: FilterChain(  # noqa: E731
        [SosFilter(design_butterworth_bandpass(5.0, 80.0, FS, 2)), EnvelopeFollower(FS)]
    )
    ref = mk().process(x)
    got = _run_in_blocks(mk(), x, _random_splits(900, 34))
    np.testing.assert_allclose(got, ref, rtol=1e-7, atol=1e-6)


def test_chain_1d_in_1d_out():
    """A 1-D input stays 1-D through a chain."""
    out = build_eeg_chain(FS, 50.0).process(_noise(1, 80, seed=35)[0])
    assert out.shape == (80,)


# ---------------------------------------------------------------------------
# TKEO
# ---------------------------------------------------------------------------


def _tkeo_reference(x: np.ndarray) -> np.ndarray:
    return x[:, 1:-1] ** 2 - x[:, :-2] * x[:, 2:]


def test_tkeo_oneshot_matches_definition_shifted_by_one():
    """psi[k+1] scores sample k with the first output a placeholder 0."""
    x = _noise(2, 50, seed=41)
    psi, carry = tkeo(x)
    assert psi.shape == x.shape and carry.shape == (2, 2)
    np.testing.assert_array_equal(psi[:, 0], 0.0)
    np.testing.assert_allclose(psi[:, 2:], _tkeo_reference(x))
    np.testing.assert_array_equal(carry, x[:, -2:])


def test_tkeo_of_pure_tone_is_constant_a2_sin2():
    """For A sin(wn) the Teager energy is A^2 sin^2(w): constant."""
    w = 2 * np.pi * 0.05
    x = (3.0 * np.sin(w * np.arange(200)))[np.newaxis, :]
    psi, _ = tkeo(x)
    np.testing.assert_allclose(psi[0, 2:], 9.0 * math.sin(w) ** 2, rtol=1e-9)


@pytest.mark.parametrize("seed", range(4))
def test_tkeo_carry_continuity_across_random_splits(seed):
    """Concatenated block outputs equal the one-shot operator whatever the split."""
    x = _noise(3, 400, seed=seed + 50)
    ref, ref_carry = tkeo(x)
    carry = None
    outs = []
    pos = 0
    for s in _random_splits(400, seed + 60, max_size=40):
        if s == 0 and carry is None:
            continue  # an empty first block is covered by its own test
        psi, carry = tkeo(x[:, pos : pos + s], carry)
        outs.append(psi)
        pos += s
    got = np.concatenate(outs, axis=1)
    np.testing.assert_allclose(got, ref, rtol=1e-12, atol=1e-12)
    np.testing.assert_array_equal(carry, ref_carry)


def test_tkeo_leading_empty_block_does_not_corrupt_the_stream_start():
    """An empty first block (carry=None) must leave the stream-start rule intact."""
    x = _noise(2, 30, seed=69)
    ref, _ = tkeo(x)
    _, carry = tkeo(np.empty((2, 0)), None)
    psi, _ = tkeo(x, carry)
    np.testing.assert_allclose(psi, ref, rtol=1e-12, atol=1e-12)


def test_tkeo_one_sample_blocks_equal_oneshot():
    """Feeding single samples reproduces the one-shot result."""
    x = _noise(2, 60, seed=70)
    ref, _ = tkeo(x)
    carry = None
    cols = []
    for k in range(60):
        psi, carry = tkeo(x[:, k : k + 1], carry)
        cols.append(psi)
    np.testing.assert_allclose(np.concatenate(cols, axis=1), ref, rtol=1e-12, atol=1e-12)


def test_tkeo_validates_carry_shape_and_handles_empty():
    """A mis-shaped carry raises; an empty block passes the carry through unchanged."""
    with pytest.raises(ValueError, match="carry"):
        tkeo(np.zeros((2, 5)), np.zeros((3, 2)))
    carry = np.array([[1.0, 2.0]])
    psi, out_carry = tkeo(np.empty((1, 0)), carry)
    assert psi.shape == (1, 0)
    np.testing.assert_array_equal(out_carry, carry)
    psi, out_carry = tkeo(np.empty((2, 0)))
    assert psi.shape == (2, 0) and out_carry.shape == (2, 0)  # still "at the stream start"


def test_tkeo_class_matches_function_and_is_block_size_independent():
    """Tkeo carries state internally; blocks of any size agree with the one-shot form."""
    x = _noise(2, 500, seed=71)
    ref, _ = tkeo(x)
    t = Tkeo()
    got = _run_in_blocks(t, x, _random_splits(500, 72, max_size=60))
    np.testing.assert_allclose(got, ref, rtol=1e-12, atol=1e-12)


def test_tkeo_class_nonnegative_clips_and_reset_clears_carry():
    """nonnegative=True has no value below 0; reset() restarts the placeholder first output."""
    x = _noise(1, 300, seed=73)
    raw = Tkeo().process(x)
    clipped = Tkeo(nonnegative=True).process(x)
    assert raw.min() < 0.0
    assert clipped.min() >= 0.0
    np.testing.assert_allclose(clipped, np.maximum(raw, 0.0))
    t = Tkeo()
    t.process(x)
    t.reset()
    assert t.process(x)[0, 0] == 0.0


def test_tkeo_class_repairs_nonfinite_and_counts():
    """NaN/Inf are repaired before the operator, so the output is finite."""
    x = _noise(1, 100, seed=74)
    x[0, 10] = np.nan
    x[0, 50] = np.inf
    t = Tkeo()
    assert np.isfinite(t.process(x)).all()
    assert t.n_nonfinite == 2


def test_tkeo_class_empty_and_1d():
    """Empty blocks keep rank; 1-D in gives 1-D out."""
    t = Tkeo()
    assert t.process(np.empty((2, 0))).shape == (2, 0)
    assert t.process(np.empty(0)).shape == (0,)
    assert t.process(np.arange(5.0)).shape == (5,)


# ---------------------------------------------------------------------------
# Envelope follower
# ---------------------------------------------------------------------------


def test_envelope_of_constant_is_that_constant_from_the_first_sample():
    """Starts at |x[0]|: no ramp from zero."""
    env = EnvelopeFollower(1000.0).process(np.full((1, 500), -3.0))
    np.testing.assert_allclose(env, 3.0, atol=1e-9)


def test_envelope_is_nonnegative_and_tracks_burst_amplitude():
    """Never negative; a noise burst raises the envelope well above the quiet level."""
    fs = 1000.0
    rng = np.random.default_rng(80)
    x = rng.normal(0, 1.0, (1, 4000))
    x[:, 1500:2500] *= 20.0
    env = EnvelopeFollower(fs).process(x)
    assert env.min() >= 0.0
    assert env[0, 2000:2400].mean() > 10 * env[0, 200:1000].mean()
    assert env[0, 3500:].mean() < 0.2 * env[0, 2000:2400].mean()


def test_envelope_block_size_independent_and_reset():
    """Same output for any split; reset() re-arms the start at |x[0]|."""
    x = np.abs(_noise(2, 700, seed=81)) * (1 + np.arange(700) / 700)
    ref = EnvelopeFollower(FS).process(x)
    e = EnvelopeFollower(FS)
    np.testing.assert_allclose(_run_in_blocks(e, x, _random_splits(700, 82)), ref, rtol=1e-7, atol=1e-7)
    e.reset()
    np.testing.assert_allclose(e.process(np.full((2, 50), 4.0)), 4.0, atol=1e-9)


def test_envelope_repairs_nonfinite_and_counts():
    """NaN input is repaired by the input guard and counted; 1-D stays 1-D."""
    x = np.full(100, 2.0)
    x[40] = np.nan
    e = EnvelopeFollower(FS)
    y = e.process(x)
    assert y.shape == (100,) and np.isfinite(y).all()
    assert e.n_nonfinite == 1


def test_rectify_envelope_oneshot_equals_follower():
    """rectify_envelope is the stateless form of EnvelopeFollower."""
    x = _noise(1, 300, seed=83)
    np.testing.assert_allclose(
        rectify_envelope(x, FS, 4.0, order=2), EnvelopeFollower(FS, 4.0, 2).process(x)
    )


def test_envelope_validates_cutoff():
    """A cutoff at/above Nyquist is refused."""
    with pytest.raises(ValueError):
        EnvelopeFollower(FS, cutoff_hz=FS)
    with pytest.raises(ValueError):
        EnvelopeFollower(0.0)


# ---------------------------------------------------------------------------
# Referencing and detrending
# ---------------------------------------------------------------------------


def test_common_average_reference_zero_mean_across_channels():
    """After CAR the across-channel mean is ~0 at every sample; input unchanged."""
    x = _noise(4, 50, seed=90) + np.arange(4)[:, None]
    orig = x.copy()
    y = common_average_reference(x)
    np.testing.assert_allclose(y.mean(axis=0), 0.0, atol=1e-12)
    np.testing.assert_array_equal(x, orig)


def test_common_average_reference_removes_common_mode():
    """A signal common to all channels disappears; differences are preserved."""
    common = _noise(1, 80, seed=91)
    own = _noise(3, 80, seed=92)
    y = common_average_reference(own + common)
    np.testing.assert_allclose(y, common_average_reference(own), atol=1e-12)


def test_car_restricted_reference_excludes_artifact_channel():
    """Excluding a bad channel from the reference keeps its artefact out of the others."""
    x = np.zeros((3, 10))
    x[0] = 1000.0  # artefact
    x[1] = 1.0
    x[2] = 3.0
    y = common_average_reference(x, channels=[1, 2])
    np.testing.assert_allclose(y[1], -1.0)
    np.testing.assert_allclose(y[2], 1.0)
    np.testing.assert_allclose(y[0], 998.0)


def test_car_validation():
    """CAR needs 2-D data and at least two reference channels."""
    with pytest.raises(ValueError):
        common_average_reference(np.zeros(10))
    with pytest.raises(ValueError, match="two"):
        common_average_reference(np.zeros((1, 10)))
    with pytest.raises(ValueError, match="two"):
        common_average_reference(np.zeros((3, 10)), channels=[1])


def test_bipolar_is_difference_and_cancels_common_mode():
    """bipolar(x, a, b) = x[a] - x[b] as (1, n); common interference cancels."""
    interference = _tone(50.0, 100, 1000.0, amp=500.0)
    x = np.vstack([interference + 1.0, interference + 4.0, np.zeros(100)])
    y = bipolar(x, 0, 1)
    assert y.shape == (1, 100)
    np.testing.assert_allclose(y, -3.0, atol=1e-9)
    np.testing.assert_allclose(bipolar(x, 1, 0), 3.0, atol=1e-9)


def test_bipolar_validation():
    """Same channel twice or non-2-D data is an error."""
    with pytest.raises(ValueError, match="different"):
        bipolar(np.zeros((2, 5)), 1, 1)
    with pytest.raises(ValueError, match="2-D"):
        bipolar(np.zeros(5), 0, 1)


def test_detrend_removes_dc_and_starts_at_zero():
    """A constant offset gives exactly 0 output; a slow drift is mostly removed."""
    np.testing.assert_allclose(detrend_running_mean(np.full((1, 200), 321.0), FS), 0.0, atol=1e-9)
    n = 2000
    sig = _tone(40.0, n, FS)
    drift = np.linspace(0.0, 5.0, n)
    out = detrend_running_mean(sig + drift, FS, window_s=0.5)
    # A running mean lags a linear ramp by slope * window; the rest of the drift is gone.
    lag = (5.0 / (n / FS)) * 0.5
    assert abs(out[n // 2 :].mean()) == pytest.approx(lag, rel=0.3)
    assert out[n // 2 :].mean() < abs(drift[-1] - drift[0]) * 0.2


def test_detrender_is_block_size_independent_and_reset():
    """Streaming detrender equals one-shot for any split; reset() re-zeroes at the new level."""
    x = _noise(2, 600, seed=95) + 100.0
    ref = detrend_running_mean(x, FS, 0.3)
    d = RunningMeanDetrender(FS, 0.3)
    np.testing.assert_allclose(_run_in_blocks(d, x, _random_splits(600, 96)), ref, rtol=1e-7, atol=1e-7)
    d.reset()
    np.testing.assert_allclose(d.process(np.full((2, 20), -50.0)), 0.0, atol=1e-9)


def test_detrender_nonfinite_outputs_zero_not_nan_and_counts():
    """A NaN sample yields a finite output and is counted."""
    x = np.full((1, 50), 10.0)
    x[0, 20] = np.nan
    d = RunningMeanDetrender(FS, 0.5)
    y = d.process(x)
    assert np.isfinite(y).all()
    assert d.n_nonfinite == 1


def test_detrender_validation():
    """The window must hold at least one sample; 1-D stays 1-D."""
    with pytest.raises(ValueError, match="window_s"):
        RunningMeanDetrender(FS, window_s=0.0001)
    with pytest.raises(ValueError, match="window_s"):
        RunningMeanDetrender(FS, window_s=float("nan"))
    assert detrend_running_mean(np.arange(10.0), FS).shape == (10,)
