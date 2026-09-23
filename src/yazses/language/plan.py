"""Pure language-profile resolution into inspectable config mutations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from yazses.language.profiles import LanguageProfileError, get_profile
from yazses.stt.download import is_english_only, language_model_problem

ResolveMode = Literal["preserve", "recommended"]


@dataclass(frozen=True)
class ConfigMutation:
    """One canonical config-field change proposed by a language switch."""

    section: str
    key: str
    before: object
    after: object
    reason: str


@dataclass(frozen=True)
class LanguagePlan:
    """Everything a caller needs to preview/preflight a language switch.

    model_download names the model whose availability should be preflighted if the
    plan changes models. It does not mean the model is absent: checking the cache is
    I/O and intentionally belongs to the application/preflight layer.
    """

    requested: str
    canonical_profile: str
    mutations: tuple[ConfigMutation, ...]
    model_download: str | None
    required_extras: tuple[str, ...]
    warnings: tuple[str, ...]
    restart_required: bool


def _stt(current):
    """Accept a full Config or a SttConfig/duck-typed equivalent."""

    return getattr(current, "stt", current)


def _engine(value: object) -> str:
    return (str(value or "faster-whisper").strip().lower() or "faster-whisper")


def _model(value: object) -> str:
    return str(value or "base.en").strip() or "base.en"


def _mutation(
    out: list[ConfigMutation],
    *,
    section: str,
    key: str,
    before: object,
    after: object,
    reason: str,
) -> None:
    if before != after:
        out.append(
            ConfigMutation(
                section=section,
                key=key,
                before=before,
                after=after,
                reason=reason,
            )
        )


def resolve_profile(
    requested: str,
    current,
    *,
    model: str | None = None,
    engine: str | None = None,
    mode: ResolveMode = "preserve",
) -> LanguagePlan:
    """Resolve a high-level language request without side effects.

    Preserve mode keeps a currently compatible model/engine. Recommended mode selects
    the profile baseline. Explicit model/engine arguments are user requirements and
    are refused rather than silently corrected when they contradict Mandarin support.
    """

    if mode not in ("preserve", "recommended"):
        raise ValueError("mode must be 'preserve' or 'recommended'")
    if mode == "recommended" and (model is not None or engine is not None):
        raise LanguageProfileError(
            "Recommended mode selects the profile engine/model itself; do not combine "
            "it with an explicit model or engine override."
        )

    profile = get_profile(requested)
    stt = _stt(current)

    current_engine = _engine(getattr(stt, "engine", "faster-whisper"))
    current_model = _model(getattr(stt, "model", "base.en"))
    current_language = str(getattr(stt, "language", "en") or "").strip()
    current_script = str(getattr(stt, "chinese_script", "") or "").strip().lower()

    requested_engine = _engine(engine) if engine is not None else current_engine
    requested_model = _model(model) if model is not None else current_model

    if engine is not None and requested_engine != "faster-whisper":
        raise LanguageProfileError(
            "Explicit --engine overrides in language profiles currently support only "
            "'faster-whisper'. Existing compatible specialized English engines are "
            "preserved when no override is requested; configure engine-specific models "
            "through their own feature/settings path."
        )
    if model is not None and requested_engine != "faster-whisper":
        raise LanguageProfileError(
            "Explicit --model overrides in language profiles are validated only for "
            "'faster-whisper'. Switch to --engine faster-whisper as well, or configure "
            "the specialized engine through its own feature/settings path."
        )

    if profile.speech_language == "zh" and model is not None:
        problem = language_model_problem(requested_model, "zh")
        if problem:
            raise LanguageProfileError(problem)

    if mode == "recommended":
        target_engine = profile.recommended_engine
        target_model = profile.recommended_model
    else:
        target_engine = requested_engine
        target_model = requested_model

        if profile.speech_language == "zh":
            if target_engine != "faster-whisper":
                target_engine = profile.recommended_engine
                target_model = profile.recommended_model
            elif language_model_problem(target_model, "zh"):
                target_model = profile.recommended_model

    if mode == "preserve":
        if engine is not None:
            target_engine = requested_engine
        if model is not None:
            target_model = requested_model

    mutations: list[ConfigMutation] = []

    engine_reason = (
        f"{profile.id} recommended engine"
        if mode == "recommended"
        else "current engine is not declared Mandarin-capable"
    )
    _mutation(
        mutations,
        section="stt",
        key="engine",
        before=current_engine,
        after=target_engine,
        reason=engine_reason,
    )

    if target_model != current_model:
        if mode == "recommended":
            model_reason = f"{profile.id} recommended model"
        elif is_english_only(current_model) and profile.speech_language == "zh":
            model_reason = f"{current_model} is English-only"
        else:
            model_reason = "current model is not compatible with the selected language/engine"
        _mutation(
            mutations,
            section="stt",
            key="model",
            before=current_model,
            after=target_model,
            reason=model_reason,
        )

    _mutation(
        mutations,
        section="stt",
        key="language",
        before=current_language,
        after=profile.speech_language,
        reason=f"speech language for {profile.id}",
    )
    _mutation(
        mutations,
        section="stt",
        key="chinese_script",
        before=current_script,
        after=profile.output_script,
        reason=(
            f"output script for {profile.id}"
            if profile.output_script
            else "English profile does not use Han-script normalisation"
        ),
    )

    changed_model = target_model if target_model != current_model else None
    required_extras = ("chinese",) if profile.output_script else ()

    return LanguagePlan(
        requested=requested,
        canonical_profile=profile.id,
        mutations=tuple(mutations),
        model_download=changed_model,
        required_extras=required_extras,
        warnings=(),
        restart_required=bool(mutations),
    )
