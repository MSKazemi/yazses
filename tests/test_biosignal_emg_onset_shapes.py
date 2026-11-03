"""Characterisation: which synthetic shapes the onset detector fires on, and which it does not.

This file pins the detector's CURRENT behaviour. It does not change it. The smooth unipolar
Hann bump is a known limit (see ``test_biosignal_emg_onset.py``, the strict xfail): it fires for
50-150 ms at ``>= 600`` uV. Those counts are recorded here so that a detector change which
moves them shows up as a deliberate diff, not as a silent shift.

Every count is over ``range(12)`` seeds of white noise at 5 uV (the relaxed floor), calibrated
through the detector's own band-pass, offline, deterministic. The counts were measured on this
repository's numpy; a numpy change to its random stream may move them, in which case re-measure
and update the table rather than loosening it. In-between counts carry a +-3 band; the "never"
and "always" rows are exact. Each row is one shape at one sampling rate.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pytest

from yazses.biosignal.emg_onset import EmgOnsetDetector, OnsetThresholds, bandlimited_rms
from yazses.biosignal.types import ChannelInfo, EventKind, SampleBlock, SignalKind

SIGMA0 = 5.0  # relaxed-noise standard deviation (uV)
EMG1 = (ChannelInfo("emg0", SignalKind.EMG),)
SEEDS = range(12)


@lru_cache(maxsize=None)
def _calibration(fs: float) -> tuple[float, float]:
    rng = np.random.default_rng(1234)
    n = int(6 * fs)
    base = bandlimited_rms(rng.normal(0.0, SIGMA0, (1, n)), fs)
    mvc = bandlimited_rms(rng.normal(0.0, 10 * SIGMA0, (1, n)), fs)
    return base, mvc


def _thresholds(fs: float) -> OnsetThresholds:
    base, mvc = _calibration(fs)
    return OnsetThresholds.from_calibration(base, mvc)


def _run(det: EmgOnsetDetector, x: np.ndarray, fs: float) -> int:
    """Stream ``x`` in 20 ms blocks and count SQUEEZE_ON events."""
    size = max(1, int(0.02 * fs))
    n_on = 0
    for pos in range(0, x.shape[1], size):
        blk = SampleBlock(x[:, pos:pos + size], fs, EMG1, pos / fs)
        n_on += sum(e.kind is EventKind.SQUEEZE_ON for e in det.process(blk))
    return n_on


def _hann_bump(fs: float, seed: int, amp: float, ms: float) -> np.ndarray:
    """Relaxed noise plus one unipolar Hann bump (a smooth, same-signed excursion)."""
    rng = np.random.default_rng(seed)
    n = int(3.0 * fs)
    at = int(1.5 * fs) + int(rng.integers(0, 3))
    x = rng.normal(0.0, SIGMA0, (1, n))
    w = max(1, int(ms / 1000.0 * fs))
    x[0, at:at + w] += amp * np.hanning(w)
    return x


def _rect_burst(fs: float, seed: int, ms: float, mult: float) -> np.ndarray:
    """Relaxed noise with one zero-mean rectangular burst ``mult`` times the floor."""
    rng = np.random.default_rng(seed)
    n = int(3.0 * fs)
    at = int(1.5 * fs) + int(rng.integers(0, 3))
    x = rng.normal(0.0, SIGMA0, (1, n))
    m = int(ms / 1000.0 * fs)
    x[0, at:at + m] = rng.normal(0.0, SIGMA0 * mult, m)
    return x


def _fire_count(make, fs: float, **kw) -> int:
    """How many of the ``SEEDS`` runs produce at least one SQUEEZE_ON."""
    hits = 0
    for s in SEEDS:
        det = EmgOnsetDetector(_thresholds(fs))
        hits += _run(det, make(fs, s, **kw), fs) >= 1
    return hits


# -- smooth unipolar Hann bumps: the measured map -------------------------------------------
#
# (fs, amplitude uV, duration ms) -> SQUEEZE_ON runs out of 12. "0" never fires, "12" always
# does. Everything in between is the boundary the known limit describes. 30 ms never fires
# (shorter than the minimum burst); 200 ms at 1000 uV never fires; 50-150 ms at >= 600 uV
# usually does.

HANN_MAP = [
    (500.0, 1000.0, 30.0, 0),
    (500.0, 1000.0, 50.0, 12),
    (500.0, 1000.0, 80.0, 12),
    (500.0, 1000.0, 120.0, 12),
    (500.0, 1000.0, 150.0, 11),
    (500.0, 1000.0, 200.0, 0),
    (500.0, 300.0, 50.0, 2),
    (250.0, 600.0, 80.0, 12),
    (250.0, 1000.0, 50.0, 10),
    (250.0, 1000.0, 120.0, 12),
    (1000.0, 300.0, 80.0, 0),
    (1000.0, 600.0, 50.0, 10),
]


def _near(count: int, expected: int) -> bool:
    """Exact at the decisive ends (never / always); +-3 of 12 in between, so that a numpy
    random-stream change does not fail a row whose meaning ("it sometimes fires") is unchanged."""
    tol = 0 if expected in (0, len(SEEDS)) else 3
    return abs(count - expected) <= tol


@pytest.mark.parametrize(("fs", "amp", "ms", "expected"), HANN_MAP)
def test_hann_bump_fire_count_is_the_measured_value(fs, amp, ms, expected):
    assert _near(_fire_count(_hann_bump, fs, amp=amp, ms=ms), expected)


@pytest.mark.parametrize("fs", [250.0, 500.0, 1000.0])
def test_a_hann_bump_shorter_than_the_minimum_burst_never_fires(fs):
    assert _fire_count(_hann_bump, fs, amp=1000.0, ms=30.0) == 0


# -- rectangular zero-mean bursts: the true positives the detector must keep ----------------
#
# The sustain and level-drift tests (in the main file) and the artifact stage must not cost
# these. A 500 ms burst is a held contraction; a 60-100 ms burst at 3x is the marginal case.

RECT_MAP = [
    (500.0, 500.0, 3.0, 12),
    (500.0, 60.0, 5.0, 3),
    (250.0, 100.0, 3.0, 3),
    (1000.0, 60.0, 3.0, 0),
    (250.0, 60.0, 10.0, 11),
]


@pytest.mark.parametrize(("fs", "ms", "mult", "expected"), RECT_MAP)
def test_rectangular_burst_fire_count_is_the_measured_value(fs, ms, mult, expected):
    assert _near(_fire_count(_rect_burst, fs, ms=ms, mult=mult), expected)


@pytest.mark.parametrize("fs", [250.0, 500.0, 1000.0])
def test_a_held_zero_mean_contraction_fires_on_every_seed(fs):
    assert _fire_count(_rect_burst, fs, ms=500.0, mult=5.0) == len(SEEDS)


def test_a_negative_control_is_silent_at_every_rate():
    """Relaxed noise alone, no shape: nothing fires (the floor is never a squeeze)."""
    for fs in (250.0, 500.0, 1000.0):
        for s in SEEDS:
            rng = np.random.default_rng(s)
            x = rng.normal(0.0, SIGMA0, (1, int(3.0 * fs)))
            assert _run(EmgOnsetDetector(_thresholds(fs)), x, fs) == 0
