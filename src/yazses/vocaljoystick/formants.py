"""Per-frame F1/F2 + loudness + pitch producer for the Vocal Joystick (pure numpy, ADR-v2-095).

``control.py`` maps a ``(F1, F2)`` pair to a direction and integrates ``(direction, loudness,
pitch)`` frames into cursor motion, but nothing measured those three numbers. This module is the
producer: one :class:`VocalFrame` per 10 ms hop, from arbitrarily sized chunks, with only numpy
(a base dependency) — so it needs no optional extra and imports on every supported platform.

**Formants** are estimated by linear prediction, the textbook way (Markel & Gray, *Linear
Prediction of Speech*, Springer 1976; Rabiner & Schafer, *Digital Processing of Speech Signals*,
Prentice-Hall 1978, ch. 8): pre-emphasis (``1 - 0.97 z^-1``) to flatten the glottal tilt, a
Hamming window, the autocorrelation method solved by Levinson-Durbin, then the roots of the
prediction polynomial. A complex root ``r e^{j theta}`` is a resonance at
``theta * fs / (2 pi)`` Hz with bandwidth ``-ln|r| * fs / pi`` Hz; roots whose bandwidth is wider
than ``max_bandwidth_hz`` (spectral-shaping poles, not vocal-tract resonances) or whose frequency
is below ``min_formant_hz`` are dropped, and F1/F2 are the two lowest survivors.

**Pitch** is not re-implemented here: each frame calls :func:`yazses.audio.pitch.yin_f0`, the
shared YIN producer, with the same 40 ms frame / 10 ms hop as
:class:`yazses.audio.pitch.PitchTracker`. ``pitch_hz`` is ``0.0`` when unvoiced, the convention
that module already set.

**Loudness** is the frame RMS in dBFS mapped linearly onto ``[0, 1]`` between ``floor_db`` and
``ceil_db`` — monotonic in gain, which is all ``vocal_control_vector`` needs (it clamps to
``[0, 1]`` and multiplies by ``max_speed``).

The formant analysis uses the centred ``formant_ms`` of each pitch frame: a 40 ms window is
needed for YIN's 60 Hz floor, but it smears formant motion, and 25 ms is the usual LPC window.

What is checked: synthetic source-filter vowels (an impulse train through resonators at known
formants, ``tests/synthetic_voice.py``) recover F1/F2 within tolerance and order /i/ /u/ /a/
correctly (``tests/test_vocaljoystick_formants.py``). What is **not** checked: real recorded
speech, high-pitched voices whose harmonics sample the envelope sparsely (LPC is known to bias
toward a harmonic there), and nasalised or breathy vowels. The direction thresholds in
``control.py`` remain speaker-general, as the ADR says.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from yazses.audio.pitch import (
    FMAX_HZ,
    FMIN_HZ,
    FRAME_MS,
    HOP_MS,
    SILENCE_RMS,
    YIN_THRESHOLD,
    yin_f0,
)
from yazses.vocaljoystick.control import vowel_to_direction

#: LPC analysis window, centred inside each pitch frame.
FORMANT_MS = 25
#: Pre-emphasis coefficient (first-order high-pass) applied before LPC.
PRE_EMPHASIS = 0.97
#: Roots wider than this are spectral-shaping poles, not formants.
MAX_BANDWIDTH_HZ = 400.0
#: Roots below this are the glottal/DC region, not F1.
MIN_FORMANT_HZ = 90.0
#: Loudness mapping: dBFS that reads as 0 and as 1. Microphones here deliver an RMS of about
#: 0.01 (-40 dBFS) for ordinary voice (``tests/synthetic_voice.py``), so -60..-20 brackets it.
LOUDNESS_FLOOR_DB = -60.0
LOUDNESS_CEIL_DB = -20.0


def lpc_order(sample_rate: int) -> int:
    """The rule-of-thumb LPC order: two poles per kHz of bandwidth, plus two. Pure."""
    return 2 + int(sample_rate) // 1000


def lpc(frame, order: int) -> np.ndarray:
    """Prediction polynomial ``[1, a1, ..., ap]`` by autocorrelation + Levinson-Durbin. Pure.

    Returns ``[1, 0, ..., 0]`` (no resonances) for a frame too short or with no energy, so a
    caller never has to special-case silence.
    """
    x = np.asarray(frame, dtype=np.float64).ravel()
    a = np.zeros(order + 1)
    a[0] = 1.0
    if order < 1 or x.size <= order:
        return a
    # Only lags 0..order are needed: O(n * order), not the O(n^2) of a full correlation.
    r = np.array([float(np.dot(x[:x.size - k], x[k:])) for k in range(order + 1)])
    err = float(r[0])
    if err <= 0.0:
        return a
    for i in range(1, order + 1):
        acc = r[i] + float(np.dot(a[1:i], r[i - 1:0:-1]))
        k = -acc / err
        a[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a[i] = k
        err *= 1.0 - k * k
        if err <= 0.0:
            break
    return a


def formant_candidates(frame, sample_rate: int, order: int | None = None, *,
                       pre_emphasis: float = PRE_EMPHASIS,
                       max_bandwidth_hz: float = MAX_BANDWIDTH_HZ,
                       min_formant_hz: float = MIN_FORMANT_HZ) -> list[tuple[float, float]]:
    """Every accepted ``(frequency_hz, bandwidth_hz)`` resonance, lowest first. Pure."""
    x = np.asarray(frame, dtype=np.float64).ravel()
    if x.size < 4:
        return []
    x = x - x.mean()
    if float(np.sqrt(np.mean(x * x))) < SILENCE_RMS:
        return []
    x = np.append(x[0], x[1:] - pre_emphasis * x[:-1])
    x = x * np.hamming(x.size)
    a = lpc(x, lpc_order(sample_rate) if order is None else order)
    if not np.any(a[1:]):
        return []
    roots = np.roots(a)
    roots = roots[np.imag(roots) > 0.0]
    nyquist = sample_rate / 2.0
    out: list[tuple[float, float]] = []
    for z in roots:
        freq = float(np.angle(z)) * sample_rate / (2.0 * math.pi)
        mag = float(abs(z))
        if mag <= 0.0:
            continue
        bw = -math.log(mag) * sample_rate / math.pi
        if min_formant_hz <= freq < nyquist - 50.0 and 0.0 < bw <= max_bandwidth_hz:
            out.append((freq, bw))
    out.sort()
    return out


def estimate_formants(frame, sample_rate: int, order: int | None = None,
                      **kwargs) -> tuple[float, float] | None:
    """``(F1, F2)`` in Hz for one frame, or ``None`` when fewer than two resonances survive."""
    cands = formant_candidates(frame, sample_rate, order, **kwargs)
    if len(cands) < 2:
        return None
    return cands[0][0], cands[1][0]


def loudness(rms: float, floor_db: float = LOUDNESS_FLOOR_DB,
             ceil_db: float = LOUDNESS_CEIL_DB) -> float:
    """Frame RMS mapped from ``[floor_db, ceil_db]`` dBFS onto ``[0, 1]``. Pure, monotonic."""
    if ceil_db <= floor_db:
        raise ValueError("ceil_db must be above floor_db")
    if not rms > 0.0:
        return 0.0
    db = 20.0 * math.log10(rms)
    return float(min(1.0, max(0.0, (db - floor_db) / (ceil_db - floor_db))))


@dataclass(frozen=True)
class VocalFrame:
    """One analysis frame, in the shape :meth:`VocalJoystick.feed` consumes.

    ``f1_hz``/``f2_hz`` are ``0.0`` when no formant pair was found; ``pitch_hz`` is ``0.0``
    when unvoiced. ``direction`` is ``None`` unless the frame is voiced *and* has formants,
    so breath noise and silence never steer the cursor.
    """

    t_s: float
    f1_hz: float
    f2_hz: float
    pitch_hz: float
    voiced: bool
    rms: float
    loudness: float
    direction: str | None

    def joystick_args(self) -> tuple[str | None, float, float]:
        """``(vowel_dir, loudness, pitch)`` — the positional arguments of ``VocalJoystick.feed``."""
        return self.direction, self.loudness, self.pitch_hz


class VocalFrameTracker:
    """Chunk-in, :class:`VocalFrame`-out streaming tracker. Pure state, no threads.

    Framing matches :class:`yazses.audio.pitch.PitchTracker`: frame ``k`` covers samples
    ``[k*hop, k*hop + frame)`` of everything fed since :meth:`reset`, so a burst fed whole and
    the same burst fed in pieces give the same frames.
    """

    def __init__(self, sample_rate: int = 16000, frame_ms: int = FRAME_MS, hop_ms: int = HOP_MS,
                 formant_ms: int = FORMANT_MS, *, fmin: float = FMIN_HZ, fmax: float = FMAX_HZ,
                 yin_threshold: float = YIN_THRESHOLD, lpc_order_: int | None = None,
                 floor_db: float = LOUDNESS_FLOOR_DB, ceil_db: float = LOUDNESS_CEIL_DB,
                 deadzone: tuple[float, float] = (60.0, 200.0)) -> None:
        if sample_rate <= 0 or frame_ms <= 0 or hop_ms <= 0 or formant_ms <= 0:
            raise ValueError("sample_rate, frame_ms, hop_ms and formant_ms must be positive")
        if ceil_db <= floor_db:
            raise ValueError("ceil_db must be above floor_db")
        self.sample_rate = int(sample_rate)
        self.frame_len = max(8, int(round(sample_rate * frame_ms / 1000)))
        self.hop_len = max(1, int(round(sample_rate * hop_ms / 1000)))
        self.hop_s = self.hop_len / self.sample_rate
        flen = min(self.frame_len, max(8, int(round(sample_rate * formant_ms / 1000))))
        self._f_start = (self.frame_len - flen) // 2
        self._f_len = flen
        self._fmin = float(fmin)
        self._fmax = float(fmax)
        self._yin_threshold = float(yin_threshold)
        self._order = lpc_order(self.sample_rate) if lpc_order_ is None else int(lpc_order_)
        self._floor_db = float(floor_db)
        self._ceil_db = float(ceil_db)
        self._deadzone = deadzone
        self.reset()

    def reset(self) -> None:
        """Forget all audio; the next frame starts at ``t_s = 0``."""
        self._buf = np.zeros(0, dtype=np.float64)
        self._index = 0

    def feed(self, chunk) -> list[VocalFrame]:
        """Append ``chunk`` (mono samples) and return every frame it completed."""
        x = np.asarray(chunk, dtype=np.float64).ravel()
        if x.size:
            self._buf = np.concatenate((self._buf, x)) if self._buf.size else x.copy()
        out: list[VocalFrame] = []
        start = 0
        while self._buf.size - start >= self.frame_len:
            out.append(self.analyse(self._buf[start:start + self.frame_len]))
            start += self.hop_len
        if start:
            self._buf = self._buf[start:]
        return out

    def analyse(self, frame: np.ndarray) -> VocalFrame:
        """Analyse one full-length frame and advance the frame clock."""
        f0, _periodicity = yin_f0(frame, self.sample_rate, self._fmin, self._fmax,
                                  self._yin_threshold)
        centred = frame - frame.mean()
        rms = float(np.sqrt(np.mean(centred * centred)))
        voiced = f0 > 0.0
        pair = None
        if voiced:
            pair = estimate_formants(frame[self._f_start:self._f_start + self._f_len],
                                     self.sample_rate, self._order)
        f1, f2 = pair if pair is not None else (0.0, 0.0)
        direction = (vowel_to_direction((f1, f2), self._deadzone)
                     if pair is not None else None)
        t_s = self._index * self.hop_s
        self._index += 1
        return VocalFrame(t_s=t_s, f1_hz=f1, f2_hz=f2, pitch_hz=f0, voiced=voiced, rms=rms,
                          loudness=loudness(rms, self._floor_db, self._ceil_db),
                          direction=direction)


def track(audio, sample_rate: int = 16000, **kwargs) -> list[VocalFrame]:
    """Every frame of a whole buffer, via one :class:`VocalFrameTracker`. Pure."""
    return VocalFrameTracker(sample_rate, **kwargs).feed(audio)
