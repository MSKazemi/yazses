import logging

import numpy as np
from faster_whisper import WhisperModel

log = logging.getLogger(__name__)


def _load_model(model_name: str, device: str, compute_type: str,
                cpu_threads: int = 0) -> WhisperModel:
    """Load the model from the local cache first, and only then from the network.

    `WhisperModel(name)` defaults to `local_files_only=False`, so faster-whisper asks
    huggingface_hub for the snapshot — and the hub is contacted **even when every file
    is already cached**, to revalidate the revision. On a good connection that is a
    fast round-trip nobody notices. It is the other cases that matter here:

    * It is a network call on the startup path of a program whose headline claim is
      that it does not need the network. The daemon made it on every single start.
    * When that call neither succeeds nor fails — a captive portal, a blackholed
      firewall rule, hub rate-limiting — there is no timeout and no error, so the
      process simply stops at "Loading STT model" forever. Measured on a machine with
      `base.en` fully cached: **>15 minutes and still hanging, ~0% CPU**, against
      **2.3 s** for the identical command with `HF_HUB_OFFLINE=1`.

    A hard failure would have been better than that, and an air-gapped machine — which
    the README names as a target — gets the hard failure and is fine. The pathological
    case is a network that answers slowly or not at all.

    So: try the cache, fall back to downloading. A cached model now loads with no
    network at all, and a missing one is fetched exactly as before. The fallback keeps
    the previous behaviour intact rather than trading one failure mode for another.
    """
    # 0 means "leave it to ctranslate2", which is how it behaved before this
    # existed; only a positive value is passed through.
    extra = {"cpu_threads": int(cpu_threads)} if int(cpu_threads or 0) > 0 else {}
    try:
        return WhisperModel(
            model_name, device=device, compute_type=compute_type,
            local_files_only=True, **extra,
        )
    except Exception:
        # Not in the cache (or the cache is unusable) — this is the first run, or a
        # newly configured model. Fetch it, which is what the user is waiting for.
        log.info("Model '%s' is not in the local cache; downloading it once.", model_name)

    try:
        return WhisperModel(model_name, device=device, compute_type=compute_type, **extra)
    except Exception as exc:
        # The download is the one step that depends on something outside this
        # machine, so it is the one that fails on a firewalled, proxied or
        # air-gapped box (#310). Raising the raw huggingface_hub error here
        # killed the daemon with a traceback the user could do nothing with;
        # ModelUnavailableError carries the three ways to get the model instead.
        from yazses.stt.errors import ModelUnavailableError

        raise ModelUnavailableError(model_name, exc) from exc


class FasterWhisperEngine:
    # Class-level default so a partially constructed engine (tests build one via
    # __new__ to exercise the streaming seam without loading a model) still has a
    # well-defined language instead of raising AttributeError mid-decode.
    _language: str = "en"

    def __init__(
        self,
        model_name: str = "tiny.en",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "en",
        cpu_threads: int = 0,
    ) -> None:
        log.info("Loading STT model '%s' on %s (%s)...", model_name, device, compute_type)
        self._model = _load_model(model_name, device, compute_type, cpu_threads)
        # `[stt] language`; "" means auto-detect, expressed to faster-whisper by
        # omitting the kwarg entirely (passing language=None means the same thing
        # but relies on an undocumented default — omission is the explicit form).
        self._language = (language or "").strip()
        log.info("Model loaded.")

    def _decode_kwargs(self, task: str | None) -> dict:
        """Language/task kwargs shared by every decode path.

        ``task="translate"`` (ADR-v2-014, X→English) must auto-detect the source,
        so it never carries a language. Otherwise pin `[stt] language`, or omit it
        when the user asked for auto-detection.
        """
        if task == "translate":
            return {"task": "translate"}
        return {"language": self._language} if self._language else {}

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> str:
        if audio.size == 0:
            return ""
        kwargs: dict = self._decode_kwargs(task)
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
        kwargs.update(self._decode_kwargs(task))
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
        have). No prompt, no word timestamps — exactly the decode the streaming
        loop has always done — but honouring `[stt] language` so a non-English
        user's rolling window isn't forced through English.
        """
        segments, _ = self._model.transcribe(audio, **self._decode_kwargs(None))
        return " ".join(s.text.strip() for s in segments).strip()
