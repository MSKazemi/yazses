"""Frames -> filled-pause inputs, and a live endpoint monitor (pure) — ADR-v2-101.

``endpoint.is_filled_pause`` takes an F0 series and a spectral-stability value; nothing on main
produced either from live audio. This module turns :class:`yazses.audio.pitch.PitchFrame` runs
into exactly those two inputs, and :class:`HesitationMonitor` keeps the answer current while a
turn records, so ``endpoint.endpoint_decision`` can be asked at any moment.

What "the trailing vocalization" means here: the ``tail_ms`` of frames that *end at the most
recent voiced frame*. Trailing silence and trailing noise are both unvoiced to YIN, so the window
does not depend on an energy threshold, which on this project's microphones sits close to the
room floor. The window must hold at least ``min_voiced_ms`` of voiced frames: a filled pause is a
sustained vocalization, and a short flat syllable at the end of an ordinary word must not extend
the endpoint. These defaults are reasoned, not measured on real speech.

Wired through :mod:`yazses.hesitation.handsfree`: the daemon builds a monitor only when both
``[hesitation]`` and ``[autostop]`` are enabled, and ``[hesitation]`` stays off by default.
"""
from __future__ import annotations

import threading
from collections import deque
from collections.abc import Sequence

import numpy as np

from yazses.audio.pitch import HOP_MS, PitchFrame, PitchTracker, spectral_stability
from yazses.hesitation.endpoint import endpoint_decision, is_filled_pause

#: Length of the trailing window the filled-pause test reads.
TAIL_MS = 400.0
#: Voiced time the window must hold before it can count as a filled pause.
MIN_VOICED_MS = 300.0
#: Most audio a monitor buffers between two reads; only the tail matters.
MAX_PENDING_S = 2.0


def trailing_window(frames: Sequence[PitchFrame], tail_ms: float = TAIL_MS,
                    hop_ms: float = HOP_MS) -> list[PitchFrame]:
    """The ``tail_ms`` of frames ending at the last voiced frame; ``[]`` if none is voiced. Pure."""
    last = next((i for i in range(len(frames) - 1, -1, -1) if frames[i].voiced), None)
    if last is None:
        return []
    count = max(1, int(round(tail_ms / hop_ms)))
    return list(frames[max(0, last + 1 - count):last + 1])


def filled_pause_inputs(frames: Sequence[PitchFrame], tail_ms: float = TAIL_MS,
                        hop_ms: float = HOP_MS) -> tuple[list[float], float]:
    """``(f0_series, spectral_stability)`` for ``is_filled_pause`` from the trailing window. Pure.

    Unvoiced frames inside the window stay in the series as ``0.0`` (the core drops them).
    An empty window gives ``([], 0.0)``, which the core reads as "not a filled pause".
    """
    window = trailing_window(frames, tail_ms, hop_ms)
    return [f.f0_hz for f in window], spectral_stability(f.flux for f in window)


def trailing_filled_pause(frames: Sequence[PitchFrame], *, tail_ms: float = TAIL_MS,
                          min_voiced_ms: float = MIN_VOICED_MS, hop_ms: float = HOP_MS,
                          f0_range_max: float = 25.0, stability_min: float = 0.7) -> bool:
    """True if the trailing vocalization is a sustained filled pause. Pure.

    Requires ``min_voiced_ms`` of voiced frames in the window, then defers to
    ``endpoint.is_filled_pause`` (flat F0 *and* a steady spectrum).
    """
    window = trailing_window(frames, tail_ms, hop_ms)
    if sum(1 for f in window if f.voiced) * hop_ms < min_voiced_ms:
        return False
    f0 = [f.f0_hz for f in window]
    stability = spectral_stability(f.flux for f in window)
    return is_filled_pause(f0, stability, f0_range_max=f0_range_max, stability_min=stability_min)


class HesitationMonitor:
    """Live "was the last thing said a filled pause?" for one recording turn.

    :meth:`push` only copies the chunk and appends it to a queue under a short lock, so the
    audio-callback thread never waits for analysis. The analysis runs on whichever thread calls
    :attr:`last_was_filled_pause` or :meth:`decision`: it swaps the queue out under that short
    lock and runs YIN outside it, under a separate analysis lock. The analysis is not incremental
    per watcher tick: in a hands-free turn ``AutoStopTurn`` consults :meth:`decision` only after
    speech was heard and at least ``MIN_SILENCE_TIMEOUT_MS`` of silence followed, so during a
    turn longer than ``max_pending_s`` the queue drops its oldest audio and the first
    consultation analyses one block of up to ``max_pending_s`` on the watcher thread. That block
    still holds the trailing vocalization, which is all the verdict needs; a :meth:`reset` from
    the hotkey thread can wait for that one analysis. The verdict is recomputed on every voiced
    frame and kept through the unvoiced frames after it, so it describes the most recent
    vocalization.

    If queued audio had to be dropped (nobody read for ``max_pending_s``), the verdict is cleared
    along with the tracker: the dropped audio may have held newer speech, so a verdict from before
    the drop no longer describes the most recent vocalization. Clearing it means "commit at the
    plain threshold", the behaviour without this feature.
    """

    def __init__(self, sample_rate: int = 16000, *, commit_ms: float = 800.0,
                 hold_extra_ms: float = 1200.0, tail_ms: float = TAIL_MS,
                 min_voiced_ms: float = MIN_VOICED_MS, f0_range_max: float = 25.0,
                 stability_min: float = 0.7, max_pending_s: float = MAX_PENDING_S) -> None:
        self._tracker = PitchTracker(sample_rate)
        self._hop_ms = self._tracker.hop_s * 1000.0
        self._commit_ms = float(commit_ms)
        self._hold_extra_ms = float(hold_extra_ms)
        self._tail_ms = float(tail_ms)
        self._min_voiced_ms = float(min_voiced_ms)
        self._f0_range_max = float(f0_range_max)
        self._stability_min = float(stability_min)
        self._max_pending = max(self._tracker.frame_len, int(max_pending_s * sample_rate))
        # ``_lock`` guards only the queue (``_pending``, ``_pending_n``, ``_gap``) and is the one
        # lock ``push`` takes. ``_analysis_lock`` guards the tracker, window and verdict. When both
        # are needed, ``_analysis_lock`` is taken first.
        self._lock = threading.Lock()
        self._analysis_lock = threading.Lock()
        self._pending: list[np.ndarray] = []
        self._pending_n = 0
        self._window: deque[PitchFrame] = deque(
            maxlen=max(1, int(round(self._tail_ms / self._hop_ms)))
        )
        self._filled = False
        self._gap = False

    def reset(self) -> None:
        """Start a new turn: drop queued audio, frames, and the last verdict."""
        with self._analysis_lock:
            with self._lock:
                self._pending = []
                self._pending_n = 0
                self._gap = False
            self._tracker.reset()
            self._window.clear()
            self._filled = False

    def push(self, chunk) -> None:
        """Queue one recorded chunk (mono). Takes only the queue lock; no analysis happens here."""
        x = np.array(chunk, dtype=np.float32, copy=True).ravel()
        if not x.size:
            return
        with self._lock:
            self._pending.append(x)
            self._pending_n += x.size
            # Nobody is reading (not a hands-free turn, or the watcher stalled): keep memory
            # bounded by dropping the oldest chunks, and restart the tracker on the next read.
            while (len(self._pending) > 1
                   and self._pending_n - self._pending[0].size >= self._max_pending):
                self._pending_n -= self._pending.pop(0).size
                self._gap = True

    def _analyse(self) -> None:
        """Analyse the queued audio. Caller holds ``_analysis_lock``, not ``_lock``."""
        with self._lock:
            if not self._pending:
                return
            chunks, self._pending = self._pending, []
            self._pending_n = 0
            gap, self._gap = self._gap, False
        audio = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
        if gap or audio.size > self._max_pending:
            # Fell behind: only the tail can matter, and frames across the gap would compare
            # spectra that were never adjacent, so restart the tracker on the kept audio. The
            # dropped audio may have held newer speech, so the old verdict goes with it.
            audio = audio[-self._max_pending:]
            self._tracker.reset()
            self._window.clear()
            self._filled = False
        for frame in self._tracker.feed(audio):
            self._window.append(frame)
            if frame.voiced:
                self._filled = trailing_filled_pause(
                    list(self._window), tail_ms=self._tail_ms,
                    min_voiced_ms=self._min_voiced_ms, hop_ms=self._hop_ms,
                    f0_range_max=self._f0_range_max, stability_min=self._stability_min,
                )

    @property
    def last_was_filled_pause(self) -> bool:
        """The verdict for the most recent vocalization, after analysing queued audio."""
        with self._analysis_lock:
            self._analyse()
            return self._filled

    def decision(self, silence_ms: float) -> str:
        """``endpoint_decision`` for the caller's trailing ``silence_ms``: ``hold`` | ``commit``."""
        return endpoint_decision(silence_ms, self.last_was_filled_pause,
                                 commit_ms=self._commit_ms, hold_extra_ms=self._hold_extra_ms)
