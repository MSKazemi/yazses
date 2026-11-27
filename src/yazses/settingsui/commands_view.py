"""Example phrases for the Voice commands page. Pure.

A short list of what the English grammar understands, not a second grammar: every phrase
here is run through ``commands.grammar.classify`` in
``tests/test_settingsui_commands_privacy.py``, so an entry the product stops understanding
fails the build.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Example:
    phrase: str
    meaning: str
    group: str


EXAMPLES: tuple[Example, ...] = (
    Example("undo", "Undo the last change", "Editing"),
    Example("delete last word", "Delete the word before the cursor", "Editing"),
    Example("delete last line", "Delete the line before the cursor", "Editing"),
    Example("select all", "Select everything", "Editing"),
    Example("copy that", "Copy the selection", "Clipboard"),
    Example("cut that", "Cut the selection", "Clipboard"),
    Example("paste", "Paste", "Clipboard"),
    Example("new line", "Start a new line", "Keys"),
    Example("press enter", "Press Enter", "Keys"),
    Example("press escape", "Press Escape", "Keys"),
    Example("go to line 42", "Jump to a line", "Navigation"),
    Example("page down", "Scroll one page down", "Navigation"),
    Example("end of line", "Move to the end of the line", "Navigation"),
    Example("move left", "Move the cursor left", "Navigation"),
    Example("save", "Save the file", "Apps"),
)


def search(query: str) -> tuple[Example, ...]:
    """The examples whose phrase, meaning or group contains *query*, in listed order."""
    needle = query.strip().casefold()
    if not needle:
        return EXAMPLES
    return tuple(
        e for e in EXAMPLES if needle in f"{e.phrase} {e.meaning} {e.group}".casefold()
    )
