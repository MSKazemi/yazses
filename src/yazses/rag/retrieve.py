"""RAG retrieval ranking + cited-context (pure) — ADR-v2-020.

Rank candidate document chunks by similarity and build a cited context block for the
answer LLM (or an extractive fallback). Pure and deterministic; the embedding model and
vector index live elsewhere and are lazy behind the ``rag`` extra.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Chunk:
    """A retrieved document chunk: its source, text, and similarity score."""
    source: str
    text: str
    score: float = 0.0


def cosine(a, b) -> float:
    """Cosine similarity of two vectors; 0.0 if either is a zero vector. Pure."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def rank_chunks(chunks, top_k: int = 4, min_score: float = 0.0):
    """Filter chunks below ``min_score``, sort by score desc, take ``top_k``.

    ``top_k <= 0`` returns all passing chunks. Stable for equal scores. Pure.
    """
    passing = [c for c in chunks if c.score >= min_score]
    ranked = sorted(passing, key=lambda c: c.score, reverse=True)
    return ranked if top_k <= 0 else ranked[:top_k]


def format_context(chunks) -> str:
    """Build a cited context block: numbered snippets + a Sources list.

    Empty input yields an empty string. Each snippet is prefixed with ``[n]`` and the
    same indices map to sources, so a generated answer can cite ``[n]``. Pure.
    """
    chunks = list(chunks)
    if not chunks:
        return ""
    body = "\n".join(f"[{i}] {c.text}" for i, c in enumerate(chunks, 1))
    sources = "\n".join(f"[{i}] {c.source}" for i, c in enumerate(chunks, 1))
    return f"{body}\n\nSources:\n{sources}"
