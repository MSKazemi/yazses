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

        status = probe_backend(
            backend,
            adapter="yazses.denoise.deepfilter",
            requires=("df",),
            extra=None,  # there is no `denoise` extra — probe reports this honestly
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
    try:
        from yazses.denoise.deepfilter import denoise as _df  # lazy heavy import
        return _df(audio, sample_rate, strength=float(getattr(config, "strength", 1.0)))
    except Exception as exc:
        _warn_unavailable_once(backend, exc)
        return audio  # passthrough on any failure — never break dictation
