"""Discourse-marker outline builder (pure) — ADR-v2-038.

Segment a spoken monologue into a bulleted outline: split on sentence boundaries, strip a
leading discourse marker, and flag action items as checkboxes. Pure and deterministic; the
SLM-quality reflow lives behind an extra.
"""
from __future__ import annotations

import re

# Leading markers that introduce a new outline point (stripped from the bullet body).
_BULLET_MARKERS = (
    "first of all", "first", "firstly", "second", "secondly", "third", "thirdly",
    "next", "then", "after that", "also", "additionally", "furthermore", "moreover",
    "finally", "lastly", "in conclusion", "to summarize",
)
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
        # strip a leading discourse or action marker from the bullet body
        for m in (*_BULLET_MARKERS, "action item", "action"):
            if low.startswith(m):
                body = s[len(m):].lstrip(" ,:;-")
                break
        body = body or s
        lines.append(("- [ ] " if is_action else "- ") + body)
    return "\n".join(lines)
