"""Language-neutral command intent types shared by grammar implementations."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IntentType(str, Enum):
    DICTATE = "dictate"
    NAVIGATE = "navigate"
    EDIT = "edit"
    REFACTOR = "refactor"
    TERMINAL = "terminal"
    MACRO = "macro"


@dataclass
class CommandIntent:
    intent: IntentType
    action: str
    args: dict[str, str] = field(default_factory=dict)
    raw_text: str = ""
