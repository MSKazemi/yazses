"""Language grammar registry and command-language resolution.

English stays eagerly available for the default path. Mandarin is imported lazily only
when selected, so an English installation pays no Chinese-module import cost.
"""
from __future__ import annotations

from yazses.commands.grammars.base import CommandGrammar
from yazses.commands.grammars.en import ENGLISH_GRAMMAR

_REGISTERED = ("en", "zh")


def _normalise_explicit(value: str) -> str:
    return (value or "").strip().lower().replace("_", "-")


def resolve_command_language(configured: str, speech_language: str) -> str:
    """Resolve [commands] language; auto follows the effective STT language.

    The return value may be unsupported. Callers must not silently map an unknown
    language to English; that would execute English commands in unrelated speech.
    """

    configured_key = _normalise_explicit(configured) or "auto"
    if configured_key != "auto":
        return configured_key

    speech = _normalise_explicit(speech_language)
    if not speech:
        return ""
    if speech == "en" or speech.startswith("en-"):
        return "en"
    if speech in {"zh", "zh-cn", "zh-tw", "zh-hans", "zh-hant"}:
        return "zh"
    if speech == "zh-hk":
        return "zh-hk"
    return speech.split("-", 1)[0]


def get_grammar(language: str = "en") -> CommandGrammar:
    """Return a registered Tier-1 grammar or raise; never cross-language fallback."""

    key = _normalise_explicit(language)
    if key == "en" or key.startswith("en-"):
        return ENGLISH_GRAMMAR
    if key == "zh":
        from yazses.commands.grammars.zh import MANDARIN_GRAMMAR

        return MANDARIN_GRAMMAR
    raise KeyError(f"No Tier-1 command grammar registered for {language!r}")


def registered_languages() -> tuple[str, ...]:
    return _REGISTERED
