"""Shared grammar data model; contains no language-specific phrases."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from yazses.commands.types import IntentType


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
