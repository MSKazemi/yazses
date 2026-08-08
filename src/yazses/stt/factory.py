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
    if name not in ("", DEFAULT_ENGINE):
        log.warning(
            "Unknown [stt] engine %r — falling back to %s "
            "(valid engines: faster-whisper, parakeet)",
            name, DEFAULT_ENGINE,
        )
    return _build_faster_whisper(stt)


def _build_faster_whisper(stt: "SttConfig", fallback_from: str = "") -> "SttEngine":
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
    if language and language.lower() != "en" and model.lower().endswith(".en"):
        log.warning(
            "[stt] language = %r needs a multilingual model, but [stt] model = %r "
            "is English-only — speech will be mis-transcribed as English. Fix: set "
            "model = %r (drop the .en suffix).",
            language, model, model[: -len(".en")] or "small",
        )
    return FasterWhisperEngine(
        model_name=model,
        device=getattr(stt, "device", "cpu"),
        compute_type=getattr(stt, "compute_type", "int8"),
        language=language,
    )
