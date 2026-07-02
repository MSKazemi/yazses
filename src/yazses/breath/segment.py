"""Breath envelope + onset detection + breath-group segmentation (pure) — ADR-v2-099.

Recover inhalation onsets from a microphone envelope and group tokens into breath chunks. Pure numpy;
no model.
"""
from __future__ import annotations

import numpy as np


def breath_envelope(audio, fs: int, smooth_s: float = 0.05) -> np.ndarray:
    """Rectified, moving-average-smoothed amplitude envelope. Pure."""
    a = np.abs(np.asarray(audio, dtype=float))
    if a.size == 0:
        return a
    win = max(1, int(fs * smooth_s))
    kernel = np.ones(win) / win
    return np.convolve(a, kernel, mode="same")


def detect_breath_onsets(env, fs: int, min_gap_s: float = 1.0,
                         rel_threshold: float = 0.6):
    """Return onset times (s) where the envelope crosses up through a relative threshold. Pure.

    Onsets closer together than ``min_gap_s`` are debounced.
    """
    e = np.asarray(env, dtype=float)
    if e.size == 0:
        return []
    peak = float(np.max(e))
    if peak <= 0.0:
        return []
    thr = rel_threshold * peak
    onsets = []
    last = -1e9
    above = False
    for i in range(e.size):
        t = i / fs
        if e[i] >= thr:
            if not above and t - last >= min_gap_s:
                onsets.append(t)
                last = t
            above = True
        else:
            above = False
    return onsets


def segment_by_breath(tokens, token_times, breath_onsets):
    """Group tokens into breath chunks — a breath onset before a token starts a new group. Pure."""
    toks = list(tokens or ())
    if not toks:
        return []
    onsets = sorted(breath_onsets or ())
    groups = []
    cur = []
    oi = 0
    for tok, t in zip(toks, token_times):
        while oi < len(onsets) and onsets[oi] <= t:
            if cur:
                groups.append(" ".join(cur))
                cur = []
            oi += 1
        cur.append(tok)
    if cur:
        groups.append(" ".join(cur))
    return groups
