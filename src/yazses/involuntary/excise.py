"""Involuntary-vocalization detection + span excision (pure) — ADR-v2-102.

Classify a non-speech segment (cough/throat-clear/sneeze) and remove tokens overlapping flagged
spans. Pure and deterministic; the acoustic classifier is the lazy extra.
"""
from __future__ import annotations


def is_involuntary_vocalization(seg_feats):
    """Classify a segment → ``cough`` | ``throat_clear`` | ``sneeze`` | ``None``. Pure.

    ``seg_feats``: ``duration_ms``, ``peak_energy`` (0–1), ``centroid_hz``, ``voiced`` (bool),
    ``burst`` (bool).
    """
    dur = seg_feats.get("duration_ms", 0)
    energy = seg_feats.get("peak_energy", 0.0)
    centroid = seg_feats.get("centroid_hz", 0)
    voiced = bool(seg_feats.get("voiced", False))
    burst = bool(seg_feats.get("burst", False))
    if burst and dur < 500 and energy >= 0.5 and not voiced:
        return "cough" if centroid < 1500 else "sneeze"
    if not voiced and not burst and 100 < dur < 800 and centroid < 1000:
        return "throat_clear"
    return None


def excise_nonspeech_spans(tokens, token_spans, flagged_spans):
    """Drop any token whose ``(start, end)`` span overlaps a flagged span. Pure."""
    flagged = list(flagged_spans or ())
    kept = []
    for tok, (start, end) in zip(list(tokens or ()), token_spans):
        overlaps = any(not (end <= fs or start >= fe) for fs, fe in flagged)
        if not overlaps:
            kept.append(tok)
    return kept
