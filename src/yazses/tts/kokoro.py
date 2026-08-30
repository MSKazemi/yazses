"""Kokoro-82M TTS backend (Apache-2.0) — the default Read-Back voice.

Runs int8 ONNX inference on CPU via ``kokoro-onnx`` (optional ``tts`` extra) and
plays each sentence chunk through ``sounddevice`` (already a core dep for the
recorder). Constructing this backend imports ``kokoro_onnx`` and loads the model;
any failure raises so the factory can fall back to :class:`NullTtsBackend`.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from pathlib import Path

from yazses.tts.chunking import sentence_chunks

log = logging.getLogger(__name__)


class KokoroTtsBackend:
    """Sentence-chunked Kokoro TTS with barge-in cancel."""

    def __init__(self, config) -> None:
        from kokoro_onnx import Kokoro  # optional `tts` extra; raises if absent

        self._config = config
        self._voice = config.voice if config.voice != "default" else "af_heart"
        self._speed = config.speed
        self._sample_rate = config.sample_rate
        # kokoro-onnx >=0.4 needs an explicit (model, voices) pair. Honour config
        # overrides, else resolve the shared cache dir and download on first use.
        model_path, voices_path = self._resolve_models()
        self._kokoro = Kokoro(str(model_path), str(voices_path))
        self._cancel = threading.Event()
        # Set by `begin`, consumed by the next `speak`/`synthesize`. See `begin`.
        self._claimed = False
        self._claim_lock = threading.Lock()

    def _resolve_models(self):
        from yazses.tts.download import download_models, model_paths

        default_model, default_voices = model_paths()
        model = self._config.model_path or str(default_model)
        voices = getattr(self._config, "voices_path", "") or str(default_voices)
        # Only reach for the network when a file is genuinely missing.
        if not (Path(model).exists() and Path(voices).exists()):
            log.info("Read-Back voice model missing; downloading (one-time, ~340 MB)…")
            download_models(echo=lambda m: log.info("%s", m))
        return model, voices

    @property
    def name(self) -> str:
        return "kokoro"

    def begin(self) -> None:
        """Claim the next utterance, clearing a barge-in meant for the previous one.

        Read-back is requested on one thread and spoken on another, so the backend
        cannot tell a cancel aimed at what is playing from one aimed at what has
        been requested but not started. Only the caller knows that ordering, so the
        caller claims the utterance -- inside whatever lock it uses to sequence its
        own cancels -- and `speak` then stops clearing the flag itself. A cancel
        arriving after the claim is therefore never lost.

        Not part of the `TtsBackend` Protocol: it is duck-typed at the call site so
        adding it cannot change what `isinstance` accepts for a backend that
        predates it.
        """
        with self._claim_lock:
            self._claimed = True
            self._cancel.clear()

    def _take_claim(self) -> None:
        """Consume a `begin`, or self-heal for a caller that never issues one.

        A caller that does not order its own cancels -- anything holding this
        backend directly rather than through the daemon's read-back path -- would
        otherwise be silenced permanently by a single barge-in, because nothing
        would ever clear the flag again.
        """
        with self._claim_lock:
            if not self._claimed:
                self._cancel.clear()
            self._claimed = False

    def synthesize(self, text: str) -> Iterator[bytes]:
        import numpy as np

        self._take_claim()
        for chunk in sentence_chunks(text):
            if self._cancel.is_set():
                return
            samples, _sr = self._kokoro.create(
                chunk, voice=self._voice, speed=self._speed
            )
            yield np.asarray(samples, dtype="float32").tobytes()

    def speak(self, text: str) -> None:
        import sounddevice as sd

        self._take_claim()
        for chunk in sentence_chunks(text):
            if self._cancel.is_set():
                break
            try:
                samples, sr = self._kokoro.create(
                    chunk, voice=self._voice, speed=self._speed
                )
                sd.play(samples, sr)
                sd.wait()
            except Exception as exc:  # never let a playback error break the daemon
                log.debug("Kokoro speak error: %s", exc)
                break

    def cancel(self) -> None:
        self._cancel.set()
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass
