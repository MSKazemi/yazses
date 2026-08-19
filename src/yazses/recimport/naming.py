"""Speaker-name resolution for diarized recordings (pure core) — ADR-v2-125.

Decide the display name for each diarized speaker cluster, with this precedence:

1. **Explicit** — ``--rename speaker_0=Alice`` / positional ``--names "Alice,Bob"``.
2. **Enrolled voiceprint** — a cluster with at least ``min_speaker_seconds`` of
   aggregated speech is embedded (mean centroid) and cosine-matched against the user's
   enrolled voiceprints; a match at/above ``name_threshold`` gets that person's name.
   This gate is deliberate: ECAPA embeddings are unreliable on short audio, so clusters
   below the duration floor are never named from voice (research §5).
3. **Anonymous** — otherwise ``"Speaker 1"``, ``"Speaker 2"``, … in first-appearance
   order.

The default path (no embedder) is fully pure and testable. The voiceprint path takes an
injected embedder + enrolled profiles, so it is testable with a fake and never
auto-enrolls anyone (biometric-consent policy, research §6 / ADR-011/012).
"""
from __future__ import annotations

import logging

import numpy as np

from yazses.voiceprint.profiles import nearest_profile

log = logging.getLogger(__name__)


def _ordered_speakers(utterances):
    """Canonical speaker ids in first-appearance order (skips the empty id)."""
    order = []
    for u in utterances:
        if u.speaker and u.speaker not in order:
            order.append(u.speaker)
    return order


def unmatched_renames(utterances, renames) -> list:
    """Rename keys that name no speaker in this recording, sorted. Pure.

    A mistyped or out-of-range speaker id -- `speaker_5` on a two-speaker file, or
    `Speaker_0` with the wrong case -- otherwise renames nobody and reports nothing, so
    the transcript comes back saying "Speaker 1" and the user is left to work out why.
    """
    known = set(_ordered_speakers(utterances))
    return sorted(
        spk for spk, name in (renames or {}).items()
        if name and str(name).strip() and spk not in known
    )


def resolve_names(
    utterances,
    *,
    names=None,
    renames=None,
    embedder=None,
    audio=None,
    sample_rate: int = 16000,
    profiles=None,
    min_speaker_seconds: float = 3.0,
    name_threshold: float = 0.5,
):
    """Return a ``{canonical_speaker_id: display_name}`` map. Pure given its inputs.

    ``names`` maps to speakers in first-appearance order; ``renames`` is an explicit
    ``{speaker_id: name}`` override (wins over positional names and voiceprints).
    ``embedder``/``audio``/``profiles`` enable the voiceprint path; when any is absent
    that path is skipped. Unmatched or too-short clusters fall back to ``"Speaker N"``.
    """
    order = _ordered_speakers(utterances)
    renames = dict(renames or {})
    result: dict = {}

    # (1) positional names, applied in first-appearance order
    if names:
        for spk, name in zip(order, names):
            if name and name.strip():
                result[spk] = name.strip()

    # (1b) explicit renames win -- but only for speakers that are actually in the
    # recording. The returned map is documented as {canonical_speaker_id: display_name},
    # and a `--rename speaker_5=Bob` on a two-speaker file used to add `speaker_5` to it:
    # a key naming nobody, which no renderer ever looks up. The rename simply did nothing
    # and said nothing. `unmatched_renames` lets the caller say so.
    known = set(order)
    for spk, name in renames.items():
        if name and name.strip() and spk in known:
            result[spk] = name.strip()

    # (2) voiceprint auto-naming for still-unnamed clusters
    if embedder is not None and profiles and audio is not None:
        durations = _speaker_durations(utterances)
        for spk in order:
            if spk in result:
                continue
            if durations.get(spk, 0.0) < min_speaker_seconds:
                continue
            centroid = _cluster_centroid(spk, utterances, embedder, audio, sample_rate)
            if centroid is None:
                continue
            match = nearest_profile(centroid, profiles, min_similarity=name_threshold)
            if match:
                result[spk] = match

    # (3) anonymous fallback, numbered by first appearance
    n = 0
    for spk in order:
        if spk not in result:
            n += 1
            result[spk] = f"Speaker {n}"
        else:
            # keep numbering stable/independent of named clusters
            n = max(n, 0)
    return result


def _speaker_durations(utterances) -> dict:
    """Total speech seconds per canonical speaker id. Pure."""
    totals: dict = {}
    for u in utterances:
        if u.speaker:
            totals[u.speaker] = totals.get(u.speaker, 0.0) + max(0.0, u.end - u.start)
    return totals


def _cluster_centroid(speaker, utterances, embedder, audio, sample_rate):
    """Mean embedding over a speaker's audio segments, or ``None`` on failure.

    Concatenates the speaker's utterance spans and embeds them; a longer aggregate is a
    more stable d-vector than any single window (research §5). Any embedder failure
    degrades to ``None`` (→ the cluster stays anonymous), never raising into the CLI.
    """
    try:
        n = len(audio)
        chunks = []
        for u in utterances:
            if u.speaker != speaker:
                continue
            i0 = max(0, int(u.start * sample_rate))
            i1 = min(n, int(u.end * sample_rate))
            if i1 > i0:
                chunks.append(audio[i0:i1])
        if not chunks:
            return None
        segment = np.concatenate(chunks)
        emb = embedder.embed(segment, sample_rate)
        return getattr(emb, "vector", emb)
    except Exception as exc:  # pragma: no cover - defensive, backend-dependent
        log.warning("Voiceprint naming skipped for %s (%s).", speaker, exc)
        return None
