from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # annotations only -- never imported at runtime by this block
    import sounddevice as sd

log = logging.getLogger(__name__)


def _sd():
    """Import sounddevice on first use, not at import time.

    `import sounddevice` calls `Pa_Initialize()` **during the import**, and on a host
    with no usable audio system that raises rather than returning an empty device list:

        sounddevice.PortAudioError: Error initializing PortAudio:
        Internal PortAudio error [PaErrorCode -9986]

    Because `core/daemon.py` imports this module at its own module scope, that made
    `import yazses.core.daemon` itself impossible there -- an unhandled traceback from a
    line nobody called, on a machine that may only ever have wanted `yazses transcribe`,
    which needs no microphone at all. Measured on a Windows Server 2022 host with no
    audio device: **45 test files could not even be collected**, which is a large part
    of why regressions keep reaching Windows unseen. A stopped Windows Audio service, an
    RDP session without audio redirection, a container and a CI runner all look the same
    way to PortAudio.

    `audio/devices.py` already imports it inside each function for this reason, which is
    why `yazses doctor` and `yazses audio devices` report the problem instead of dying of
    it. This is the same rule applied to the module that was the exception: the failure
    belongs to whoever asks to open a microphone, not to whoever imports the file.
    """
    import sounddevice as sd

    return sd

# Opening the mic can fail transiently when the audio server (PipeWire/Pulse)
# is briefly busy — e.g. another stream is being torn down. Retrying after a
# short pause recovers automatically instead of requiring a daemon restart.
#
# The pause is not free, and that is the part this used to get wrong. By the
# time `start()` is called the key is already down, the tray is already green
# and the earcon has already told an eyes-free user to speak. Whatever they say
# during the pause is gone: there is no buffer to recover it from, because the
# stream that would fill one is the stream that failed to open.
#
# Measured on a real machine (`daemon.log`, 2026-08-18→20): 12 failed opens in
# 149 bursts (8%), and *every one* recovered on the second attempt — only
# "attempt 1/3" ever appears. The server was busy for far less than the flat
# 300 ms this waited, so the wait was many times longer than the fault it was
# waiting out. The delays are front-loaded instead: the first retry is quick,
# and the second is sized so the cumulative budget stays at the previous 600 ms
# — nothing that used to recover on the third attempt now fails instead.
_OPEN_RETRY_DELAYS_S: tuple[float, ...] = (0.05, 0.55)
# Derived, so a change to one can never leave the other behind.
_OPEN_ATTEMPTS = len(_OPEN_RETRY_DELAYS_S) + 1


class AudioRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        max_seconds: int = 90,
        on_chunk: Callable[[np.ndarray], None] | None = None,
        accumulate: bool = True,
        device: str | int | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._max_seconds = max_seconds
        self._on_chunk = on_chunk
        # Meeting mode streams chunks to disk via ``on_chunk`` and does not need the
        # in-memory buffer; ``accumulate=False`` keeps memory bounded over a long run
        # (hold-to-talk keeps the default ``True``). ``max_seconds=0`` disables the cap.
        self._accumulate = accumulate
        # Pinned input device: a name substring (``[audio] device``) resolved fresh at
        # each ``start()``, an explicit PortAudio index, or None to follow the OS
        # default. Mutable so the daemon's auto-heal can retarget a live recorder.
        self.device = device
        # Name of the device actually opened by the last ``start()`` — the daemon
        # records this as "last-good" when the clip yields usable audio.
        self.current_device_name: str | None = None
        self._chunks: list[np.ndarray] = []
        self._n_samples = 0
        self._stream: sd.InputStream | None = None

    def _resolve_device(self) -> int | None:
        """Resolve ``self.device`` to a PortAudio index (or None = OS default)."""
        dev = self.device
        if isinstance(dev, int):
            return dev
        if not isinstance(dev, str) or not dev.strip():
            return None
        # Name substring: resolve against a fresh device list so a hotplug index
        # shift can't break the pin. No match → None → fall back to OS default.
        from yazses.audio.devices import list_input_devices, resolve_input_device

        return resolve_input_device(dev, list_input_devices())

    def _opened_device_name(self, index: int | None) -> str | None:
        """Best-effort name of the device at ``index`` (or the OS default)."""
        try:
            from yazses.audio.devices import current_default_input_name

            if index is None:
                return current_default_input_name()
            info = _sd().query_devices(index)
            return str(info.get("name")) if info else None
        except Exception:
            return None

    def start(self) -> None:
        self._chunks = []
        self._n_samples = 0
        self._stream = None
        device_index = self._resolve_device()
        last_exc: Exception | None = None
        for attempt in range(1, _OPEN_ATTEMPTS + 1):
            try:
                stream = _sd().InputStream(
                    samplerate=self._sample_rate,
                    channels=1,
                    dtype="float32",
                    callback=self._callback,
                    device=device_index,
                )
                stream.start()
            except Exception as exc:  # PortAudioError and friends
                last_exc = exc
                pause = (
                    _OPEN_RETRY_DELAYS_S[attempt - 1]
                    if attempt <= len(_OPEN_RETRY_DELAYS_S)
                    else 0.0
                )
                # Name the cost. "Microphone open failed … (attempt 1/3)" alone reads
                # as a hiccup that was recovered, which is how 12 real occurrences went
                # unexamined: the retry was documented, the dropped speech never was.
                log.warning(
                    "Microphone open failed (attempt %d/%d): %s%s",
                    attempt,
                    _OPEN_ATTEMPTS,
                    exc,
                    f" — retrying in {round(pause * 1000)} ms; anything said during "
                    "that pause is not captured." if pause else "",
                )
                if pause:
                    time.sleep(pause)
                continue
            self._stream = stream
            self.current_device_name = self._opened_device_name(device_index)
            log.debug("Audio recording started (device=%s)", self.current_device_name)
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
