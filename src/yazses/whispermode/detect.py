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


def burst_is_whispered(
    audio,
    fs: int,
    voicing_max: float = 0.3,
    tilt_min: float = -1.0,
    frame_ms: int = 64,
    max_frames: int = 24,
    level_floor: float = 1e-4,
) -> bool:
    """Whole-burst whisper decision for the sotto-voce command channel. Pure.

    Frames the burst, keeps only frames with audible energy (silence between
    words has no phonation either way), and takes the *median* per-frame
    verdict inputs — a majority of frames must look whispered, so one breathy
    word inside voiced speech doesn't flip the burst. At most ``max_frames``
    frames are analysed, spread evenly across the burst, so the decision cost
    stays flat no matter how long the hold was.
    """
    x = np.asarray(audio, dtype=float).ravel()
    step = max(1, int(fs * frame_ms / 1000))
    frames = [x[i:i + step] for i in range(0, x.size - step + 1, step)]
    frames = [f for f in frames if float(np.abs(f).mean()) >= level_floor]
    if not frames:
        return False
    if len(frames) > max_frames:
        idx = np.linspace(0, len(frames) - 1, max_frames).astype(int)
        frames = [frames[i] for i in idx]
    voicings = [voicing_ratio(f) for f in frames]
    tilts = [spectral_tilt(f, fs) for f in frames]
    feats = {"voicing": float(np.median(voicings)), "tilt": float(np.median(tilts))}
    return is_whispered(feats, voicing_max=voicing_max, tilt_min=tilt_min)


def whisper_adaptation(gain_db: float = 6.0, vad_scale: float = 0.5) -> dict:
    """Return the gain/VAD/prompt adjustments to apply while whisper is detected. Pure."""
    return {"gain_db": gain_db, "vad_scale": vad_scale, "prompt_hint": "whispered speech"}
