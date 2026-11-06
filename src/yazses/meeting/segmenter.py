"""Continuous-audio → utterance segmentation (pure) — ADR-v2-127.

Meeting mode captures audio non-stop; the live-transcript view needs it cut into
utterance-sized chunks to feed the STT engine. ``UtteranceSegmenter`` does this with a
simple, dependency-free VAD state machine: accumulate voiced audio, and when trailing
silence exceeds ``hangover_ms`` (and the utterance is at least ``min_utterance_ms``),
emit the buffered utterance. The silence decision is an injected predicate, so the core
is pure and fully unit-testable with a fake VAD (the real one is ``vad_calibrated`` or
Silero, chosen by config in the daemon).

It also knows *where* each utterance began, in samples from the first chunk ever
pushed (dropped leading silence included), and publishes that as ``last_start_s``.
The live transcript used to stamp a line with the clock at the moment its decode
*finished*, which is the utterance's end plus the hangover plus the decode time plus
any queue backlog (a hard cut at ``max_utterance_ms`` skips the hangover) -- so a line
was stamped at least its own utterance's length late, and lines kept
drifting later on a machine whose decoder could not keep up. The sample position is
the same timeline as ``audio.wav`` and the batch transcript's word timings.
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
        # Samples pushed so far (all of them, silent or not) and the index at which
        # the buffered utterance began. Both are audio-time, never wall-clock time.
        self._pos = 0
        self._start = 0
        self._last_start = 0

    @property
    def last_start_s(self) -> float:
        """Audio offset, in seconds, of the first sample of the last emitted utterance.

        Read it right after :meth:`push` or :meth:`flush` returns an utterance. ``0.0``
        before any utterance has been emitted.
        """
        return self._last_start / self._sr if self._sr else 0.0

    def push(self, chunk: np.ndarray) -> np.ndarray | None:
        """Feed one audio chunk; return a completed utterance ndarray, or ``None``.

        An utterance completes when trailing silence reaches ``hangover_ms`` after some
        voiced audio, or when the buffer reaches ``max_utterance_ms`` (a hard cut so a
        monologue still segments). Leading silence before any speech is discarded.
        """
        silent = bool(self._is_silent(chunk))
        n = int(np.asarray(chunk).shape[0])
        at = self._pos
        self._pos += n

        if not self._voiced:
            if silent:
                return None  # drop leading silence
            self._voiced = True
            self._start = at

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
        self._last_start = self._start
        self._reset()
        return audio

    def _reset(self) -> None:
        self._buf = []
        self._buf_len = 0
        self._trailing_silence = 0
        self._voiced = False
