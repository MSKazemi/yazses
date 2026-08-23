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
            status = probe_backend(
                backend, adapter=adapter, requires=requires, extra=extra
            )
            if status.available:
                # The adapter imported and every dependency the probe knows about
                # is present, so the probe has nothing to report -- and pasting its
                # "is available" onto this caller's "unavailable:" prefix produced a
                # message that contradicted itself in a single sentence, while
                # discarding the one thing that would have helped: the exception.
                #
                # It is reachable, not theoretical. The probe answers from
                # `importlib.util.find_spec`, which reports whether a package is on
                # disk, never whether it imports -- and Resemblyzer pulls in
                # `webrtcvad`, whose first line is `import pkg_resources`, removed
                # from setuptools in 81.0.0. So a correctly installed
                # `voiceprint-resemblyzer` extra raises ModuleNotFoundError on a
                # current setuptools and the user was told the backend was
                # available. `recimport/factory.py` already guards this; the two
                # were written from the same shape and only one got the fix.
                return str(exc)
            if status.implemented or status.missing:
                return status.message
    except Exception:  # pragma: no cover - diagnostics must never mask the real error
        pass
    return str(exc)
