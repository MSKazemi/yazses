"""Multi-user profile routing (pure) — ADR-v2-028.

Pick the enrolled speaker profile whose voiceprint is closest to the current utterance,
so a shared machine loads the right person's vocab/hotkey/cleanup automatically. Pure and
deterministic; the embedder is lazy behind the ``voiceprint`` extra and profile embeddings
live only in the encrypted corpus (ADR-012).
"""
from __future__ import annotations

import numpy as np


def _cosine(a, b) -> float:
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def nearest_profile(embedding, profiles, *, min_similarity: float = 0.5):
    """Return the enrolled profile name closest to ``embedding``, or ``None``.

    ``profiles`` maps a profile name to its stored voiceprint embedding. Returns the
    name whose cosine similarity is highest, but only when that best similarity is at
    least ``min_similarity``; otherwise ``None`` (→ keep the default profile). No profiles,
    or a zero query embedding, yields ``None``. Pure.
    """
    if not profiles:
        return None
    best_name = None
    best_sim = -1.0
    for name, emb in profiles.items():
        sim = _cosine(embedding, emb)
        if sim > best_sim:
            best_name, best_sim = name, sim
    if best_name is not None and best_sim >= min_similarity:
        return best_name
    return None
