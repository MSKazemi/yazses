"""Schema slot-filling (pure) — ADR-v2-063.

Match a user-defined schema against one utterance, routing values to named fields. Pure and
deterministic; the SpeechLLM tier for freeform mapping is deferred.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Slot:
    """One template field.

    ``after``: trigger keywords whose following token is the value ("priority high" → "high").
    ``choices``: an enum whose first present member is the value ("firefox" → "firefox").
    """
    name: str
    after: tuple = ()
    choices: tuple = field(default_factory=tuple)


def fill_slots(text: str, slots) -> dict:
    """Fill ``slots`` from ``text``; returns ``{field: value}`` for matched fields only. Pure."""
    low = (text or "").lower()
    result: dict = {}
    for slot in slots:
        for kw in slot.after:
            m = re.search(rf"\b{re.escape(kw.lower())}\s+([a-z0-9]+)", low)
            if m:
                result[slot.name] = m.group(1)
                break
        if slot.name in result:
            continue
        for choice in slot.choices:
            if re.search(rf"\b{re.escape(choice.lower())}\b", low):
                result[slot.name] = choice.lower()
                break
    return result
