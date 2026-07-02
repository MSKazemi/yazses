"""Tone-aware formatting (pure) — ADR-v2-017.

Map a detected affect label + confidence onto light text formatting (terminal
``!``/``?``). Conservative by default (only clear excitement/question); expressive
mode widens the label set. Pure and deterministic — no model here; the SER backend
supplies the label and stays lazy behind the ``affect`` extra.
"""
from __future__ import annotations

# Affect label → terminal punctuation. Conservative acts only on unambiguous cases.
_CONSERVATIVE = {"excited": "!", "question": "?"}
_EXPRESSIVE = {
    "excited": "!", "happy": "!", "emphatic": "!", "angry": "!", "surprised": "!",
    "question": "?", "questioning": "?",
}


def format_affect(
    text: str,
    label: str,
    confidence: float = 1.0,
    *,
    mode: str = "conservative",
    min_confidence: float = 0.6,
) -> str:
    """Apply tone-driven terminal punctuation, or return ``text`` unchanged.

    No-ops (returns the input verbatim) when: text is blank; confidence is below
    ``min_confidence``; the label is neutral/unknown for the active ``mode``; or the
    text already ends in ``!``/``?``. A trailing period is replaced by the affect
    punctuation; trailing whitespace is preserved. Pure.
    """
    if not text or not text.strip():
        return text
    if confidence < min_confidence:
        return text
    table = _EXPRESSIVE if mode == "expressive" else _CONSERVATIVE
    want = table.get((label or "neutral").lower())
    if want is None:
        return text
    stripped = text.rstrip()
    trailing_ws = text[len(stripped):]
    if stripped[-1] in "!?":
        return text  # already expressive; don't stack punctuation
    if stripped[-1] == ".":
        stripped = stripped[:-1]
    return stripped + want + trailing_ws
