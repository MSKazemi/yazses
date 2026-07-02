"""Voice-clone readiness + backend selection (pure) — ADR-v2-042.

Decide whether enrollment has enough audio to clone the user's voice and pick the clone
backend, defaulting to the permissively-licensed one. Pure and deterministic; the clone model
lives behind the ``tts`` extra.
"""
from __future__ import annotations

# Backends by license posture. OpenVoice V2 is permissive → the safe default; F5/XTTS are
# non-commercial and only used on explicit opt-in.
_PERMISSIVE = frozenset({"openvoice"})
_NONCOMMERCIAL = frozenset({"f5", "xtts"})
_KNOWN = _PERMISSIVE | _NONCOMMERCIAL


def clone_ready(reference_seconds: float, min_seconds: float = 3.0) -> bool:
    """Whether enrollment holds enough reference audio to clone the voice. Pure."""
    return reference_seconds >= min_seconds


def select_clone_backend(config) -> str:
    """Return the clone backend from config, defaulting to permissive OpenVoice V2.

    An unset or unknown backend falls back to ``openvoice`` (never silently pick a
    non-commercial engine). Pure.
    """
    backend = (getattr(config, "clone_backend", "") or "").lower().strip()
    if backend in _KNOWN:
        return backend
    return "openvoice"
