"""Language grammar registry.

Only English is registered in this behavior-preserving refactor. Mandarin is added in
its own reviewed change so an English extraction cannot hide command behavior changes.
"""
from __future__ import annotations

from yazses.commands.grammars.base import CommandGrammar
from yazses.commands.grammars.en import ENGLISH_GRAMMAR

_GRAMMARS = {
    "en": ENGLISH_GRAMMAR,
}


def get_grammar(language: str = "en") -> CommandGrammar:
    key = (language or "en").strip().lower().replace("_", "-")
    if key.startswith("en-"):
        key = "en"
    try:
        return _GRAMMARS[key]
    except KeyError as exc:
        raise KeyError(f"No Tier-1 command grammar registered for {language!r}") from exc


def registered_languages() -> tuple[str, ...]:
    return tuple(_GRAMMARS)
