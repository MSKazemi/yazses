"""Fact-cue detection + cloze generation + SM-2 scheduling (pure) — ADR-v2-112.

Detect a "remember that X is Y" fact, build an Anki cloze card, and schedule reviews by SM-2. Pure;
no dependency (deck export is a thin downstream writer).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CUE = re.compile(r"\b(?:remember that|note that|remember|learn that)\b\s+(.+)$", re.IGNORECASE)
_ISA = re.compile(r"^(.*?)\s+\b(is|was|are|were|means|equals|equal to)\b\s+(.+?)\.?$", re.IGNORECASE)


@dataclass(frozen=True)
class Fact:
    subject: str
    predicate: str
    value: str


@dataclass(frozen=True)
class Card:
    front: str
    back: str
    cloze: str


@dataclass(frozen=True)
class Sm2State:
    reps: int = 0
    interval: int = 0
    ease: float = 2.5


def detect_fact(utterance: str):
    """Detect a "remember that X is Y" fact, or ``None``. Pure."""
    cue = _CUE.search(utterance or "")
    if not cue:
        return None
    m = _ISA.match(cue.group(1).strip())
    if not m:
        return None
    return Fact(m.group(1).strip(), m.group(2).lower(), m.group(3).strip().rstrip("."))


def to_cloze(fact: Fact) -> Card:
    """Build an Anki cloze card from a :class:`Fact`. Pure."""
    return Card(
        front=f"{fact.subject} {fact.predicate} ...",
        back=fact.value,
        cloze=f"{fact.subject} {fact.predicate} {{{{c1::{fact.value}}}}}",
    )


def sm2_schedule(state: Sm2State, grade: int) -> Sm2State:
    """Return the next SM-2 state for a review ``grade`` (0–5); grade < 3 lapses. Pure."""
    if grade < 3:
        return Sm2State(reps=0, interval=1, ease=state.ease)
    ease = max(1.3, state.ease + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02)))
    reps = state.reps + 1
    if reps == 1:
        interval = 1
    elif reps == 2:
        interval = 6
    else:
        interval = round(state.interval * ease)
    return Sm2State(reps=reps, interval=interval, ease=ease)
