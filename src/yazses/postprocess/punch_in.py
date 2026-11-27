"""Punch-In (P1 core) — correct a span by re-speaking just that phrase.

The user re-speaks a short phrase; this locates the closest-matching word span in
the recent dictation buffer and proposes replacing it with the respoken text —
like punch-in recording in a DAW. Per the evidence (Suhm 2001: pure respeak fixes
only ~35% and re-fails on retry), the design surfaces the top 2-3 aligned
candidates for the user to confirm rather than auto-splicing; the daemon/UI layer
(re-record capture + confirm + keyboard fallback) is P2.

Alignment uses stdlib ``difflib`` (no third-party dependency). Spec:
design/specs/punch-in.md.

"Words" are ``postprocess/cjk.py::break_units``: whitespace-separated words, and single
characters inside Chinese or Japanese. With whitespace words a whole Chinese clause was
one span, so re-speaking part of it replaced all of it (#501).
"""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from yazses.postprocess.cjk import break_units, render_units


@dataclass(frozen=True)
class Candidate:
    """A proposed correction: replace buffer[start_word:end_word] with new_text."""
    start_word: int
    end_word: int
    score: float
    old_text: str
    new_text: str


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def propose_corrections(
    buffer: str,
    respoken: str,
    *,
    max_candidates: int = 3,
    min_score: float = 0.5,
) -> list[Candidate]:
    """Locate the spans in ``buffer`` closest to ``respoken`` and propose replacements.

    Returns up to ``max_candidates`` candidates with similarity >= ``min_score``,
    best first. Empty when either input is blank or nothing clears the threshold.
    """
    words = break_units(buffer)
    respoken = respoken.strip()
    if not words or not respoken:
        return []

    r = len(break_units(respoken))
    window_sizes = {max(1, r - 1), r, r + 1}

    cands: list[Candidate] = []
    for w in window_sizes:
        for start in range(0, len(words) - w + 1):
            end = start + w
            span = render_units(words[start:end])
            score = _ratio(span, respoken)
            if score >= min_score:
                cands.append(Candidate(start, end, score, span, respoken))

    # Best score first; tie-break toward the window length closest to the respoken
    # phrase so an exact-length match beats an off-by-one with the same ratio.
    cands.sort(key=lambda c: (-c.score, abs((c.end_word - c.start_word) - r)))
    return cands[:max_candidates]


def apply_top_candidate(
    buffer: str,
    respoken: str,
    *,
    max_candidates: int = 3,
    min_score: float = 0.5,
    choose: int = 0,
) -> tuple[str | None, list[Candidate]]:
    """Propose corrections and build the corrected full burst for one candidate.

    Returns ``(corrected_text, candidates)``. ``corrected_text`` is ``buffer`` with
    the ``choose``-th candidate's span replaced by the respoken phrase; it is
    ``None`` when nothing clears ``min_score`` or ``choose`` is out of range. The
    full ``candidates`` list is returned so the caller can surface alternatives for
    the user to confirm (the spec rejects silent auto-splicing; respeak fixes only
    ~35% on the first try, Suhm 2001).
    """
    cands = propose_corrections(
        buffer, respoken, max_candidates=max_candidates, min_score=min_score
    )
    if not cands or choose < 0 or choose >= len(cands):
        return None, cands
    chosen = cands[choose]
    words = break_units(buffer)
    new = break_units(chosen.new_text)
    # The replacement joins the text before it the way the replaced span did.
    new[0] = (words[chosen.start_word][0], new[0][1])
    corrected = words[: chosen.start_word] + new + words[chosen.end_word :]
    return render_units(corrected), cands
