"""Noise-suppression front-end dispatch (guarded) — ADR-v2-015.

``apply_denoise`` returns the input audio unchanged when denoise is off or its
backend is unavailable, and otherwise runs the lazy DeepFilterNet backend. It never
raises: any backend error falls back to the original audio so dictation is never
broken by enhancement.
"""
from __future__ import annotations


def apply_denoise(audio, config, sample_rate: int = 16000):
    """Return denoised audio, or the input unchanged when off/unavailable.

    Off by default (``[denoise] enabled = false``) → identity passthrough. When
    enabled with ``backend = deepfilternet``, lazily imports the backend; if the
    ``denoise`` extra isn't installed (or anything fails), returns the original
    audio. Pure/guarded from the caller's perspective.
    """
    if not getattr(config, "enabled", False):
        return audio
    backend = str(getattr(config, "backend", "none") or "none").lower()
    if backend in ("", "none"):
        return audio
    try:
        from yazses.denoise.deepfilter import denoise as _df  # lazy heavy import
        return _df(audio, sample_rate, strength=float(getattr(config, "strength", 1.0)))
    except Exception:
        return audio  # passthrough on any failure — never break dictation
