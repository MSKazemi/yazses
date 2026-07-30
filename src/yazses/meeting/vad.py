"""Meeting-mode VAD backend selection — ADR-v2-127 (P4).

The utterance segmenter needs an ``is_silent(chunk) -> bool`` predicate. Meeting Mode
lets ``[meeting] vad_backend`` choose between the always-available calibrated RMS gate
(``audio/vad_calibrated.py``) and an optional Silero neural VAD. :func:`build_is_silent`
is the single factory the daemon calls; it degrades gracefully to the calibrated gate
whenever Silero is unselected, its optional dependency is absent, or the model fails to
load — mirroring the diarizer's graceful-degrade (``recimport.factory.build_diarizer``),
so a misconfigured backend never breaks capture.

The pure selection/fallback logic here is fully unit-testable; the heavy Silero loader
lives behind the optional ``silero`` extra in :mod:`yazses.meeting.silero_vad` and is
imported lazily only when actually selected.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np

log = logging.getLogger(__name__)

IsSilent = Callable[[np.ndarray], bool]


def _build_silero(config) -> IsSilent | None:
    """Build the Silero predicate, or ``None`` if the optional backend is unavailable.

    Isolated so tests can monkeypatch it; the real loader (torch/onnx) rides in with the
    optional ``silero`` extra and is exercised on hardware, not in CI.
    """
    from yazses.meeting.silero_vad import make_silero_is_silent  # optional `silero` extra

    return make_silero_is_silent(config)


def build_is_silent(config, accessibility) -> IsSilent:
    """Return the ``is_silent`` predicate for *config*'s ``vad_backend``.

    Defaults to the calibrated RMS gate. ``vad_backend = "silero"`` selects the neural
    VAD; if its dependency/model is missing it logs and falls back to calibrated, so the
    meeting still records with a working segmenter.
    """
    from yazses.audio.vad_calibrated import is_silent_calibrated

    def calibrated(chunk: np.ndarray) -> bool:
        return is_silent_calibrated(chunk, accessibility)

    backend = (getattr(config, "vad_backend", "calibrated") or "calibrated").lower()
    if backend != "silero":
        return calibrated
    try:
        predicate = _build_silero(config)
    except Exception as exc:
        log.warning("Silero VAD unavailable (%s); using the calibrated gate.", exc)
        return calibrated
    if predicate is None:
        log.warning("Silero VAD not built; using the calibrated gate.")
        return calibrated
    return predicate
