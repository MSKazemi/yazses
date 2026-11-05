"""Ambient Scratch — spoken notes-to-self (ADR-v2-005).

``parse_scratch`` (pure) detects a note-to-self phrase and extracts the note.
``ScratchPad`` is a tiny JSONL-backed store (like the vocabulary file) — append,
list, clear. OFF by default: nothing calls these unless ``[recall] scratch``.
Notes are plain local files under the user's data dir; no cloud, no telemetry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from yazses.system.private_files import private_dir, write_private_text

# Leading trigger phrases that mark an utterance as a note-to-self rather than
# text to type.
_SCRATCH_TRIGGERS = (
    "note to self",
    "make a note",
    "remind me that",
    "remember that",
    "jot down",
)


def parse_scratch(phrase: str) -> str | None:
    """Extract the note text from a note-to-self phrase, or ``None`` if not one.

    Returns the text after the trigger (possibly ``""`` if the trigger stood
    alone, which the caller should treat as an empty note and ignore).
    """
    cleaned = phrase.strip()
    low = cleaned.lower()
    for trig in _SCRATCH_TRIGGERS:
        if low == trig or low.startswith(trig + " "):
            return cleaned[len(trig):].strip(" ,:-")
    return None


@dataclass
class ScratchNote:
    ts: float
    text: str


class ScratchPad:
    """JSONL-backed note store. Best-effort: malformed lines are skipped."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def add(self, text: str, ts: float) -> bool:
        """Append a note. Returns False (no-op) for empty text."""
        text = (text or "").strip()
        if not text:
            return False
        # Spoken notes-to-self: owner-only (0700 dir / 0600 file) on POSIX.
        private_dir(self._path.parent)
        write_private_text(
            self._path, json.dumps({"ts": float(ts), "text": text}) + "\n", append=True,
        )
        return True

    def list(self) -> list[ScratchNote]:
        if not self._path.exists():
            return []
        out: list[ScratchNote] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                out.append(ScratchNote(ts=float(d.get("ts", 0.0)),
                                       text=str(d.get("text", ""))))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue
        return out

    def clear(self) -> int:
        """Delete all notes; returns how many were removed."""
        n = len(self.list())
        if self._path.exists():
            self._path.unlink()
        return n
