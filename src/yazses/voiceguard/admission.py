"""Burst-level Voice Guard admission (ADR-v2-018) — the daemon's one call.

Two pure questions, both numpy-only and both taking the heavy pieces as arguments:

- :func:`inactive_reason` — is the guard enabled but unable to judge anything, and why.
  The guard refuses to run in that state instead of admitting or rejecting every burst
  without saying so; the daemon logs the reason once and `yazses doctor` prints it.
- :func:`burst_refusal` — embed the whole burst with the injected speaker embedder, take
  the cosine similarity to the enrolled voiceprint, and hand it to :func:`gate.admit`.
  A burst that cannot be scored is admitted *and reported*, never admitted silently.

No anti-spoof model ships, so the spoof score is always ``None``. With the default
``fail_open = true`` that means the speaker match is the whole guard; with
``fail_open = false`` every burst would be refused for want of a score nobody can
produce, which is why :func:`inactive_reason` refuses that configuration outright.

The default ``match_threshold`` is tuned on synthetic signals only (the unit tests), not
on recorded speech; a cold, a new microphone or a whisper can lower the similarity.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from yazses.voiceguard.gate import GateDecision, admit
from yazses.voiceprint.embedding import cosine_similarity


def inactive_reason(
    cfg: Any, *, embedder_ready: bool | None, enrolled: bool, unreadable: bool = False
) -> str | None:
    """Why an enabled ``[voiceguard]`` cannot judge any burst, or ``None``. Pure.

    ``None`` too when ``[voiceguard]`` is off — there is nothing to explain.
    ``embedder_ready`` is ``None`` when the caller cannot tell (``doctor`` does not load
    the model; the registry's dependency check reports a missing library there).
    ``unreadable`` means a voiceprint file exists but could not be decrypted or loaded.
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
    if not enrolled and unreadable:
        return (
            "a voiceprint file exists but could not be decrypted or loaded (a changed "
            "key or a damaged file), so there is nothing to match a burst against. Run "
            "`yazses enroll-voice` again, then `yazses restart`"
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


def similarity(
    audio: np.ndarray, sample_rate: int, embedder: Any, voiceprint: np.ndarray
) -> tuple[float | None, str | None]:
    """Cosine similarity of the whole burst to *voiceprint*, and why there is none.

    Returns ``(score, None)``, or ``(None, reason)`` when the burst could not be scored.
    The reason is for the log: a failure here repeats on every burst (an enrolled
    voiceprint from a different ``[voiceprint] backend`` has a different length on every
    one), so the caller must say so loudly rather than admit everything in silence.
    Never raises.
    """
    try:
        vector = np.asarray(embedder.embed(audio, sample_rate).vector)
        enrolled = np.asarray(voiceprint)
        if vector.shape != enrolled.shape:
            return None, (
                f"the enrolled voiceprint has {enrolled.size} dimensions and the current "
                f"`[voiceprint] backend` produces {vector.size}, so no burst can be "
                "compared with it. Run `yazses enroll-voice` again with this backend, "
                "then `yazses restart`"
            )
        return cosine_similarity(vector, enrolled), None
    except Exception as exc:
        return None, f"the speaker embedder failed on a burst ({type(exc).__name__}: {exc})"


def burst_refusal(
    audio: np.ndarray, sample_rate: int, embedder: Any, voiceprint: np.ndarray, config: Any
) -> tuple[str | None, str | None]:
    """``(refusal, inert)`` for one burst. Never raises; no anti-spoof score (``None``).

    ``refusal`` is the gate's reason when it refuses the burst, else ``None``. ``inert``
    is set when the burst could not be scored at all: the burst is then admitted (the
    ``fail_open`` policy :func:`inactive_reason` insists on) and the caller must warn
    with ``inert`` so a guard that judges nothing is never silent about it.
    """
    score, inert = similarity(audio, sample_rate, embedder, voiceprint)
    if score is None:
        return None, inert
    decision: GateDecision = admit(score, None, config)
    return (None if decision.admit else decision.reason), None
