"""Accessibility Continuum — Whisper / Low-Effort Mode (pure) — ADR-v2-012.

Quiet-speech capture: lower the VAD threshold by a factor so whispered dictation
isn't discarded as silence. Pure threshold math; the daemon applies the result to
the VAD gate (via ``dataclasses.replace``). Semantic Capture is a separate opt-in
seam that reuses the LLM-cleanup path.
"""
from __future__ import annotations


def effective_vad_threshold(base_threshold: float, config) -> float:
    """Return the VAD threshold to use, lowered when Whisper Mode is active.

    When ``[continuum] enabled`` and ``whisper_mode`` are both set, the base
    threshold is scaled by ``whisper_threshold_factor`` (clamped to [0.01, 1.0]) so
    quiet speech passes the silence gate. Otherwise the base threshold is returned
    unchanged. Pure and deterministic.
    """
    if not (getattr(config, "enabled", False) and getattr(config, "whisper_mode", False)):
        return base_threshold
    raw = getattr(config, "whisper_threshold_factor", 1.0)
    factor = float(raw) if raw is not None else 1.0
    factor = min(1.0, max(0.01, factor))  # never zero or raise the gate
    return base_threshold * factor
