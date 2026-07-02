"""Speaker-label map + rename grammar + attributed renderer (pure) — ADR-v2-074.

Canonicalize raw diarizer speaker ids, hold voice-assigned display names, and render turns as
attributed Markdown. Pure and deterministic; the diarization model lives behind the ``diarize``
extra.
"""
from __future__ import annotations

import re

_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "zero": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
}
_RENAME = re.compile(
    r"(?:call|rename|name)\s+speaker\s+(\w+)\s+(?:to\s+|as\s+)?([A-Za-z][\w'\-]*)"
    r"|speaker\s+(\w+)\s+is\s+([A-Za-z][\w'\-]*)",
    re.IGNORECASE,
)


def _speaker_index(token: str):
    """Map a speaker token ("2", "two", "SPEAKER_01") to an int index, or ``None``. Pure."""
    t = (token or "").lower().strip()
    m = re.search(r"(\d+)", t)
    if m:
        return int(m.group(1))
    for w in re.findall(r"[a-z]+", t):
        if w in _NUM_WORDS:
            return _NUM_WORDS[w]
    return None


def canonical_speaker(raw: str):
    """Canonicalize a raw speaker id to ``speaker_N``, or ``None`` if no index found. Pure."""
    idx = _speaker_index(str(raw))
    return f"speaker_{idx}" if idx is not None else None


def parse_rename(text: str):
    """Parse a spoken rename into ``(canonical_id, name)``, or ``None``. Pure."""
    m = _RENAME.search(text or "")
    if not m:
        return None
    token = m.group(1) or m.group(3)
    name = m.group(2) or m.group(4)
    canon = canonical_speaker(token)
    return (canon, name) if canon else None


class SpeakerLabelMap:
    """Maps canonical speaker ids to display names, defaulting to a pretty "Speaker N"."""

    def __init__(self) -> None:
        self._names: dict = {}

    def rename(self, raw: str, name: str) -> bool:
        """Assign ``name`` to a raw/canonical speaker id. Returns False if unrecognized."""
        canon = canonical_speaker(raw)
        if canon is None:
            return False
        self._names[canon] = name
        return True

    def apply_command(self, text: str) -> bool:
        """Apply a spoken rename command; True if it renamed someone."""
        parsed = parse_rename(text)
        if not parsed:
            return False
        self._names[parsed[0]] = parsed[1]
        return True

    def display(self, raw: str) -> str:
        """The display name for a speaker id (assigned name or a default "Speaker N")."""
        canon = canonical_speaker(raw)
        if canon is None:
            return str(raw)
        if canon in self._names:
            return self._names[canon]
        return f"Speaker {canon.rsplit('_', 1)[1]}"


def render_attributed_markdown(turns, label_map: SpeakerLabelMap) -> str:
    """Render ``(speaker_id, text)`` turns as ``**Name:** text`` lines, merging runs. Pure."""
    lines = []
    prev = None
    for raw, text in turns:
        name = label_map.display(raw)
        if name == prev:
            lines[-1] = f"{lines[-1]} {text}".rstrip()
        else:
            lines.append(f"**{name}:** {text}".rstrip())
            prev = name
    return "\n".join(lines)
