"""The shared F0 + spectral-flux producer (`yazses.audio.pitch`) on synthetic signals.

numpy only, so nothing here can be absent on any supported platform (FreeBSD included) and
no skip marker is needed. Signals come from `tests/synthetic_voice.py`; no recorded audio.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from tests.synthetic_voice import SR, glide, hum, silence, white_noise
from yazses.audio.pitch import (
    PitchTracker,
    spectral_flux,
    spectral_stability,
    track,
    yin_f0,
)


def _voiced_f0(frames):
    return [f.f0_hz for f in frames if f.voiced]


@pytest.mark.parametrize("hz", [80.0, 120.0, 220.0, 330.0, 450.0])
def test_a_sine_is_tracked_within_one_percent(hz):
    t = np.arange(SR) / SR
    frames = track(0.01 * np.sin(2 * np.pi * hz * t), SR)
    f0 = _voiced_f0(frames)
    assert len(f0) == len(frames)  # every frame of a steady sine is voiced
    assert abs(float(np.median(f0)) - hz) / hz < 0.01
    assert max(abs(f - hz) for f in f0) / hz < 0.02


def test_a_harmonic_hum_reports_its_fundamental_not_a_partial():
    f0 = _voiced_f0(track(hum(150.0, 0.5), SR))
    assert f0 and abs(float(np.median(f0)) - 150.0) < 1.5


def test_tracking_is_independent_of_gain():
    """YIN normalises the difference function, so a quiet mic and a loud one agree."""
    quiet = _voiced_f0(track(hum(200.0, 0.3, amp=0.001), SR))
    loud = _voiced_f0(track(hum(200.0, 0.3, amp=0.3), SR))
    assert len(quiet) == len(loud)
    assert np.allclose(quiet, loud, rtol=1e-6)


def test_silence_is_unvoiced_with_no_stability_to_report():
    frames = track(silence(0.5), SR)
    assert frames and not any(f.voiced for f in frames)
    assert all(math.isnan(f.flux) for f in frames)  # a dropout is not "perfectly steady"
    assert spectral_stability(f.flux for f in frames) == 0.0


@pytest.mark.parametrize("level", [1e-4, 0.01, 0.3])
def test_white_noise_is_unvoiced_and_spectrally_unsteady(level):
    frames = track(white_noise(1.0, level=level), SR)
    assert sum(f.voiced for f in frames) / len(frames) < 0.02
    assert spectral_stability(f.flux for f in frames) < 0.7


def test_a_steady_hum_is_spectrally_stable_and_a_glide_is_less_so():
    steady = track(hum(120.0, 0.6, noise=5e-4), SR)
    moving = track(hum(glide(220.0, 110.0, 0.6), 0.6, noise=5e-4), SR)
    s_steady = spectral_stability(f.flux for f in steady)
    s_moving = spectral_stability(f.flux for f in moving)
    assert s_steady > 0.95
    assert s_moving < s_steady


def test_a_glide_is_followed():
    frames = track(hum(glide(150.0, 300.0, 0.8), 0.8), SR)
    f0 = _voiced_f0(frames)
    assert f0[0] < 165.0 and f0[-1] > 280.0
    assert all(b >= a - 2.0 for a, b in zip(f0, f0[1:], strict=False))  # monotone, small jitter


def test_feeding_in_chunks_gives_the_same_frames_as_one_call():
    audio = hum(glide(140.0, 260.0, 0.7), 0.7, noise=1e-3)
    whole = track(audio, SR)
    tracker = PitchTracker(SR)
    pieces = []
    rng = np.random.default_rng(3)
    pos = 0
    while pos < audio.size:
        n = int(rng.integers(1, 1500))  # irregular, like the recorder's unfixed blocksize
        pieces.extend(tracker.feed(audio[pos:pos + n]))
        pos += n
    assert len(pieces) == len(whole)
    for a, b in zip(pieces, whole, strict=True):
        assert a.t_s == pytest.approx(b.t_s)
        assert a.f0_hz == pytest.approx(b.f0_hz, abs=1e-9)
        assert a.voiced == b.voiced


def test_frame_timing_and_reset():
    tracker = PitchTracker(SR)
    frames = tracker.feed(hum(200.0, 0.2))
    assert frames[0].t_s == 0.0
    assert frames[1].t_s == pytest.approx(0.010)
    assert math.isnan(frames[0].flux) and not math.isnan(frames[1].flux)
    tracker.reset()
    again = tracker.feed(hum(200.0, 0.2))
    assert again[0].t_s == 0.0 and math.isnan(again[0].flux)
    assert tracker.feed([]) == []


def test_yin_edge_cases():
    assert yin_f0([], SR) == (0.0, 0.0)
    assert yin_f0(np.zeros(640), SR) == (0.0, 0.0)
    # A frame too short to hold two periods of the floor cannot search it, and says unvoiced
    # rather than inventing a frequency.
    assert yin_f0(np.ones(6), SR)[0] == 0.0
    with pytest.raises(ValueError):
        PitchTracker(0)


def test_spectral_flux_bounds():
    p = np.array([1.0, 2.0, 3.0])
    assert spectral_flux(p, p * 7.0) == pytest.approx(0.0)  # same shape, any level
    assert spectral_flux([1.0, 0.0], [0.0, 1.0]) == pytest.approx(1.0)
    assert spectral_flux([0.0, 0.0], [0.0, 0.0]) == 0.0
    assert spectral_flux([0.0, 0.0], [1.0, 0.0]) == 1.0
    assert spectral_stability([]) == 0.0
    assert spectral_stability([float("nan"), 0.2]) == pytest.approx(0.8)
