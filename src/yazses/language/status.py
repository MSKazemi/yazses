"""Derive language/profile coherence from canonical YazSes config."""
from __future__ import annotations

import copy
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


# The `[stt]` keys `derive_status` judges. A feature toggle that writes none of them
# cannot change the language verdict, so it is never inspected.
_LANGUAGE_KEYS = ("engine", "model", "language", "chinese_script")


def feature_toggle_refusal(current, writes) -> str:
    """Why applying a feature toggle's *writes* to *current* must be refused, or ``""``.

    #497: `yazses language set` and the Settings language row switch a profile as one
    unit, but `features enable chinese-script` wrote ``chinese_script`` onto the
    default ``base.en`` + ``en`` install, and `features enable stt-parakeet`/`stt-moonshine`
    wrote an English-only engine under Mandarin speech -- each a single command that
    left `yazses doctor` at FAIL. The CLI and the settings window both ask here, so
    they refuse the same toggles with the same words.

    Pure: *writes* are the registry's ``(section, key, value, quote)`` tuples and are
    applied to a copy. Refuses only when the toggle *adds* a problem that
    :func:`derive_status` reports -- the same check doctor and `language status` run --
    so a config that is already incoherent is not blamed on the toggle, and a toggle
    that repairs one (turning a stray script off) is never refused.
    """

    changes = {
        key: str(value)
        for section, key, value, *_quote in writes or ()
        if section == "stt" and key in _LANGUAGE_KEYS
    }
    stt = _stt(current)
    if not changes or stt is None:
        return ""

    candidate_stt = copy.copy(stt)
    for key, value in changes.items():
        setattr(candidate_stt, key, value)
    if hasattr(current, "stt"):
        candidate = copy.copy(current)
        candidate.stt = candidate_stt
    else:
        candidate = candidate_stt

    before = set(derive_status(current).problems)
    after = derive_status(candidate)
    added = [problem for problem in after.problems if problem not in before]
    if not added:
        return ""

    if after.output_script and after.speech_language != "zh":
        remedy = (
            "Han-script output is part of a Mandarin profile: run "
            "`yazses language set zh-CN` (Simplified) or `yazses language set zh-TW` "
            "(Traditional), which set the speech language, a multilingual model and "
            "the script together."
        )
    elif "engine" in changes:
        engine = str(getattr(stt, "engine", "") or "faster-whisper")
        remedy = (
            f"Keep [stt] engine = \"{engine}\" for "
            f"{after.speech_language or 'auto-detected'!r} speech, or switch the "
            "language first (`yazses language set en`)."
        )
    else:
        remedy = "`yazses language status` shows the current settings."
    return (
        "it would leave the language settings inconsistent — "
        + "; ".join(problem.rstrip(". ") for problem in added)
        + ". Nothing was written. "
        + remedy
    )
