"""Discourse-marker outline builder (pure) — ADR-v2-038.

Segment a spoken monologue into a bulleted outline: split on sentence boundaries, strip a
leading discourse marker, and flag action items as checkboxes. Pure and deterministic; the
SLM-quality reflow lives behind an extra.
"""
from __future__ import annotations

import re

# Leading markers that introduce a new outline point (stripped from the bullet body).
#
# Order in this tuple is NOT the matching order -- see `_leading_marker`, which tries the
# longest first. Written in reading order because the matching loop used to walk it as
# written and broke on the first hit, so "first" shadowed "firstly" and "second" shadowed
# "secondly":
#
#   "Firstly we fix the tray."  ->  "- ly we fix the tray"
#
# Three of the commonest spoken outline markers were each mangled into nonsense.
_BULLET_MARKERS = (
    "first of all", "first", "firstly", "second", "secondly", "third", "thirdly",
    "next", "then", "after that", "also", "additionally", "furthermore", "moreover",
    "finally", "lastly", "in conclusion", "to summarize",
)

#: Fillers that open a sentence in real speech. This command is for "a long rambling
#: monologue", and the single commonest thing in one is a filler -- yet only ordering
#: words were stripped, so "Um we should fix the tray" kept its "Um".
#:
#: Sourced from `DisfluencyConfig.filler_words`, the list the dictation filter already
#: uses, rather than a second copy that would drift from it. The extras below are ones
#: that only matter *sentence-initially*, which is why they are not in that list: mid
#: sentence, "so" and "well" and "right" are ordinary words.
_EXTRA_LEADING_FILLERS = (
    "so basically", "basically", "okay so", "and then", "and so", "so anyway",
    "anyway", "actually", "well", "okay", "right", "i guess", "i think",
    "sort of", "kind of", "like", "so",
)


def _leading_fillers() -> tuple[str, ...]:
    """Sentence-initial fillers, shared with the dictation disfluency filter."""
    from yazses.config import DisfluencyConfig

    return (*DisfluencyConfig().filler_words, *_EXTRA_LEADING_FILLERS)


def _leading_marker(low: str) -> str | None:
    """The longest marker this sentence opens with, or ``None``. Pure.

    Longest-first is load-bearing: the candidates overlap ("first"/"firstly",
    "so"/"so basically"), and first-match-wins leaves the remainder of the longer word
    in the bullet.
    """
    candidates = (
        *_BULLET_MARKERS, *_leading_fillers(), "action item", "action",
    )
    hits = [m for m in candidates if low.startswith(m)]
    if not hits:
        return None
    return max(hits, key=len)
# Phrases anywhere in a sentence that mark it as an action item.
_ACTION_MARKERS = (
    "action item", "to do", "todo", "i need to", "we need to", "note to self",
    "remember to", "follow up", "make sure to",
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[.!?]+", text or "") if s.strip()]


def reflow(text: str) -> str:
    """Rewrite a monologue into a bulleted outline. Pure.

    Each sentence becomes a bullet; a leading discourse marker is stripped; sentences
    containing an action phrase become ``- [ ]`` checkboxes. Empty input returns ``""``.
    """
    sentences = _sentences(text)
    if not sentences:
        return ""
    lines: list[str] = []
    for s in sentences:
        low = s.lower()
        is_action = any(m in low for m in _ACTION_MARKERS)
        body = s
        # Strip leading discourse/filler/action markers. Repeated, because real speech
        # stacks them -- "so um basically we should" opens with three.
        while (m := _leading_marker(body.lower())) is not None:
            stripped = body[len(m):].lstrip(" ,:;-")
            if not stripped:
                break  # the whole sentence was the marker; keep it rather than emit ""
            body = stripped
        body = body or s
        lines.append(("- [ ] " if is_action else "- ") + body)
    return "\n".join(lines)
