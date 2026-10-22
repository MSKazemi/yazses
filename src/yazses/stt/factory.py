"""Build the configured STT engine (`[stt] engine`).

Guard-and-fallback: a config value must never brick dictation. An unknown engine
name, a missing optional dependency, or a backend that fails to load all fall
back to faster-whisper — with an honest log line saying exactly what happened
and how to get the requested engine (never a silent engine switch, per the
`system/backends.py` honesty rule).

One deliberate exception (#515): a `[stt] language` the resolved engine/model
cannot transcribe is *refused* with `LanguageUnsupportedError`, not fallen back
from. Every fallback here ends on an English-only checkpoint, so "staying up"
would mean typing English for Persian speech — a working-looking failure, which is
worse than an ERROR state that says what to change.

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
    engine = _build_raw_engine(stt)
    engine = _with_han_script(engine, stt)
    return _with_persian_normaliser(engine, stt)


def refuse_unsupported_language(engine: str, model: str, language: str) -> None:
    """Raise `LanguageUnsupportedError` when *engine*/*model* cannot do *language*.

    The engine-side half of #515: `language/capability.py` is the cited table, and a
    pairing it marks ``unsupported`` is refused here, before any model is loaded,
    instead of being logged and then transcribed as English. faster-whisper itself
    replaces the language with "en" for an English-only tokenizer and only logs it;
    Parakeet v2 and Moonshine take no language at all. An ``unknown`` verdict (a
    custom checkpoint) is logged, never refused — guessing would reject a model
    that works.
    """
    from yazses.language.capability import check
    from yazses.stt.errors import LanguageUnsupportedError

    support = check(engine, model, language)
    if support.verdict == "unsupported":
        log.error("[stt] %s", support.reason)
        raise LanguageUnsupportedError(
            support.engine, support.model, (language or "").strip(), support.reason
        )
    if support.verdict == "unknown":
        log.warning("[stt] %s", support.reason)


def _build_raw_engine(stt: "SttConfig") -> "SttEngine":
    name = (getattr(stt, "engine", "") or DEFAULT_ENGINE).strip().lower()
    language = (getattr(stt, "language", "en") or "").strip()
    if name in ("parakeet", "moonshine"):
        # Before the import, so a pairing that would type English is refused rather
        # than loaded — and rather than "fixed" by the faster-whisper fallback below,
        # whose default `base.en` is English-only too.
        refuse_unsupported_language(name, getattr(stt, "model", "") or "", language)
    if name == "parakeet":
        try:
            from yazses.stt.parakeet import ParakeetEngine

            return ParakeetEngine(stt)
        except ModuleNotFoundError as exc:
            missing = exc.name or "onnx_asr"
            log.warning(
                "[stt] engine = \"parakeet\" but its optional dependency (%s) is not "
                "installed — falling back to faster-whisper for now. Fix: "
                "yazses features enable stt-parakeet",
                missing,
            )
            reason = (f"its optional dependency {missing} is not installed "
                      "(yazses features enable stt-parakeet)")
        except Exception as exc:
            # e.g. a failed model download. Dictation must still come up.
            log.exception(
                "Parakeet STT engine failed to load — falling back to faster-whisper"
            )
            reason = _load_error_reason(exc)
        return _mark_fallback(_build_faster_whisper(stt, fallback_from="parakeet"),
                              "parakeet", reason)
    if name == "moonshine":
        try:
            from yazses.stt.moonshine import MoonshineEngine

            return MoonshineEngine(stt)
        except ModuleNotFoundError as exc:
            missing = exc.name or "moonshine_onnx"
            log.warning(
                "[stt] engine = \"moonshine\" but its optional dependency (%s) is not "
                "installed — falling back to faster-whisper for now. Fix: "
                "yazses features enable stt-moonshine",
                missing,
            )
            reason = (f"its optional dependency {missing} is not installed "
                      "(yazses features enable stt-moonshine)")
        except Exception as exc:
            log.exception(
                "Moonshine STT engine failed to load — falling back to faster-whisper"
            )
            reason = _load_error_reason(exc)
        return _mark_fallback(_build_faster_whisper(stt, fallback_from="moonshine"),
                              "moonshine", reason)
    if name not in ("", DEFAULT_ENGINE):
        log.warning(
            "Unknown [stt] engine %r — falling back to %s "
            "(valid engines: faster-whisper, parakeet, moonshine)",
            name, DEFAULT_ENGINE,
        )
        return _mark_fallback(_build_faster_whisper(stt), name,
                              "it is not an engine YazSes knows")
    return _build_faster_whisper(stt)


def _load_error_reason(exc: BaseException) -> str:
    """The exception's type only: its message can carry a local path or a user name,
    and `yazses status` output gets pasted into bug reports. The log has the detail."""
    return f"it failed to load ({type(exc).__name__}; see `yazses logs`)"


def _mark_fallback(engine: "SttEngine", requested: str, reason: str) -> "SttEngine":
    """Record on the fallback engine which engine was asked for and why it is not running.

    `yazses status` reads these through :func:`describe_active_engine` (#644). Never
    raises: an engine that cannot take attributes (a test double) is returned as is,
    because a fallback exists to keep dictation up.
    """
    try:
        engine.fallback_from = requested  # type: ignore[attr-defined]
        engine.fallback_reason = reason  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        pass
    return engine


def describe_active_engine(engine: object) -> dict[str, str] | None:
    """What *engine* is, the checkpoint it loaded, and the fallback that put it there.

    ``None`` when the engine does not say (a test double, or a third-party engine), so
    a caller reports "unknown" instead of echoing `[stt] engine` as if it had been
    verified. The wrapper engines forward attribute lookups to the engine they wrap.
    """
    name = getattr(engine, "engine_name", None)
    if not isinstance(name, str) or not name:
        return None
    model = getattr(engine, "model_name", "")
    fallback_from = getattr(engine, "fallback_from", "")
    fallback_reason = getattr(engine, "fallback_reason", "")
    return {
        "engine": name,
        "model": model if isinstance(model, str) else "",
        "fallback_from": fallback_from if isinstance(fallback_from, str) else "",
        "fallback_reason": fallback_reason if isinstance(fallback_reason, str) else "",
    }


def render_engine_status_lines(status: dict) -> list[str]:
    """`yazses status` lines for the decoder, from the daemon's status reply.

    A daemon older than #644 sends no ``engine`` field; it gets the old single
    ``model:`` line, unchanged, rather than a guess.
    """
    engine = status.get("engine")
    if not engine:
        return [f"  model:    {status.get('model')}"]
    model = status.get("engine_model") or status.get("model")
    lines = [f"  model:    {model} ({engine})"]
    fallback = status.get("engine_fallback")
    if isinstance(fallback, dict) and fallback.get("from"):
        lines.append(
            f"  FALLBACK: [stt] engine = {fallback['from']} is not running, because "
            f"{fallback.get('reason') or 'it did not load'}. {engine} decodes instead."
        )
    return lines


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
    # An English-only checkpoint cannot decode Persian. faster-whisper does not
    # fail on it — it swaps the language for "en" (or, for Distil-Whisper's large
    # models, decodes with a model trained only on English) — so the user would
    # get fluent-looking English. Refused here, before the model loads (#515); the
    # daemon holds in ERROR state with a toast. The rule itself lives in
    # `language/capability.py` because the settings window, the config loader and
    # doctor apply it too; two copies of this condition would drift.
    refuse_unsupported_language(DEFAULT_ENGINE, model, language)
    return FasterWhisperEngine(
        model_name=model,
        device=getattr(stt, "device", "cpu"),
        compute_type=getattr(stt, "compute_type", "int8"),
        language=language,
        cpu_threads=int(getattr(stt, "cpu_threads", 0) or 0),
        beam_size=int(getattr(stt, "beam_size", 0) or 0),
        condition_on_previous_text=bool(
            getattr(stt, "condition_on_previous_text", True)
        ),
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


def _with_persian_normaliser(engine: "SttEngine", stt: "SttConfig") -> "SttEngine":
    """Wrap *engine* so Persian output receives conservative Unicode normalisation.

    Applied at the same single-chokepoint factory level as `_with_han_script`
    so dictation, `yazses transcribe`, meeting mode and the streaming decoder
    all get it from one wiring point. Returns *engine* untouched when the
    feature is off (`[stt] persian_normalisation` unset, or `[stt] language` not
    Persian), preserving the zero-cost zero-wrapper guarantee for everyone who
    has not opted in — an existing `language = "fa"` install included.
    """
    from yazses.postprocess.output_profile import profile_for
    from yazses.postprocess.persian_text import is_persian_language

    # FA-01 (#509): the output profile of the *STT* language decides what, if
    # anything, rewrites the text; pass-through languages get `None` here.
    normalise = profile_for(getattr(stt, "language", "")).build_normaliser(stt)
    if normalise is None:
        # Set but inert is worth one line: a toggle that reads "on" and does nothing
        # is the failure `_with_han_script` warns about for an `.en` model.
        if getattr(stt, "persian_normalisation", False) and not is_persian_language(
            getattr(stt, "language", "")
        ):
            log.warning(
                "[stt] persian_normalisation is on but [stt] language = %r is not "
                "Persian, so it has no effect. Fix: set language = \"fa\".",
                getattr(stt, "language", ""),
            )
        return engine
    return _PersianNormaliserEngine(engine, normalise)


class _PersianNormaliserEngine:
    """Decorator over an :class:`SttEngine` that normalises Persian output."""

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
        converted = [
            dataclasses.replace(w, text=self._normalise(w.text)) for w in words
        ] if words else words
        return self._normalise(text), converted

    def decode_window(self, audio) -> str:
        return self._normalise(self._inner.decode_window(audio))

    def __getattr__(self, name: str):
        return getattr(self._inner, name)
