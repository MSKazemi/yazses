"""On-screen term harvesting (pure) — ADR-v2-051.

Mine proper-noun/identifier-like tokens from visible text sources (accessibility nodes,
clipboard/selection) to prime Whisper's initial_prompt. Pure and deterministic; the OCR pixel
path lives behind the ``screenocr`` extra.
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _is_interesting(tok: str) -> bool:
    """A token worth priming: proper noun, camel/Pascal/snake identifier, or acronym. Pure."""
    if len(tok) < 2:
        return False
    if "_" in tok:
        return True                                    # snake_case identifier
    if tok.isupper():
        return True                                    # ACRONYM
    if tok[0].isupper():
        return True                                    # Capitalized / PascalCase
    if any(c.isupper() for c in tok[1:]):
        return True                                    # camelCase
    return False


def extract_terms(text: str) -> list:
    """Return the interesting tokens from one text blob, in order. Pure."""
    return [t for t in _TOKEN.findall(text or "") if _is_interesting(t)]


def harvest_terms(sources, max_terms: int = 32) -> list:
    """Dedup (case-insensitive, first spelling wins) + cap interesting terms across sources. Pure."""
    seen: dict = {}
    for src in sources:
        for t in extract_terms(src or ""):
            key = t.lower()
            if key not in seen:
                seen[key] = t
                if len(seen) >= max_terms:
                    return list(seen.values())
    return list(seen.values())
