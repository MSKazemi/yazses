"""Mandarin evaluation normalizer (zh-eval-v1) and a pure character-error scorer.

Part of MODEL-01 / #503 (CHN-40): the instrument every Chinese model comparison is
scored with, so that Whisper ``small``, ``large-v3-turbo``, ``large-v3`` and any later
candidate are measured with one normalization and one alignment.

Library only, stdlib only, imported by `bench_mandarin.py` and never by the daemon.
Like `persian_metrics.py` it is deliberately **separate from the production code path**
(`yazses.postprocess.han_script`): evaluation and production normalization must be able to
drift independently, or a production bug fix would silently move historical benchmark
numbers. A test pins that this module imports nothing from ``yazses``.

Why a hand-written scorer rather than jiwer: CER for Chinese is the whole metric, and
the S/D/I split is what MODEL-07's error analysis reads, so the alignment is kept in one
place that runs wherever the suite runs (jiwer is a benchmark-group dependency the base
install does not have). Its *total* edit count is a plain Levenshtein distance, which the
tests cross-check against jiwer where jiwer is installed.

Four views of the same text, each a separate column in a result (§6 "punctuation-aware
and punctuation-stripped CER" and §9 "recognition CER and script-rendering errors must be
reported separately" of `design/chinese/model-strategy.md`):

``raw``
    The code points exactly as the reference and the hypothesis hold them. Nothing is
    folded, so a full-width comma against an ASCII one, a space Whisper inserted, and a
    Traditional character for a Simplified reference all count. This is what a user sees.
``punct``
    zh-eval-v1 **with punctuation kept**: NFC, width folding, Latin case folding, all
    whitespace removed. Punctuation errors still count, but not the width of the glyph.
``normalized``
    zh-eval-v1: the ``punct`` view with every Unicode punctuation character removed.
``script``
    The ``normalized`` view after folding both texts to one Han script (OpenCC ``t2s`` or
    ``s2t``). Only produced when a converter is actually available; otherwise the result
    says so and the column is ``null``, never a copy of ``normalized``.

zh-eval-v1, rule by rule (each one is pinned by a test in tests/test_bench_mandarin.py):

1. Unicode NFC. (NFC already maps a CJK compatibility ideograph such as U+F900 to its
   unified form, a canonical singleton.) Not NFKC: NFKC also rewrites compatibility
   characters -- ``①`` to ``1``, ``²`` to ``2``, ``㎏`` to ``kg`` -- which would hide
   model behaviour that is worth seeing.
2. Width folding, by explicit table rather than NFKC: full-width ASCII U+FF01-U+FF5E to
   U+0021-U+007E, the ideographic space U+3000 to a space, and the half-width CJK
   punctuation U+FF61-U+FF64 to its ordinary form (。「」、). Nothing else.
3. Latin case folding (``str.casefold``). Mixed Mandarin-English dictation spells the
   same word ``iPhone``/``iphone``; the raw column keeps the difference.
4. Whitespace removed entirely. Mandarin is written without spaces, and Whisper's
   habit of spacing around embedded Latin is not a recognition error. Consequence,
   stated rather than hidden: in the normalized views a Latin word costs one edit per
   letter, so English-heavy utterances weigh more than their word count.
5. ``normalized`` only: drop every character whose Unicode general category is
   punctuation (``P*``). Symbols (``S*``: ``¥``, ``+``, ``°``) are kept: they carry
   meaning. Note that ``%`` is category ``Po`` and is therefore dropped.
6. Digits are NOT folded to Han numerals or back. ``2024年`` against ``二零二四年`` is a
   real difference in what the user receives; number handling is reported separately
   (MODEL-07), not normalized away here.

Changing any rule above means a new ``EVAL_NORMALIZER_VERSION``, never an edit in place.
"""
from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence
from typing import NamedTuple

EVAL_NORMALIZER_VERSION = "zh-eval-v1"

#: What "a character" means for the CER in a result; stamped into every artifact.
TOKENISATION = (
    "cer: unicode code points; raw = as given; punct/normalized/script = after "
    "zh-eval-v1 with all whitespace removed (a Latin word is one edit per letter)"
)

#: The four views, in the order a result lists them.
VIEWS = ("raw", "punct", "normalized", "script")

_WIDTH = {cp: cp - 0xFEE0 for cp in range(0xFF01, 0xFF5F)}
_WIDTH[0x3000] = 0x20
_WIDTH.update({0xFF61: 0x3002, 0xFF62: 0x300C, 0xFF63: 0x300D, 0xFF64: 0x3001})

#: A text -> text Han-script converter (OpenCC's ``convert``), or ``None``.
ScriptConverter = Callable[[str], str]


def fold_width(text: str) -> str:
    """Rule 2: full-width ASCII and half-width CJK punctuation to their ordinary forms."""
    return text.translate(_WIDTH)


def _strip_punctuation(text: str) -> str:
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith("P"))


def normalize_zh_eval_v1(
    text: str,
    *,
    keep_punctuation: bool = False,
    script_converter: ScriptConverter | None = None,
) -> str:
    """Apply zh-eval-v1 to *text*; see the module docstring for every rule.

    ``keep_punctuation=True`` gives the ``punct`` view. ``script_converter`` gives the
    ``script`` view and is applied after width folding, before punctuation is dropped,
    so a converter that maps punctuation cannot undo rule 5.
    """
    out = unicodedata.normalize("NFC", text)
    out = fold_width(out)
    if script_converter is not None:
        out = unicodedata.normalize("NFC", script_converter(out))
    out = out.casefold()
    out = "".join(out.split())
    if not keep_punctuation:
        out = _strip_punctuation(out)
    return out


class EditCounts(NamedTuple):
    """One alignment's outcome. ``ref_chars`` is the CER denominator."""

    substitutions: int
    deletions: int
    insertions: int
    hits: int
    ref_chars: int

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions


ZERO = EditCounts(0, 0, 0, 0, 0)


def combine(a: EditCounts, b: EditCounts) -> EditCounts:
    """Field-wise sum: corpus CER is total edits over total reference characters."""
    return EditCounts(*(x + y for x, y in zip(a, b)))


def align(reference: str, hypothesis: str) -> EditCounts:
    """Minimum-edit alignment of two strings, character by character.

    Total edits are the Levenshtein distance. Where several alignments share that
    minimum, the backtrace prefers a hit or substitution, then a deletion, then an
    insertion -- a fixed rule, so the S/D/I split of a given pair never varies between
    runs or hosts (another scorer may split a tie differently while agreeing on the total).
    """
    n, m = len(reference), len(hypothesis)
    if n == 0:
        return EditCounts(0, 0, m, 0, 0)
    if m == 0:
        return EditCounts(0, n, 0, 0, n)
    prev = list(range(m + 1))
    rows = [prev]
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        r = reference[i - 1]
        for j in range(1, m + 1):
            cost = 0 if r == hypothesis[j - 1] else 1
            cur[j] = min(prev[j - 1] + cost, prev[j] + 1, cur[j - 1] + 1)
        rows.append(cur)
        prev = cur

    s = d = ins = h = 0
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            same = reference[i - 1] == hypothesis[j - 1]
            if rows[i][j] == rows[i - 1][j - 1] + (0 if same else 1):
                if same:
                    h += 1
                else:
                    s += 1
                i -= 1
                j -= 1
                continue
        if i > 0 and rows[i][j] == rows[i - 1][j] + 1:
            d += 1
            i -= 1
        else:
            ins += 1
            j -= 1
    return EditCounts(s, d, ins, h, n)


def cer(counts: EditCounts) -> float | None:
    """Corpus CER in percent, or ``None`` when there is no reference text to score."""
    if counts.ref_chars == 0:
        return None
    return round(counts.errors / counts.ref_chars * 100, 2)


def views(
    reference: str, hypothesis: str, script_converter: ScriptConverter | None
) -> dict[str, tuple[str, str] | None]:
    """The (reference, hypothesis) pair under each view; ``script`` is ``None`` without a converter."""
    def both(**kw) -> tuple[str, str]:
        return normalize_zh_eval_v1(reference, **kw), normalize_zh_eval_v1(hypothesis, **kw)

    return {
        "raw": (reference, hypothesis),
        "punct": both(keep_punctuation=True),
        "normalized": both(),
        "script": both(script_converter=script_converter) if script_converter else None,
    }


def score(
    references: Sequence[str],
    hypotheses: Sequence[str],
    *,
    script_converter: ScriptConverter | None = None,
) -> dict:
    """Corpus CER and S/D/I counts under every view, plus a per-utterance breakdown.

    Pure: no I/O, no clock. An empty *reference* (after ``strip``) is skipped from every
    view and counted under ``n_skipped_empty``, so all four views score the same pairs;
    an empty *hypothesis* is not skipped, because it is the model's failure (all
    deletions). Exact-match rates are over the same scored pairs.
    """
    if len(references) != len(hypotheses):
        raise ValueError(
            f"references/hypotheses must align: {len(references)}/{len(hypotheses)}"
        )
    if not references:
        raise ValueError("nothing to score: empty input")

    totals: dict[str, EditCounts] = {v: ZERO for v in VIEWS}
    exact = {v: 0 for v in VIEWS}
    per_utterance: list[dict | None] = []
    n = 0
    for ref, hyp in zip(references, hypotheses):
        if not ref.strip():
            per_utterance.append(None)
            continue
        n += 1
        row: dict[str, dict | None] = {}
        for view, pair in views(ref, hyp, script_converter).items():
            if pair is None:
                row[view] = None
                continue
            counts = align(*pair)
            totals[view] = combine(totals[view], counts)
            exact[view] += pair[0] == pair[1]
            row[view] = counts._asdict()
        per_utterance.append(row)

    applied = script_converter is not None
    out: dict = {"n_pairs": n, "n_skipped_empty": len(references) - n, "views": {}}
    for view in VIEWS:
        if view == "script" and not applied:
            out["views"][view] = None
            continue
        t = totals[view]
        out["views"][view] = {
            "cer": cer(t),
            **t._asdict(),
            "exact_match": round(exact[view] / n, 4) if n else None,
        }
    norm = out["views"]["normalized"]["cer"]
    scr = out["views"]["script"]["cer"] if applied else None
    # §9: report the delta, so a correct-but-wrong-script transcription is visible as such.
    out["script_delta_cer"] = (
        round(norm - scr, 2) if norm is not None and scr is not None else None
    )
    out["per_utterance"] = per_utterance
    return out
