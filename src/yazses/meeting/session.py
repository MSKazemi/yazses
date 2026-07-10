"""Meeting recording session lifecycle — ADR-v2-127.

``MeetingSession`` owns one in-progress meeting: it streams incoming audio chunks to a
WAV sink on disk (so memory stays bounded over an hour), tracks elapsed time via an
injected clock, and holds the rolling live-transcript lines for the status view. It does
**not** transcribe or diarize — that is ``finalize``'s job at stop. The audio sink and
clock are injectable, so the whole lifecycle is unit-testable with fakes and no mic.
"""
from __future__ import annotations

import wave
from collections.abc import Callable
from pathlib import Path

import numpy as np


class WavFileSink:
    """Append float32 chunks to a 16-bit PCM mono WAV (stdlib ``wave``; no new dep)."""

    def __init__(self, path: str | Path, sample_rate: int = 16000) -> None:
        self._path = Path(path)
        self._sr = sample_rate
        self._wav = wave.open(str(self._path), "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)  # int16
        self._wav.setframerate(sample_rate)

    def write(self, chunk: np.ndarray) -> None:
        arr = np.asarray(chunk, dtype="float32")
        clipped = np.clip(arr, -1.0, 1.0)
        self._wav.writeframes((clipped * 32767.0).astype("<i2").tobytes())

    def close(self) -> None:
        try:
            self._wav.close()
        except Exception:  # pragma: no cover - defensive teardown
            pass


def read_wav_mono_f32(path: str | Path) -> np.ndarray:
    """Read a 16-bit PCM mono WAV (as written by :class:`WavFileSink`) to float32.

    Uses only the stdlib ``wave`` module — the recording is always clean PCM16, so this
    avoids any decoder dependency for the finalize post-pass.
    """
    with wave.open(str(path), "rb") as w:
        frames = w.readframes(w.getnframes())
    if not frames:
        return np.array([], dtype="float32")
    return (np.frombuffer(frames, dtype="<i2").astype("float32") / 32768.0)


class MeetingSession:
    """A single hands-free meeting recording (start → append chunks → stop)."""

    def __init__(
        self,
        meeting_id: str,
        meeting_dir: str | Path,
        *,
        sample_rate: int = 16000,
        started_at: float = 0.0,
        sink=None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.meeting_id = meeting_id
        self.dir = Path(meeting_dir)
        self.sample_rate = sample_rate
        self.started_at = started_at
        self.ended_at: float | None = None
        self._clock = clock
        self._n_samples = 0
        self.live_lines: list[str] = []
        self._closed = False
        self.audio_path = self.dir / "audio.wav"
        self._sink = sink if sink is not None else WavFileSink(self.audio_path, sample_rate)

    def append_chunk(self, chunk: np.ndarray) -> None:
        """Persist one captured audio chunk. No-op after ``stop``."""
        if self._closed:
            return
        self._n_samples += int(np.asarray(chunk).shape[0])
        self._sink.write(chunk)

    def add_live_line(self, text: str) -> None:
        """Append a finalized live-transcript line for the status view."""
        text = (text or "").strip()
        if text:
            self.live_lines.append(text)

    def duration_s(self) -> float:
        """Captured audio duration in seconds (from sample count, clock-independent)."""
        return self._n_samples / self.sample_rate if self.sample_rate else 0.0

    def elapsed_s(self) -> float:
        """Wall-clock seconds since start (uses the injected clock if provided)."""
        if self._clock is None:
            return self.duration_s()
        end = self.ended_at if self.ended_at is not None else self._clock()
        return max(0.0, end - self.started_at)

    def stop(self) -> Path:
        """Close the WAV sink and return the recording path. Idempotent."""
        if not self._closed:
            if self._clock is not None:
                self.ended_at = self._clock()
            self._sink.close()
            self._closed = True
        return self.audio_path
