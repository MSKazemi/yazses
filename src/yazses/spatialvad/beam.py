"""GCC-PHAT time-delay estimate + spatial gate (pure) — ADR-v2-098.

Estimate the inter-mic time delay (reverberation-robust phase transform), convert it to an arrival
angle, and gate windows outside a tolerance around the user's seat. Pure numpy; no model.
"""
from __future__ import annotations

import math

import numpy as np

_SPEED_OF_SOUND = 343.0   # m/s


def gcc_phat(sig_l, sig_r, fs: int = 16000, max_tau=None, interp: int = 1) -> float:
    """Estimate the delay (s) of ``sig_l`` relative to ``sig_r`` via GCC-PHAT. Pure.

    Positive → the left channel lags (source toward the right mic).
    """
    a = np.asarray(sig_l, dtype=float)
    b = np.asarray(sig_r, dtype=float)
    n = a.shape[0] + b.shape[0]
    A = np.fft.rfft(a, n=n)
    B = np.fft.rfft(b, n=n)
    R = A * np.conj(B)
    denom = np.abs(R)
    denom[denom == 0.0] = 1e-12
    cc = np.fft.irfft(R / denom, n=interp * n)
    max_shift = interp * n // 2
    if max_tau is not None:
        max_shift = min(int(interp * fs * max_tau), max_shift)
    cc = np.concatenate((cc[-max_shift:], cc[:max_shift + 1]))
    shift = int(np.argmax(np.abs(cc))) - max_shift
    return shift / float(interp * fs)


def tdoa_to_angle(tau: float, mic_distance_m: float = 0.14) -> float:
    """Convert a time-delay (s) to an arrival angle in degrees (−90…+90). Pure."""
    if mic_distance_m <= 0.0:
        return 0.0
    ratio = tau * _SPEED_OF_SOUND / mic_distance_m
    ratio = max(-1.0, min(1.0, ratio))
    return math.degrees(math.asin(ratio))


def spatial_gate(angle: float, target_angle: float = 0.0, tolerance_deg: float = 35.0) -> bool:
    """Return ``True`` (keep) if ``angle`` is within ``tolerance_deg`` of the target. Pure."""
    return abs(angle - target_angle) <= tolerance_deg
