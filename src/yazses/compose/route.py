"""Compose-mode routing + plausibility guard (pure) — ADR-v2-049.

Decide the translation direction for compose mode and reject implausible MT output. Pure and
deterministic; the MT model lives behind the ``translate`` extra.
"""
from __future__ import annotations


def compose_route(source: str, target: str):
    """Return ``(source, target)`` for compose mode, or ``None`` when same/blank. Pure."""
    s = (source or "").strip().lower()
    t = (target or "").strip().lower()
    if not s or not t or s == t:
        return None
    return (s, t)


def is_plausible(src_text: str, out_text: str, max_ratio: float = 3.0, min_ratio: float = 0.25) -> bool:
    """Reject MT output whose length ratio vs the source is implausible. Pure.

    Empty source → any output is implausible (nothing to translate); non-empty source with empty
    output is implausible (the model dropped the text).
    """
    s = len(src_text or "")
    o = len(out_text or "")
    if s == 0:
        return False
    if o == 0:
        return False
    ratio = o / s
    return min_ratio <= ratio <= max_ratio
