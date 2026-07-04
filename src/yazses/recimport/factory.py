"""Diarizer factory (dormancy + graceful degradation) — ADR-v2-125.

``build_diarizer`` returns ``None`` when diarization is not requested, the backend is
``none``, or the optional ``diarization`` extra (sherpa-onnx) / its model files are
absent — callers then produce a plain, unattributed transcript instead of crashing.
Mirrors ``yazses.voiceprint.factory.build_embedder`` (ADR-011: nothing loads or
downloads unless explicitly enabled).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def build_diarizer(config):
    """Return a diarizer for *config*, or ``None`` when dormant/unavailable."""
    if not getattr(config, "diarize", False):
        return None

    backend = getattr(config, "backend", "sherpa")
    if backend == "none":
        return None
    try:
        if backend == "sherpa":
            from yazses.recimport.diarizer import SherpaDiarizer

            return SherpaDiarizer(config)
        if backend == "pyannote":
            from yazses.recimport.pyannote_backend import PyannoteDiarizer

            return PyannoteDiarizer(config)
        log.warning("Unknown diarization backend %r; diarization disabled.", backend)
        return None
    except Exception as exc:
        log.warning(
            "Diarization backend %r unavailable (%s); install the `diarization` extra "
            "and run `yazses transcribe --download-models`. Producing a plain transcript.",
            backend, exc,
        )
        return None
