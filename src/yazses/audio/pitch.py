"""Streaming F0 + spectral-flux frames over recorder audio (pure numpy, no model).

Two designed-but-unwired features need the same per-frame acoustics and nothing on main
produced them: Hesitation-Hold Endpointing (ADR-v2-101) reads an F0 series and a spectral
stability value, and Pitch-Contour Gestures (ADR-v2-103) read an F0 contour. The existing
voicing measures (``whispermode.detect.voicing_ratio``, ``involuntary.audio._frame_voiced``)
answer "is there a periodic peak?" but never say *which* frequency, and ``postprocess.prosody``
gets F0 from Praat via the optional ``parselmouth`` extra at word midpoints only, after the
burst is over. This module is the shared producer: one :class:`PitchFrame` per hop, from
arbitrarily sized chunks, with only numpy (a base dependency).

**F0** is YIN (de Cheveigné & Kawahara, "YIN, a fundamental frequency estimator for speech and
music", JASA 111(4), 2002): the cumulative-mean-normalised difference function, the first dip
under an absolute threshold, refined by parabolic interpolation. A frame is *voiced* when that
dip is under ``threshold``. YIN is amplitude-invariant, so the decision does not depend on the
microphone's gain; only exact digital silence (RMS under the fixed module constant
``SILENCE_RMS``, not a parameter) is short-circuited to unvoiced, because the normalised
difference is undefined there.

**Spectral flux** is the total-variation distance between consecutive frames' normalised power
spectra (Hann window, bins up to ``flux_max_hz``), in ``[0, 1]``: ``0`` for an unchanging
spectrum, ``1`` for disjoint ones. A sustained vowel or nasal stays near ``0``; a phoneme change
moves it. ``spectral_stability`` turns a run of fluxes into the ``0..1`` steadiness value that
``hesitation.endpoint.is_filled_pause`` takes.

Thresholds here are signal-processing defaults checked on synthetic tones and noise
(``tests/test_audio_pitch.py``). They have not been measured on real recorded speech.
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

#: Analysis window. 40 ms holds two periods of the 60 Hz floor (YIN needs lag <= window/2).
FRAME_MS = 40
#: One frame per hop. 10 ms is the usual speech-analysis hop.
HOP_MS = 10
#: Pitch search range. Covers adult speaking F0 and a hummed rise into the upper register.
FMIN_HZ = 60.0
FMAX_HZ = 500.0
#: YIN absolute threshold on the normalised difference (the paper uses 0.1-0.15).
YIN_THRESHOLD = 0.15
#: RMS below which a frame is digital silence (the normalised difference is undefined).
SILENCE_RMS = 1e-5
#: Upper edge of the band spectral flux is measured over (where voiced energy lives).
FLUX_MAX_HZ = 4000.0


@dataclass(frozen=True)
class PitchFrame:
    """Acoustics of one analysis frame.

    ``t_s`` is the frame's start, in seconds from the first sample fed since the last reset.
    ``f0_hz`` is ``0.0`` when the frame is unvoiced (the convention both pure cores already
    filter on). ``periodicity`` is ``1 - d'(tau)`` at the chosen lag, clipped to ``[0, 1]``.
    ``flux`` is NaN for a frame with nothing to compare with: the first frame after a reset, a
    digital-silence frame, and the first frame after one.
    """

    t_s: float
    f0_hz: float
    voiced: bool
    periodicity: float
    rms: float
    flux: float


def yin_f0(frame, sample_rate: int, fmin: float = FMIN_HZ, fmax: float = FMAX_HZ,
           threshold: float = YIN_THRESHOLD) -> tuple[float, float]:
    """``(f0_hz, periodicity)`` for one frame by YIN; ``f0_hz`` is ``0.0`` when unvoiced. Pure.

    The integration window is half the frame, so the frame must hold at least two periods of
    ``fmin`` for that floor to be searchable; the upper lag bound is clipped to what fits.
    """
    x = np.asarray(frame, dtype=np.float64).ravel()
    n = x.size
    w = n // 2
    tau_min = max(2, int(math.floor(sample_rate / fmax)))
    tau_max = min(w - 1, int(math.ceil(sample_rate / fmin)))
    if w < 4 or tau_max <= tau_min:
        return 0.0, 0.0
    x = x - x.mean()
    if float(np.sqrt(np.mean(x * x))) < SILENCE_RMS:
        return 0.0, 0.0
    # d(tau) = sum_{j<w} (x[j] - x[j+tau])^2 = e0 + e(tau) - 2 r(tau), for tau in [0, w).
    sq = np.concatenate(([0.0], np.cumsum(x * x)))
    taus = np.arange(w)
    e0 = sq[w]
    e_tau = sq[taus + w] - sq[taus]
    r = np.correlate(x, x[:w], mode="valid")[:w]
    d = np.maximum(e0 + e_tau - 2.0 * r, 0.0)
    # Cumulative-mean-normalised difference d'(tau); d'(0) = 1 by definition.
    cmnd = np.ones(w)
    running = np.cumsum(d[1:])
    with np.errstate(divide="ignore", invalid="ignore"):
        cmnd[1:] = np.where(running > 0, d[1:] * taus[1:] / running, 1.0)
    search = cmnd[tau_min:tau_max + 1]
    below = np.flatnonzero(search < threshold)
    if below.size:
        tau = tau_min + int(below[0])
        while tau + 1 <= tau_max and cmnd[tau + 1] < cmnd[tau]:
            tau += 1  # walk down to the bottom of this dip
    else:
        tau = tau_min + int(np.argmin(search))
    dip = float(cmnd[tau])
    periodicity = float(min(1.0, max(0.0, 1.0 - dip)))
    if dip >= threshold:
        return 0.0, periodicity
    # Parabolic interpolation around the dip for a sub-sample lag.
    shift = 0.0
    if 0 < tau < w - 1:
        a, b, c = cmnd[tau - 1], cmnd[tau], cmnd[tau + 1]
        denom = a - 2.0 * b + c
        if denom > 0:
            shift = float(min(0.5, max(-0.5, 0.5 * (a - c) / denom)))
    return float(sample_rate / (tau + shift)), periodicity


def _band_power(frame: np.ndarray, sample_rate: int, max_hz: float) -> np.ndarray:
    win = np.hanning(frame.size)
    power = np.abs(np.fft.rfft(frame * win)) ** 2
    freqs = np.fft.rfftfreq(frame.size, 1.0 / sample_rate)
    return power[freqs <= max_hz]


def spectral_flux(prev_power, power) -> float:
    """Total-variation distance between two power spectra, each normalised to sum 1. Pure.

    ``0`` = same spectral shape, ``1`` = disjoint. Two all-zero spectra are identical (``0``);
    one all-zero spectrum against a non-zero one is maximally different (``1``).
    """
    p = np.asarray(prev_power, dtype=np.float64)
    q = np.asarray(power, dtype=np.float64)
    sp, sq_ = float(p.sum()), float(q.sum())
    if sp <= 0.0 and sq_ <= 0.0:
        return 0.0
    if sp <= 0.0 or sq_ <= 0.0:
        return 1.0
    return float(min(1.0, 0.5 * np.abs(p / sp - q / sq_).sum()))


def spectral_stability(fluxes: Iterable[float]) -> float:
    """``1 - mean(flux)`` over the finite fluxes, in ``[0, 1]``; ``0.0`` if there are none. Pure.

    Returning ``0.0`` (unstable) for an empty run is the conservative side: a caller cannot
    read steadiness into frames that were never compared.
    """
    vals = [f for f in fluxes if f is not None and math.isfinite(f)]
    if not vals:
        return 0.0
    return float(min(1.0, max(0.0, 1.0 - sum(vals) / len(vals))))


class PitchTracker:
    """Chunk-in, :class:`PitchFrame`-out streaming tracker. Pure state, no threads.

    :meth:`feed` accepts chunks of any length (the recorder does not fix a block size) and
    returns the frames that became complete. Frame ``k`` covers samples
    ``[k*hop, k*hop + frame)`` of everything fed since :meth:`reset`, so a burst fed in one
    call and the same burst fed in pieces give the same frames.
    """

    def __init__(self, sample_rate: int = 16000, frame_ms: int = FRAME_MS, hop_ms: int = HOP_MS,
                 fmin: float = FMIN_HZ, fmax: float = FMAX_HZ,
                 threshold: float = YIN_THRESHOLD, flux_max_hz: float = FLUX_MAX_HZ) -> None:
        if sample_rate <= 0 or frame_ms <= 0 or hop_ms <= 0:
            raise ValueError("sample_rate, frame_ms and hop_ms must be positive")
        self.sample_rate = int(sample_rate)
        self.frame_len = max(8, int(round(sample_rate * frame_ms / 1000)))
        self.hop_len = max(1, int(round(sample_rate * hop_ms / 1000)))
        self.hop_s = self.hop_len / self.sample_rate
        self._fmin = float(fmin)
        self._fmax = float(fmax)
        self._threshold = float(threshold)
        self._flux_max_hz = float(flux_max_hz)
        self.reset()

    def reset(self) -> None:
        """Forget all audio; the next frame starts at ``t_s = 0`` with NaN flux."""
        self._buf = np.zeros(0, dtype=np.float64)
        self._index = 0
        self._prev_power: np.ndarray | None = None

    def feed(self, chunk) -> list[PitchFrame]:
        """Append ``chunk`` (mono samples) and return every frame it completed."""
        x = np.asarray(chunk, dtype=np.float64).ravel()
        if x.size:
            self._buf = np.concatenate((self._buf, x)) if self._buf.size else x.copy()
        out: list[PitchFrame] = []
        start = 0
        while self._buf.size - start >= self.frame_len:
            out.append(self._analyse(self._buf[start:start + self.frame_len]))
            start += self.hop_len
        if start:
            self._buf = self._buf[start:]
        return out

    def _analyse(self, frame: np.ndarray) -> PitchFrame:
        f0, periodicity = yin_f0(frame, self.sample_rate, self._fmin, self._fmax,
                                 self._threshold)
        centred = frame - frame.mean()
        rms = float(np.sqrt(np.mean(centred * centred)))
        if rms < SILENCE_RMS:
            # Digital silence has no spectral shape to be steady or unsteady about: comparing
            # two all-zero spectra would score a dropout as perfectly "stable".
            flux = math.nan
            self._prev_power = None
        else:
            power = _band_power(centred, self.sample_rate, self._flux_max_hz)
            flux = (math.nan if self._prev_power is None
                    else spectral_flux(self._prev_power, power))
            self._prev_power = power
        t_s = self._index * self.hop_s
        self._index += 1
        return PitchFrame(t_s=t_s, f0_hz=f0, voiced=f0 > 0.0, periodicity=periodicity,
                          rms=rms, flux=flux)


def track(audio, sample_rate: int = 16000, **kwargs) -> list[PitchFrame]:
    """Every frame of a whole buffer (a finished burst), via one :class:`PitchTracker`. Pure."""
    return PitchTracker(sample_rate, **kwargs).feed(audio)
