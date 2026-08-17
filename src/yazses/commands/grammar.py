"""Code command grammar classifier — detects voice commands in transcribed text."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


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
    action: str           # e.g. "delete_words", "go_to_line"
    args: dict[str, str] = field(default_factory=dict)  # e.g. {"n": "3"}, {"name": "main"}
    raw_text: str = ""


# Number word → digit normalisation
_NUM_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}


def _normalise_numwords(text: str) -> str:
    """Replace spelled-out numbers with digits (case-insensitive)."""
    pattern = re.compile(r'\b(' + '|'.join(_NUM_WORDS) + r')\b', re.IGNORECASE)
    return pattern.sub(lambda m: _NUM_WORDS[m.group(1).lower()], text)


# Sentence punctuation Whisper adds to short utterances ("Undo." / "Save file.")
# that would otherwise break the anchored ^...$ command patterns. Stripped from
# both ends before matching; interior punctuation (e.g. "main.py") is preserved.
_OUTER_PUNCT = " \t\r\n.,!?;:\"'`…"


def _strip_outer_punct(text: str) -> str:
    return text.strip().strip(_OUTER_PUNCT).strip()


# Grammar rules: (compiled_pattern, IntentType, action_name, arg_names_from_groups)
# Each rule: pattern must match the full (stripped, lowercased) text or a leading/trailing command phrase.
# Rules are evaluated in order; first match wins.

_RULES: list[tuple[re.Pattern, IntentType, str, list[str]]] = []


def _add(pattern: str, intent: IntentType, action: str, arg_names: list[str] | None = None) -> None:
    _RULES.append((re.compile(pattern, re.IGNORECASE), intent, action, arg_names or []))


# EDIT commands
_add(r'^delete\s+(?:the\s+)?last\s+(\d+)\s+words?$', IntentType.EDIT, "delete_words", ["n"])
_add(r'^delete\s+(?:the\s+)?last\s+word$', IntentType.EDIT, "delete_words", [])
_add(r'^delete\s+(?:the\s+)?last\s+(\d+)\s+lines?$', IntentType.EDIT, "delete_lines", ["n"])
_add(r'^delete\s+(?:the\s+)?last\s+line$', IntentType.EDIT, "delete_lines", [])
_add(r'^undo(?:\s+that)?$', IntentType.EDIT, "undo", [])
_add(r'^undo\s+(\d+)\s+times?$', IntentType.EDIT, "undo_n", ["n"])
_add(r'^save(?:\s+file)?(?:\s+now)?$', IntentType.EDIT, "save", [])
_add(r'^copy(?:\s+(?:that|this|line|selection))?$', IntentType.EDIT, "copy", [])
_add(r'^paste(?:\s+here)?$', IntentType.EDIT, "paste", [])
# Multi-word forms first: "comment this line" is what people actually say, and the
# README documented it, but the pattern only ever allowed ONE trailing word — so the
# phrase fell through to DICTATE and the words were typed into the file. Safe to widen
# because the pattern is anchored at both ends: only these exact utterances match, and
# ordinary prose containing "comment" is untouched.
_add(
    r'^comment(?:\s+(?:this\s+line|the\s+line|this\s+selection|this|line|selection|out))?$',
    IntentType.EDIT, "comment", [],
)
_add(r'^select\s+(\d+)\s+lines?$', IntentType.EDIT, "select_lines", ["n"])
_add(r'^select\s+(?:to\s+)?end$', IntentType.EDIT, "select_to_end", [])
_add(r'^select\s+all$', IntentType.EDIT, "select_all", [])

# Basic keystroke commands (the keys any command mode is expected to handle).
_add(r'^(?:press\s+)?(?:enter|return)$', IntentType.EDIT, "press_enter", [])
_add(r'^new\s+line$', IntentType.EDIT, "press_enter", [])
_add(r'^(?:press\s+)?tab$', IntentType.EDIT, "press_tab", [])
_add(r'^(?:press\s+)?(?:escape|esc)$', IntentType.EDIT, "press_escape", [])
_add(r'^(?:press\s+)?backspace$', IntentType.EDIT, "press_backspace", [])
_add(r'^cut(?:\s+(?:that|this|line|selection))?$', IntentType.EDIT, "cut", [])

# NAVIGATE commands
_add(r'^go\s+to\s+line\s+(\d+)$', IntentType.NAVIGATE, "go_to_line", ["n"])
_add(r'^page\s+up$', IntentType.NAVIGATE, "page_up", [])
_add(r'^page\s+down$', IntentType.NAVIGATE, "page_down", [])
_add(r'^(?:go\s+to\s+)?(?:start|beginning)\s+of\s+(?:the\s+)?line$', IntentType.NAVIGATE, "line_home", [])
_add(r'^(?:go\s+to\s+)?end\s+of\s+(?:the\s+)?line$', IntentType.NAVIGATE, "line_end", [])
_add(r'^(?:go|move)\s+up$', IntentType.NAVIGATE, "arrow_up", [])
_add(r'^(?:go|move)\s+down$', IntentType.NAVIGATE, "arrow_down", [])
_add(r'^(?:go|move)\s+left$', IntentType.NAVIGATE, "arrow_left", [])
_add(r'^(?:go|move)\s+right$', IntentType.NAVIGATE, "arrow_right", [])
_add(r'^(?:go\s+to|jump\s+to|find)\s+(?:function|method|def)\s+(.+)$', IntentType.NAVIGATE, "go_to_function", ["name"])
_add(r'^(?:go\s+to|jump\s+to|find)\s+class\s+(.+)$', IntentType.NAVIGATE, "go_to_class", ["name"])
_add(r'^(?:go\s+to|open)\s+file\s+(.+)$', IntentType.NAVIGATE, "go_to_file", ["name"])

# TERMINAL commands
_add(r'^run\s+(?:the\s+)?tests?$', IntentType.TERMINAL, "run_tests", [])
_add(r'^run\s+(?:the\s+)?build$', IntentType.TERMINAL, "run_build", [])
_add(r'^run\s+that$', IntentType.TERMINAL, "run_last", [])
_add(r'^run\s+(.+)$', IntentType.TERMINAL, "run_command", ["cmd"])

# REFACTOR commands
_add(r'^rename\s+(?:this|symbol|it)\s+to\s+(.+)$', IntentType.REFACTOR, "rename_symbol", ["name"])
_add(r'^new\s+function\s+(?:called?\s+)?(.+)$', IntentType.EDIT, "new_function", ["name"])
_add(r'^new\s+class\s+(?:called?\s+)?(.+)$', IntentType.EDIT, "new_class", ["name"])
_add(r'^new\s+file\s+(?:called?\s+)?(.+)$', IntentType.EDIT, "new_file", ["name"])


class _MacroHit(Protocol):
    # Read-only on purpose: the real collaborator is `commands.macros.Macro`, a
    # frozen dataclass. A bare `trigger: str` here would declare a *settable*
    # attribute, and those are invariant — a frozen dataclass cannot satisfy it,
    # which pushes the type error out to the daemon's classify() call sites.
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
    """Classify transcribed text as a command or plain dictation.

    Returns CommandIntent with intent=DICTATE if no command matches.
    Tier 0: optional user macro table (whole-utterance exact match), checked first.
    Tier 1: regex rules (< 5 ms).
    Tier 2: optional SLM router called when Tier 1 returns DICTATE.
    """
    if not text or not text.strip():
        return CommandIntent(intent=IntentType.DICTATE, action="inject", raw_text=text)

    # Tier 0: user-defined macros (run before the regex grammar).
    if macro_table is not None:
        macro = macro_table.match(text)
        if macro is not None:
            return CommandIntent(
                intent=IntentType.MACRO,
                action="expand",
                args={"trigger": macro.trigger},
                raw_text=text,
            )

    normalised = _normalise_numwords(_strip_outer_punct(text))

    for pattern, intent, action, arg_names in _RULES:
        m = pattern.match(normalised)
        if m:
            args: dict[str, str] = {}
            for i, name in enumerate(arg_names, 1):
                try:
                    args[name] = m.group(i).strip()
                except IndexError:
                    pass
            return CommandIntent(intent=intent, action=action, args=args, raw_text=text)

    if slm_router is not None:
        slm_result = slm_router.classify(text, profile)
        if slm_result is not None:
            return slm_result

    return CommandIntent(intent=IntentType.DICTATE, action="inject", raw_text=text)
