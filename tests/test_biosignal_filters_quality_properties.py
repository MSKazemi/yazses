"""Property-based tests for ``yazses.biosignal.filters`` and ``yazses.biosignal.quality``.

Totality and invariants, not corpus cases: any finite float array of any length (0, 1, 2,
a few thousand), constant and all-zero signals, NaN/Inf, extreme amplitudes, and sample
rates from 100 Hz to 2 kHz (including rates whose Nyquist sits below a band edge). Asserted:

* no exception other than a documented ``ValueError``;
* finite output for finite input, and output length equal to input length;
* chunked processing equals whole-array processing (filter state carries across blocks);
* the quality monitor never reports GOOD for flat, saturated or NaN data.

Synthetic, deterministic per example, offline. Example counts are kept modest so the file
runs in well under 20 s.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from yazses.biosignal import filters as F
from yazses.biosignal.quality import (
    QualityStatus,
    SignalQualityMonitor,
)
from yazses.biosignal.types import ChannelInfo, SampleBlock, SignalKind

pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")

prop_settings = settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
small_settings = settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)

# Finite microvolt-scale samples. Extreme amplitudes are covered separately.
_FINITE = st.floats(min_value=-1e4, max_value=1e4, allow_nan=False, allow_infinity=False)
_ANY_FLOAT = st.one_of(
    _FINITE,
    st.just(float("nan")),
    st.just(float("inf")),
    st.just(float("-inf")),
)
_FS = st.one_of(
    st.sampled_from([100.0, 137.5, 200.0, 250.0, 500.0, 1000.0, 2000.0]),
    st.floats(min_value=100.0, max_value=2000.0, allow_nan=False, allow_infinity=False),
)
_LENGTH = st.one_of(st.sampled_from([0, 1, 2, 3, 7, 16, 63, 64, 65]), st.integers(0, 400))


def _vec(elements: st.SearchStrategy[float], max_size: int) -> st.SearchStrategy[np.ndarray]:
    return st.lists(elements, min_size=0, max_size=max_size).map(
        lambda v: np.array(v, dtype=np.float64)
    )


def _signal(n_ch: int, n: int, seed: int, scale: float) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, scale, size=(n_ch, n))


# ---------------------------------------------------------------------------
# Filters: design and totality
# ---------------------------------------------------------------------------


@prop_settings
@given(
    low=st.floats(allow_nan=True, allow_infinity=True),
    high=st.floats(allow_nan=True, allow_infinity=True),
    fs=st.floats(allow_nan=True, allow_infinity=True),
    order=st.integers(min_value=-2, max_value=8),
)
def test_bandpass_design_is_stable_or_documented_valueerror(low, high, fs, order):
    """Arbitrary edges, rate and order: a stable cascade, or a ValueError. Never anything else."""
    try:
        sections = F.design_butterworth_bandpass(low, high, fs, order)
    except ValueError:
        return
    assert sections
    assert all(s.is_stable() for s in sections)


@prop_settings
@given(fs=_FS, mains=st.one_of(st.none(), st.sampled_from([50.0, 60.0]), st.floats(-5, 1000)))
def test_chain_builders_are_total_for_any_rate(fs, mains):
    """Every builder either returns a chain that filters finite data to the same length, or
    raises ValueError (sample rate below a band edge, mains at or above Nyquist, ...)."""
    for build in (F.build_emg_chain, F.build_eeg_chain):
        try:
            chain = build(fs, mains)
        except ValueError:
            continue
        x = _signal(2, 300, seed=1, scale=50.0)
        y = chain.process(x)
        assert y.shape == x.shape
        assert np.all(np.isfinite(y))
    try:
        chain = F.build_eog_chain(fs)
    except ValueError:
        return
    y = chain.process(_signal(1, 300, seed=2, scale=50.0))
    assert y.shape == (1, 300) and np.all(np.isfinite(y))


@small_settings
@given(fs=st.sampled_from([20.0, 30.0, 39.0, 40.0, 44.0, 55.0]))
def test_rates_below_band_edge_raise_valueerror(fs):
    """Documented: a rate too low for the band is a typed error, not a silent band-stop."""
    with pytest.raises(ValueError):
        F.build_emg_chain(fs, None)


# ---------------------------------------------------------------------------
# Filters: finiteness and length
# ---------------------------------------------------------------------------


@prop_settings
@given(
    x=_vec(_ANY_FLOAT, 300),
    fs=st.sampled_from([100.0, 250.0, 500.0, 2000.0]),
    two_d=st.booleans(),
)
def test_chain_output_is_finite_and_length_preserving_for_any_input(x, fs, two_d):
    """NaN and Inf are repaired at the input; the output is finite and keeps the shape."""
    try:  # a 50 Hz notch at or near Nyquist is a documented ValueError (see filters.py)
        chain = F.build_eeg_chain(fs, 50.0)
    except ValueError:
        return
    data = np.tile(x, (2, 1)) if two_d else x
    y = chain.process(data)
    assert y.shape == data.shape
    assert np.all(np.isfinite(y))


@prop_settings
@given(x=_vec(_FINITE, 300), fs=_FS, window=st.floats(0.05, 5.0))
def test_detrender_and_envelope_are_finite_and_length_preserving(x, fs, window):
    if x.size == 0:
        assert F.detrend_running_mean(x, fs, window).shape == (0,)
        return
    d = F.RunningMeanDetrender(fs, window)
    out = d.process(x)
    assert out.shape == x.shape and np.all(np.isfinite(out))
    env = F.EnvelopeFollower(fs).process(x)
    assert env.shape == x.shape and np.all(np.isfinite(env))
    assert np.all(env >= 0.0)


@prop_settings
@given(x=_vec(_FINITE, 300))
def test_tkeo_block_is_length_preserving_and_finite(x):
    psi, carry = F.tkeo(x)
    assert psi.shape == (0,) or psi.shape[-1] == x.size
    assert np.all(np.isfinite(psi))
    assert carry.shape[-1] in (0, 2)


# ---------------------------------------------------------------------------
# Filters: extreme amplitudes, constant and zero signals
# ---------------------------------------------------------------------------


@prop_settings
@given(
    amp=st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False),
    n=st.integers(0, 200),
    fs=st.sampled_from([100.0, 250.0, 2000.0]),
)
def test_extreme_amplitude_stays_finite(amp, n, fs):
    x = _signal(1, n, seed=3, scale=1.0) * amp
    y = F.build_eeg_chain(fs, None).process(x)
    assert y.shape == x.shape
    assert np.all(np.isfinite(y))


@prop_settings
@given(c=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False, allow_infinity=False),
       n=st.integers(1, 300), fs=st.sampled_from([100.0, 250.0, 2000.0]))
def test_constant_signal_produces_no_start_up_transient(c, n, fs):
    """Steady-state initialisation: a constant input (bio-amplifier DC offset) gives ~0 out."""
    y = F.build_emg_chain(fs, None).process(np.full(n, c))
    assert np.all(np.isfinite(y))
    assert np.max(np.abs(y)) <= 1e-6 * max(1.0, abs(c))


@prop_settings
@given(n=st.integers(0, 300), fs=_FS)
def test_all_zero_input_gives_exact_zero(n, fs):
    try:  # 50 Hz notch at or near Nyquist: documented ValueError, not a silent chain
        chain = F.build_eeg_chain(fs, 50.0)
    except ValueError:
        return
    y = chain.process(np.zeros((2, n)))
    assert np.array_equal(y, np.zeros((2, n)))


# ---------------------------------------------------------------------------
# Filters: chunked == whole (state continuity)
# ---------------------------------------------------------------------------


def _split(n: int, cuts: list[int]) -> list[slice]:
    edges = sorted({0, n, *[min(max(c, 0), n) for c in cuts]})
    return [slice(a, b) for a, b in zip(edges[:-1], edges[1:], strict=True)]


@prop_settings
@given(
    n=st.integers(1, 500),
    cuts=st.lists(st.integers(0, 500), max_size=6),
    seed=st.integers(0, 2**16),
    with_nan=st.booleans(),
    backend=st.sampled_from(["numpy", "scipy"]),
)
def test_sos_chunked_equals_whole(n, cuts, seed, with_nan, backend):
    """Carrying state across chunks (with NaN repair across the boundary) equals one call."""
    x = _signal(2, n, seed=seed, scale=100.0) + 500.0  # DC offset, as a real amplifier has
    if with_nan:
        rng = np.random.default_rng(seed + 1)
        x[rng.random(x.shape) < 0.05] = np.nan
    sections = F.design_butterworth_bandpass(20.0, 100.0, 250.0, 4)
    whole = F.SosFilter(sections, backend=backend).process(x)
    chunked_f = F.SosFilter(sections, backend=backend)
    parts = [chunked_f.process(x[:, s]) for s in _split(n, cuts)]
    chunked = np.concatenate(parts, axis=1)
    assert chunked.shape == whole.shape
    np.testing.assert_allclose(chunked, whole, rtol=1e-9, atol=1e-6)


@prop_settings
@given(n=st.integers(1, 400), cuts=st.lists(st.integers(0, 400), max_size=5),
       seed=st.integers(0, 2**16))
def test_tkeo_chunked_equals_whole(n, cuts, seed):
    x = _signal(2, n, seed=seed, scale=10.0)
    whole, _ = F.tkeo(x)
    carry = None
    parts = []
    for s in _split(n, cuts):
        psi, carry = F.tkeo(x[:, s], carry)
        parts.append(psi)
    np.testing.assert_allclose(np.concatenate(parts, axis=1), whole, rtol=1e-12, atol=1e-9)


@prop_settings
@given(n=st.integers(1, 400), cuts=st.lists(st.integers(0, 400), max_size=5),
       seed=st.integers(0, 2**16))
def test_detrender_and_envelope_chunked_equal_whole(n, cuts, seed):
    x = _signal(1, n, seed=seed, scale=50.0)[0] + 300.0
    for make, run in (
        (lambda: F.RunningMeanDetrender(250.0, 1.0), lambda f, v: f.process(v)),
        (lambda: F.EnvelopeFollower(250.0), lambda f, v: f.process(v)),
    ):
        whole = run(make(), x)
        f = make()
        chunked = np.concatenate([run(f, x[s]) for s in _split(n, cuts)])
        np.testing.assert_allclose(chunked, whole, rtol=1e-9, atol=1e-6)


# ---------------------------------------------------------------------------
# Quality monitor: totality
# ---------------------------------------------------------------------------

_KINDS = [SignalKind.EEG, SignalKind.EOG, SignalKind.EMG]


def _block(data: np.ndarray, fs: float, t0: float, kinds) -> SampleBlock:
    chans = tuple(ChannelInfo(f"ch{i}", kinds[i]) for i in range(data.shape[0]))
    return SampleBlock(data=data, fs=fs, channels=chans, t0=t0)


@small_settings
@given(
    fs=st.sampled_from([100.0, 250.0, 500.0]),
    n_ch=st.integers(1, 3),
    block_sizes=st.lists(st.integers(0, 120), min_size=1, max_size=8),
    seed=st.integers(0, 2**16),
    scale=st.sampled_from([0.0, 1e-3, 5.0, 40.0, 1e4]),
    inject=st.booleans(),
)
def test_monitor_is_total_and_reports_are_bounded(fs, n_ch, block_sizes, seed, scale, inject):
    """Any blocking of any data: no exception, enum status, scores in [0, 1], no NaN metrics."""
    mon = SignalQualityMonitor()
    rng = np.random.default_rng(seed)
    t = 0.0
    for size in block_sizes:
        data = rng.normal(0.0, scale, size=(n_ch, size))
        if inject and size:
            data[0, :: max(1, size // 3)] = np.nan
        rep = mon.update(_block(data, fs, t, _KINDS[:n_ch]))
        t += size / fs
        assert isinstance(rep.overall, QualityStatus)
        assert 0.0 <= rep.score <= 1.0
        for ch in rep.channels:
            assert 0.0 <= ch.score <= 1.0
            assert 0.0 <= ch.contact_score <= 1.0
            assert all(math.isfinite(v) for v in ch.metrics.values())


# ---------------------------------------------------------------------------
# Quality monitor: never GOOD for flat / saturated / NaN data
# ---------------------------------------------------------------------------


def _all_reports_not_good(rep_iter):
    for rep in rep_iter:
        assert rep.overall is not QualityStatus.GOOD, rep
        for ch in rep.channels:
            assert ch.status is not QualityStatus.GOOD, (ch.name, ch.reasons, ch.metrics)


@small_settings
@given(
    value=st.floats(min_value=-1e5, max_value=1e5, allow_nan=False, allow_infinity=False),
    fs=st.sampled_from([100.0, 250.0, 500.0]),
    n_ch=st.integers(1, 3),
    chunk=st.sampled_from([1, 37, 250]),
)
def test_flat_signal_is_never_good(value, fs, n_ch, chunk):
    """A constant (dead or stuck) channel is never reported GOOD, at any block size."""
    total = int(fs * 9)
    mon = SignalQualityMonitor()
    reports = []
    t = 0.0
    for start in range(0, total, chunk):
        size = min(chunk, total - start)
        data = np.full((n_ch, size), value)
        reports.append(mon.update(_block(data, fs, t, _KINDS[:n_ch])))
        t += size / fs
    _all_reports_not_good(reports)


@small_settings
@given(
    fs=st.sampled_from([250.0, 500.0]),
    n_ch=st.integers(1, 2),
    seed=st.integers(0, 2**16),
    rail=st.sampled_from([600.0, 2500.0]),
)
def test_railed_signal_is_never_good(fs, n_ch, seed, rail):
    """EEG clipped hard at +-rail (above the 500 uV EEG limit): never GOOD."""
    total = int(fs * 9)
    raw = _signal(n_ch, total, seed=seed, scale=5000.0)
    clipped = np.clip(raw, -rail, rail)
    mon = SignalQualityMonitor()
    reports = []
    for start in range(0, total, 125):
        seg = clipped[:, start : start + 125]
        reports.append(
            mon.update(_block(seg, fs, start / fs, [SignalKind.EEG] * n_ch))
        )
    _all_reports_not_good(reports)


@small_settings
@given(fs=st.sampled_from([250.0, 500.0]), n_ch=st.integers(1, 2))
def test_all_nan_is_never_good(fs, n_ch):
    total = int(fs * 9)
    mon = SignalQualityMonitor()
    reports = []
    for start in range(0, total, 125):
        size = min(125, total - start)
        data = np.full((n_ch, size), np.nan)
        reports.append(mon.update(_block(data, fs, start / fs, [SignalKind.EEG] * n_ch)))
    _all_reports_not_good(reports)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DESIGN DECISION, not a fixed defect: nonfinite_frac_degraded=0.001 means a window "
        "with one NaN in 2000 samples (500 Hz, 4 s) grades GOOD. Whether any NaN should cap "
        "a channel at DEGRADED changes what counts as GOOD for real recordings, so the "
        "threshold is left for the owner to decide."
    ),
)
@small_settings
@given(
    fs=st.sampled_from([250.0, 500.0]),
    seed=st.integers(0, 2**16),
    n_bad=st.integers(1, 3),
)
def test_a_few_nans_in_a_window_are_not_good(fs, seed, n_bad):
    """Literal requirement: a window that contains NaN is never reported GOOD."""
    total = int(fs * 9)
    data = _signal(1, total, seed=seed, scale=20.0)
    rng = np.random.default_rng(seed + 7)
    # NaNs land in the last 2 s, so the final 4 s window that is judged last contains them.
    tail = int(fs * 2)
    data[0, total - tail + rng.choice(tail, size=n_bad, replace=False)] = np.nan
    mon = SignalQualityMonitor()
    reports = []
    for start in range(0, total, 125):
        seg = data[:, start : start + 125]
        reports.append(mon.update(_block(seg, fs, start / fs, [SignalKind.EEG])))
    _all_reports_not_good(reports[-1:])


@settings(max_examples=3, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(n=st.integers(15_000, 25_000), seed=st.integers(0, 2**16))
def test_long_stream_is_finite_length_preserving_and_chunk_consistent(n, seed):
    """A long stream (about 100 s at 250 Hz) is finite, keeps its length, and a chunked run
    of it matches the whole run."""
    x = _signal(1, n, seed=seed, scale=30.0)[0]
    whole = F.build_eeg_chain(250.0, 50.0).process(x)
    assert whole.shape == x.shape and np.all(np.isfinite(whole))
    chain = F.build_eeg_chain(250.0, 50.0)
    chunked = np.concatenate([chain.process(x[i : i + 997]) for i in range(0, n, 997)])
    np.testing.assert_allclose(chunked, whole, rtol=1e-9, atol=1e-6)
