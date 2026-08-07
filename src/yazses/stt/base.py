"""The pluggable STT engine seam (`[stt] engine`).

:class:`SttEngine` is the Protocol every speech-to-text backend implements, so
the daemon (and streaming, and any future caller) depends on a seam instead of
on faster-whisper concretely. This is what lets `[stt] engine = "parakeet"`
swap the recognizer without touching the pipeline — and keeps every backend's
heavy runtime (CTranslate2, onnx-asr, …) a lazy import inside its own module,
never a cost of importing this one.

Deliberately tiny: exactly the three methods the daemon uses today. The ``Word``
dataclass referenced by :meth:`SttEngine.transcribe_words` stays canonical in
``yazses.postprocess.prosody`` (its consumer), imported here only for typing so
this module adds zero import weight.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

import numpy as np

if TYPE_CHECKING:
    from yazses.postprocess.prosody import Word


@runtime_checkable
class SttEngine(Protocol):
    """What the daemon needs from a speech-to-text backend.

    All engines accept ``initial_prompt`` and ``task`` even when the underlying
    model has no equivalent (they document and ignore them) so the daemon's call
    sites never need per-engine branches.
    """

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> str:
        """Decode a whole utterance to plain text."""
        ...

    def transcribe_words(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> "tuple[str, list[Word]]":
        """Decode with per-word timestamps; ``(text, [])`` = no word data."""
        ...

    def decode_window(self, audio: np.ndarray) -> str:
        """Plain fast decode of a rolling streaming window (LocalAgreement)."""
        ...
