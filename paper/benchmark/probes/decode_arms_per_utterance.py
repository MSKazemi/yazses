"""Is greedy-without-context broadly better, or better on two pathological clips?

`decode-determinism-large-v3-test-other.json` settles determinism and corpus WER:
`baseline` gives five distinct outputs and 4.84-6.21 % WER, `greedy` is bit-identical
across five runs at 15.26 %, and `greedy_no_context` is bit-identical at 3.82 %. In all
three arms the substitutions (87) and deletions (15) are **the same every time** -- only
insertions move, 78-129 for baseline against 466 and 40.

That is enough to decide "is it deterministic" and not enough to decide "should YazSes
ship it", because a corpus total cannot say *where* a 1.7-point gain comes from. If it
is two clips that ran away into a repetition loop, a user who never triggers one sees
nothing and the change is really about determinism. If it is spread across the corpus,
the default should move on accuracy alone. The two cases call for different release
notes, and a mean cannot tell them apart.

So this records **per utterance**: reference length and the three error classes, for
every arm, which makes the comparison *paired* -- the same audio, the same reference,
the same machine -- and lets the difference be tested rather than eyeballed:

* an **exact sign test** over the utterances that changed, which assumes nothing about
  the distribution of a per-utterance WER (it is bounded below, heavily zero-inflated,
  and nothing like normal);
* a **paired bootstrap** over utterances for the corpus-level delta, resampling whole
  utterances because words within one are not independent (Bisani & Ney, ICASSP 2004);
* the concentration curve -- what share of the total gain the worst *k* utterances
  supply -- which is the question in the title, answered as a number.

Baseline is decoded `--baseline-repeats` times (default 3) because it is the one arm
that is *not* deterministic; scoring it once would compare a fixed arm against a single
draw of a random one. The deterministic arms are decoded once, which the five-run
determinism artifact is what licenses.

    python paper/benchmark/probes/decode_arms_per_utterance.py test-other 200 large-v3
"""
from __future__ import annotations

import gc
import json
import random
import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))

import jiwer  # noqa: E402

import bench_wer  # noqa: E402
from _common import RESULTS_DIR, load_audio, librispeech_subset, write_result  # noqa: E402
from decode_determinism import ARMS, _patched, _release  # noqa: E402

N_BOOT = 10_000
SEED = 20260824
ALPHA = 0.05


def _per_utterance(ids: list[str], refs: list[str], hyps: list[str]) -> list[dict]:
    """Error counts for each utterance, scored one at a time and carrying its own id.

    Scored individually rather than sliced out of one corpus alignment: jiwer aligns the
    concatenation, and an insertion at a boundary can be charged to either neighbour.
    Per-utterance alignment is what makes the pairing exact.

    The id travels *in the row* rather than being recovered by position later. An
    utterance with an empty reference is unscorable and is dropped here, so the surviving
    rows no longer line up with the subset list -- and a comparison that indexed a
    parallel `ids` list would then name the wrong audio for every utterance after the
    first gap. Silently mislabelling which clip a finding belongs to is worse than losing
    it, because the label is what makes the finding checkable by someone else.
    """
    rows = []
    for utt_id, ref, hyp in zip(ids, refs, hyps):
        if not ref.strip():
            continue
        m = jiwer.process_words([ref], [hyp])
        rows.append({
            "id": utt_id,
            "ref_words": len(ref.split()),
            "insertions": m.insertions,
            "substitutions": m.substitutions,
            "deletions": m.deletions,
            "errors": m.insertions + m.substitutions + m.deletions,
        })
    return rows


def _corpus_wer(rows: list[dict]) -> float:
    words = sum(r["ref_words"] for r in rows)
    return sum(r["errors"] for r in rows) / words * 100 if words else 0.0


def exact_sign_test(better: int, worse: int) -> float:
    """Two-sided exact sign test. Ties carry no information and are excluded."""
    from math import comb

    n = better + worse
    if n == 0:
        return 1.0
    k = min(better, worse)
    tail = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def median_run(runs: list[list[dict]]) -> list[dict]:
    """The run to pair against: the median by corpus WER, never the best or the mean.

    The mean is not a run -- it has no per-utterance rows to pair against -- and the best
    run would compare a fixed arm against the most favourable draw of a random one, which
    is the same error as reporting a benchmark's best-of-five.
    """
    return sorted(runs, key=_corpus_wer)[len(runs) // 2]


def compare(base: list[dict], arm: list[dict]) -> dict:
    """Paired comparison of *arm* against *base* over the same utterances."""
    if [r["id"] for r in base] != [r["id"] for r in arm]:
        raise ValueError("arms scored different utterances; the pairing would be a lie")
    rng = random.Random(SEED)
    deltas = [a["errors"] - b["errors"] for b, a in zip(base, arm)]
    better = sum(1 for d in deltas if d < 0)
    worse = sum(1 for d in deltas if d > 0)

    n = len(base)
    draws = []
    for _ in range(N_BOOT):
        idx = [rng.randrange(n) for _ in range(n)]
        bw = sum(base[i]["ref_words"] for i in idx)
        if not bw:
            continue
        db = sum(base[i]["errors"] for i in idx) / bw * 100
        da = sum(arm[i]["errors"] for i in idx) / bw * 100
        draws.append(da - db)
    draws.sort()
    lo = draws[int(ALPHA / 2 * len(draws))]
    hi = draws[int((1 - ALPHA / 2) * len(draws)) - 1]

    # Concentration: how much of the total gain the worst few utterances supply.
    gains = sorted(((-d, base[i]["id"]) for i, d in enumerate(deltas) if d < 0), reverse=True)
    total_gain = sum(g for g, _ in gains)
    concentration = {
        f"top_{k}": {
            "share_of_gain": round(sum(g for g, _ in gains[:k]) / total_gain, 3)
            if total_gain else 0.0,
            "utterances": [u for _, u in gains[:k]],
        }
        for k in (1, 3, 5, 10) if k <= len(gains)
    }
    return {
        "corpus_wer_base": round(_corpus_wer(base), 3),
        "corpus_wer_arm": round(_corpus_wer(arm), 3),
        "delta_wer": round(_corpus_wer(arm) - _corpus_wer(base), 3),
        "delta_wer_ci95": [round(lo, 3), round(hi, 3)],
        "utterances_better": better,
        "utterances_worse": worse,
        "utterances_unchanged": len(deltas) - better - worse,
        "sign_test_p": round(exact_sign_test(better, worse), 4),
        "total_errors_removed": total_gain,
        "gain_concentration": concentration,
        "verdict": (
            "no resolvable difference" if lo <= 0 <= hi
            else ("arm is better" if hi < 0 else "arm is worse")
        ),
    }


def run(split: str, n: int, model: str, baseline_repeats: int) -> dict:
    subset = librispeech_subset(n, stratified=True, split=split)
    refs = [bench_wer._normalize(r) for _, _, r, _ in subset]
    ids = [u for u, _, _, _ in subset]
    audio = [load_audio(f) for _, f, _, _ in subset]

    def decode(extra: dict) -> list[str]:
        engine = _patched(bench_wer._build("faster-whisper", model), extra)
        out = [bench_wer._normalize(engine.transcribe(a)) for a in audio]
        _release(engine)
        gc.collect()
        return out

    per_arm: dict[str, list[list[dict]]] = {}
    for arm, extra in ARMS.items():
        reps = baseline_repeats if arm == "baseline" else 1
        runs = []
        for r in range(reps):
            t0 = time.monotonic()
            rows = _per_utterance(ids, refs, decode(extra))
            runs.append(rows)
            print(f"[arms] {arm} run {r}: WER={_corpus_wer(rows):.2f}% "
                  f"({time.monotonic() - t0:.0f}s)", flush=True)
        per_arm[arm] = runs

    base = median_run(per_arm["baseline"])

    return {
        "probe": {
            "measured": (
                "Whether the decode-arm WER difference is broad or carried by a few "
                "runaway utterances: per-utterance error counts for every arm, paired "
                "sign test, paired bootstrap over utterances, and gain concentration."
            ),
            "produced_by": "paper/benchmark/probes/decode_arms_per_utterance.py",
        },
        "config": {
            "dataset": f"LibriSpeech {split}", "n_utterances": len(subset),
            "model": model, "baseline_repeats": baseline_repeats,
            "arms": {k: (v or "faster-whisper defaults") for k, v in ARMS.items()},
            "bootstrap_resamples": N_BOOT, "seed": SEED,
            "normalizer": "whisper_normalizer.english.EnglishTextNormalizer",
            "pairing_baseline": "median run of the baseline arm, by corpus WER",
        },
        "baseline_runs_wer": [round(_corpus_wer(r), 3) for r in per_arm["baseline"]],
        "comparisons": {
            arm: compare(base, per_arm[arm][0])
            for arm in ARMS if arm != "baseline"
        },
        "per_utterance": {
            "ids": [r["id"] for r in base],
            "ref_words": [r["ref_words"] for r in base],
            "baseline_errors": [r["errors"] for r in base],
            **{f"{arm}_errors": [r["errors"] for r in per_arm[arm][0]]
               for arm in ARMS if arm != "baseline"},
        },
    }


def main() -> None:
    split = sys.argv[1] if len(sys.argv) > 1 else "test-other"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    model = sys.argv[3] if len(sys.argv) > 3 else "large-v3"
    reps = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    payload = run(split, n, model, reps)
    print(f"wrote {write_result(f'probes/decode-arms-per-utterance-{model}-{split}', payload)}")


if __name__ == "__main__":
    main()
