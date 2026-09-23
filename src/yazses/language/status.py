"""Derive language/profile coherence from canonical YazSes config."""
from __future__ import annotations

from dataclasses import dataclass

from yazses.language.profiles import get_profile
from yazses.stt.download import language_model_problem


@dataclass(frozen=True)
class LanguageStatus:
    speech_language: str
    output_script: str
    engine: str
    model: str
    profile_match: str | None
    custom_model: bool
    coherent: bool
    problems: tuple[str, ...]


def _stt(current):
    return getattr(current, "stt", current)


def derive_status(current) -> LanguageStatus:
    """Inspect config only; perform no dependency probe, download, or model import."""

    stt = _stt(current)
    engine = (
        str(getattr(stt, "engine", "faster-whisper") or "faster-whisper")
        .strip()
        .lower()
        or "faster-whisper"
    )
    model = str(getattr(stt, "model", "base.en") or "base.en").strip() or "base.en"
    language = str(getattr(stt, "language", "en") or "").strip().lower()
    script = str(getattr(stt, "chinese_script", "") or "").strip().lower()

    problems: list[str] = []

    pair_problem = language_model_problem(model, language)
    if pair_problem:
        problems.append(pair_problem)

    if script not in {"", "simplified", "traditional"}:
        problems.append(
            f"unknown [stt] chinese_script {script!r}; expected '', 'simplified', "
            "or 'traditional'"
        )

    if script and language != "zh":
        problems.append(
            f"[stt] chinese_script={script!r} is set while speech language is "
            f"{language or '<auto>'!r}; Han-script normalisation is a Chinese-output setting"
        )

    if language == "zh" and engine != "faster-whisper":
        problems.append(
            f"[stt] engine {engine!r} is not declared Mandarin-capable; "
            "use 'faster-whisper' for the P1 Mandarin profiles"
        )

    profile_match: str | None = None
    if language == "en" and not script:
        profile_match = "en"
    elif language == "zh" and script == "simplified":
        profile_match = "zh-CN"
    elif language == "zh" and script == "traditional":
        profile_match = "zh-TW"

    custom_model = False
    if profile_match is not None:
        profile = get_profile(profile_match)
        custom_model = (
            model != profile.recommended_model
            or engine != profile.recommended_engine
        )

    return LanguageStatus(
        speech_language=language,
        output_script=script,
        engine=engine,
        model=model,
        profile_match=profile_match,
        custom_model=custom_model,
        coherent=not problems,
        problems=tuple(problems),
    )
