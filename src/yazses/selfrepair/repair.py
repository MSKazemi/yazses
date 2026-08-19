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
    r"\b(\S+)\s+(" + "|".join(_EDIT_TERMS) + r")\s+(\S+)", re.IGNORECASE
)

#: Words that make "<X> I mean" an ordinary English construction rather than a repair.
#: A bare "i mean" is one of the commonest phrases in the language, and this rule DELETES
#: the word before it, so an unguarded match silently removes real speech:
#:
#:     "that is not what I mean at all"  ->  "that is not at all"
#:     "do you know what I mean"         ->  "do you at all" (etc.)
#:
#: Applied only to the bare term. The explicit markers -- "no I mean", "make that",
#: "or rather" -- are unambiguous corrections and stay unrestricted, which is why the
#: shipped example ("email Sarah no I mean Sara") is unaffected.
_NOT_A_REPARANDUM = frozenset(
    "what know that which you we they i whatever how".split()
)
_BARE_I_MEAN = "i mean"


def _repair_one(m: re.Match) -> str:
    """The reparans, or the span untouched when this is ordinary English.

    A missed repair leaves the words as spoken and the user sees them. A false one
    deletes a word silently, in a dictation product, and may never be noticed -- so the
    ambiguous case resolves toward leaving the text alone.
    """
    reparandum, term, reparans = m.group(1), m.group(2), m.group(3)
    if term.strip().lower() == _BARE_I_MEAN and reparandum.lower() in _NOT_A_REPARANDUM:
        return m.group(0)
    return reparans


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
        new = _PATTERN.sub(_repair_one, out, count=1)
        if new == out:
            return new
        out = new
    # Unreachable in practice: each pass removes one reparandum+editing-term, so the text
    # strictly shrinks and converges in far fewer than 16 passes for any real utterance.
    return out  # pragma: no cover
