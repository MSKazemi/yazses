"""Shared grammar data model; contains no language-specific phrases."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from yazses.commands.types import IntentType


def _identity_arg(_name: str, value: str) -> str:
    return value


@dataclass(frozen=True)
class GrammarRule:
    pattern: re.Pattern[str]
    intent: IntentType
    action: str
    arg_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommandGrammar:
    language: str
    rules: tuple[GrammarRule, ...]
    normalise: Callable[[str], str]
    #: Canonicalise one captured argument. Returning ``None`` rejects the rule, so an
    #: argument the grammar cannot interpret fails closed instead of reaching dispatch.
    normalise_arg: Callable[[str, str], str | None] = _identity_arg
