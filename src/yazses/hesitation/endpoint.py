"""Filled-pause detection + hesitation-aware endpoint rule (pure) — ADR-v2-101.

Detect a filled hesitation (flat, spectrally-stable vocalization) and extend the endpoint threshold
so the speaker is not cut off. Pure and deterministic; the F0/spectral extraction is the lazy extra.
"""
from __future__ import annotations


def is_filled_pause(f0_series, spectral_stability: float,
                    f0_range_max: float = 25.0, stability_min: float = 0.7) -> bool:
    """True if the trailing vocalization is a filled pause (flat F0, stable spectrum). Pure.

    ``spectral_stability`` is a 0–1 measure of how steady the spectral envelope is (a sustained
    vowel/nasal is high). A filled pause has a small F0 range *and* high stability.
    """
    voiced = [f for f in (f0_series or ()) if f and f > 0]
    if not voiced:
        return False
    f0_range = max(voiced) - min(voiced)
    return f0_range <= f0_range_max and spectral_stability >= stability_min


def endpoint_decision(silence_ms: float, last_was_filled_pause: bool,
                      commit_ms: float = 800.0, hold_extra_ms: float = 1200.0) -> str:
    """Return ``"commit"`` or ``"hold"`` for the current trailing silence. Pure.

    The commit threshold is extended by ``hold_extra_ms`` right after a filled pause.
    """
    threshold = commit_ms + (hold_extra_ms if last_was_filled_pause else 0.0)
    return "commit" if silence_ms >= threshold else "hold"
