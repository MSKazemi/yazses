"""Hallucination Guard (pure) — ADR-v2-025.

Detect fabricated transcript content Whisper emits on silence/noise/breath so it never gets
typed: curated ghost phrases (whole-transcript-only), degenerate repetition loops, and — when
segment signals are available — the standard Whisper hallucination tells (no_speech_prob /
avg_logprob / compression_ratio). Pure and deterministic; conservative by design.
"""
from __future__ import annotations

import re

# Video-outro artefacts Whisper hallucinates on silence — phrases nobody dictates. Matched
# ONLY against the entire cleaned transcript (never as substrings), so real speech is safe.
_GHOST_PHRASES = frozenset(
    [
        "thanks for watching",
        "thank you for watching",
        "please subscribe",
        "subscribe to my channel",
        "like and subscribe",
        "don't forget to subscribe",
        "see you next time",
        "see you in the next video",
        "thanks for watching and i'll see you in the next video",
    ]
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (text or "").lower())).strip()


def is_ghost_phrase(text: str) -> bool:
    """True if the whole cleaned transcript is a known Whisper ghost/outro phrase. Pure."""
    return _norm(text) in _GHOST_PHRASES


def is_repetition_loop(text: str, min_repeats: int = 3) -> bool:
    """True if the text is dominated by one short phrase repeated ``min_repeats``+ times.

    Catches Whisper's degenerate loops ("the the the the", or a clause echoed many times).

    The repeated unit must cover the whole normalized text, **except that the last repeat
    may be cut short**. That allowance is the difference between catching real loops and
    catching only tidy ones: the decoder stops at a segment or token boundary, so a real
    loop usually ends part-way through a repeat. Taken from a live corpus, the text that
    was actually typed was

        each machete de shiramasun  x3  + "each"

    -- thirteen words. The previous rule required the unit to tile exactly (``n % unit``),
    and 13 is prime, so a textbook loop scored as ordinary speech and went to the injector.

    The trailing remainder must be a **prefix of the unit**, which is what an interrupted
    repeat looks like; anything else is a different phrase and the text is left alone.
    Pure.
    """
    words = _norm(text).split()
    n = len(words)
    if n < min_repeats:
        return False
    for unit in range(1, n // min_repeats + 1):
        block = words[:unit]
        reps = 0
        while words[reps * unit:(reps + 1) * unit] == block:
            reps += 1
        if reps < min_repeats:
            continue
        tail = words[reps * unit:]
        # An exact tiling (no tail) or a repeat interrupted mid-phrase both count. A tail
        # that is not the start of the unit means the loop ended and speech resumed.
        if tail == block[:len(tail)]:
            return True
    return False


def segment_is_hallucination(no_speech_prob, avg_logprob, compression_ratio, config) -> bool:
    """Signal gate using Whisper's per-segment tells. Any ``None`` signal is skipped. Pure.

    Flags a segment when it is very likely silence (``no_speech_prob`` high) or the decode is
    low-confidence (``avg_logprob`` low) or degenerate/repetitive (``compression_ratio`` high).
    """
    ns = float(getattr(config, "no_speech_threshold", 0.6))
    lp = float(getattr(config, "logprob_threshold", -1.0))
    cr = float(getattr(config, "compression_ratio_threshold", 2.4))
    if no_speech_prob is not None and no_speech_prob >= ns:
        return True
    if avg_logprob is not None and avg_logprob <= lp:
        return True
    if compression_ratio is not None and compression_ratio >= cr:
        return True
    return False


def should_drop(text, config) -> bool:
    """Text-level decision (ghost phrase or repetition loop) honouring config toggles. Pure."""
    if not getattr(config, "enabled", False):
        return False
    if getattr(config, "drop_ghost_phrases", True) and is_ghost_phrase(text):
        return True
    if getattr(config, "drop_loops", True) and is_repetition_loop(text):
        return True
    return False


def ghost_words() -> frozenset[str]:
    """Every word that appears in a known ghost phrase.

    Exposed for the learning loop. `yazses tune` mines terms that a correction
    contained and the live transcript did not, and proposes priming them into
    Whisper's ``initial_prompt``. Whisper's own silence hallucinations are exactly
    that shape — a clip decodes to "Thanks for watching", the user's re-dictation
    does not contain those words, and the miner reads them as vocabulary the model
    keeps failing to hear.

    Priming them is the one thing an ``initial_prompt`` must never do: it biases the
    decoder *toward* the phrase this module exists to delete. Observed on a real
    corpus, where the top proposal opened with `for you thanks watching`.
    """
    return frozenset(word for phrase in _GHOST_PHRASES for word in phrase.split())
