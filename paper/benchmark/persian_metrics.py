"""Persian evaluation normalizer (fa-eval-v1) and text-quality metrics.

Part of FA-04 / #513 (Persian benchmark harness).

The evaluation normalizer follows design/specs/persian-benchmark-and-validation.md §6:
it is deliberately separate from the production Persian normalizer
(`yazses.postprocess.persian_text`), versioned independently, and contains only
pure string operations without depending on production STT or postprocessing code.
Evaluation and production normalization must be able to drift independently;
coupling them would allow production bug fixes to silently move historical
benchmark numbers.

Scope of fa-eval-v1 (§6):
- Unicode NFC normalization.
- Canonical Persian Yeh/Kaf mapping (Arabic Yeh U+064A and Alef Maksura U+0649 ->
  Persian Yeh U+06CC, Arabic Kaf U+0643 -> Persian Keheh U+06A9). Yeh with hamza
  (U+0626) is left exactly as NFC leaves it.
- Standardized whitespace (collapse runs of spaces/tabs/newlines, strip ends).
- Digits and punctuation are intentionally NOT altered here because §6 requires
  digit/punct alterations to be separately reported (they materially change WER/CER).
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from typing import NamedTuple

EVAL_NORMALIZER_VERSION = "fa-eval-v1"

ZWNJ = "\u200c"
ARABIC_YEH = "\u064a"
PERSIAN_YEH = "\u06cc"
ARABIC_KAF = "\u0643"
PERSIAN_KAF = "\u06a9"
ALEF_MAQSURA = "\u0649"

_CANONICAL_LETTERS = {
    ARABIC_YEH: PERSIAN_YEH,
    ALEF_MAQSURA: PERSIAN_YEH,
    ARABIC_KAF: PERSIAN_KAF,
}


def normalize_fa_eval_v1(text: str) -> str:
    """Normalize Persian text for evaluation per spec §6 (fa-eval-v1).

    Applies Unicode NFC, maps Arabic Yeh/Kaf to canonical Persian equivalents,
    and standardizes whitespace. Digits and punctuation are preserved.
    """
    if not text:
        return ""
    # 1. Unicode NFC
    s = unicodedata.normalize("NFC", text)
    # 2. Canonical Yeh/Kaf
    out: list[str] = []
    for ch in s:
        out.append(_CANONICAL_LETTERS.get(ch, ch))
    s = "".join(out)
    # 3. Standardized whitespace (preserve ZWNJ; collapse standard spaces/tabs/newlines)
    words = s.split()
    return " ".join(words)


class ZwnjMetrics(NamedTuple):
    """ZWNJ precision and recall on references containing U+200C."""

    reference_count: int
    hypothesis_count: int
    matched_count: int
    precision: float
    recall: float
    f1: float


class QualityMetrics(NamedTuple):
    """Persian text quality metrics per spec §5."""

    arabic_yeh_count: int
    arabic_kaf_count: int
    zwnj_metrics: ZwnjMetrics


def count_arabic_variants(text: str) -> tuple[int, int]:
    """Count non-canonical Arabic Yeh and Kaf characters in text."""
    yeh = sum(1 for ch in text if ch in (ARABIC_YEH, ALEF_MAQSURA))
    kaf = sum(1 for ch in text if ch == ARABIC_KAF)
    return yeh, kaf


def _zwnj_contexts(text: str) -> Counter:
    """One ``(previous letter, next letter)`` key per ZWNJ in *text*.

    Letters are canonicalised the same way the evaluation normalizer does, so a
    joiner between the same two letters matches even when one side spells a letter
    with the Arabic variant (that is a letter error, and the Yeh/Kaf counts already
    report it). A ZWNJ at either end of the text keys against ``""``.
    """
    contexts: Counter = Counter()
    for i, ch in enumerate(text):
        if ch != ZWNJ:
            continue
        prev = _CANONICAL_LETTERS.get(text[i - 1], text[i - 1]) if i > 0 else ""
        nxt = _CANONICAL_LETTERS.get(text[i + 1], text[i + 1]) if i + 1 < len(text) else ""
        contexts[(prev, nxt)] += 1
    return contexts


def compute_zwnj_metrics(
    references: list[str], hypotheses: list[str]
) -> ZwnjMetrics:
    """Compute ZWNJ precision and recall across paired reference/hypothesis utterances.

    A hypothesis ZWNJ is credited only if the reference has a ZWNJ between the same
    two letters in that utterance (each reference joiner can be claimed once). Counting
    joiners per utterance without looking at where they sit would report perfect
    quality for a hypothesis that has the right *number* of joiners in the wrong
    places, which is exactly the kind of error §5 exists to expose.
    """
    total_ref = 0
    total_hyp = 0
    total_match = 0
    for r, h in zip(references, hypotheses):
        ref_ctx = _zwnj_contexts(r)
        hyp_ctx = _zwnj_contexts(h)
        total_ref += sum(ref_ctx.values())
        total_hyp += sum(hyp_ctx.values())
        total_match += sum((ref_ctx & hyp_ctx).values())

    prec = (total_match / total_hyp) if total_hyp > 0 else (1.0 if total_ref == 0 else 0.0)
    rec = (total_match / total_ref) if total_ref > 0 else (1.0 if total_hyp == 0 else 0.0)
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) > 0 else 0.0

    return ZwnjMetrics(
        reference_count=total_ref,
        hypothesis_count=total_hyp,
        matched_count=total_match,
        precision=round(prec, 4),
        recall=round(rec, 4),
        f1=round(f1, 4),
    )


def compute_persian_quality(
    references: list[str], hypotheses: list[str]
) -> QualityMetrics:
    """Compute all §5 Persian text quality metrics for hypotheses against references."""
    joined_hyp = " ".join(hypotheses)
    yeh, kaf = count_arabic_variants(joined_hyp)
    zwnj = compute_zwnj_metrics(references, hypotheses)
    return QualityMetrics(
        arabic_yeh_count=yeh,
        arabic_kaf_count=kaf,
        zwnj_metrics=zwnj,
    )
