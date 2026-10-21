"""Synthetic voiced signals for the pitch-tracker, hesitation and contour tests.

One generator rather than one per test file, so every test of `yazses.audio.pitch` and its two
consumers agrees on what "a hum" is. Nothing here is recorded audio: AGENTS.md forbids real user
audio in fixtures, and a synthetic tone has a known F0 to check the tracker against.

A "hum" is a harmonic tone (five partials, each 0.6x the previous) whose F0 follows ``f0`` — a
constant, or a function of time in seconds — plus optional Gaussian noise. Amplitudes are in the
range this project's microphones actually deliver (mean |x| of a few thousandths), not full scale.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

SR = 16000


def hum(f0: float | Callable[[np.ndarray], np.ndarray], seconds: float, *, amp: float = 0.01,
        noise: float = 0.0, seed: int = 0, ramp_s: float = 0.0, sr: int = SR) -> np.ndarray:
    """A harmonic tone whose instantaneous F0 (Hz) is ``f0``, as float32 mono.

    ``ramp_s`` fades the tone in and out with a raised cosine, as a voice does; without it
    the tone switches on at full level, and the frames straddling that edge read as unsteady.
    """
    t = np.arange(int(round(sr * seconds))) / sr
    freq = f0(t) if callable(f0) else np.full(t.size, float(f0))
    phase = 2.0 * np.pi * np.cumsum(freq) / sr
    x = sum((0.6 ** k) * np.sin((k + 1) * phase) for k in range(5)) * amp
    n_ramp = min(int(round(sr * ramp_s)), t.size // 2)
    if n_ramp:
        fade = 0.5 - 0.5 * np.cos(np.linspace(0.0, np.pi, n_ramp))
        x[:n_ramp] *= fade
        x[-n_ramp:] *= fade[::-1]
    if noise:
        x = x + np.random.default_rng(seed).normal(0.0, noise, t.size)
    return np.asarray(x, dtype=np.float32)


def glide(start_hz: float, end_hz: float, seconds: float) -> Callable[[np.ndarray], np.ndarray]:
    """A linear F0 glide from ``start_hz`` to ``end_hz`` over ``seconds``."""
    return lambda t: start_hz + (end_hz - start_hz) * (t / seconds)


def silence(seconds: float, sr: int = SR) -> np.ndarray:
    return np.zeros(int(round(sr * seconds)), dtype=np.float32)


def white_noise(seconds: float, level: float = 0.01, seed: int = 1, sr: int = SR) -> np.ndarray:
    return np.random.default_rng(seed).normal(0.0, level, int(round(sr * seconds))).astype(
        np.float32
    )


#: Average adult-male formants (Hz), Peterson & Barney, "Control methods used in a study of the
#: vowels", JASA 24(2):175-184, 1952, Table II: F1, F2, F3.
PETERSON_BARNEY_MALE = {
    "i": (270.0, 2290.0, 3010.0),
    "a": (730.0, 1090.0, 2440.0),
    "u": (300.0, 870.0, 2240.0),
}


def _resonator_ir(freq: float, bw: float, sr: int) -> np.ndarray:
    """Impulse response of the two-pole resonator ``1 / (1 - 2r cos(th) z^-1 + r^2 z^-2)``."""
    r = float(np.exp(-np.pi * bw / sr))
    th = 2.0 * np.pi * freq / sr
    n = np.arange(int(np.ceil(np.log(1e-6) / np.log(r))) + 1)
    return (r ** n) * np.sin((n + 1) * th) / np.sin(th)


def vowel(formants: tuple[float, ...], seconds: float, *, f0: float = 120.0, amp: float = 0.01,
          bandwidths: tuple[float, ...] = (60.0, 90.0, 120.0, 175.0), f4: float = 3500.0,
          sr: int = SR) -> np.ndarray:
    """A source-filter vowel: an impulse train at ``f0`` through resonators at ``formants``.

    The source is shaped by a double pole at ``0.97`` (the glottal -12 dB/octave roll-off) and
    the output by a first difference (lip radiation, +6 dB/octave), the classic Fant/Klatt
    cascade. ``f4`` is appended as a fixed higher formant. The result is scaled to RMS ``amp``.
    """
    n = int(round(sr * seconds))
    src = np.zeros(n)
    src[(np.arange(0.0, seconds, 1.0 / f0) * sr).astype(int)] = 1.0
    k = np.arange(400)
    x = np.convolve(src, (k + 1) * 0.97 ** k)[:n]
    for freq, bw in zip((*formants, f4), bandwidths, strict=False):
        x = np.convolve(x, _resonator_ir(freq, bw, sr))[:n]
    x = np.append(x[0], np.diff(x))
    x = x / float(np.sqrt(np.mean(x * x))) * amp
    return np.asarray(x, dtype=np.float32)
