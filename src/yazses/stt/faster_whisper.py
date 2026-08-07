import logging

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)


class FasterWhisperEngine:
    def __init__(
        self,
        model_name: str = "tiny.en",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        log.info("Loading STT model '%s' on %s (%s)...", model_name, device, compute_type)
        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
        log.info("Model loaded.")

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> str:
        if audio.size == 0:
            return ""
        # task="translate" (ADR-v2-014, X→English): let Whisper auto-detect the
        # source language; otherwise keep the English fast path.
        kwargs: dict = {"task": "translate"} if task == "translate" else {"language": "en"}
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        segments, _ = self._model.transcribe(audio, **kwargs)
        return " ".join(seg.text.strip() for seg in segments).strip()

    def transcribe_words(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> "tuple[str, list]":
        """Transcribe with per-word timestamps for Prosody Ink (spec-prosody-ink).

        Returns ``(text, words)`` where ``words`` is a list of
        :class:`yazses.postprocess.prosody.Word`. Used only on the batch path when
        ``[prosody] enabled`` — the small ``word_timestamps=True`` decode cost is
        not paid by non-prosody users (who keep the :meth:`transcribe` fast path).
        Degrades to an empty word list if the model yields no per-word data.
        """
        from yazses.postprocess.prosody import Word

        if audio.size == 0:
            return "", []
        kwargs: dict = {"word_timestamps": True}
        kwargs.update({"task": "translate"} if task == "translate" else {"language": "en"})
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt
        segments, _ = self._model.transcribe(audio, **kwargs)
        texts: list[str] = []
        words: list[Word] = []
        for seg in segments:
            texts.append(seg.text.strip())
            for w in getattr(seg, "words", None) or []:
                words.append(Word(
                    text=w.word.strip(),
                    start=float(w.start),
                    end=float(w.end),
                    probability=float(getattr(w, "probability", 0.0) or 0.0),
                ))
        return " ".join(texts).strip(), words

    def decode_window(self, audio: np.ndarray) -> str:
        """Plain fast decode of a rolling streaming window (LocalAgreement, ADR-002).

        The single seam ``stt.streaming.StreamingEngine`` drives, so streaming
        never reaches into the private ``_model`` (which other engines don't
        have). English fast path, no prompt, no word timestamps — exactly the
        decode the streaming loop has always done.
        """
        segments, _ = self._model.transcribe(audio, language="en")
        return " ".join(s.text.strip() for s in segments).strip()
