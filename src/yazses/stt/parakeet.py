"""NVIDIA Parakeet TDT engine over onnx-asr (`[stt] engine = "parakeet"`).

WHY: Parakeet TDT 0.6B v2 sits above whisper-large-v3 on the Hugging Face Open
ASR leaderboard (lower English WER) while decoding at ~30x realtime on CPU via
int8 ONNX — several times faster than whisper-small — and, being a
CTC/transducer-family model, it does not hallucinate text on silence the way
Whisper's decoder can. English-only (v2), so it is opt-in
(`yazses features enable stt-parakeet`), never the default.

Dependency isolation: ``onnx_asr`` (pip ``onnx-asr``, ~a NumPy + onnxruntime
stack, no torch, no NeMo) is imported lazily in ``__init__`` only. Importing
this module is free; construction without the package raises
``ModuleNotFoundError``, which ``stt.factory.build_engine`` turns into an
honest warning + faster-whisper fallback. The model (~600 MB int8) is
downloaded from Hugging Face by onnx-asr itself on first load and cached.

onnx-asr API coded against (verified on 0.11, current on PyPI 0.12):
``onnx_asr.load_model(name, quantization=...)`` returns an adapter whose
``recognize(waveform_float32, sample_rate=16000)`` returns the transcript
(plain ``str`` for the default text adapter). :meth:`_extract_text` stays
defensive about richer result shapes (objects with ``.text``, batch lists).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from yazses.config import SttConfig
    from yazses.postprocess.prosody import Word

log = logging.getLogger(__name__)

# The flagship English checkpoint; also what the docs/leaderboard numbers refer to.
DEFAULT_MODEL = "nemo-parakeet-tdt-0.6b-v2"
# Parakeet consumes 16 kHz mono float32 — the daemon's native capture format.
_NATIVE_SAMPLE_RATE = 16000


class ParakeetEngine:
    """:class:`yazses.stt.base.SttEngine` backend over onnx-asr Parakeet TDT."""

    def __init__(self, config: "SttConfig") -> None:
        model_name = (getattr(config, "model", "") or "").strip()
        if "parakeet" not in model_name.lower():
            # `[stt] model` normally names a Whisper checkpoint (base.en, …);
            # only honour it here when it is actually a Parakeet model, so
            # switching engines never requires editing two keys in lockstep.
            model_name = DEFAULT_MODEL
        self._model_name = model_name
        # Mirror the Whisper int8 default: quantized weights when the config
        # asks for them, full precision otherwise.
        compute_type = (getattr(config, "compute_type", "") or "").lower()
        self._quantization = "int8" if "int8" in compute_type else None
        self._warned_translate = False
        # Parakeet TDT 0.6B v2 is English-only, so `[stt] language` has nothing to
        # act on here. Say so rather than letting a user who set language = "de"
        # assume it took effect (system/backends.py honesty rule).
        language = (getattr(config, "language", "en") or "").strip()
        if language and language.lower() != "en":
            log.warning(
                "[stt] language = %r is ignored by the Parakeet engine, which is "
                "English-only. Fix: set [stt] engine = \"faster-whisper\" with a "
                "multilingual model (e.g. model = \"small\").",
                language,
            )
        log.info("Loading STT model '%s' via onnx-asr (Parakeet)...", model_name)
        self._model = self._load()
        log.info("Model loaded.")

    # ---- SttEngine protocol -------------------------------------------------

    def transcribe(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> str:
        """Decode an utterance to text.

        ``initial_prompt`` is accepted and ignored: Parakeet has no decoder
        prompt to bias (decode-time hotword boosting is the successor feature,
        future work) — accepting it keeps the daemon's call sites engine-blind.
        ``task="translate"`` is Whisper-only; we log once and transcribe
        verbatim rather than fail a burst.
        """
        if audio.size == 0:
            return ""
        if task == "translate" and not self._warned_translate:
            self._warned_translate = True
            log.warning(
                "task='translate' is Whisper-only — the Parakeet engine "
                "transcribes verbatim instead (set [stt] engine = "
                "\"faster-whisper\" if you need spoken translation)"
            )
        waveform = _to_native_rate(np.asarray(audio, dtype=np.float32), sample_rate)
        return self._extract_text(self._recognize(waveform))

    def transcribe_words(
        self,
        audio: np.ndarray,
        sample_rate: int = 16000,
        initial_prompt: str | None = None,
        task: str | None = None,
    ) -> "tuple[str, list[Word]]":
        """Decode; word timestamps are not provided — returns ``(text, [])``.

        onnx-asr exposes timestamps only through a separate adapter
        (``with_timestamps()``) and only on some models, so we return an empty
        word list, the documented "no per-word data" degradation: every caller
        in ``core/daemon.py`` (prosody, confidence) guards with
        ``if prosody_words`` and simply skips those decorations.
        """
        return (
            self.transcribe(
                audio, sample_rate, initial_prompt=initial_prompt, task=task
            ),
            [],
        )

    def decode_window(self, audio: np.ndarray) -> str:
        """Plain batch decode of the rolling streaming window.

        LocalAgreement (stt/streaming.py) only needs "decode what you have so
        far, fast"; a full-window batch decode is semantically equivalent to
        what the Whisper engine does here.
        """
        return self.transcribe(audio)

    # ---- onnx-asr isolation -------------------------------------------------
    # Kept in small private methods so the third-party surface we touch is
    # explicit, monkeypatchable, and defended in one place each.

    def _load(self):
        # lazy: optional dep (`yazses features enable stt-parakeet`). It ships no type
        # stubs and is absent from a default install, so the checker cannot resolve it
        # — that is expected here rather than a missing dependency.
        import onnx_asr  # type: ignore[import-not-found]

        if self._quantization:
            try:
                return onnx_asr.load_model(
                    self._model_name, quantization=self._quantization
                )
            except Exception as exc:
                # Not every checkpoint publishes quantized weights; precision is
                # a preference, not a reason to lose the engine.
                log.warning(
                    "Parakeet %s weights unavailable for '%s' (%s) — "
                    "loading default precision",
                    self._quantization, self._model_name, exc,
                )
        return onnx_asr.load_model(self._model_name)

    def _recognize(self, waveform: np.ndarray):
        try:
            return self._model.recognize(waveform, sample_rate=_NATIVE_SAMPLE_RATE)
        except TypeError:
            # Older onnx-asr adapters without the sample_rate keyword.
            return self._model.recognize(waveform)

    @staticmethod
    def _extract_text(result) -> str:
        """Normalize onnx-asr's result shapes to plain text.

        The default text adapter returns ``str``; other adapters return result
        objects carrying ``.text``; batch calls return lists. Stay liberal so an
        onnx-asr upgrade can't silently break dictation.
        """
        if result is None:
            return ""
        if isinstance(result, str):
            return result.strip()
        if isinstance(result, (list, tuple)):
            return " ".join(
                t for t in (ParakeetEngine._extract_text(r) for r in result) if t
            ).strip()
        text = getattr(result, "text", None)
        if text is not None:
            return str(text).strip()
        return str(result).strip()


def _to_native_rate(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    """Linear-resample to 16 kHz when the daemon captures at another rate.

    The daemon records at 16 kHz by default, so this is a pass-through in
    practice; plain ``np.interp`` is plenty for the odd non-default config and
    avoids adding a resampling dependency.
    """
    if sample_rate == _NATIVE_SAMPLE_RATE or audio.size == 0:
        return audio
    n_out = max(1, int(round(audio.size * _NATIVE_SAMPLE_RATE / float(sample_rate))))
    positions = np.linspace(0.0, audio.size - 1, num=n_out)
    return np.interp(positions, np.arange(audio.size), audio).astype(np.float32)
