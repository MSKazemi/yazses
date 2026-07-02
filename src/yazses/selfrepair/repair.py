"""Mid-utterance self-repair (pure) — ADR-v2-058.

Replace "<reparandum> <editing-term> <reparans>" spans with the reparans, resolving chained
repairs. Pure and deterministic; the open-ended SpeechLLM classifier is deferred.
"""
from __future__ import annotations

import re

# Curated editing terms that mark a correction: the token before is dropped, the token after kept.
_EDIT_TERMS = (
    r"no,?\s+i mean",
    r"i mean",
    r"make that",
    r"or rather",
    r"no,?\s+make it",
    r"scratch that,?\s+i mean",
)
_PATTERN = re.compile(
    r"\b(\S+)\s+(?:" + "|".join(_EDIT_TERMS) + r")\s+(\S+)", re.IGNORECASE
)


def apply_self_repair(text: str) -> str:
    """Apply in-burst corrections, dropping each reparandum for its reparans. Pure.

    Loops so chained repairs ("A no I mean B no I mean C" → "C") fully resolve.
    """
    if not text:
        return text
    out = text
    # Replace one (leftmost) repair per pass and loop, so chained repairs resolve left-to-right
    # ("A no I mean B no I mean C" → "C") without an ambiguous editing term mis-splitting them.
    for _ in range(16):  # bounded: far more than any real chain of repairs
        new = _PATTERN.sub(r"\2", out, count=1)
        if new == out:
            return new
        out = new
    # Unreachable in practice: each pass removes one reparandum+editing-term, so the text
    # strictly shrinks and converges in far fewer than 16 passes for any real utterance.
    return out  # pragma: no cover
