"""Silero neural VAD backend for Meeting Mode (optional ``silero`` extra) — ADR-v2-127.

An ``is_silent(chunk) -> bool`` predicate backed by the Silero VAD ONNX model, offered as
an alternative to the calibrated RMS gate for noisier rooms. Heavy and optional: imported
lazily and only when ``[meeting] vad_backend = "silero"``; absent extra → the factory in
:mod:`yazses.meeting.vad` falls back to the calibrated gate. The ONNX path avoids a torch
dependency. On-device only (ADR-011). Exercised on hardware, not in CI.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np

log = logging.getLogger(__name__)

_WINDOW = 512  # Silero's fixed frame size at 16 kHz


def make_silero_is_silent(config) -> Callable[[np.ndarray], bool] | None:  # pragma: no cover - heavy, needs the `silero` extra
    """Return a Silero-backed ``is_silent`` predicate, or ``None`` if unavailable.

    Loads the ONNX Silero model once; the returned predicate reports a chunk silent when
    no 512-sample window in it reaches ``silero_threshold`` speech probability.
    """
    try:
        from silero_vad import load_silero_vad
    except Exception as exc:
        log.warning("`silero` extra not installed (%s).", exc)
        return None

    model = load_silero_vad(onnx=True)
    threshold = float(getattr(config, "silero_threshold", 0.5) or 0.5)
    sr = 16000

    def is_silent(chunk: np.ndarray) -> bool:
        arr = np.asarray(chunk, dtype="float32").flatten()
        if arr.size < _WINDOW:
            return True
        peak = 0.0
        for i in range(0, arr.size - _WINDOW + 1, _WINDOW):
            prob = float(model(arr[i:i + _WINDOW], sr))
            if prob > peak:
                peak = prob
            if peak >= threshold:
                return False
        return peak < threshold

    return is_silent
