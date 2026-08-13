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
            "Diarization backend %r unavailable: %s. Producing a plain transcript.",
            backend, _unavailable_detail(backend, exc),
        )
        return None


def _unavailable_detail(backend: str, exc: Exception) -> str:
    """Explain *why* a diarization backend failed, without misdirecting the user.

    The backends ship behind *different* extras — ``diarization`` is sherpa-onnx,
    ``diarization-pyannote`` is pyannote.audio — so a blanket "install the
    `diarization` extra" would send a pyannote user after a package that cannot
    supply what they selected. Route the message through the shared probe so each
    case names its own extra.

    Only sherpa gets the ``--download-models`` hint: pyannote fetches its
    pretrained pipeline itself on first construction, so telling a pyannote user
    to run a sherpa model download would be a second wrong instruction.
    """
    try:
        from yazses.system.backends import probe_backend

        adapters = {
            "sherpa": ("yazses.recimport.diarizer", ("sherpa_onnx",), "diarization"),
            "pyannote": (
                "yazses.recimport.pyannote_backend",
                ("pyannote.audio",),
                "diarization-pyannote",
            ),
        }
        if backend in adapters:
            adapter, requires, extra = adapters[backend]
            status = probe_backend(
                backend, adapter=adapter, requires=requires, extra=extra
            )
            if backend == "sherpa" and status.implemented:
                return (
                    f"{status.message} and run `yazses transcribe --download-models`"
                )
            return status.message
    except Exception:  # pragma: no cover - diagnostics must never mask the real error
        pass
    return str(exc)
