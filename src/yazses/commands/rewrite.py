"""Offline Command Mode: rewrite the selection by voice (#99).

Select text anywhere, hold the command key, say "make this shorter" — and the
selection is rewritten in place by a **local** model. Voice-editing of selected
text is the most-praised capability in the paid dictation tools and it is
cloud-only in every product that has it; doing it offline is the point.

This module is the **grammar and the safety policy**, both pure. The engine that
captures a selection, calls a model and types the result is `rewrite/engine.py`,
so everything decided here is testable without a clipboard, a model, or a desktop.

## Why the guards are the feature

A rewrite replaces text the user already has. Getting it wrong does not produce a
worse suggestion — it **destroys their writing**. So the rule is that a rewrite is
rejected unless it is provably plausible, and rejection leaves the selection
untouched:

* **Length bounds per instruction.** "Make this shorter" that returns something
  longer has not followed the instruction; "fix the grammar" that halves the text
  has deleted content rather than corrected it. Each instruction carries its own
  band, because "summarise" and "fix typos" are not the same operation.
* **A model that answers with the instruction** ("Sure, here is a shorter
  version:") is refused — a preamble means it treated the prompt as chat.
* **Empty, unchanged, or absurd output** is refused.

An LLM cannot be trusted to follow instructions; it can be checked afterwards.
That asymmetry is the whole design.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RewriteIntent:
    """A recognised rewrite request."""

    action: str            # shorter | longer | grammar | bullets | tone | custom
    instruction: str       # what to tell the model
    min_ratio: float       # of the original length
    max_ratio: float


# Each preset carries its own plausibility band. These are not tuning knobs; they
# are what makes "shorter" checkable at all.
_PRESETS: dict[str, tuple[str, float, float]] = {
    "shorter": ("Rewrite the text to be shorter and clearer, keeping every fact.",
                0.25, 0.95),
    "longer": ("Expand the text with more detail, keeping the meaning and tone.",
               1.05, 3.0),
    "grammar": ("Correct spelling, grammar and punctuation. Change nothing else.",
                0.75, 1.35),
    "bullets": ("Rewrite the text as a concise bulleted list, one point per line.",
                0.4, 1.5),
    "formal": ("Rewrite the text in a more formal, professional register.",
               0.6, 1.8),
    "casual": ("Rewrite the text in a warmer, more casual register.",
               0.6, 1.8),
}

# Anchored at BOTH ends. "make this shorter" is a sentence someone might dictate
# into a document, and a suffix match would execute it instead of typing it —
# the failure this project has already had three times (revise.py, bookmarks,
# windowctl).
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?:make|rewrite)\s+(?:this|it|that)\s+(?:much\s+)?shorter", re.I), "shorter"),
    (re.compile(r"(?:make|rewrite)\s+(?:this|it|that)\s+(?:much\s+)?(?:longer|more detailed)", re.I), "longer"),
    (re.compile(r"(?:fix|correct)\s+(?:the\s+)?(?:grammar|spelling|typos?)(?:\s+here)?", re.I), "grammar"),
    (re.compile(r"(?:turn|make|rewrite)\s+(?:this|it|that)\s+into\s+(?:a\s+)?bullet(?:ed)?(?:\s+(?:point|list))?s?", re.I), "bullets"),
    (re.compile(r"(?:make|rewrite)\s+(?:this|it|that)\s+(?:more\s+)?formal", re.I), "formal"),
    (re.compile(r"(?:make|rewrite)\s+(?:this|it|that)\s+(?:more\s+)?casual", re.I), "casual"),
]

# Free-form: "rewrite this as a haiku", "reword this for a customer".
_CUSTOM = re.compile(
    r"(?:rewrite|reword|rephrase)\s+(?:this|it|that)\s+(?:as|for|into|to be)\s+(?P<what>.+)",
    re.I,
)

# A free-form instruction has no preset band, so it gets the widest plausible one.
_CUSTOM_BOUNDS = (0.25, 3.0)


def parse_rewrite(text: str) -> RewriteIntent | None:
    """Recognise a rewrite request. Pure. None means "this is not one"."""
    phrase = (text or "").strip().rstrip(".!?")
    if not phrase:
        return None
    for pattern, action in _PATTERNS:
        if pattern.fullmatch(phrase):
            instruction, low, high = _PRESETS[action]
            return RewriteIntent(action, instruction, low, high)
    match = _CUSTOM.fullmatch(phrase)
    if match:
        what = match.group("what").strip()
        low, high = _CUSTOM_BOUNDS
        return RewriteIntent(
            "custom", f"Rewrite the text as {what}. Keep the meaning.", low, high
        )
    return None


class Rejection(str):
    """Why a rewrite was refused. A str subclass so it logs and notifies cleanly."""


# Openers that mean the model answered the prompt instead of doing the work.
_PREAMBLES = (
    "sure", "here is", "here's", "certainly", "of course", "okay", "ok,",
    "i've", "i have", "revised:", "rewritten:", "output:", "result:",
)


def check_rewrite(original: str, candidate: str, intent: RewriteIntent) -> Rejection | None:
    """Decide whether *candidate* may replace *original*. Pure.

    Returns None when the rewrite is acceptable, otherwise the reason. Refusing
    is always safe — the selection stays as the user wrote it.
    """
    text = (candidate or "").strip()
    if not text:
        return Rejection("the model returned nothing")
    if text == original.strip():
        return Rejection("the model returned the text unchanged")

    lowered = text.lower()
    if any(lowered.startswith(p) for p in _PREAMBLES):
        return Rejection("the model replied to the instruction instead of rewriting")

    original_length = len(original.strip())
    if original_length == 0:
        return Rejection("there was no selection to rewrite")
    ratio = len(text) / original_length
    if ratio < intent.min_ratio:
        return Rejection(
            f"the rewrite is {ratio:.0%} of the original — too short for "
            f"{intent.action!r}, so it probably dropped content"
        )
    if ratio > intent.max_ratio:
        return Rejection(
            f"the rewrite is {ratio:.0%} of the original — too long for "
            f"{intent.action!r}"
        )
    return None
