"""English Tier-1 command grammar.

This module is a behavior-preserving extraction of the historical global rule table
from commands/grammar.py. Rule order, regex source, normalization, and argument names
are intentionally unchanged because first-match order is part of the contract shared
with the Android port.
"""
from __future__ import annotations

import re

from yazses.commands.grammars.base import CommandGrammar, GrammarRule
from yazses.commands.types import IntentType

_NUM_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
}

_OUTER_PUNCT = " \t\r\n.,!?;:\"'`…"


def normalise_numwords(text: str) -> str:
    """Replace English spelled-out numbers with digits, case-insensitively."""
    pattern = re.compile(r'\b(' + '|'.join(_NUM_WORDS) + r')\b', re.IGNORECASE)
    return pattern.sub(lambda m: _NUM_WORDS[m.group(1).lower()], text)


def strip_outer_punct(text: str) -> str:
    """Remove punctuation Whisper commonly adds around short English commands."""
    return text.strip().strip(_OUTER_PUNCT).strip()


def normalise(text: str) -> str:
    return normalise_numwords(strip_outer_punct(text))


_rules: list[GrammarRule] = []


def _add(
    pattern: str,
    intent: IntentType,
    action: str,
    arg_names: tuple[str, ...] = (),
) -> None:
    _rules.append(
        GrammarRule(
            re.compile(pattern, re.IGNORECASE),
            intent,
            action,
            arg_names,
        )
    )


# EDIT commands
_add(r"^delete\s+(?:the\s+)?last\s+(\d+)\s+words?$", IntentType.EDIT, "delete_words", ("n",))
_add(r"^delete\s+(?:the\s+)?last\s+word$", IntentType.EDIT, "delete_words")
_add(r"^delete\s+(?:the\s+)?last\s+(\d+)\s+lines?$", IntentType.EDIT, "delete_lines", ("n",))
_add(r"^delete\s+(?:the\s+)?last\s+line$", IntentType.EDIT, "delete_lines")
_add(r"^undo(?:\s+that)?$", IntentType.EDIT, "undo")
_add(r"^undo\s+(\d+)\s+times?$", IntentType.EDIT, "undo_n", ("n",))
_add(r"^save(?:\s+file)?(?:\s+now)?$", IntentType.EDIT, "save")
_add(r"^copy(?:\s+(?:that|this|line|selection))?$", IntentType.EDIT, "copy")
_add(r"^paste(?:\s+here)?$", IntentType.EDIT, "paste")
_add(
    r"^comment(?:\s+(?:this\s+line|the\s+line|this\s+selection|this|line|selection|out))?$",
    IntentType.EDIT,
    "comment",
)
_add(r"^select\s+(\d+)\s+lines?$", IntentType.EDIT, "select_lines", ("n",))
_add(r"^select\s+(?:to\s+)?end$", IntentType.EDIT, "select_to_end")
_add(r"^select\s+all$", IntentType.EDIT, "select_all")

# Basic keystroke commands.
_add(r"^(?:press\s+)?(?:enter|return)$", IntentType.EDIT, "press_enter")
_add(r"^new\s+line$", IntentType.EDIT, "press_enter")
_add(r"^(?:press\s+)?tab$", IntentType.EDIT, "press_tab")
_add(r"^(?:press\s+)?(?:escape|esc)$", IntentType.EDIT, "press_escape")
_add(r"^(?:press\s+)?backspace$", IntentType.EDIT, "press_backspace")
_add(r"^cut(?:\s+(?:that|this|line|selection))?$", IntentType.EDIT, "cut")

# NAVIGATE commands
_add(r"^go\s+to\s+line\s+(\d+)$", IntentType.NAVIGATE, "go_to_line", ("n",))
_add(r"^page\s+up$", IntentType.NAVIGATE, "page_up")
_add(r"^page\s+down$", IntentType.NAVIGATE, "page_down")
_add(
    r"^(?:go\s+to\s+)?(?:start|beginning)\s+of\s+(?:the\s+)?line$",
    IntentType.NAVIGATE,
    "line_home",
)
_add(r"^(?:go\s+to\s+)?end\s+of\s+(?:the\s+)?line$", IntentType.NAVIGATE, "line_end")
_add(r"^(?:go|move)\s+up$", IntentType.NAVIGATE, "arrow_up")
_add(r"^(?:go|move)\s+down$", IntentType.NAVIGATE, "arrow_down")
_add(r"^(?:go|move)\s+left$", IntentType.NAVIGATE, "arrow_left")
_add(r"^(?:go|move)\s+right$", IntentType.NAVIGATE, "arrow_right")
_add(
    r"^(?:go\s+to|jump\s+to|find)\s+(?:function|method|def)\s+(.+)$",
    IntentType.NAVIGATE,
    "go_to_function",
    ("name",),
)
_add(r"^(?:go\s+to|jump\s+to|find)\s+class\s+(.+)$", IntentType.NAVIGATE, "go_to_class", ("name",))
_add(r"^(?:go\s+to|open)\s+file\s+(.+)$", IntentType.NAVIGATE, "go_to_file", ("name",))

# TERMINAL commands
_add(r"^run\s+(?:the\s+)?tests?$", IntentType.TERMINAL, "run_tests")
_add(r"^run\s+(?:the\s+)?build$", IntentType.TERMINAL, "run_build")
_add(r"^run\s+that$", IntentType.TERMINAL, "run_last")
_add(r"^run\s+(.+)$", IntentType.TERMINAL, "run_command", ("cmd",))

# REFACTOR commands
_add(r"^rename\s+(?:this|symbol|it)\s+to\s+(.+)$", IntentType.REFACTOR, "rename_symbol", ("name",))
_add(r"^new\s+function\s+(?:called?\s+)?(.+)$", IntentType.EDIT, "new_function", ("name",))
_add(r"^new\s+class\s+(?:called?\s+)?(.+)$", IntentType.EDIT, "new_class", ("name",))
_add(r"^new\s+file\s+(?:called?\s+)?(.+)$", IntentType.EDIT, "new_file", ("name",))


ENGLISH_GRAMMAR = CommandGrammar(
    language="en",
    rules=tuple(_rules),
    normalise=normalise,
)
