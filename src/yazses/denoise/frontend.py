"""Noise-suppression front-end dispatch (guarded) — ADR-v2-015.

``apply_denoise`` returns the input audio unchanged when denoise is off or its
backend is unavailable, and otherwise runs the lazy DeepFilterNet backend. It never
raises: any backend error falls back to the original audio so dictation is never
broken by enhancement.

Degrading is silent to the *audio* but not to the *user*: enabling ``[denoise]`` and
then getting untouched audio with no explanation is indistinguishable from the
feature working badly, so the first fallback per backend logs why (matching the
"never degrade silently" rule the Meeting Mode model-availability warning follows).
The warning is emitted once per backend, not per dictation burst — this runs on the
hot path for every hold.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Backends already reported as unavailable — keeps the warning to once per process
# instead of once per dictation burst.
_warned: set[str] = set()


def _warn_unavailable_once(backend: str, exc: Exception) -> None:
    """Explain the passthrough the first time *backend* fails. Never raises."""
    if backend in _warned:
        return
    _warned.add(backend)
    try:
        from yazses.system.backends import probe_backend

        # Per-backend, because they fail for opposite reasons: `spectral` is
        # missing a package you can install, while `deepfilternet` has no adapter
        # and can never get one (numpy<2.0 vs this project's numpy>=2.4.6, #69) —
        # so it must be offered no remedy at all.
        if backend == "spectral":
            status = probe_backend(
                backend,
                adapter="yazses.denoise.spectral",
                requires=("noisereduce",),
                extra="denoise",
            )
        else:
            status = probe_backend(
                backend,
                adapter="yazses.denoise.deepfilter",
                requires=("df",),
                extra=None,  # nothing to install — see the module docstring
            )
        detail = status.message
    except Exception:  # pragma: no cover - diagnostics must never break dictation
        detail = f"{backend!r} unavailable ({exc})"
    log.warning(
        "Denoise is enabled but %s. Audio is passed through unprocessed.", detail
    )


def apply_denoise(audio, config, sample_rate: int = 16000):
    """Return denoised audio, or the input unchanged when off/unavailable.

    Off by default (``[denoise] enabled = false``) → identity passthrough. When
    enabled with ``backend = deepfilternet``, lazily imports the backend; if the
    backend is unavailable (or anything fails), returns the original audio and logs
    why once. Pure/guarded from the caller's perspective.
    """
    if not getattr(config, "enabled", False):
        return audio
    backend = str(getattr(config, "backend", "none") or "none").lower()
    if backend in ("", "none"):
        return audio
    strength = float(getattr(config, "strength", 1.0))
    try:
        if backend == "spectral":
            # The only backend that can actually install: deepfilternet pins
            # numpy<2.0 against this project's numpy>=2.4.6 (#69).
            from yazses.denoise.spectral import denoise as run_spectral

            return run_spectral(audio, sample_rate, strength=strength)
        from yazses.denoise.deepfilter import denoise as run_deepfilter  # lazy heavy

        return run_deepfilter(audio, sample_rate, strength=strength)
    except Exception as exc:
        _warn_unavailable_once(backend, exc)
        return audio  # passthrough on any failure — never break dictation
