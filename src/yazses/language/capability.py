"""Which speech languages each STT engine/model can actually transcribe (#515).

A pure, data-driven table: no I/O, no model import, no optional dependency. Every
claim in it cites the source it was read from — a model card or the engine's own
docs — so a reviewer can check a row without trusting this file. A claim that could
not be cited is marked ``verified=False`` and is never used to *refuse* a config,
only to report it.

Why it exists. Pairing a non-English ``[stt] language`` with an English-only
checkpoint does not fail. faster-whisper 1.2.1 (``transcribe.py``) replaces the
language with ``"en"`` for a model whose tokenizer is not multilingual and logs a
warning nobody reads; Parakeet TDT v2 and Moonshine take no language at all. The
user gets fluent-looking English for Persian speech. The older guard
(``stt/download.py::is_english_only``) only knew the ``.en`` suffix, so it missed
the Distil-Whisper ``large`` checkpoints (English-only by their model cards, but
named without ``.en`` and shipped with a multilingual tokenizer, so faster-whisper
does not even warn) and every non-Whisper engine.

``check`` is the one answer every surface asks: the config loader
(``configcheck``), the engine factory, the Settings window, ``yazses language
status`` and ``yazses doctor``. Two copies of this rule are how they drift.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "CAPABILITIES",
    "DEFAULT_ENGINE",
    "ENGINE_DEFAULT_MODELS",
    "LanguageSupport",
    "ModelCapability",
    "Verdict",
    "WHISPER_LANGUAGES",
    "check",
    "find_capability",
    "normalise_language",
    "resolve_engine",
    "resolve_model",
]

Verdict = Literal["supported", "unsupported", "unknown"]

DEFAULT_ENGINE = "faster-whisper"

#: The checkpoint each non-Whisper engine loads when ``[stt] model`` does not name
#: one of its own. Mirrors the engines' ``DEFAULT_MODEL`` constants; the test suite
#: asserts the two agree, so a changed default cannot leave this table describing a
#: model nobody loads.
ENGINE_DEFAULT_MODELS: dict[str, str] = {
    "parakeet": "nemo-parakeet-tdt-0.6b-v2",
    "moonshine": "moonshine/base",
}

# ── Sources ──────────────────────────────────────────────────────────────────
# Quoted text is copied from the page as read on 2026-10-21.

_SRC_WHISPER = (
    "https://github.com/openai/whisper#available-models-and-languages",
    "\"four with English-only versions\"; \"The .en models for English-only "
    "applications\"; tiny/base/small/medium/large are the multilingual models",
)
_SRC_WHISPER_V3 = (
    "https://huggingface.co/openai/whisper-large-v3",
    "large-v3 adds \"A new language token for Cantonese\"",
)
_SRC_WHISPER_TURBO = (
    "https://huggingface.co/openai/whisper-large-v3-turbo",
    "tagged 99 languages; \"an optimized version of large-v3\" (openai/whisper README)",
)
_SRC_DISTIL_V2 = (
    "https://huggingface.co/distil-whisper/distil-large-v2",
    "\"Distil-Whisper is currently only available for English speech recognition.\"",
)
_SRC_DISTIL_V3 = (
    "https://huggingface.co/distil-whisper/distil-large-v3",
    "\"the third and final installment of the Distil-Whisper English series\"",
)
_SRC_DISTIL_V35 = (
    "https://huggingface.co/distil-whisper/distil-large-v3.5",
    "\"the newest addition to the Distil-Whisper English family\"",
)
_SRC_PARAKEET_V2 = (
    "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2",
    "\"designed for high-quality English transcription\"",
)
_SRC_PARAKEET_V3 = (
    "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3",
    "\"expanding language support from English to 25 European languages\"",
)
_SRC_MOONSHINE = (
    "https://huggingface.co/UsefulSensors/moonshine",
    "\"capable of transcribing English speech audio into English text\"; tiny and "
    "base are both marked English-only",
)

#: Whisper's language codes, minus Cantonese (``yue``), which only the large-v3
#: tokenizer has. Mirrors ``faster_whisper.tokenizer._LANGUAGE_CODES`` (1.2.1);
#: ``tests/test_language_capability.py`` asserts equality when faster-whisper is
#: installed, the same drift guard ``stt/download.py::WHISPER_MODELS`` has.
WHISPER_LANGUAGES: frozenset[str] = frozenset({
    "af", "am", "ar", "as", "az", "ba", "be", "bg", "bn", "bo", "br", "bs", "ca",
    "cs", "cy", "da", "de", "el", "en", "es", "et", "eu", "fa", "fi", "fo", "fr",
    "gl", "gu", "ha", "haw", "he", "hi", "hr", "ht", "hu", "hy", "id", "is", "it",
    "ja", "jw", "ka", "kk", "km", "kn", "ko", "la", "lb", "ln", "lo", "lt", "lv",
    "mg", "mi", "mk", "ml", "mn", "mr", "ms", "mt", "my", "ne", "nl", "nn", "no",
    "oc", "pa", "pl", "ps", "pt", "ro", "ru", "sa", "sd", "si", "sk", "sl", "sn",
    "so", "sq", "sr", "su", "sv", "sw", "ta", "te", "tg", "th", "tk", "tl", "tr",
    "tt", "uk", "ur", "uz", "vi", "yi", "yo", "zh",
})
_WHISPER_V3_LANGUAGES = WHISPER_LANGUAGES | {"yue"}

_ENGLISH = frozenset({"en"})

#: Parakeet TDT 0.6B v3's 25 languages, as listed on its model card.
_PARAKEET_V3_LANGUAGES: frozenset[str] = frozenset({
    "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr", "hr", "hu", "it",
    "lt", "lv", "mt", "nl", "pl", "pt", "ro", "ru", "sk", "sl", "sv", "uk",
})


@dataclass(frozen=True)
class ModelCapability:
    """What one checkpoint of one engine can transcribe, and where that is stated."""

    engine: str
    model: str
    languages: frozenset[str]
    source_url: str
    evidence: str
    #: The multilingual checkpoint to suggest instead, for an English-only one.
    alternative: str = ""
    #: False when the claim could not be traced to a source. Never used to refuse.
    verified: bool = True

    @property
    def multilingual(self) -> bool:
        return self.languages != _ENGLISH


def _fw(model: str, languages: frozenset[str], source: tuple[str, str],
        alternative: str = "") -> ModelCapability:
    return ModelCapability(
        engine="faster-whisper", model=model, languages=languages,
        source_url=source[0], evidence=source[1], alternative=alternative,
    )


#: One row per checkpoint YazSes knows by name. The faster-whisper names are exactly
#: `stt/download.py::WHISPER_MODELS`; a test holds the two equal, so adding a model
#: there without stating its languages here fails the suite.
CAPABILITIES: tuple[ModelCapability, ...] = (
    _fw("tiny.en", _ENGLISH, _SRC_WHISPER, "tiny"),
    _fw("base.en", _ENGLISH, _SRC_WHISPER, "base"),
    _fw("small.en", _ENGLISH, _SRC_WHISPER, "small"),
    _fw("medium.en", _ENGLISH, _SRC_WHISPER, "medium"),
    _fw("tiny", WHISPER_LANGUAGES, _SRC_WHISPER),
    _fw("base", WHISPER_LANGUAGES, _SRC_WHISPER),
    _fw("small", WHISPER_LANGUAGES, _SRC_WHISPER),
    _fw("medium", WHISPER_LANGUAGES, _SRC_WHISPER),
    _fw("large-v1", WHISPER_LANGUAGES, _SRC_WHISPER),
    _fw("large-v2", WHISPER_LANGUAGES, _SRC_WHISPER),
    _fw("large-v3", _WHISPER_V3_LANGUAGES, _SRC_WHISPER_V3),
    # `large` resolves to large-v3 (stt/download.py::WHISPER_MODELS).
    _fw("large", _WHISPER_V3_LANGUAGES, _SRC_WHISPER_V3),
    _fw("large-v3-turbo", _WHISPER_V3_LANGUAGES, _SRC_WHISPER_TURBO),
    _fw("turbo", _WHISPER_V3_LANGUAGES, _SRC_WHISPER_TURBO),
    # Distil-Whisper: English-only by every model card, although the large ones keep
    # Whisper's multilingual tokenizer — so faster-whisper does not force "en" and
    # does not warn; it decodes Persian with a model trained on English.
    _fw("distil-small.en", _ENGLISH, _SRC_DISTIL_V2, "small"),
    _fw("distil-medium.en", _ENGLISH, _SRC_DISTIL_V2, "medium"),
    _fw("distil-large-v2", _ENGLISH, _SRC_DISTIL_V2, "large-v2"),
    _fw("distil-large-v3", _ENGLISH, _SRC_DISTIL_V3, "large-v3"),
    _fw("distil-large-v3.5", _ENGLISH, _SRC_DISTIL_V35, "large-v3"),
    ModelCapability(
        engine="parakeet", model="nemo-parakeet-tdt-0.6b-v2", languages=_ENGLISH,
        source_url=_SRC_PARAKEET_V2[0], evidence=_SRC_PARAKEET_V2[1],
    ),
    ModelCapability(
        engine="parakeet", model="nemo-parakeet-tdt-0.6b-v3",
        languages=_PARAKEET_V3_LANGUAGES,
        source_url=_SRC_PARAKEET_V3[0], evidence=_SRC_PARAKEET_V3[1],
    ),
    ModelCapability(
        engine="moonshine", model="moonshine/tiny", languages=_ENGLISH,
        source_url=_SRC_MOONSHINE[0], evidence=_SRC_MOONSHINE[1],
    ),
    ModelCapability(
        engine="moonshine", model="moonshine/base", languages=_ENGLISH,
        source_url=_SRC_MOONSHINE[0], evidence=_SRC_MOONSHINE[1],
    ),
)

_BY_KEY: dict[tuple[str, str], ModelCapability] = {
    (c.engine, c.model.lower()): c for c in CAPABILITIES
}

_KNOWN_ENGINES = ("faster-whisper", "parakeet", "moonshine")


@dataclass(frozen=True)
class LanguageSupport:
    """The verdict for one (engine, model, language) triple.

    ``engine`` and ``model`` are what would actually *run*: an unknown engine falls
    back to faster-whisper and a Whisper name under ``engine = "parakeet"`` loads
    Parakeet's default, exactly as the engines themselves resolve them.
    """

    engine: str
    model: str
    language: str
    verdict: Verdict
    #: True/False when the table knows the checkpoint, None when it does not.
    multilingual: bool | None
    capability: ModelCapability | None
    #: Actionable text for ``unsupported`` and ``unknown``; empty when supported.
    reason: str = ""

    @property
    def source_url(self) -> str:
        return self.capability.source_url if self.capability else ""


def normalise_language(language: str | None) -> str:
    """``"fa-IR"`` → ``"fa"``; ``""``/``"translate"``/``"auto"`` → ``""`` (auto-detect)."""
    code = (language or "").strip().lower().replace("_", "-")
    if code in ("", "auto", "translate"):
        return ""
    return code.split("-", 1)[0]


def resolve_engine(engine: str | None) -> str:
    """The engine `stt/factory.py` builds for *engine*: unknown names fall back."""
    name = (engine or "").strip().lower()
    return name if name in _KNOWN_ENGINES else DEFAULT_ENGINE


def resolve_model(engine: str, model: str | None) -> str:
    """The checkpoint *engine* loads for ``[stt] model = model``.

    Parakeet honours the name only when it names a Parakeet model and Moonshine only
    a ``moonshine/`` one (see their ``__init__``); otherwise each loads its default.
    """
    name = (model or "").strip()
    if engine == "parakeet":
        return name if "parakeet" in name.lower() else ENGINE_DEFAULT_MODELS["parakeet"]
    if engine == "moonshine":
        return name if name.startswith("moonshine/") else ENGINE_DEFAULT_MODELS["moonshine"]
    return name or "base.en"


def find_capability(engine: str, model: str) -> ModelCapability | None:
    """The table row for *engine*/*model*, or None for a custom/unknown checkpoint."""
    return _BY_KEY.get((engine, (model or "").strip().lower()))


def _english_only_reason(lang: str, support_engine: str, model: str,
                         cap: ModelCapability | None) -> str:
    if support_engine == "faster-whisper":
        suggestion = (cap.alternative if cap and cap.alternative else
                      model.strip()[: -len(".en")] if model.lower().endswith(".en") else "")
        suggestion = suggestion or "small"
        fix = (
            f"Choose {suggestion!r} instead — drop the .en suffix."
            if model.lower().endswith(".en")
            else f"Choose the multilingual {suggestion!r} instead."
        )
        return (
            f"{lang!r} needs a multilingual model, but {model!r} is English-only — "
            f"speech would be mis-transcribed as English rather than refused. {fix}"
        )
    return (
        f"{lang!r} needs a multilingual model, but the {support_engine} engine loads "
        f"{model!r}, which is English-only — speech would be mis-transcribed as "
        "English rather than refused. Fix: set [stt] engine = \"faster-whisper\" "
        "with a multilingual model (e.g. model = \"small\")."
    )


def check(engine: str | None, model: str | None, language: str | None) -> LanguageSupport:
    """Can *engine* running *model* transcribe *language*? Pure; never raises.

    * ``supported`` — the table cites a source saying so, or the language is
      auto-detect/English (an English-only model handles both as designed).
    * ``unsupported`` — the table cites a source saying it cannot. Callers refuse.
    * ``unknown`` — a custom checkpoint (hub id, local path) or an unverified row.
      Callers report it; they never refuse on it, because guessing would reject a
      model that works.

    A custom faster-whisper name ending in ``.en`` is still treated as English-only:
    that suffix is Whisper's own naming convention for the English-only checkpoints
    (openai/whisper README), which is what the older guard relied on.
    """
    eng = resolve_engine(engine)
    mdl = resolve_model(eng, model)
    lang = normalise_language(language)
    cap = find_capability(eng, mdl)

    if cap is None:
        english_only = eng == "faster-whisper" and mdl.lower().endswith(".en")
        multilingual: bool | None = False if english_only else None
        if not lang or lang == "en":
            return LanguageSupport(eng, mdl, lang, "supported", multilingual, None)
        if english_only:
            return LanguageSupport(
                eng, mdl, lang, "unsupported", False, None,
                _english_only_reason(lang, eng, mdl, None),
            )
        return LanguageSupport(
            eng, mdl, lang, "unknown", None, None,
            f"{mdl!r} is not a checkpoint YazSes has language data for, so it cannot "
            f"confirm the model transcribes {lang!r}. Check the model's card; "
            "if it is English-only, speech will come out as English.",
        )

    if not lang or lang in cap.languages:
        return LanguageSupport(eng, mdl, lang, "supported", cap.multilingual, cap)

    if not cap.verified:
        return LanguageSupport(
            eng, mdl, lang, "unknown", cap.multilingual, cap,
            f"YazSes has no cited source on whether {mdl!r} transcribes {lang!r}.",
        )

    if not cap.multilingual:
        reason = _english_only_reason(lang, eng, mdl, cap)
    elif eng == "faster-whisper" and lang in _WHISPER_V3_LANGUAGES:
        reason = (
            f"{lang!r} needs the large-v3 tokenizer, which {mdl!r} does not have "
            f"(source: {_SRC_WHISPER_V3[0]}). Fix: set [stt] model = \"large-v3\" "
            "or \"large-v3-turbo\"."
        )
    else:
        reason = (
            f"{lang!r} is not among the languages {mdl!r} ({eng}) transcribes "
            f"(source: {cap.source_url}). "
            + (
                "Fix: use a language code Whisper knows, e.g. \"fa\" or \"de\"."
                if eng == "faster-whisper"
                else "Fix: set [stt] engine = \"faster-whisper\" with a multilingual "
                "model (e.g. model = \"small\")."
            )
        )
    return LanguageSupport(eng, mdl, lang, "unsupported", cap.multilingual, cap, reason)
