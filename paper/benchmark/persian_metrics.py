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
- Canonical Persian Yeh/Kaf mapping (Arabic Yeh U+064A -> Persian Yeh U+06CC,
  Arabic Kaf U+0643 -> Persian Kaf U+06A9, Arabic Yeh with hamza above U+0626 ->
  U+06CC + U+0654 / U+0626 preserved per NFC).
- Standardized whitespace (collapse runs of spaces/tabs/newlines, strip ends).
- Digits and punctuation are intentionally NOT altered here because §6 requires
  digit/punct alterations to be separately reported (they materially change WER/CER).
"""

from __future__ import annotations

import unicodedata
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


def compute_zwnj_metrics(
    references: list[str], hypotheses: list[str]
) -> ZwnjMetrics:
    """Compute ZWNJ precision and recall across paired reference/hypothesis utterances.

    A ZWNJ in hypothesis is credited as a match if the corresponding reference
    also contains a ZWNJ at roughly the same word context (approximated here by
    per-utterance count alignment: min(ref_zwnj, hyp_zwnj)).
    """
    total_ref = 0
    total_hyp = 0
    total_match = 0
    for r, h in zip(references, hypotheses):
        r_zwnj = r.count(ZWNJ)
        h_zwnj = h.count(ZWNJ)
        total_ref += r_zwnj
        total_hyp += h_zwnj
        total_match += min(r_zwnj, h_zwnj)

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
