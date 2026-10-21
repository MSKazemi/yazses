"""Vocal-Strain Guard producer side (ADR-v2-034): biomarkers backend + session history.

The history and the monitor are pure and are tested directly with a fake backend. The
Praat path needs ``parselmouth`` (the optional ``prosody`` extra); those tests skip,
with that reason, where it is not installed. They use ``tests.decoder_stack.installed``
for the check but not its ``needs_*`` markers, whose skip reason is about the FreeBSD
decoder stack and would be false here.
"""
from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from tests.decoder_stack import installed
from yazses.voicehealth.biomarkers import (
    BREAK_SUGGESTION_BODY,
    BREAK_SUGGESTION_TITLE,
    Biomarkers,
    ParselmouthBiomarkers,
    StrainHistory,
    StrainMonitor,
)

needs_parselmouth = pytest.mark.skipif(
    not installed("parselmouth"),
    reason="parselmouth (the optional `prosody` extra) is not installed",
)


@dataclass
class _Cfg:
    enabled: bool = True
    threshold: float = 0.6
    min_samples: int = 5


HEALTHY = Biomarkers(jitter=0.004, shimmer=0.03, hnr=22.0)   # strain ~0.17
STRAINED = Biomarkers(jitter=0.03, shimmer=0.15, hnr=4.0)     # strain ~0.93


def _feed(history: StrainHistory, readings, start: float = 0.0, step: float = 10.0):
    """Feed readings one per *step* seconds; return the indices that fired."""
    fired = []
    for i, r in enumerate(readings):
        if history.observe(r, start + i * step):
            fired.append(i)
    return fired


# ---- StrainHistory: the conservative decision --------------------------------------

def test_rising_strain_fires_once_after_baseline_and_full_window():
    h = StrainHistory(_Cfg())
    fired = _feed(h, [HEALTHY] * 5 + [STRAINED] * 5)
    # 5 baseline readings never fire; the 5th strained reading completes the window.
    assert fired == [9]
    assert h.suggestions == 1
    assert h.window == ()  # cleared after a suggestion


def test_baseline_readings_never_fire_even_when_strained():
    h = StrainHistory(_Cfg())
    assert _feed(h, [STRAINED] * 5) == []
    assert h.baseline is not None and h.baseline > 0.9


def test_constant_high_strain_never_fires():
    # A rough voice or a noisy microphone scores high from the first utterance. That is
    # not drift, and a reminder every 45 minutes all day would be a nag.
    h = StrainHistory(_Cfg())
    assert _feed(h, [STRAINED] * 200) == []


def test_high_but_not_risen_enough_does_not_fire():
    h = StrainHistory(_Cfg(threshold=0.6), min_rise=0.15)
    # baseline 0.55, window 0.65: above threshold, but only 0.10 above baseline.
    assert _feed(h, [0.55] * 5 + [0.65] * 5) == []


def test_min_rise_zero_reduces_to_the_core_rule():
    h = StrainHistory(_Cfg(), min_rise=0.0)
    assert _feed(h, [0.7] * 5 + [0.7] * 5) == [9]


def test_below_threshold_never_fires_despite_rise():
    h = StrainHistory(_Cfg(threshold=0.6))
    # Rise of 0.4, but the window mean 0.5 is under the 0.6 threshold.
    assert _feed(h, [0.1] * 5 + [0.5] * 50) == []


def test_disabled_config_never_fires():
    h = StrainHistory(_Cfg(enabled=False))
    assert _feed(h, [HEALTHY] * 5 + [STRAINED] * 100) == []


def test_cooldown_suppresses_a_second_suggestion():
    h = StrainHistory(_Cfg(), cooldown_s=600.0, max_per_session=10)
    fired = _feed(h, [HEALTHY] * 5 + [STRAINED] * 100, step=10.0)
    # First fire at index 9 (t=90 s); the next is allowed from t=690 s, i.e. index 69.
    assert fired[0] == 9
    assert all(b - a >= 60 for a, b in zip(fired, fired[1:]))
    assert fired[1] == 69


def test_session_cap_bounds_suggestions():
    h = StrainHistory(_Cfg(), cooldown_s=0.0, max_per_session=2)
    fired = _feed(h, [HEALTHY] * 5 + [STRAINED] * 500)
    assert len(fired) == 2
    # After a suggestion the window is cleared, so the next needs a full fresh window.
    assert fired == [9, 14]


def test_reset_starts_a_new_session():
    h = StrainHistory(_Cfg(), cooldown_s=0.0, max_per_session=1)
    assert _feed(h, [HEALTHY] * 5 + [STRAINED] * 5) == [9]
    assert _feed(h, [STRAINED] * 20, start=1000.0) == []  # capped
    h.reset()
    assert h.baseline is None and h.suggestions == 0
    assert _feed(h, [HEALTHY] * 5 + [STRAINED] * 5, start=2000.0) == [9]


def test_non_finite_readings_are_ignored():
    h = StrainHistory(_Cfg())
    assert h.observe(float("nan"), 0.0) is False
    assert h.observe(float("inf"), 0.0) is False
    assert h.baseline is None and h.window == ()


@pytest.mark.parametrize(
    "reading",
    [
        Biomarkers(float("nan"), 0.1, 10.0),
        Biomarkers(float("inf"), 0.0, 20.0),
        Biomarkers(0.01, float("-inf"), 20.0),
        Biomarkers(0.01, 0.05, float("nan")),
    ],
)
def test_non_finite_biomarkers_are_ignored(reading):
    # strain_level clamps into [0, 1], and max(0.0, nan) is 0.0, so without the
    # is_finite() check a NaN field would enter the baseline as a finite score.
    h = StrainHistory(_Cfg(), baseline_samples=1)
    assert h.observe(reading, 0.0) is False
    assert h.baseline is None and h.window == ()
    assert h._baseline == []


def test_default_window_means_no_suggestion_before_40_utterances():
    @dataclass
    class _DefaultCfg:  # the shipped VoicehealthConfig defaults, enabled
        enabled: bool = True
        threshold: float = 0.6
        min_samples: int = 20

    h = StrainHistory(_DefaultCfg())
    fired = _feed(h, [HEALTHY] * 20 + [STRAINED] * 100, step=1.0)
    assert fired and fired[0] == 39


def test_history_keeps_only_floats():
    h = StrainHistory(_Cfg())
    _feed(h, [HEALTHY] * 5 + [HEALTHY] * 3)
    assert all(isinstance(v, float) for v in h.window)


# ---- StrainMonitor: end-to-end with a fake backend ---------------------------------

class _FakeBackend:
    def __init__(self, readings):
        self._readings = list(readings)
        self.calls = 0

    def measure(self, audio, sample_rate):
        self.calls += 1
        r = self._readings.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_monitor_end_to_end_with_fake_backend():
    readings = [HEALTHY] * 5 + [None, RuntimeError("praat failed")] + [STRAINED] * 5
    backend = _FakeBackend(readings)
    monitor = StrainMonitor(backend, StrainHistory(_Cfg()))
    audio = np.zeros(16000, dtype=np.float32)
    fired = [i for i in range(len(readings)) if monitor.on_utterance(audio, 16000, i * 5.0)]
    assert backend.calls == len(readings)
    # None and the exception are skipped (not counted), so the 5th STRAINED fires.
    assert fired == [len(readings) - 1]


def test_monitor_ignores_non_finite_backend_reading():
    backend = _FakeBackend([Biomarkers(float("nan"), 0.1, 10.0)])
    monitor = StrainMonitor(backend, StrainHistory(_Cfg()))
    assert monitor.on_utterance([0.0], 16000, 0.0) is False
    assert monitor.history.baseline is None


def test_suggestion_text_fits_a_windows_balloon():
    assert len(BREAK_SUGGESTION_TITLE) < 64
    assert len(BREAK_SUGGESTION_BODY) <= 256
    assert "not a diagnosis" in BREAK_SUGGESTION_BODY


def test_module_does_not_import_parselmouth_at_module_scope():
    src = Path(__file__).resolve().parents[1] / "src/yazses/voicehealth/biomarkers.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    top = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top.add(node.module.split(".")[0])
    assert "parselmouth" not in top and "numpy" not in top


# ---- ParselmouthBiomarkers --------------------------------------------------------

def _vowel(f0: float = 150.0, seconds: float = 1.0, sr: int = 16000,
           noise: float = 0.0, seed: int = 0) -> np.ndarray:
    """A synthetic sustained vowel: a harmonic series at *f0*, plus optional noise."""
    t = np.arange(int(seconds * sr)) / sr
    wave = sum((1.0 / k) * np.sin(2 * np.pi * k * f0 * t) for k in range(1, 15))
    wave = 0.3 * wave / np.max(np.abs(wave))
    if noise:
        wave = wave + noise * np.random.default_rng(seed).standard_normal(t.size)
    return wave.astype(np.float32)


def _perturbed_vowel(f0: float = 150.0, seconds: float = 1.0, sr: int = 16000, *,
                     period_sd: float = 0.0, amplitude_sd: float = 0.0,
                     seed: int = 0) -> np.ndarray:
    """A vowel built period by period: *period_sd* perturbs each period's length only
    (jitter), *amplitude_sd* scales each period's amplitude only (shimmer)."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    bounds, amps = [0.0], []
    while bounds[-1] < seconds:
        bounds.append(bounds[-1] + (1.0 / f0) * (1.0 + period_sd * rng.standard_normal()))
        amps.append(1.0 + amplitude_sd * rng.standard_normal())
    edges, gains = np.array(bounds), np.array(amps)
    idx = np.searchsorted(edges, t, side="right") - 1
    phase = 2 * np.pi * (idx + (t - edges[idx]) / (edges[idx + 1] - edges[idx]))
    wave = sum((1.0 / k) * np.sin(k * phase) for k in range(1, 15)) * gains[idx]
    return (0.3 * wave / np.max(np.abs(wave))).astype(np.float32)


def test_parselmouth_backend_returns_none_without_the_extra(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "parselmouth", None)
    assert ParselmouthBiomarkers().measure(_vowel(), 16000) is None


@needs_parselmouth
def test_parselmouth_measures_a_clean_sustained_vowel():
    reading = ParselmouthBiomarkers().measure(_vowel(), 16000)
    assert reading is not None and reading.is_finite()
    # A perfectly periodic synthetic vowel: near-zero perturbation, high HNR.
    assert 0.0 <= reading.jitter < 0.01
    assert 0.0 <= reading.shimmer < 0.05
    assert reading.hnr > 20.0
    assert reading.strain() < 0.25


@needs_parselmouth
def test_parselmouth_noise_raises_strain():
    clean = ParselmouthBiomarkers().measure(_vowel(), 16000)
    noisy = ParselmouthBiomarkers().measure(_vowel(noise=0.08), 16000)
    assert clean is not None and noisy is not None
    assert noisy.hnr < clean.hnr
    assert noisy.strain() > clean.strain()


@needs_parselmouth
def test_parselmouth_rejects_silence_and_too_short_audio():
    backend = ParselmouthBiomarkers()
    assert backend.measure(np.zeros(16000, dtype=np.float32), 16000) is None
    assert backend.measure(_vowel(seconds=0.1), 16000) is None  # ~15 periods < 50
    assert backend.measure(np.zeros(0, dtype=np.float32), 16000) is None


@needs_parselmouth
def test_parselmouth_feeds_the_monitor():
    monitor = StrainMonitor(ParselmouthBiomarkers(), StrainHistory(_Cfg()))
    for i in range(5):
        assert monitor.on_utterance(_vowel(seed=i), 16000, float(i)) is False
    baseline = monitor.history.baseline
    assert baseline is not None and math.isfinite(baseline) and baseline < 0.25


@needs_parselmouth
def test_parselmouth_jitter_tracks_period_perturbation_only():
    # Period lengths vary with a 2 % standard deviation, amplitude is constant. Local
    # jitter of i.i.d. Gaussian periods is about 1.13 x 2 % (E|a-b| = 2*sd/sqrt(pi));
    # Praat measured 0.0213 here. RAP/PPQ5 measured ~0.013 and DDP ~0.037, so the band
    # also catches the wrong jitter command, and the near-zero shimmer catches a swap.
    clean = ParselmouthBiomarkers().measure(_perturbed_vowel(), 16000)
    jittered = ParselmouthBiomarkers().measure(_perturbed_vowel(period_sd=0.02), 16000)
    assert clean is not None and jittered is not None
    assert jittered.jitter > 100 * max(clean.jitter, 1e-6)
    assert 0.016 < jittered.jitter < 0.03
    assert jittered.shimmer < 0.01


@needs_parselmouth
def test_parselmouth_shimmer_tracks_amplitude_perturbation_only():
    # Each period's amplitude varies with a 15 % standard deviation, period length is
    # constant. Praat measured local shimmer 0.108 here (APQ3 0.058, DDA 0.175), and
    # jitter stays near zero, so swapping the two fields fails this test.
    clean = ParselmouthBiomarkers().measure(_perturbed_vowel(), 16000)
    shimmered = ParselmouthBiomarkers().measure(_perturbed_vowel(amplitude_sd=0.15), 16000)
    assert clean is not None and shimmered is not None
    assert shimmered.shimmer > 100 * max(clean.shimmer, 1e-6)
    assert 0.07 < shimmered.shimmer < 0.15
    assert shimmered.jitter < 0.002
