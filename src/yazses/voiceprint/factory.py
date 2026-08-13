"""Speaker-embedder factory (dormancy + graceful degradation).

``build_embedder`` returns ``None`` when ``[voiceprint] enabled = false`` (dormant)
or when the optional ``voiceprint`` extra (speechbrain / resemblyzer) is not
installed — callers treat ``None`` as "no voiceprint available" and stay dormant,
so nothing crashes and no model downloads unless explicitly enabled (ADR-011).
"""
from __future__ import annotations

import logging

from yazses.voiceprint.base import SpeakerEmbedder

log = logging.getLogger(__name__)


def build_embedder(config) -> SpeakerEmbedder | None:
    """Return a speaker embedder for *config*, or None when dormant/unavailable."""
    if not getattr(config, "enabled", False):
        return None

    backend = getattr(config, "backend", "ecapa")
    try:
        if backend == "ecapa":
            from yazses.voiceprint.ecapa import EcapaEmbedder

            return EcapaEmbedder(config)
        if backend == "resemblyzer":
            from yazses.voiceprint.resemblyzer_backend import ResemblyzerEmbedder

            return ResemblyzerEmbedder(config)
        log.warning("Unknown voiceprint backend %r; voiceprint disabled.", backend)
        return None
    except Exception as exc:
        log.warning(
            "Voiceprint backend %r unavailable: %s. "
            "Voiceprint-dependent features stay dormant.",
            backend, _unavailable_detail(backend, exc),
        )
        return None


def _unavailable_detail(backend: str, exc: Exception) -> str:
    """Explain *why* a backend failed, without misdirecting the user.

    The two backends are alternatives shipped behind *different* extras —
    ``voiceprint`` is speechbrain/ECAPA, ``voiceprint-resemblyzer`` is
    Resemblyzer — so a single blanket "install the `voiceprint` extra" would send
    half the users after a package that cannot supply what they selected. Route
    the message through the shared probe so each case names its own extra.
    """
    try:
        from yazses.system.backends import probe_backend

        adapters = {
            "ecapa": ("yazses.voiceprint.ecapa", ("speechbrain",), "voiceprint"),
            "resemblyzer": (
                "yazses.voiceprint.resemblyzer_backend",
                ("resemblyzer",),
                "voiceprint-resemblyzer",
            ),
        }
        if backend in adapters:
            adapter, requires, extra = adapters[backend]
            return probe_backend(
                backend, adapter=adapter, requires=requires, extra=extra
            ).message
    except Exception:  # pragma: no cover - diagnostics must never mask the real error
        pass
    return str(exc)
