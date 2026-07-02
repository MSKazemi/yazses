"""Input-agnostic chord resolver (pure) — ADR-v2-043.

Canonicalize a set of simultaneously-held inputs into a stable chord id and map it to a bound
action. Pure and deterministic; physical sensors only feed abstract input tokens in.
"""
from __future__ import annotations


def normalize_chord(keys) -> str:
    """Canonicalize simultaneously-held inputs into a stable chord id.

    Order-independent and de-duplicated; empty/blank tokens are dropped. Pure.
    E.g. ``["Nod", "hold"]`` and ``["hold", "nod", "hold"]`` both → ``"hold+nod"``.
    """
    tokens = sorted({k.lower().strip() for k in keys if k and k.strip()})
    return "+".join(tokens)


def resolve_chord(keys, mapping):
    """Map a held-input chord to its bound action via ``mapping``, or ``None``. Pure."""
    return mapping.get(normalize_chord(keys))
