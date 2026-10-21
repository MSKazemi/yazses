"""Derive language/profile coherence from canonical YazSes config."""
from __future__ import annotations

from dataclasses import dataclass

from yazses.language.capability import check
from yazses.language.profiles import get_profile


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
    # The Tier-1 command grammar the daemon will actually use, resolved exactly as
    # `Daemon.__init__` resolves it ([commands] language, "auto" following the speech
    # language). Defaults keep the dataclass constructible by older callers.
    command_language: str = ""
    command_language_pinned: bool = False
    command_grammar_available: bool = False
    commands_enabled: bool = True
    # Coherent-but-surprising combinations (an explicit [commands] language that does
    # not match the speech language). Never a reason to call a config INVALID: the
    # design preserves an explicit pin, so it is reported, not refused.
    warnings: tuple[str, ...] = ()
    # #515: what the resolved engine/model can transcribe, from the cited table in
    # `language/capability.py`. `effective_model` is the checkpoint that would
    # actually load (Parakeet/Moonshine ignore a Whisper name in `[stt] model`);
    # `multilingual` is None for a custom checkpoint the table does not know;
    # `language_support` is "supported" | "unsupported" | "unknown".
    effective_model: str = ""
    multilingual: bool | None = None
    language_support: str = "supported"
    support_source: str = ""
    support_reason: str = ""


def _stt(current):
    return getattr(current, "stt", current)


def command_language_state(current, speech_language: str) -> tuple[str, bool, bool, bool]:
    """``(resolved, pinned, grammar_available, enabled)`` for *current*'s commands.

    Uses the registry's own resolver, the one the daemon calls, so status/doctor can
    never describe a grammar the daemon would not select. Checks availability by
    registry membership only: the Mandarin grammar module is not imported.

    *current* may be a whole ``Config`` or a bare ``SttConfig``; without a
    ``commands`` section the shipped defaults (enabled, ``auto``) apply.
    """

    from yazses.commands.grammars.registry import (
        registered_languages,
        resolve_command_language,
    )

    commands = getattr(current, "commands", None)
    configured = str(getattr(commands, "language", "auto") or "auto").strip().lower()
    enabled = bool(getattr(commands, "enabled", True))
    resolved = resolve_command_language(configured, speech_language)
    pinned = configured not in ("", "auto")
    return resolved, pinned, resolved in registered_languages(), enabled


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

    support = check(engine, model, language)
    if support.verdict == "unsupported":
        problems.append(support.reason)

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

    command_language, pinned, grammar_available, commands_enabled = (
        command_language_state(current, language)
    )
    warnings: list[str] = []
    if support.verdict == "unknown":
        warnings.append(support.reason)
    if commands_enabled and pinned and language in {"en", "zh"} and command_language != language:
        warnings.append(
            f"[commands] language is pinned to {command_language!r} while speech is "
            f"{language!r}: spoken commands are matched against the {command_language!r} "
            "grammar. Set [commands] language = \"auto\" to follow the speech language."
        )

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
        command_language=command_language,
        command_language_pinned=pinned,
        command_grammar_available=grammar_available,
        commands_enabled=commands_enabled,
        warnings=tuple(warnings),
        effective_model=support.model,
        multilingual=support.multilingual,
        language_support=support.verdict,
        support_source=support.source_url,
        support_reason=support.reason,
    )
