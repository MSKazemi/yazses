"""Per-word playback timeline built from TTS sentence chunks (pure) — ADR-v2-108.

``align.build_schedule`` needs a duration for every word, and no TTS backend reports one:
Kokoro synthesizes and plays a whole sentence at a time. What a backend *can* say cheaply
is, for each sentence chunk, how many samples it played, at what sample rate, and when
playback of that chunk began on the monotonic clock. This module turns that into a
per-word timeline and answers "which word was playing at monotonic time *t*?" — the
question a barge-in asks.

Each chunk's duration (``n_samples / sample_rate``) is spread over its words in
proportion to a per-word weight: :func:`char_weight` (letters and digits, the default)
or :func:`syllable_weight` (an English vowel-group heuristic). Both are estimates — the
chunk's own leading/trailing silence, comma pauses and the audio device's output latency
are not modelled. True forced alignment remains the later tier the ADR names.

Word indices are global across chunks and equal positions in ``text.split()`` of the
text that was chunked: ``tts.chunking.sentence_chunks`` splits only at whitespace and
strips each piece, so concatenating the chunks' ``split()`` lists reproduces the
original's. That is what lets a caller turn an index back into a place in the text.

Dependency-free (stdlib only). Nothing calls this yet; ``[proofback]`` stays dormant.
"""
from __future__ import annotations

import re
import threading
from bisect import bisect_right
from collections.abc import Callable, Iterable
from dataclasses import dataclass

Weight = Callable[[str], float]

_VOWEL_GROUP = re.compile(r"[aeiouy]+")


def char_weight(word: str) -> float:
    """Weight a word by its letter/digit count (Unicode-aware), never less than 1."""
    return float(max(1, sum(1 for ch in word if ch.isalnum())))


def syllable_weight(word: str) -> float:
    """Estimate syllables: vowel groups plus one per digit, never less than 1.

    An English heuristic. A word containing any non-ASCII letter falls back to
    :func:`char_weight`, so mixed-script text should use ``char_weight`` throughout
    rather than mixing the two scales.
    """
    letters = [ch for ch in word if ch.isalnum()]
    if any(not ch.isascii() for ch in letters):
        return char_weight(word)
    lower = "".join(letters).lower()
    groups = len(_VOWEL_GROUP.findall("".join(ch for ch in lower if not ch.isdigit())))
    # A final silent "e" ("make", "home") adds a vowel group but not a syllable;
    # "-le" ("table") is the usual exception.
    if groups > 1 and lower.endswith("e") and not lower.endswith("le"):
        groups -= 1
    digits = sum(1 for ch in lower if ch.isdigit())
    return float(max(1, groups + digits))


@dataclass(frozen=True)
class TimedWord:
    """One word's estimated playback interval on the monotonic clock, ``[start_s, end_s)``."""

    index: int
    text: str
    chunk: int
    start_s: float
    end_s: float


class PlaybackTimeline:
    """Accumulates sentence chunks as they start playing; maps a time to a word.

    ``add_chunk`` has the signature of a playback listener (``text, n_samples,
    sample_rate, started_at``) so a backend can report straight into it. A lock makes
    it safe to append on the playback thread while a barge-in queries on another.
    """

    def __init__(self, weight: Weight = char_weight) -> None:
        self._weight = weight
        self._lock = threading.Lock()
        self._words: list[TimedWord] = []
        self._starts: list[float] = []
        self._chunks = 0
        self._last_chunk_start: float | None = None

    @classmethod
    def contiguous(
        cls,
        chunks: Iterable[tuple[str, int]],
        sample_rate: int,
        start: float,
        weight: Weight = char_weight,
    ) -> PlaybackTimeline:
        """Build a timeline assuming the chunks play back to back from ``start``.

        Real playback has gaps (the next chunk is synthesized after the previous one
        finishes); a caller that can stamp each chunk should use ``add_chunk`` instead.
        """
        timeline = cls(weight)
        t = start
        for text, n_samples in chunks:
            timeline.add_chunk(text, n_samples, sample_rate, t)
            t += n_samples / sample_rate
        return timeline

    def add_chunk(self, text: str, n_samples: int, sample_rate: int, started_at: float) -> None:
        """Record that chunk *text* (``n_samples`` at ``sample_rate``) began at ``started_at``.

        A chunk with no words still counts as a chunk (its index is consumed) but
        contributes no word. Raises ``ValueError`` on a non-positive sample rate, a
        negative sample count, or a start earlier than the previous chunk's.
        """
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")
        if n_samples < 0:
            raise ValueError(f"n_samples must be non-negative, got {n_samples}")
        words = text.split()
        weights = [max(0.0, float(self._weight(w))) for w in words]
        total = sum(weights)
        duration = n_samples / sample_rate
        with self._lock:
            if self._last_chunk_start is not None and started_at < self._last_chunk_start:
                raise ValueError("chunks must be added in playback order")
            self._last_chunk_start = started_at
            chunk = self._chunks
            self._chunks += 1
            t = started_at
            for i, (w, wt) in enumerate(zip(words, weights, strict=True)):
                share = duration * (wt / total) if total > 0 else duration / len(words)
                # The last word ends exactly at the chunk's end, free of float drift.
                end = started_at + duration if i == len(words) - 1 else t + share
                self._words.append(TimedWord(len(self._words), w, chunk, t, end))
                self._starts.append(t)
                t = end

    @property
    def words(self) -> tuple[TimedWord, ...]:
        """Every word recorded so far, in playback order."""
        with self._lock:
            return tuple(self._words)

    def word_at(self, t: float, lag_s: float = 0.0) -> int:
        """Return the index of the word playing at monotonic time ``t``, or ``-1`` if empty.

        ``lag_s`` is subtracted from ``t`` first, for a caller that wants to allow for
        the listener's reaction time; the default applies none (ADR-v2-108 leaves the
        value open). Before the first word this clamps to word 0. In the silence
        between two chunks, and after the last chunk, it returns the last word that
        started — the word the listener most recently heard.
        """
        with self._lock:
            if not self._starts:
                return -1
            i = bisect_right(self._starts, t - lag_s) - 1
            return self._words[max(i, 0)].index

    def end_s(self) -> float | None:
        """The estimated end of the last recorded word, or ``None`` if empty."""
        with self._lock:
            return self._words[-1].end_s if self._words else None
