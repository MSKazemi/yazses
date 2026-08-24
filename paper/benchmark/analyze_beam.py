"""Is one beam width actually better than another, or is the grid within its own noise?

`bench_beam.py` publishes a table of WERs a few hundredths of a point apart: 4.01
against 4.07 on clean audio, 9.46 against 9.84 on hard audio. Every one of those gaps
is far narrower than the 95 % interval on either endpoint -- at 200 utterances that
interval spans roughly a full point -- so a reader comparing the two published
percentages is comparing two numbers whose error bars overlap almost entirely, and the
table invites exactly that.

Two independent intervals is the wrong instrument, and it is the wrong instrument in
the direction that loses findings: every beam width decodes **the same utterances**,
so the two conditions share nearly all their variance. Which utterances happen to be
hard is common to both and cancels. The paired bootstrap keeps that cancellation --
resample the utterance *indices* once per replicate and score both conditions on the
same resample, then take the difference -- and the resulting interval on the
difference is several times narrower than either interval on a level.

This is the standard estimator for ASR system comparison (Bisani & Ney, "Bootstrap
estimates for confidence intervals in ASR performance evaluation", ICASSP 2004). The
reported p is the two-sided bootstrap proportion of replicates whose difference has
the opposite sign to the observed one -- an achieved significance level, not a t-test.

Reads the `per_utt_errors` / `per_utt_ref_words` arrays that `bench_beam.py` writes. A
result produced before those existed carries only totals; this says so and stops,
rather than falling back to comparing two levels, which is the reading it exists to
replace.

    uv run --group benchmark python paper/benchmark/analyze_beam.py paper/results/beam-test-clean.json
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

#: Replicates. 10_000 rather than the 1_000 `bench_wer.py` uses for a level: the
#: quantity here is a *p-value* near the tail, and 1_000 replicates cannot resolve one
#: below 0.001 at all -- it would report 0.0 and mean "fewer than one in a thousand".
BOOTSTRAP_N = 10_000
#: Fixed so a re-run of the analysis reproduces the published p exactly. The decode is
#: already done; this seed governs only the resampling.
SEED = 20260824
ALPHA = 0.05


def _cells(row: dict) -> tuple[list[int], list[int]]:
    errs = row.get("per_utt_errors")
    words = row.get("per_utt_ref_words")
    if not isinstance(errs, list) or not isinstance(words, list):
        raise ValueError("row carries no per-utterance counts")
    if len(errs) != len(words):
        raise ValueError(f"row has {len(errs)} error counts and {len(words)} word counts")
    return errs, words


def _wer(errs: list[int], words: list[int], idx: list[int]) -> float:
    total_w = sum(words[i] for i in idx)
    if not total_w:
        return 0.0
    return sum(errs[i] for i in idx) / total_w * 100


def paired_bootstrap(a: dict, b: dict, n: int = BOOTSTRAP_N, seed: int = SEED) -> dict:
    """Bootstrap the WER difference `a - b` over shared utterance resamples."""
    ea, wa = _cells(a)
    eb, wb = _cells(b)
    if len(ea) != len(eb):
        raise ValueError(f"rows cover different utterance counts: {len(ea)} vs {len(eb)}")
    if wa != wb:
        # Reference word counts are a property of the *reference*, not the decode, so
        # they must be identical across two rows of one run. If they are not, the two
        # rows scored different utterances and pairing them is meaningless -- a
        # silently mis-paired bootstrap would report a confident interval on nothing.
        raise ValueError("rows do not share a reference; they cannot be paired")

    size = len(ea)
    rng = random.Random(seed)
    observed = _wer(ea, wa, list(range(size))) - _wer(eb, wb, list(range(size)))
    diffs = []
    for _ in range(n):
        idx = [rng.randrange(size) for _ in range(size)]
        diffs.append(_wer(ea, wa, idx) - _wer(eb, wb, idx))
    diffs.sort()
    # Achieved significance level: how often the resampled difference lands on the
    # other side of zero from the observed one. Doubled for a two-sided reading.
    if observed >= 0:
        tail = sum(1 for d in diffs if d <= 0) / n
    else:
        tail = sum(1 for d in diffs if d >= 0) / n
    return {
        "a": f"{a['model']} beam={a['beam_size']}",
        "b": f"{b['model']} beam={b['beam_size']}",
        "split": a.get("split"),
        "a_wer": a["wer_pct"],
        "b_wer": b["wer_pct"],
        "diff": round(observed, 3),
        "diff_ci95": [round(diffs[int(0.025 * n)], 3), round(diffs[int(0.975 * n)], 3)],
        "p": round(min(1.0, 2 * tail), 4),
        "n_utterances": size,
    }


def analyse(path: Path, baseline: int = 1) -> dict:
    """Every beam width against `baseline`, within each model.

    Beam 1 is the default baseline because it is the *claim* under test: the source
    called it "measurably worse", and every other width is an argument for paying more
    decode than it costs. Comparing every pair instead would multiply the tests without
    answering a question anyone asked.

    `baseline=2` asks the second question, and it is the one that decides a default:
    beam search plainly earns its cost against beam 1, but the shipped value is 5, and
    whether 5 beats 2 is a different comparison that "5 beats 1" cannot answer. Both
    are recorded, because a reader deciding what to set needs the pair, not one of them.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["rows"]
    if any("per_utt_errors" not in r for r in rows):
        raise SystemExit(
            f"{path} carries only per-row totals, not per-utterance counts.\n"
            "The paired bootstrap needs to score both conditions on one resample of\n"
            "the same utterances; totals cannot be paired. Re-run bench_beam.py.\n"
            "Comparing the two published levels instead is the reading this script\n"
            "exists to replace, so it is deliberately not offered as a fallback."
        )

    by_model: dict[str, list[dict]] = {}
    for row in rows:
        by_model.setdefault(row["model"], []).append(row)

    out = []
    for model, cells in sorted(by_model.items()):
        cells.sort(key=lambda r: r["beam_size"])
        base = next((c for c in cells if c["beam_size"] == baseline), None)
        if base is None:
            continue  # this model was not measured at the requested baseline
        for cell in cells:
            if cell["beam_size"] == baseline:
                continue
            out.append(paired_bootstrap(base, cell))
    return {
        "source": path.name,
        "provenance": data.get("provenance"),
        "method": "paired bootstrap over utterances, 10000 replicates, seed 20260824",
        "baseline_beam": baseline,
        "alpha": ALPHA,
        "comparisons": out,
        "n_comparisons": len(out),
        "n_significant": sum(1 for c in out if c["p"] < ALPHA),
    }


def _report(res: dict) -> None:
    b = res["baseline_beam"]
    print(f"Paired bootstrap of the WER difference against beam={b}, same utterances")
    print(f"source: {res['source']}   comparisons: {res['n_comparisons']}\n")
    print(f"{'comparison':<34} {'beam' + str(b):>6} {'cell':>6} {'diff':>7} {'95% CI':>18} {'p':>8}")
    for c in res["comparisons"]:
        ci = f"[{c['diff_ci95'][0]:+.2f}, {c['diff_ci95'][1]:+.2f}]"
        star = " *" if c["p"] < res["alpha"] else ""
        # A bootstrap p is a proportion of replicates, so its resolution is 1/N and
        # it cannot express anything smaller. Printing `0.0000` would claim a
        # certainty the method does not have.
        shown = f"<{1 / BOOTSTRAP_N:.4f}" if c["p"] == 0.0 else f"{c['p']:.4f}"
        print(
            f"{c['a'] + ' vs ' + c['b'].split()[-1]:<34} {c['a_wer']:>6} {c['b_wer']:>6} "
            f"{c['diff']:>+7.3f} {ci:>18} {shown:>8}{star}"
        )
    print(
        f"\n{res['n_significant']} of {res['n_comparisons']} reach p < {res['alpha']}. "
        f"A positive difference means beam {res['baseline_beam']} scored worse "
        "(higher WER) than the cell.\n"
        "An interval that straddles zero means the published gap between those two "
        "rows is not distinguishable from resampling noise on this subset -- which is "
        "a result about the subset, not proof the settings are equivalent."
    )


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    baseline = 1
    for a in sys.argv[1:]:
        if a.startswith("--baseline="):
            baseline = int(a.split("=", 1)[1])
    if not args:
        raise SystemExit(
            f"usage: {Path(sys.argv[0]).name} [--baseline=N] <beam-*.json> [...]"
        )
    for arg in args:
        path = Path(arg)
        res = analyse(path, baseline)
        _report(res)
        # The baseline is in the filename, not only in the payload: writing both
        # analyses to one name would let the second silently displace the first, and
        # the two answer different questions.
        suffix = "-significance" if baseline == 1 else f"-significance-vs-beam{baseline}"
        out = path.with_name(f"{path.stem}{suffix}.json")
        out.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {out}\n")


if __name__ == "__main__":
    main()
