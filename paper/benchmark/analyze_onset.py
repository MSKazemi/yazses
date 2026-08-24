"""Is a difference between two cells of the onset grid an effect, or is it noise?

`bench_onset.py` reports a first-word count per cell -- 186 of 200 here, 182 there.
Reading a table like that as a ranking is the mistake this script exists to prevent.
At n=200 the 95 % confidence interval on a single proportion is about +/- 9
utterances wide, so almost every pair in the grid overlaps and an unpaired reading
says nothing at all.

But the cells are not independent samples. Every cell decodes the *same 200
utterances*; only the lead-in changes. That makes the comparison **paired**, and a
paired comparison throws away the utterances both conditions agreed on -- which is
almost all of them -- and asks only about the handful that changed verdict. That is
McNemar's test, and it is far more sensitive than comparing two counts:

    b = utterances A got right and B got wrong
    c = utterances A got wrong and B got right

Under the null "the lead-in changes nothing", each discordant utterance is a coin
flip, so b ~ Binomial(b + c, 0.5). The exact two-sided binomial p-value is computed
here rather than the chi-square approximation, because b + c is routinely under 10
in this grid and the approximation is not valid there.

This needs `first_word_hits` -- the per-utterance outcome string that `bench_onset.py`
writes. A result produced before that field existed carries only the counts, and this
script says so and stops rather than falling back to an unpaired test that would
answer a different question with the same confident tone.

    uv run --group benchmark python paper/benchmark/analyze_onset.py paper/results/onset.json
"""
from __future__ import annotations

import json
import sys
from math import comb
from pathlib import Path

#: A difference is called only below this. Nothing here is corrected for multiplicity
#: on purpose -- the comparisons reported are the ones named in the documentation, and
#: `_report` prints how many were run so a reader can apply their own correction.
ALPHA = 0.05


def exact_mcnemar(b: int, c: int) -> float:
    """Two-sided exact binomial p-value for `b` successes in `b + c` fair trials.

    Returns 1.0 when there are no discordant pairs: two conditions that never
    disagreed on any utterance are not evidence of a difference, and 0/0 is not a
    test result.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def _hits(row: dict) -> list[bool] | None:
    s = row.get("first_word_hits")
    if not isinstance(s, str) or not s:
        return None
    return [ch == "1" for ch in s]


def compare(a: dict, b: dict) -> dict:
    """McNemar over two grid cells. Raises if either lacks per-utterance outcomes."""
    ha, hb = _hits(a), _hits(b)
    if ha is None or hb is None:
        raise ValueError("a cell carries no `first_word_hits`")
    if len(ha) != len(hb):
        raise ValueError(f"cells cover different utterance counts: {len(ha)} vs {len(hb)}")
    only_a = sum(1 for x, y in zip(ha, hb) if x and not y)
    only_b = sum(1 for x, y in zip(ha, hb) if y and not x)
    return {
        "a": f"{a['arm']} cut={a['cut_ms']} lead={a['lead_ms']}",
        "b": f"{b['arm']} cut={b['cut_ms']} lead={b['lead_ms']}",
        "a_ok": sum(ha),
        "b_ok": sum(hb),
        "n": len(ha),
        "only_a": only_a,
        "only_b": only_b,
        "discordant": only_a + only_b,
        "p": round(exact_mcnemar(only_a, only_b), 4),
    }


def _key(row: dict) -> tuple:
    return (row.get("run", 0), row["arm"], row["cut_ms"], row["lead_ms"])


def analyse(path: Path) -> dict:
    """Every within-row comparison against that row's lead=0 baseline.

    Only cells from the same run and the same cut are compared. Comparing across
    runs would measure decoder repeatability, and comparing across cuts would compare
    two different pieces of audio -- neither is the question the setting poses, which
    is always "does prepending silence to *this* clip help?".
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data["rows"]
    missing = [r for r in rows if _hits(r) is None]
    if missing:
        raise SystemExit(
            f"{path} has {len(missing)} of {len(rows)} cells with no `first_word_hits`.\n"
            "That field is the per-utterance outcome and it is what makes the test\n"
            "paired. This result predates it; re-run bench_onset.py to get a result\n"
            "this script can read. An unpaired test on the counts alone would answer\n"
            "a different question and is deliberately not offered as a fallback."
        )

    by_group: dict[tuple, list[dict]] = {}
    for row in rows:
        by_group.setdefault((row.get("run", 0), row["arm"], row["cut_ms"]), []).append(row)

    out = []
    for group, cells in sorted(by_group.items()):
        cells.sort(key=lambda r: r["lead_ms"])
        base = next((c for c in cells if c["lead_ms"] == 0), None)
        if base is None:
            continue
        for cell in cells:
            if cell["lead_ms"] == 0:
                continue
            out.append(compare(base, cell))
    distinct = _collapse_replicates(out)
    return {
        "source": path.name,
        "provenance": data.get("provenance"),
        "alpha": ALPHA,
        "comparisons": out,
        "n_comparisons": len(out),
        "n_significant": sum(1 for c in out if c["p"] < ALPHA),
        "distinct": distinct,
        "n_distinct": len(distinct),
        "n_distinct_significant": sum(1 for d in distinct if d["significant_runs"] == d["runs"]),
        "bonferroni_alpha": round(ALPHA / max(len(distinct), 1), 5),
    }


def _collapse_replicates(comparisons: list[dict]) -> list[dict]:
    """Group the per-run comparisons by the condition they test.

    The grid is run end to end twice, so every comparison appears once per run --
    against the *same 200 utterances*, decoded by a model that is deterministic on
    identical input. Those are replicates, not independent tests. Counting them as
    separate tests inflates the multiplicity correction (Bonferroni over 32 where 16
    conditions were asked) and, worse, double-counts a single lucky cell as two
    findings. The replication is real information and is kept -- as `runs` and
    `significant_runs`, so a reader can see a p-value that held up twice -- but the
    correction is applied over the conditions actually asked.
    """
    groups: dict[str, list[dict]] = {}
    for c in comparisons:
        groups.setdefault(c["b"], []).append(c)
    out = []
    for label, reps in sorted(groups.items()):
        ps = [r["p"] for r in reps]
        out.append({
            "comparison": label,
            "baseline": reps[0]["a"],
            "runs": len(reps),
            "p_per_run": ps,
            "p_max": max(ps),
            "significant_runs": sum(1 for p in ps if p < ALPHA),
            # Direction, not just magnitude: `only_a` is the baseline winning. A
            # condition whose sign flips between replicates is noise no p-value
            # should be allowed to dress up.
            "baseline_wins_per_run": [r["only_a"] for r in reps],
            "cell_wins_per_run": [r["only_b"] for r in reps],
            "direction_consistent": len({r["only_a"] > r["only_b"] for r in reps}) == 1,
        })
    return out


def _report(res: dict) -> None:
    print(f"McNemar, paired by utterance, against lead=0 within each arm and cut")
    print(f"source: {res['source']}   comparisons: {res['n_comparisons']}\n")
    print(f"{'baseline vs cell':<52} {'base':>5} {'cell':>5} {'b':>3} {'c':>3} {'p':>8}")
    for c in res["comparisons"]:
        star = " *" if c["p"] < res["alpha"] else ""
        print(
            f"{c['b']:<52} {c['a_ok']:>5} {c['b_ok']:>5} "
            f"{c['only_a']:>3} {c['only_b']:>3} {c['p']:>8.4f}{star}"
        )
    n_d = res["n_distinct"]
    print(
        f"\n{res['n_significant']} of {res['n_comparisons']} rows reach p < {res['alpha']} "
        f"uncorrected, but those rows are {n_d} distinct comparisons measured "
        f"{res['n_comparisons'] // max(n_d, 1)}x each on the same utterances -- replicates, "
        f"not independent tests. Correcting over the {n_d} conditions actually asked, "
        f"a Bonferroni reader should use p < {res['bonferroni_alpha']:.5f}; "
        f"{sum(1 for d in res['distinct'] if d['p_max'] < res['bonferroni_alpha'])} survive it."
    )
    held = [d for d in res["distinct"] if d["significant_runs"] == d["runs"]]
    if held:
        print("\nUncorrected p < %.2f in *every* replicate:" % res["alpha"])
        for d in held:
            arrow = "lead-in HURTS" if d["baseline_wins_per_run"][0] > d["cell_wins_per_run"][0] else "lead-in helps"
            print(f"  {d['comparison']:<44} p={d['p_per_run']}  {arrow}")
    flaky = [d for d in res["distinct"] if not d["direction_consistent"]]
    if flaky:
        print(f"\n{len(flaky)} comparison(s) changed sign between replicates: "
              + ", ".join(d["comparison"] for d in flaky))


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "results" / "onset.json"
    res = analyse(path)
    _report(res)
    out = path.with_name(f"{path.stem}-significance.json")
    out.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
