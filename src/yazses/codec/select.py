"""Streaming-codec STT engine selection (pure) — ADR-v2-022.

Decide whether to route decoding to the low-latency neural-codec streaming engine
(Kyutai/Mimi) or the default faster-whisper. Pure; the codec engine is heavy, lazy behind
the ``codec`` extra, and dormant unless enabled + available.
"""
from __future__ import annotations


def select_engine(config) -> str:
    """Return the STT engine key: ``"codec"`` or ``"whisper"`` (default).

    Returns ``"codec"`` only when codec streaming is enabled with a real backend; any
    other combination keeps the default faster-whisper engine, so an unconfigured or
    heavy-backend setup never changes decoding behavior. Pure and deterministic.
    """
    if not getattr(config, "enabled", False):
        return "whisper"
    backend = str(getattr(config, "backend", "none") or "none").lower()
    return "codec" if backend not in ("", "none") else "whisper"
