"""Turn routing for two-way interpreting (pure) — ADR-v2-044.

Parse a language pair and route each turn to a translation direction based on its detected
language. Pure and deterministic; the S2S/translation model lives elsewhere.
"""
from __future__ import annotations


def parse_pair(pair: str):
    """Parse ``"en-es"`` → ``("en", "es")``. Raises ValueError on a malformed pair. Pure."""
    parts = [p.strip().lower() for p in (pair or "").split("-")]
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"invalid language pair: {pair!r}")
    return parts[0], parts[1]


def route_turn(detected_lang: str, pair: str):
    """Return the ``(source, target)`` direction for a turn, or ``None``. Pure.

    When the detected language is one side of the pair, translate into the other side; a
    language outside the pair returns ``None`` (don't translate).
    """
    a, b = parse_pair(pair)
    lang = (detected_lang or "").strip().lower()
    if lang == a:
        return (a, b)
    if lang == b:
        return (b, a)
    return None
