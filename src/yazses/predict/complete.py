"""Predictive completion control layer (pure) — ADR-v2-016.

Parse accept/decline voice control phrases and merge an accepted suggestion into
the dictation buffer, de-duplicating an overlapping boundary. The on-device
generator is lazy and lives elsewhere; this layer is pure and testable.
"""
from __future__ import annotations

#: The phrases that act on an open offer, and nothing else. Both sets are consumed, so a
#: phrase here is a phrase the user can never dictate as a whole utterance while an offer
#: is open -- each one has to be worth that cost.
#:
#: Narrowed on 2026-10-23 (owner decision). Wave 5 removed "no" and "never mind" from the
#: declines; the same reasoning took out every other phrase a person says as ordinary
#: one-utterance dictation: "accept", "accept that", "yes take it", "keep it" and
#: "use that" no longer accept, and "decline", "reject" and "cancel that" no longer
#: decline. "Keep it." or "Decline." replying to a message is now typed, and it
#: dismisses the offer like any other speech. What is left addresses the suggestion
#: itself ("accept suggestion") or is the short form the notification names ("take it").
#: Declining is optional anyway -- any other speech dismisses the offer and is
#: dictated -- so a missing decline word costs nothing, while a wrong one costs the
#: user's text.
_ACCEPT = frozenset(["accept suggestion", "take it"])
_DECLINE = frozenset(["discard"])


def parse_accept(phrase) -> str | None:
    """Return ``"accept"``, ``"decline"``, or ``None`` (not a control phrase).

    ``None`` means "keep talking" — the phrase is ordinary dictation, not a
    response to a suggestion. Only the whole utterance counts ("take it easy" is
    dictation); outer punctuation and case are ignored.
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
