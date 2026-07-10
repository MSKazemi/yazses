import logging
import time
from collections.abc import Callable

import numpy as np
import sounddevice as sd

log = logging.getLogger(__name__)

# Opening the mic can fail transiently when the audio server (PipeWire/Pulse)
# is briefly busy — e.g. another stream is being torn down. Retrying after a
# short pause recovers automatically instead of requiring a daemon restart.
_OPEN_ATTEMPTS = 3
_OPEN_RETRY_DELAY_S = 0.3


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        max_seconds: int = 90,
        on_chunk: Callable[[np.ndarray], None] | None = None,
        accumulate: bool = True,
    ) -> None:
        self._sample_rate = sample_rate
        self._max_seconds = max_seconds
        self._on_chunk = on_chunk
        # Meeting mode streams chunks to disk via ``on_chunk`` and does not need the
        # in-memory buffer; ``accumulate=False`` keeps memory bounded over a long run
        # (hold-to-talk keeps the default ``True``). ``max_seconds=0`` disables the cap.
        self._accumulate = accumulate
        self._chunks: list[np.ndarray] = []
        self._n_samples = 0
        self._stream: sd.InputStream | None = None

    def start(self) -> None:
        self._chunks = []
        self._n_samples = 0
        self._stream = None
        last_exc: Exception | None = None
        for attempt in range(1, _OPEN_ATTEMPTS + 1):
            try:
                stream = sd.InputStream(
                    samplerate=self._sample_rate,
                    channels=1,
                    dtype="float32",
                    callback=self._callback,
                )
                stream.start()
            except Exception as exc:  # PortAudioError and friends
                last_exc = exc
                log.warning(
                    "Microphone open failed (attempt %d/%d): %s",
                    attempt, _OPEN_ATTEMPTS, exc,
                )
                if attempt < _OPEN_ATTEMPTS:
                    time.sleep(_OPEN_RETRY_DELAY_S)
                continue
            self._stream = stream
            log.debug("Audio recording started")
            return
        raise RuntimeError(
            f"Could not open microphone after {_OPEN_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            log.warning("Audio callback status: %s", status)
        if self._max_seconds and (self._n_samples + frames) > self._max_seconds * self._sample_rate:
            return
        self._n_samples += frames
        chunk = indata.copy().flatten()
        if self._accumulate:
            self._chunks.append(chunk)
        if self._on_chunk is not None:
            self._on_chunk(chunk)

    def stop(self) -> np.ndarray:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:  # never let teardown crash the pipeline
                log.warning("Error closing mic stream: %s", exc)
            self._stream = None
        if not self._chunks:
            return np.array([], dtype="float32")
        audio = np.concatenate(self._chunks)
        log.debug("Audio captured: %.2f seconds", len(audio) / self._sample_rate)
        return audio
