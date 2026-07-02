"""Framing / overlap-add / target-mask plumbing (pure numpy) — ADR-v2-084.

The signal-processing scaffolding for target-speaker extraction: window a signal into frames,
attenuate frames whose target-speaker score is low, and reconstruct. Pure; the TSE model that
scores frames lives elsewhere.
"""
from __future__ import annotations

import numpy as np


def frame_signal(signal, frame_len: int, hop: int):
    """Slice ``signal`` into overlapping frames of ``frame_len`` at stride ``hop``. Pure."""
    sig = np.asarray(signal, dtype=float)
    if frame_len <= 0 or hop <= 0 or len(sig) < frame_len:
        return np.empty((0, max(frame_len, 0)))
    n = 1 + (len(sig) - frame_len) // hop
    return np.stack([sig[i * hop:i * hop + frame_len] for i in range(n)])


def apply_target_mask(frames, scores, threshold: float, floor: float = 0.0):
    """Attenuate frames whose ``scores`` fall below ``threshold`` (multiply by ``floor``). Pure."""
    f = np.asarray(frames, dtype=float)
    if f.size == 0:
        return f
    s = np.asarray(scores, dtype=float)
    mask = np.where(s >= threshold, 1.0, floor)
    return f * mask[:, None]


def overlap_add(frames, hop: int):
    """Reconstruct a signal from Hann-windowed frames via normalized overlap-add. Pure."""
    f = np.asarray(frames, dtype=float)
    if f.size == 0:
        return np.zeros(0)
    n, flen = f.shape
    out_len = (n - 1) * hop + flen
    out = np.zeros(out_len)
    norm = np.zeros(out_len)
    window = np.hanning(flen) if flen > 1 else np.ones(flen)
    for i in range(n):
        out[i * hop:i * hop + flen] += f[i] * window
        norm[i * hop:i * hop + flen] += window
    norm[norm == 0] = 1.0
    return out / norm
