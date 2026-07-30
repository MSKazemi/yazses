"""Word count + writing-goal tracking (pure) — ADR-v2-092.

Accumulate injected word counts, track a goal, and render a spoken-ready progress string. Pure and
deterministic; the spoken answer reuses the existing TTS.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"\S+")
_GOAL = re.compile(r"\b(?:goal|target)\b(?:\s+(?:of|to|is|:))?\s+(\d+)|\bset\s+(?:my\s+)?goal\s+(?:to\s+)?(\d+)",
                   re.IGNORECASE)


def count_words(text: str) -> int:
    """Count whitespace-delimited words in ``text``. Pure."""
    return len(_WORD.findall(text or ""))


def render_progress(count: int, goal: int) -> str:
    """A spoken-ready progress line for ``count`` words against ``goal`` (0 = none). Pure."""
    if goal > 0:
        remaining = goal - count
        if remaining <= 0:
            return f"You've reached your goal of {goal} words, with {count} typed."
        return f"{count} of {goal} words — {remaining} to go."
    return f"{count} words so far."


class WordGoalTracker:
    """Accumulates injected word counts against an optional goal. Pure state."""

    def __init__(self, goal: int = 0) -> None:
        self._count = 0
        self._goal = max(0, goal)

    def add(self, text: str) -> None:
        """Add the word count of an injected string."""
        self._count += count_words(text)

    def set_goal(self, goal: int) -> None:
        self._goal = max(0, goal)

    def count(self) -> int:
        return self._count

    def reset(self) -> None:
        self._count = 0

    def progress(self) -> str:
        """A spoken-ready progress line, with or without a goal. Pure."""
        return render_progress(self._count, self._goal)


def parse_goal_command(text: str):
    """Parse a spoken goal-setting command into an int, or ``None``. Pure."""
    m = _GOAL.search(text or "")
    if not m:
        return None
    return int(m.group(1) or m.group(2))
