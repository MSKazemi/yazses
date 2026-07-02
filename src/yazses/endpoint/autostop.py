"""Hands-free auto-stop decision (pure) — ADR-v2-029.

Decide when to end a tap-and-speak turn: trailing silence exceeds the timeout, or the turn
hits a hard max-duration cap. Pure and deterministic; the semantic (Smart Turn v2) refinement
lives behind the ``turn`` extra and only tightens the silence decision when present.
"""
from __future__ import annotations


def should_stop(silence_ms, elapsed_ms, config) -> bool:
    """Return True when a hands-free turn should end.

    Ends when ``elapsed_ms`` reaches ``max_duration_ms`` (hard safety cap, checked first) or
    trailing ``silence_ms`` reaches ``silence_timeout_ms``. Disabled config never stops
    (caller keeps its own boundary). Pure.
    """
    if not getattr(config, "enabled", False):
        return False
    max_ms = float(getattr(config, "max_duration_ms", 30000))
    if max_ms > 0 and elapsed_ms >= max_ms:
        return True
    silence_timeout = float(getattr(config, "silence_timeout_ms", 800))
    return silence_ms >= silence_timeout
