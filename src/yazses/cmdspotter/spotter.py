"""Few-shot command spotter (pure) — ADR-v2-064.

An enrollment store of labelled prototype embeddings and a cosine-similarity matcher. Pure and
deterministic; the KWS encoder that turns audio into embeddings lives behind the ``kws`` extra.
"""
from __future__ import annotations

import math


def cosine(a, b) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 if either is a zero vector. Pure."""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class CommandSpotter:
    """Match an embedding to the nearest enrolled command label above a threshold. Pure logic."""

    def __init__(self, threshold: float = 0.75) -> None:
        self._threshold = threshold
        self._prototypes: dict = {}   # label → list[embedding]

    def enroll(self, label: str, embedding) -> None:
        """Add one few-shot example embedding for ``label``."""
        self._prototypes.setdefault(label, []).append(list(embedding))

    def labels(self) -> list:
        """Enrolled command labels."""
        return list(self._prototypes)

    def match(self, embedding):
        """Return the best label whose max prototype similarity ≥ threshold, else ``None``. Pure."""
        best_label, best_sim = None, self._threshold
        for label, protos in self._prototypes.items():
            sim = max(cosine(embedding, p) for p in protos)
            if sim >= best_sim:
                best_label, best_sim = label, sim
        return best_label
