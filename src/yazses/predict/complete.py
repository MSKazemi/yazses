"""Predictive completion control layer (pure) — ADR-v2-016.

Parse accept/decline voice control phrases and merge an accepted suggestion into
the dictation buffer, de-duplicating an overlapping boundary. The on-device
generator is lazy and lives elsewhere; this layer is pure and testable.
"""
from __future__ import annotations

_ACCEPT = frozenset(
    ["accept", "accept that", "take it", "yes take it", "keep it", "use that"]
)
_DECLINE = frozenset(
    ["no", "decline", "discard", "reject", "cancel that", "never mind"]
)


def parse_accept(phrase) -> str | None:
    """Return ``"accept"``, ``"decline"``, or ``None`` (not a control phrase).

    ``None`` means "keep talking" — the phrase is ordinary dictation, not a
    response to a suggestion. Outer punctuation/case are ignored.
    """
    p = (phrase or "").strip().lower().strip(".!?,")
    if not p:
        return None
    if p in _ACCEPT:
        return "accept"
    if p in _DECLINE:
        return "decline"
    return None


def merge_completion(buffer: str, suggestion: str) -> str:
    """Append ``suggestion`` to ``buffer``, de-duplicating a word-overlap boundary.

    If the buffer's trailing words match the suggestion's leading words
    (case-insensitive), the overlap isn't repeated. Spacing normalises to one
    space. Empty suggestion returns the buffer unchanged. Pure.
    """
    b = (buffer or "").rstrip()
    s = (suggestion or "").strip()
    if not s:
        return buffer
    if not b:
        return s
    bw = b.split()
    sw = s.split()
    max_ov = min(len(bw), len(sw))
    ov = 0
    for k in range(max_ov, 0, -1):
        if [w.lower() for w in bw[-k:]] == [w.lower() for w in sw[:k]]:
            ov = k
            break
    tail = " ".join(sw[ov:])
    return b if not tail else f"{b} {tail}"
