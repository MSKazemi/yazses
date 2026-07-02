"""Whisper detection features + adaptation (pure) — ADR-v2-100.

Compute voicing ratio and spectral tilt, decide whether a frame is whispered, and return the
gain/VAD/prompt adaptation. Pure numpy; no model.
"""
from __future__ import annotations

import numpy as np


def voicing_ratio(frame) -> float:
    """Normalized autocorrelation peak in the pitch-lag range (0=aperiodic, ~1=voiced). Pure."""
    x = np.asarray(frame, dtype=float)
    if x.size < 2:
        return 0.0
    x = x - x.mean()
    ac = np.correlate(x, x, mode="full")[x.size - 1:]
    if ac[0] == 0.0:
        return 0.0
    ac = ac / ac[0]
    lo = min(20, x.size - 1)
    tail = ac[lo:]
    if tail.size == 0:  # pragma: no cover - lo <= size-1 so tail always has >=1 element
        return 0.0
    return float(np.max(tail))


def spectral_tilt(frame, fs: int) -> float:
    """Least-squares slope of the log-magnitude spectrum vs log-frequency. Pure.

    Whispered speech is flatter (a less-negative slope) than voiced speech.
    """
    x = np.asarray(frame, dtype=float)
    if x.size < 4:
        return 0.0
    spec = np.abs(np.fft.rfft(x)) + 1e-9
    freqs = np.fft.rfftfreq(x.size, 1.0 / fs)
    logf = np.log(freqs[1:])
    logs = np.log(spec[1:])
    slope, _ = np.polyfit(logf, logs, 1)
    return float(slope)


def is_whispered(feats, voicing_max: float = 0.3, tilt_min: float = -1.0) -> bool:
    """True if features indicate whisper: low voicing *and* a flat (>= ``tilt_min``) tilt. Pure."""
    return feats.get("voicing", 1.0) <= voicing_max and feats.get("tilt", -5.0) >= tilt_min


def whisper_adaptation(gain_db: float = 6.0, vad_scale: float = 0.5) -> dict:
    """Return the gain/VAD/prompt adjustments to apply while whisper is detected. Pure."""
    return {"gain_db": gain_db, "vad_scale": vad_scale, "prompt_hint": "whispered speech"}
