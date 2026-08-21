"""Build the configured STT engine (`[stt] engine`).

Guard-and-fallback: a config value must never brick dictation. An unknown engine
name, a missing optional dependency, or a backend that fails to load all fall
back to faster-whisper — with an honest log line saying exactly what happened
and how to get the requested engine (never a silent engine switch, per the
`system/backends.py` honesty rule).

The concrete engines are imported inside :func:`build_engine` so their heavy
runtimes (CTranslate2, onnx-asr) stay lazy: importing this module costs nothing.
"""
from __future__ import annotations

import dataclasses
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yazses.config import SttConfig
    from yazses.stt.base import SttEngine

log = logging.getLogger(__name__)

DEFAULT_ENGINE = "faster-whisper"


def build_engine(stt: "SttConfig") -> "SttEngine":
    """Return the STT engine `[stt] engine` selects, falling back to Whisper.

    ``getattr`` guards keep this callable with any duck-typed config (tests,
    older configs without the ``engine`` key).
    """
    return _with_han_script(_build_raw_engine(stt), stt)


def _build_raw_engine(stt: "SttConfig") -> "SttEngine":
    name = (getattr(stt, "engine", "") or DEFAULT_ENGINE).strip().lower()
    if name == "parakeet":
        try:
            from yazses.stt.parakeet import ParakeetEngine

            return ParakeetEngine(stt)
        except ModuleNotFoundError as exc:
            log.warning(
                "[stt] engine = \"parakeet\" but its optional dependency (%s) is not "
                "installed — falling back to faster-whisper for now. Fix: "
                "yazses features enable stt-parakeet",
                exc.name or "onnx_asr",
            )
        except Exception:
            # e.g. a failed model download. Dictation must still come up.
            log.exception(
                "Parakeet STT engine failed to load — falling back to faster-whisper"
            )
        return _build_faster_whisper(stt, fallback_from="parakeet")
    if name == "moonshine":
        try:
            from yazses.stt.moonshine import MoonshineEngine

            return MoonshineEngine(stt)
        except ModuleNotFoundError as exc:
            log.warning(
                "[stt] engine = \"moonshine\" but its optional dependency (%s) is not "
                "installed — falling back to faster-whisper for now. Fix: "
                "yazses features enable stt-moonshine",
                exc.name or "moonshine_onnx",
            )
        except Exception:
            log.exception(
                "Moonshine STT engine failed to load — falling back to faster-whisper"
            )
        return _build_faster_whisper(stt, fallback_from="moonshine")
    if name not in ("", DEFAULT_ENGINE):
        log.warning(
            "Unknown [stt] engine %r — falling back to %s "
            "(valid engines: faster-whisper, parakeet, moonshine)",
            name, DEFAULT_ENGINE,
        )
    return _build_faster_whisper(stt)


def _build_faster_whisper(stt: "SttConfig", fallback_from: str = "") -> "SttEngine":
    from yazses.stt.download import language_model_problem
    from yazses.stt.faster_whisper import FasterWhisperEngine

    model = (getattr(stt, "model", "") or "base.en").strip() or "base.en"
    # When falling back from another engine, `[stt] model` may name that
    # engine's model (e.g. "nemo-parakeet-tdt-0.6b-v2"), which Whisper cannot
    # load — the fallback would crash the daemon it exists to protect. Use the
    # Whisper default instead, and say so.
    if fallback_from and fallback_from in model.lower():
        log.warning(
            "[stt] model %r belongs to the %s engine — the faster-whisper "
            "fallback uses 'base.en' instead", model, fallback_from,
        )
        model = "base.en"
    language = (getattr(stt, "language", "en") or "").strip()
    # An `.en` checkpoint has no language tokens at all — it physically cannot
    # decode German. Silently forcing English would hand the user fluent-looking
    # nonsense (Whisper transliterates rather than erroring), which is the worst
    # possible failure mode, so say exactly what is wrong and what to change.
    #
    # The rule itself lives in `stt/download.py` because the settings window has
    # to apply it too — before writing, where it can still be refused rather than
    # merely logged. Two copies of this condition would drift.
    problem = language_model_problem(model, language)
    if problem:
        log.warning("[stt] %s", problem)
    return FasterWhisperEngine(
        model_name=model,
        device=getattr(stt, "device", "cpu"),
        compute_type=getattr(stt, "compute_type", "int8"),
        language=language,
        cpu_threads=int(getattr(stt, "cpu_threads", 0) or 0),
        beam_size=int(getattr(stt, "beam_size", 0) or 0),
    )


def _with_han_script(engine: "SttEngine", stt: "SttConfig") -> "SttEngine":
    """Wrap *engine* so Chinese output lands in the configured Han script.

    Applied here rather than at each call site so dictation, `yazses transcribe`,
    meeting capture and the streaming decoder all get it from one wiring point —
    the same single-chokepoint rule `_effective_initial_prompt` follows. Returns
    *engine* untouched when the feature is off or ``opencc`` is absent, so the
    default install carries no wrapper at all.
    """
    from yazses.postprocess.han_script import build_han_normaliser

    normalise = build_han_normaliser(stt)
    if normalise is None:
        return engine

    # An `.en` checkpoint cannot emit Han characters at all, so the conversion
    # would run on every utterance and change nothing. `features enable
    # chinese-script` writes the key without touching `[stt] model`, so this
    # pairing is what a user lands on by default — say it plainly rather than
    # leaving a toggle that reports "on" and silently does nothing.
    model = (getattr(stt, "model", "") or "").strip()
    if model.lower().endswith(".en"):
        log.warning(
            "[stt] chinese_script is set but [stt] model = %r is English-only, so "
            "there will never be Chinese output to convert. Fix: set model = %r "
            "(drop the .en suffix) and language = \"zh\".",
            model, model[: -len(".en")] or "small",
        )
    return _HanScriptEngine(engine, normalise)


class _HanScriptEngine:
    """Decorator over an :class:`SttEngine` that rewrites its Chinese output.

    Delegates anything it does not convert, so an engine-specific attribute a
    caller reaches for still resolves through the wrapper.
    """

    def __init__(self, inner: "SttEngine", normalise) -> None:
        self._inner = inner
        self._normalise = normalise

    def transcribe(self, audio, sample_rate: int = 16000, initial_prompt=None,
                   task=None) -> str:
        return self._normalise(
            self._inner.transcribe(audio, sample_rate, initial_prompt, task)
        )

    def transcribe_words(self, audio, sample_rate: int = 16000,
                         initial_prompt=None, task=None):
        text, words = self._inner.transcribe_words(
            audio, sample_rate, initial_prompt, task
        )
        # Convert each word too: the caller re-renders per-word output (speaker
        # labels, subtitles, Confidence Ink), so converting only the joined text
        # would leave those surfaces in the script the user asked to leave.
        converted = [
            dataclasses.replace(w, text=self._normalise(w.text)) for w in words
        ] if words else words
        return self._normalise(text), converted

    def decode_window(self, audio) -> str:
        return self._normalise(self._inner.decode_window(audio))

    def __getattr__(self, name: str):
        return getattr(self._inner, name)
