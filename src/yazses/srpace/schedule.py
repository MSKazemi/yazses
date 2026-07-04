"""Clause chunking + screen-reader-paced injection scheduling (pure) — ADR-v2-120.

Split text into clause-sized chunks and assign each a cumulative delay so injection matches a
screen reader's words-per-minute reading rate, giving it time to announce each chunk. Pure and
deterministic; the injector applies the delays.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Chunk:
    text: str
    delay_ms: int          # cumulative delay from the start before this chunk is injected


def chunk_clauses(text: str) -> list[str]:
    """Split ``text`` into clause-sized chunks at sentence/clause punctuation. Pure.

    Splits after ``. ! ? ; :`` and ``,`` while keeping the delimiter attached; whitespace-only
    fragments are dropped.
    """
    if not (text or "").strip():
        return []
    parts = re.split(r"(?<=[.!?;:,])\s+", text.strip())
    return [p for p in (frag.strip() for frag in parts) if p]


def _word_count(text: str) -> int:
    return max(len(re.findall(r"\S+", text)), 1)


def plan_injection_schedule(text: str, wpm: float = 180.0,
                            min_chunk_ms: int = 200) -> list[Chunk]:
    """Plan a paced, clause-chunked injection schedule for a screen reader. Pure.

    Each chunk's own duration is ``words / wpm`` (floored at ``min_chunk_ms``); ``delay_ms`` is the
    cumulative start time so the injector can announce chunks in sequence without overrunning the
    reader. ``wpm`` ≤ 0 falls back to a single zero-delay chunk (pacing disabled).
    """
    chunks = chunk_clauses(text)
    if not chunks:
        return []
    if wpm <= 0:
        return [Chunk(" ".join(chunks), 0)]
    out: list[Chunk] = []
    elapsed = 0
    for chunk in chunks:
        out.append(Chunk(chunk, elapsed))
        dur = max(int(_word_count(chunk) / wpm * 60_000), min_chunk_ms)
        elapsed += dur
    return out
