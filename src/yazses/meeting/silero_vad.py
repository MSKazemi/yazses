"""Silero neural VAD backend for Meeting Mode (optional ``silero`` extra) — ADR-v2-127.

An ``is_silent(chunk) -> bool`` predicate backed by the Silero VAD ONNX model, offered as
an alternative to the calibrated RMS gate for noisier rooms. Heavy and optional: imported
lazily and only when ``[meeting] vad_backend = "silero"``; absent extra → the factory in
:mod:`yazses.meeting.vad` falls back to the calibrated gate. On-device only (ADR-011):
`silero-vad` ships its ONNX inside the wheel, so choosing this backend downloads no model
and revalidates nothing — which is why it is the one model load in the tree that needs no
`system/hfcache.load_cache_first` wrapper (`tests/test_model_cache_first.py::_BUNDLED`).

**The extra is expensive, and this docstring used to say the opposite.** It claimed "the
ONNX path avoids a torch dependency"; it does not. `silero-vad` declares `torch`
unconditionally (and `torchaudio` too, before 6.2.3) — not behind its own `onnx-cpu`
extra — and imports torch at module scope, and its ONNX wrapper takes torch tensors, so
the ONNX path avoids torch only at the model's *weights*. Measured 2026-08-23 (on 6.2.1)
against this project's venv, `pip install yazses[silero]` resolves to **25 distributions,
~3.0 GB**, most of it the NVIDIA CUDA stack (`nvidia-cublas` 543 MB, `torch` 527 MB,
`nvidia-cudnn` 445 MB) on a CPU-only offline dictation tool. That is the same trap ADR-018
was written about for `speechbrain`, and the reason `[meeting] vad_backend` says so where
the choice is actually made. The default calibrated RMS gate costs nothing and is what
almost every room should use. Exercised on hardware, not in CI.

Since `silero-vad` 6.2.3 (the floor here since 2026-11-20) `torchaudio` is optional
upstream and `torch` alone is required; `onnxruntime` became optional upstream in 6.2.1,
which is why the `silero` extra names it itself. The ONNX file and the
``load_silero_vad(onnx=True)`` call are unchanged from 5.1.2; only the weights inside
`silero_vad/data/silero_vad.onnx` differ (the v6 model).
"""
from __future__ import annotations

import logging
from collections.abc import Callable

import numpy as np

log = logging.getLogger(__name__)

_WINDOW = 512  # Silero's fixed frame size at 16 kHz


def make_silero_is_silent(config) -> Callable[[np.ndarray], bool] | None:
    """Return a Silero-backed ``is_silent`` predicate, or ``None`` if unavailable.

    Loads the ONNX Silero model once; the returned predicate reports a chunk silent when
    no 512-sample window in it reaches ``silero_threshold`` speech probability.

    **The model takes a torch tensor, not an ndarray.** ``OnnxWrapper.__call__`` (5.1.2
    through 6.2.3) starts with ``x.dim()``, which an ndarray does not have, so passing
    the numpy slice straight in raised ``AttributeError`` on the first voiced chunk.
    Each window is wrapped with ``torch.from_numpy`` (no copy); torch is already a hard
    dependency of ``silero-vad``. The call returns a ``(1, 1)`` probability tensor;
    ``tests/test_meeting_silero_contract.py`` pins both halves of that contract.
    """
    try:
        import torch
        from silero_vad import load_silero_vad
    except Exception as exc:
        log.warning("`silero` extra not installed (%s).", exc)
        return None

    model = load_silero_vad(onnx=True)
    threshold = float(getattr(config, "silero_threshold", 0.5) or 0.5)
    sr = 16000

    def is_silent(chunk: np.ndarray) -> bool:
        arr = np.ascontiguousarray(np.asarray(chunk, dtype="float32").flatten())
        if arr.size < _WINDOW:
            return True
        peak = 0.0
        for i in range(0, arr.size - _WINDOW + 1, _WINDOW):
            prob = float(model(torch.from_numpy(arr[i:i + _WINDOW]), sr))
            if prob > peak:
                peak = prob
            if peak >= threshold:
                return False
        return peak < threshold

    return is_silent
