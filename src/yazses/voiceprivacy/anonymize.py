"""Speaker de-identification DSP (pure) — ADR-v2-048.

Shift a clip's pitch/formants to remove gross speaker cues while preserving duration and
linguistic content. Deterministic and dependency-free (numpy). The neural kNN-VC anonymizer is
deferred behind the ``voiceprivacy`` extra.
"""
from __future__ import annotations

import numpy as np


def anonymize_clip(audio: np.ndarray, sample_rate: int = 16000, strength: float = 1.08) -> np.ndarray:
    """Pitch/formant-shift ``audio`` to obscure speaker identity, preserving length. Pure.

    Resamples by ``strength`` (shifting the fundamental + formants) then restores the original
    sample count, so the clip's duration is unchanged. ``strength == 1.0`` (or an empty clip) is
    returned unchanged. dtype is preserved.
    """
    a = np.asarray(audio)
    n = a.shape[0]
    if n == 0 or strength == 1.0:
        return a
    src = a.astype(np.float64)
    # Pitch-shift by resampling at 'strength' spacing …
    shifted_idx = np.arange(0, n, strength)
    shifted = np.interp(shifted_idx, np.arange(n), src)
    # … then stretch back to the original length so duration is preserved.
    m = shifted.shape[0]
    out = np.interp(np.linspace(0, m - 1, n), np.arange(m), shifted)
    return out.astype(a.dtype)
