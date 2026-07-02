"""Speaking-style analytics (pure) — ADR-v2-035.

Compute communication-style metrics from transcript text (+ optional spoken duration):
filler-word rate, words-per-minute, and vocabulary diversity. Pure and deterministic; no new
dependency. Aggregation over history lives in the caller (opt-in encrypted corpus).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Conservative default filler set. Single words plus a few common multi-word fillers.
_FILLERS_SINGLE = frozenset(
    ["um", "uh", "er", "ah", "erm", "hmm", "like", "basically", "actually", "literally"]
)
_FILLERS_MULTI = ("you know", "i mean", "sort of", "kind of")


@dataclass(frozen=True)
class SpeechStats:
    """Communication-style summary of one utterance (or a concatenation)."""
    words: int
    filler_count: int
    filler_rate: float          # fillers / words, 0..1
    wpm: float                  # words per minute (0.0 when duration unknown)
    type_token_ratio: float     # unique / total words, 0..1


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def count_fillers(text: str) -> int:
    """Count filler words/phrases (multi-word phrases counted first). Pure."""
    low = f" {' '.join(_words(text))} "
    n = 0
    for phrase in _FILLERS_MULTI:
        n += low.count(f" {phrase} ")
        low = low.replace(f" {phrase} ", "  ")
    n += sum(1 for w in low.split() if w in _FILLERS_SINGLE)
    return n


def filler_rate(text: str) -> float:
    """Fillers per word in ``[0, 1]``; 0.0 for empty text. Pure."""
    total = len(_words(text))
    return count_fillers(text) / total if total else 0.0


def words_per_minute(word_count: int, duration_s: float) -> float:
    """Words per minute; 0.0 when duration is non-positive. Pure."""
    return word_count / (duration_s / 60.0) if duration_s and duration_s > 0 else 0.0


def type_token_ratio(text: str) -> float:
    """Unique-word fraction in ``[0, 1]``; 0.0 for empty text. Pure."""
    ws = _words(text)
    return len(set(ws)) / len(ws) if ws else 0.0


def analyze(text: str, duration_s: float = 0.0) -> SpeechStats:
    """Full :class:`SpeechStats` for ``text`` spoken over ``duration_s`` seconds. Pure."""
    ws = _words(text)
    total = len(ws)
    fillers = count_fillers(text)
    return SpeechStats(
        words=total,
        filler_count=fillers,
        filler_rate=(fillers / total if total else 0.0),
        wpm=words_per_minute(total, duration_s),
        type_token_ratio=(len(set(ws)) / total if total else 0.0),
    )
