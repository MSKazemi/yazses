"""Code command grammar classifier — detects voice commands in transcribed text.

Tier-1 phrase tables live under :mod:`yazses.commands.grammars`.  This module keeps
the historical public API and compatibility aliases so downstream code and the Android
parity tests do not need to change during the registry extraction.
"""
from __future__ import annotations

import logging
from typing import Protocol

from yazses.commands.grammars.en import (
    ENGLISH_GRAMMAR,
    normalise_numwords as _normalise_numwords,
    strip_outer_punct as _strip_outer_punct,
)
from yazses.commands.grammars.registry import get_grammar
from yazses.commands.types import CommandIntent, IntentType

log = logging.getLogger(__name__)

# Compatibility view for tests/tools that intentionally inspect the ordered desktop
# grammar.  Keep the historical tuple/list shape until the Android contract is moved
# to the language registry in a follow-up.
_RULES = [
    (rule.pattern, rule.intent, rule.action, list(rule.arg_names))
    for rule in ENGLISH_GRAMMAR.rules
]


class _MacroHit(Protocol):
    @property
    def trigger(self) -> str: ...


class _MacroTable(Protocol):
    def match(self, text: str) -> _MacroHit | None: ...


class _SlmRouter(Protocol):
    def classify(self, text: str, profile: str) -> CommandIntent | None: ...


def classify(
    text: str,
    profile: str = "default",
    slm_router: _SlmRouter | None = None,
    macro_table: _MacroTable | None = None,
    *,
    language: str = "en",
) -> CommandIntent:
    """Classify transcribed text as a localized command or plain dictation.

    Existing positional arguments are unchanged; language is keyword-only.

    Tier 0: optional user macro table (whole-utterance exact match), checked first.
    Tier 1: deterministic grammar for the selected language.
    Tier 2: optional SLM router, English only. Mandarin fuzzy/LLM commands are out
    of P1 scope so unmatched Chinese prose can never be promoted by the English SLM.
    """

    if not text or not text.strip():
        return CommandIntent(intent=IntentType.DICTATE, action="inject", raw_text=text)

    if macro_table is not None:
        macro = macro_table.match(text)
        if macro is not None:
            return CommandIntent(
                intent=IntentType.MACRO,
                action="expand",
                args={"trigger": macro.trigger},
                raw_text=text,
            )

    try:
        grammar = get_grammar(language)
    except KeyError:
        log.warning(
            "No Tier 1 command grammar for language %r; treating as dictation.",
            language,
        )
        return CommandIntent(intent=IntentType.DICTATE, action="inject", raw_text=text)

    normalised = grammar.normalise(text)

    for rule in grammar.rules:
        match = rule.pattern.match(normalised)
        if match:
            args: dict[str, str] = {}
            for i, name in enumerate(rule.arg_names, 1):
                try:
                    args[name] = grammar.normalise_arg(name, match.group(i).strip())
                except IndexError:
                    pass
            return CommandIntent(
                intent=rule.intent,
                action=rule.action,
                args=args,
                raw_text=text,
            )

    # Chinese P1 is intentionally deterministic. Running the English-trained/local
    # Tier-2 router on Chinese prose would broaden command execution beyond the
    # reviewed anchored grammar and violate the false-positive safety contract.
    if slm_router is not None and grammar.language == "en":
        try:
            slm_result = slm_router.classify(text, profile)
        except Exception:
            log.warning(
                "Tier 2 SLM router failed; treating as dictation.",
                exc_info=True,
            )
            slm_result = None
        if slm_result is not None:
            return slm_result

    return CommandIntent(intent=IntentType.DICTATE, action="inject", raw_text=text)
