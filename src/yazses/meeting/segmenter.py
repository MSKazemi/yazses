"""Continuous-audio → utterance segmentation (pure) — ADR-v2-127.

Meeting mode captures audio non-stop; the live-transcript view needs it cut into
utterance-sized chunks to feed the STT engine. ``UtteranceSegmenter`` does this with a
simple, dependency-free VAD state machine: accumulate voiced audio, and when trailing
silence exceeds ``hangover_ms`` (and the utterance is at least ``min_utterance_ms``),
emit the buffered utterance. The silence decision is an injected predicate, so the core
is pure and fully unit-testable with a fake VAD (the real one is ``vad_calibrated`` or
Silero, chosen by config in the daemon).
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np


class UtteranceSegmenter:
    """Group streamed audio chunks into utterances separated by silence. Pure."""

    def __init__(
        self,
        is_silent: Callable[[np.ndarray], bool],
        *,
        sample_rate: int = 16000,
        hangover_ms: int = 700,
        min_utterance_ms: int = 400,
        max_utterance_ms: int = 30000,
    ) -> None:
        self._is_silent = is_silent
        self._sr = sample_rate
        self._hangover = int(hangover_ms * sample_rate / 1000)
        self._min = int(min_utterance_ms * sample_rate / 1000)
        self._max = int(max_utterance_ms * sample_rate / 1000)
        self._buf: list[np.ndarray] = []
        self._buf_len = 0
        self._trailing_silence = 0
        self._voiced = False

    def push(self, chunk: np.ndarray) -> np.ndarray | None:
        """Feed one audio chunk; return a completed utterance ndarray, or ``None``.

        An utterance completes when trailing silence reaches ``hangover_ms`` after some
        voiced audio, or when the buffer reaches ``max_utterance_ms`` (a hard cut so a
        monologue still segments). Leading silence before any speech is discarded.
        """
        silent = bool(self._is_silent(chunk))
        n = int(np.asarray(chunk).shape[0])

        if not self._voiced:
            if silent:
                return None  # drop leading silence
            self._voiced = True

        self._buf.append(np.asarray(chunk, dtype="float32"))
        self._buf_len += n
        self._trailing_silence = self._trailing_silence + n if silent else 0

        if self._buf_len >= self._max:
            return self._flush()
        if self._trailing_silence >= self._hangover and self._buf_len >= self._min:
            return self._flush()
        return None

    def flush(self) -> np.ndarray | None:
        """Emit any buffered utterance (call at stop). ``None`` if nothing buffered."""
        if self._buf_len >= self._min:
            return self._flush()
        self._reset()
        return None

    def _flush(self) -> np.ndarray:
        audio = np.concatenate(self._buf) if self._buf else np.array([], dtype="float32")
        self._reset()
        return audio

    def _reset(self) -> None:
        self._buf = []
        self._buf_len = 0
        self._trailing_silence = 0
        self._voiced = False
