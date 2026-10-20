"""Prosody → punctuation decision engine (pure) — ADR-v2-104.

Insert sentence/clause punctuation from prosodic cues (pause duration, pitch declination reset,
terminal rise). Pure and deterministic; the F0/energy extraction is the lazy extra.
"""
from __future__ import annotations


def boundary_marks(
    count: int,
    pause_after_ms,
    pitch_reset=None,
    terminal_rise=None,
    sentence_pause_ms: float = 700.0,
    comma_pause_ms: float = 250.0,
    reset_threshold: float = 0.5,
) -> list[str]:
    """The mark (``"."``, ``"?"``, ``","`` or ``""``) that follows each of ``count`` tokens. Pure.

    A sentence boundary (a long pause, or a pitch reset with at least a comma-length pause) takes
    ``?`` when ``terminal_rise`` is set, else ``.``; a medium pause alone takes ``,``.
    Cue lists shorter than ``count`` are padded with "no cue".
    """
    marks: list[str] = []
    for i in range(count):
        pause = pause_after_ms[i] if i < len(pause_after_ms) else 0.0
        reset = pitch_reset[i] if pitch_reset is not None and i < len(pitch_reset) else 0.0
        rise = bool(terminal_rise[i]) if terminal_rise is not None and i < len(terminal_rise) else False
        is_sentence = pause >= sentence_pause_ms or (reset >= reset_threshold and pause >= comma_pause_ms)
        if is_sentence:
            marks.append("?" if rise else ".")
        elif pause >= comma_pause_ms:
            marks.append(",")
        else:
            marks.append("")
    return marks


def punctuate_from_prosody(
    tokens,
    pause_after_ms,
    pitch_reset=None,
    terminal_rise=None,
    sentence_pause_ms: float = 700.0,
    comma_pause_ms: float = 250.0,
    reset_threshold: float = 0.5,
) -> str:
    """Punctuate ``tokens`` from per-token prosodic cues. Pure.

    A sentence boundary (a long pause, or a pitch reset with at least a comma-length pause) takes
    ``?`` when ``terminal_rise`` is set, else ``.``; a medium pause alone takes ``,``.
    """
    toks = list(tokens or ())
    marks = boundary_marks(
        len(toks), pause_after_ms, pitch_reset, terminal_rise,
        sentence_pause_ms, comma_pause_ms, reset_threshold,
    )
    return " ".join(tok + mark for tok, mark in zip(toks, marks))
