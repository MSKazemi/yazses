"""Burst-level Voice Guard admission (ADR-v2-018) — the daemon's one call.

Two pure questions, both numpy-only and both taking the heavy pieces as arguments:

- :func:`inactive_reason` — is the guard enabled but unable to judge anything, and why.
  The guard refuses to run in that state instead of admitting or rejecting every burst
  without saying so; the daemon logs the reason once and `yazses doctor` prints it.
- :func:`decide` — embed the whole burst with the injected speaker embedder, take the
  cosine similarity to the enrolled voiceprint, and hand it to :func:`gate.admit`.

No anti-spoof model ships, so the spoof score is always ``None``. With the default
``fail_open = true`` that means the speaker match is the whole guard; with
``fail_open = false`` every burst would be refused for want of a score nobody can
produce, which is why :func:`inactive_reason` refuses that configuration outright.

The default ``match_threshold`` is tuned on synthetic signals only (the unit tests), not
on recorded speech; a cold, a new microphone or a whisper can lower the similarity.
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

from yazses.voiceguard.gate import GateDecision, admit
from yazses.voiceprint.embedding import cosine_similarity

log = logging.getLogger(__name__)


def inactive_reason(
    cfg: Any, *, embedder_ready: bool | None, enrolled: bool
) -> str | None:
    """Why an enabled ``[voiceguard]`` cannot judge any burst, or ``None``. Pure.

    ``None`` too when ``[voiceguard]`` is off — there is nothing to explain.
    ``embedder_ready`` is ``None`` when the caller cannot tell (``doctor`` does not load
    the model; the registry's dependency check reports a missing library there).
    """
    vg = getattr(cfg, "voiceguard", None)
    if vg is None or not getattr(vg, "enabled", False):
        return None
    if not getattr(getattr(cfg, "voiceprint", None), "enabled", False):
        return (
            "it compares each burst with your enrolled voiceprint, and `[voiceprint] "
            "enabled` is false. Set `[voiceprint] enabled = true`, run `yazses "
            "enroll-voice`, then `yazses restart`"
        )
    if embedder_ready is False:
        return (
            "no speaker embedder could load (the voiceprint warning above says why), so "
            "there is nothing to compare a burst with"
        )
    if not enrolled:
        return (
            "no voiceprint is enrolled, so there is nothing to match a burst against. "
            "Run `yazses enroll-voice`, then `yazses restart`"
        )
    if not getattr(vg, "fail_open", True):
        return (
            "`[voiceguard] fail_open = false` needs an anti-spoof score for every burst, "
            "and no anti-spoof model ships yet, so it would refuse everything you say. "
            "Set `fail_open = true`; the speaker match is still enforced"
        )
    return None


def similarity(audio: np.ndarray, sample_rate: int, embedder: Any, voiceprint: np.ndarray) -> float | None:
    """Cosine similarity of the whole burst to *voiceprint*, or ``None`` on any failure."""
    try:
        return cosine_similarity(embedder.embed(audio, sample_rate).vector, voiceprint)
    except Exception as exc:
        log.debug("Voice Guard could not embed the burst: %s", exc)
        return None


def decide(
    audio: np.ndarray, sample_rate: int, embedder: Any, voiceprint: np.ndarray, config: Any
) -> GateDecision:
    """Admit or refuse one burst. Never raises; no anti-spoof score (``None``)."""
    return admit(similarity(audio, sample_rate, embedder, voiceprint), None, config)
