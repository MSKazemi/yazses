"""Voice-biometric admission gate (pure) — ADR-v2-018.

Decide whether a dictation burst should be injected, from a speaker-match similarity
and an anti-spoof score. Pure and deterministic; the scoring models live elsewhere and
are lazy behind the ``voiceguard`` extra.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateDecision:
    """Result of the admission gate: whether to inject, and a human reason."""
    admit: bool
    reason: str


def admit(similarity, spoof_score, config) -> GateDecision:
    """Admit a burst only if it matches the enrolled speaker and isn't spoofed.

    ``similarity``: cosine similarity to the enrolled voiceprint (higher = more likely
    the user). ``spoof_score``: probability the audio is synthetic/replayed (higher =
    more likely fake). Either may be ``None`` when its model is unavailable; then the
    ``fail_open`` policy (default admit) decides, to avoid locking the user out. Pure.
    """
    if not getattr(config, "enabled", False):
        return GateDecision(True, "disabled")
    fail_open = bool(getattr(config, "fail_open", True))
    match_th = float(getattr(config, "match_threshold", 0.5))
    spoof_th = float(getattr(config, "spoof_threshold", 0.5))

    # Speaker match
    if similarity is None:
        if not fail_open:
            return GateDecision(False, "no speaker score (fail-closed)")
    elif similarity < match_th:
        return GateDecision(False, f"speaker mismatch ({similarity:.2f} < {match_th:.2f})")

    # Anti-spoof
    if spoof_score is None:
        if not fail_open:
            return GateDecision(False, "no spoof score (fail-closed)")
    elif spoof_score > spoof_th:
        return GateDecision(False, f"possible spoof ({spoof_score:.2f} > {spoof_th:.2f})")

    return GateDecision(True, "admitted")
