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


def diarization_status(config) -> dict:
    """Report diarization readiness *without* importing the heavy backend.

    Returns ``{requested, backend, extra_installed, models_present, ready}`` so callers
    (meeting start/status, doctor) can warn about a silent un-attributed transcript
    before it happens, instead of quietly degrading. Pure: only checks whether the
    ``sherpa-onnx`` module is importable and whether the model files exist on disk.
    """
    import importlib.util

    from yazses.recimport.diarizer import models_present

    requested = bool(getattr(config, "diarize", False))
    backend = getattr(config, "backend", "sherpa")
    extra = importlib.util.find_spec("sherpa_onnx") is not None
    models = models_present(config)
    ready = requested and backend == "sherpa" and extra and models
    return {
        "requested": requested, "backend": backend,
        "extra_installed": extra, "models_present": models, "ready": ready,
    }


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
