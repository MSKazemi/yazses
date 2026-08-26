"""Can a centroid-similarity rule separate a split speaker from two real ones?

Consumes the shards written by `probes/centroid_merge.py` and asks one question: pooled
over every meeting, do cluster pairs that belong to the **same** true speaker sit at higher
centroid cosine than pairs belonging to **different** speakers, and is there a single cut
between them?

The asymmetry matters more than the accuracy. Merging two clusters that are really one
person *repairs* an over-count; merging two different people **destroys** attribution and
cannot be undone downstream -- a meeting transcript then confidently puts one person's
words in another's mouth. So a false merge is scored as far worse than a missed one, and
the recommended cut is the most conservative one that still catches something.

Point estimates are not a ranking, so every pair's outcome is kept and the separation is
reported with a bootstrap interval rather than as a single number.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def load(paths: list[Path]) -> tuple[list[dict], list[dict], dict, dict]:
    """Merge the shards, and carry their provenance rather than this machine's.

    The numbers were produced on the measurement host; this analysis is a pure
    derivation and may run anywhere. Stamping the laptop that reduced the data would
    name the wrong machine. Every shard's `argv` is kept, because a result that records
    the script but not the arguments it was given is not reproducible.
    """
    pairs, meetings, config = [], [], {}
    prov: dict = {}
    argvs: list[str] = []
    for p in sorted(paths):
        d = json.loads(p.read_text(encoding="utf-8"))
        pairs.extend(d["pairs"])
        meetings.extend(d["meetings"])
        config = config or d.get("config", {})
        shard_prov = d.get("provenance") or {}
        prov = prov or dict(shard_prov)
        if shard_prov.get("argv"):
            argvs.append(shard_prov["argv"])
    if prov:
        prov["argv"] = f"{len(argvs)} shards, analysed by analyze_centroid.py"
        prov["shard_argv"] = argvs
    return pairs, meetings, config, prov


def sweep(pairs: list[dict]) -> list[dict]:
    same = np.array([p["cosine"] for p in pairs if p["same_true_speaker"]])
    diff = np.array([p["cosine"] for p in pairs if not p["same_true_speaker"]])
    rows = []
    for t in np.round(np.arange(0.30, 1.001, 0.02), 2):
        tp = int((same >= t).sum())          # correctly merged a split speaker
        fn = int((same < t).sum())           # left a split speaker split
        fp = int((diff >= t).sum())          # MERGED TWO REAL PEOPLE -- unrecoverable
        tn = int((diff < t).sum())
        rows.append({"threshold": float(t), "merged_splits": tp, "missed_splits": fn,
                     "wrong_merges": fp, "left_alone": tn,
                     "recall": round(tp / len(same), 3) if len(same) else None,
                     "precision": round(tp / (tp + fp), 3) if (tp + fp) else None})
    return rows


def bootstrap_gap(pairs: list[dict], n: int = 5000, seed: int = 0) -> dict:
    """Interval on (min same-speaker cosine - max different-speaker cosine).

    Positive means the two populations are separable by *some* threshold; the interval says
    whether that is a property of the data or of these particular meetings.
    """
    rng = np.random.default_rng(seed)
    same = np.array([p["cosine"] for p in pairs if p["same_true_speaker"]])
    diff = np.array([p["cosine"] for p in pairs if not p["same_true_speaker"]])
    if len(same) == 0 or len(diff) == 0:
        return {"gap": None, "note": "one population is empty; no separation to estimate"}
    gaps = []
    for _ in range(n):
        s = rng.choice(same, len(same), replace=True)
        d = rng.choice(diff, len(diff), replace=True)
        gaps.append(s.min() - d.max())
    lo, hi = np.percentile(gaps, [2.5, 97.5])
    return {"gap": round(float(same.min() - diff.max()), 4),
            "ci95": [round(float(lo), 4), round(float(hi), 4)],
            "n_same": int(len(same)), "n_diff": int(len(diff)),
            "same_min": round(float(same.min()), 4), "same_max": round(float(same.max()), 4),
            "diff_min": round(float(diff.min()), 4), "diff_max": round(float(diff.max()), 4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("shards", nargs="+", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()

    pairs, meetings, config, prov = load(a.shards)
    rows = sweep(pairs)
    gap = bootstrap_gap(pairs)

    over = [m for m in meetings if m["over_count"] > 0]
    print(f"meetings: {len(meetings)}  over-counting: {len(over)}  "
          f"pairs: {len(pairs)}  split pairs: {gap.get('n_same')}")
    print(f"same-speaker cosine  min={gap.get('same_min')} max={gap.get('same_max')}")
    print(f"diff-speaker cosine  min={gap.get('diff_min')} max={gap.get('diff_max')}")
    print(f"separation gap = {gap.get('gap')}  95% CI {gap.get('ci95')}")
    print("\nthreshold  merged_splits  missed  WRONG_MERGES  precision  recall")
    for r in rows:
        if r["threshold"] % 0.1 < 1e-9 or r["wrong_merges"] == 0:
            print(f"  {r['threshold']:.2f}      {r['merged_splits']:>3}"
                  f"          {r['missed_splits']:>3}       {r['wrong_merges']:>3}"
                  f"        {r['precision']}     {r['recall']}")

    safe = [r for r in rows if r["wrong_merges"] == 0 and r["merged_splits"] > 0]
    if safe:
        best = min(safe, key=lambda r: r["threshold"])
        print(f"\nlowest threshold with ZERO wrong merges: {best['threshold']} "
              f"-> repairs {best['merged_splits']}/{best['merged_splits']+best['missed_splits']} splits")
    else:
        print("\nNo threshold repairs any split without merging two real people. "
              "A centroid rule does not work on this data -- report that, do not tune it.")

    if a.out:
        a.out.write_text(json.dumps(
            {"provenance": prov, "config": config, "separation": gap, "sweep": rows,
             "meetings": meetings, "pairs": pairs}, indent=2), encoding="utf-8")
        print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
