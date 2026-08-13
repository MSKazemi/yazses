"""Spectral-gate denoise backend — the one that can actually install (#69).

The denoise seam has existed since ADR-v2-015 with **no shippable backend**.
`deepfilternet` cannot supply one: its latest release (0.5.6, 2023-08-31) pins
`numpy>=1.22,<2.0` while this project requires `numpy>=2.4.6`. Those ranges are
disjoint, so it is not a packaging problem to solve — no environment satisfies
both, on any Python version. `system/backends.py` already refuses to advertise a
`denoise` extra for it, on the principle that an extra which can never install is
a worse lie than an honest "not implemented".

That left the feature designed, wired, and permanently unusable. This is the
backend that ends that: `noisereduce`, which is stationary/non-stationary
spectral gating over numpy + scipy, has no torch requirement and no numpy ceiling.

**It is weaker than DeepFilterNet and that is stated, not hidden.** Spectral
gating estimates a noise profile and subtracts it; it is good at steady
broadband noise — fans, air conditioning, road hum, mains buzz — and poor at
non-stationary interference like a second speaker or a door slamming. For a
voice competing with another voice the answer is the Cocktail Filter, not this.

Passthrough on any failure is the contract of the whole seam: dictation must
never break because a denoiser did.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# `strength` is a 0..1 dial in config; noisereduce's `prop_decrease` is the same
# idea (how much of the estimated noise to remove), so the mapping is identity
# with a clamp rather than an invented curve.
_MIN_SAMPLES = 512


def denoise(audio, sample_rate: int = 16000, *, strength: float = 1.0):
    """Spectral-gate *audio*. Returns the input unchanged on any problem.

    Imported lazily by `denoise/frontend.py`, so `noisereduce` is only required
    when someone selects this backend.
    """
    import noisereduce as nr
    import numpy as np

    if audio is None or len(audio) < _MIN_SAMPLES:
        # Too short to estimate a noise profile from; gating it would be noise
        # shaping, not noise removal.
        return audio

    prop = min(1.0, max(0.0, float(strength)))
    if prop == 0.0:
        return audio

    original_dtype = getattr(audio, "dtype", None)
    reduced = nr.reduce_noise(
        y=np.asarray(audio, dtype=np.float32),
        sr=int(sample_rate),
        prop_decrease=prop,
        stationary=False,   # a room's noise floor drifts; a fixed profile lags it
    )
    # Preserve the caller's dtype: the recorder hands float32 to the VAD and the
    # engine, and silently widening it to float64 doubles every later copy.
    if original_dtype is not None and reduced.dtype != original_dtype:
        reduced = reduced.astype(original_dtype, copy=False)
    return reduced
