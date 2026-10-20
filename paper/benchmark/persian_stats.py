"""Uncertainty and attribution for the Persian benchmark cells (FA-05 / #514).

Pure and dependency-free: it reads the per-utterance transcripts that
``bench_persian.py --hyps-out`` writes, and answers two questions the aggregate
result JSON cannot:

* **How sure is a WER gap?** A percentile bootstrap over *utterances* (the unit the
  corpus was sampled in), and a *paired* bootstrap for two models decoded on the same
  rows, because the two cells share every reference and their errors are correlated.
* **How much WER is one orthographic habit?** Models that never emit U+200C (ZWNJ)
  pay for it in WER. ``zwnj_attributable_points`` re-scores with ZWNJ removed from
  reference and hypothesis alike; the drop is the share of the error that is ZWNJ.

Scoring matches ``bench_persian.py``: corpus-level WER (sum of word edits over sum of
reference words, empty references dropped, an empty hypothesis is a deletion), after
``normalize_fa_eval_v1``. A confidence interval says how much the *sample* could move
the number; it says nothing about another machine, corpus or decoder setting.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from persian_metrics import ZWNJ, normalize_fa_eval_v1


def word_errors(reference: str, hypothesis: str) -> tuple[int, int]:
    """``(word edit distance, reference word count)`` for one utterance."""
    ref, hyp = reference.split(), hypothesis.split()
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i]
        for j, h in enumerate(hyp, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h)))
        prev = cur
    return prev[-1], len(ref)


def per_utterance(refs: list[str], hyps: list[str]) -> list[tuple[int, int]]:
    """Edit counts per utterance after fa-eval-v1; empty references are dropped."""
    if len(refs) != len(hyps):
        raise ValueError(f"refs/hyps must align: {len(refs)}/{len(hyps)}")
    return [
        word_errors(normalize_fa_eval_v1(r), normalize_fa_eval_v1(h))
        for r, h in zip(refs, hyps)
        if r.strip()
    ]


def _wer(counts: list[tuple[int, int]]) -> float:
    words = sum(n for _, n in counts)
    if not words:
        raise ValueError("no reference words to score")
    return 100.0 * sum(e for e, _ in counts) / words


def _percentile(sorted_vals: list[float], q: float) -> float:
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


def bootstrap_wer(
    refs: list[str], hyps: list[str], *, n: int = 2000, seed: int = 0, alpha: float = 0.05
) -> tuple[float, float, float]:
    """``(WER %, lower, upper)`` — percentile bootstrap over utterances."""
    counts = per_utterance(refs, hyps)
    rng = random.Random(seed)
    k = len(counts)
    draws = sorted(_wer([counts[rng.randrange(k)] for _ in range(k)]) for _ in range(n))
    return _wer(counts), _percentile(draws, alpha / 2), _percentile(draws, 1 - alpha / 2)


def paired_bootstrap_diff(
    refs: list[str],
    hyps_a: list[str],
    hyps_b: list[str],
    *,
    n: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """``(WER_a - WER_b in points, lower, upper)`` resampling the *same* rows for both.

    An interval that excludes 0 supports "a differs from b on this sample"; one that
    contains 0 means the sample cannot separate them.
    """
    ca, cb = per_utterance(refs, hyps_a), per_utterance(refs, hyps_b)
    rng = random.Random(seed)
    k = len(ca)
    diffs: list[float] = []
    for _ in range(n):
        idx = [rng.randrange(k) for _ in range(k)]
        diffs.append(_wer([ca[i] for i in idx]) - _wer([cb[i] for i in idx]))
    diffs.sort()
    return _wer(ca) - _wer(cb), _percentile(diffs, alpha / 2), _percentile(diffs, 1 - alpha / 2)


def zwnj_attributable_points(refs: list[str], hyps: list[str]) -> tuple[float, float, float]:
    """``(WER %, WER % with ZWNJ removed from both sides, difference in points)``."""
    base = _wer(per_utterance(refs, hyps))
    strip = _wer(
        per_utterance([r.replace(ZWNJ, "") for r in refs], [h.replace(ZWNJ, "") for h in hyps])
    )
    return base, strip, base - strip


def load_hyps(path: Path) -> tuple[list[str], list[str], list[str]]:
    """``(ids, references, hypotheses)`` from a ``--hyps-out`` JSONL file."""
    ids, refs, hyps = [], [], []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                ids.append(row["id"])
                refs.append(row["reference"])
                hyps.append(row["hypothesis"])
    if not ids:
        raise SystemExit(f"no rows in {path}")
    return ids, refs, hyps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hyps", type=Path, help="JSONL from bench_persian.py --hyps-out")
    parser.add_argument("--versus", type=Path, help="a second cell on the same rows (paired)")
    parser.add_argument("--resamples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    ids, refs, hyps = load_hyps(args.hyps)
    wer, lo, hi = bootstrap_wer(refs, hyps, n=args.resamples, seed=args.seed)
    base, strip, delta = zwnj_attributable_points(refs, hyps)
    print(f"{args.hyps.name}: WER {wer:.2f}% [95% CI {lo:.2f}, {hi:.2f}] over {len(ids)} rows")
    print(f"  ZWNJ-attributable: {base:.2f}% -> {strip:.2f}% without ZWNJ ({delta:+.2f} points)")
    if args.versus:
        ids_b, _, hyps_b = load_hyps(args.versus)
        if ids_b != ids:
            raise SystemExit("--versus must cover the same ids in the same order")
        d, dlo, dhi = paired_bootstrap_diff(refs, hyps, hyps_b, n=args.resamples, seed=args.seed)
        print(f"  paired diff vs {args.versus.name}: {d:+.2f} points [95% CI {dlo:+.2f}, {dhi:+.2f}]")


if __name__ == "__main__":
    main()
