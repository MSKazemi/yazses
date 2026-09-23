"""Code command grammar classifier — detects voice commands in transcribed text.

Tier-1 phrase tables live under :mod:`yazses.commands.grammars`.  This module keeps
the historical public API and compatibility aliases so downstream code and the Android
parity tests do not need to change during the registry extraction.
"""
from __future__ import annotations

import logging
from typing import Protocol

from yazses.commands.grammars.en import ENGLISH_GRAMMAR
from yazses.commands.grammars.en import (
    normalise_numwords as _normalise_numwords,  # noqa: F401 — compat re-export
)
from yazses.commands.grammars.en import (
    strip_outer_punct as _strip_outer_punct,  # noqa: F401 — compat re-export
)
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
) -> CommandIntent:
    """Classify transcribed text as an English command or plain dictation.

    This function intentionally keeps the pre-registry signature and behavior.
    Language selection is wired in a separate change after the English extraction
    proves parity.

    Tier 0: optional user macro table (whole-utterance exact match), checked first.
    Tier 1: English regex grammar.
    Tier 2: optional SLM router called when Tier 1 returns DICTATE.
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

    normalised = ENGLISH_GRAMMAR.normalise(text)

    for rule in ENGLISH_GRAMMAR.rules:
        match = rule.pattern.match(normalised)
        if match:
            args: dict[str, str] = {}
            for i, name in enumerate(rule.arg_names, 1):
                try:
                    args[name] = match.group(i).strip()
                except IndexError:
                    pass
            return CommandIntent(
                intent=rule.intent,
                action=rule.action,
                args=args,
                raw_text=text,
            )

    if slm_router is not None:
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
