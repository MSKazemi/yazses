"""Meeting-scribe labelling/formatting (pure) — ADR-v2-019.

Turn raw diarized turns (a speaker cluster id + text) into a readable transcript:
stable per-speaker labels (enrolled user → "You"), consecutive-turn coalescing, and
"Label: text" rendering. Pure and deterministic; the diarization model lives elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    """One diarized turn: a raw speaker key and the transcribed text."""
    speaker: str
    text: str


def label_speakers(speaker_ids, self_id=None) -> dict:
    """Map raw speaker ids to stable display labels in first-appearance order.

    ``self_id`` (the enrolled user's cluster) becomes ``"You"``; every other speaker
    becomes ``"Speaker 1"``, ``"Speaker 2"``, … in the order first seen. Pure.
    """
    labels: dict = {}
    n = 0
    for sid in speaker_ids:
        if sid in labels:
            continue
        if self_id is not None and sid == self_id:
            labels[sid] = "You"
        else:
            n += 1
            labels[sid] = f"Speaker {n}"
    return labels


def merge_turns(turns):
    """Coalesce consecutive turns from the same speaker into one turn. Pure."""
    out: list[Turn] = []
    for t in turns:
        if out and out[-1].speaker == t.speaker:
            merged = f"{out[-1].text} {t.text}".strip()
            out[-1] = Turn(t.speaker, merged)
        else:
            out.append(Turn(t.speaker, t.text))
    return out


def format_transcript(turns, self_id=None) -> str:
    """Render turns as newline-joined ``"Label: text"`` after merging + labelling.

    Empty input yields an empty string. Blank-text turns are dropped. Pure.
    """
    merged = merge_turns([t for t in turns if (t.text or "").strip()])
    if not merged:
        return ""
    labels = label_speakers([t.speaker for t in merged], self_id)
    return "\n".join(f"{labels[t.speaker]}: {t.text}" for t in merged)
