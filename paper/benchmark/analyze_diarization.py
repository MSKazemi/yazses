"""Is the difference between two diarization runs an effect, or two loud recordings?

`bench_diarization.py` reports a corpus DER per run -- 26.71 % free, 29.42 % capped at
four speakers. Reading those two numbers as a ranking is the mistake this exists to
prevent, and it is a sharper mistake here than in a WER table, because the corpus is
**sixteen recordings**, not two hundred utterances. A single meeting is 6 % of the
sample and can move the mean by two points on its own.

The runs are **paired**: the same sixteen AMI meetings, the same segmentation, the same
threshold, one clustering constraint apart. So the comparison to make is per meeting,
and two estimators are reported because they answer different questions:

* **Exact sign test** over the meetings that changed. Distribution-free, and the right
  first question at n=16: did more recordings get better than got worse? A mean that
  moves while the sign test says nothing is a mean being carried by its tail.
* **Paired bootstrap** over meetings, resampling the sixteen *recordings* with
  replacement and recomputing both arms from the same resample. This is what puts an
  interval on the corpus figure, and it is done for the unweighted mean and for the
  time-weighted (NIST `md-eval`) aggregate separately, because a bootstrap of a
  time-weighted statistic and of a mean are not the same interval.

The per-meeting deltas are printed in full and stored, not summarised away. "Capping
made seven better and seven worse, with a 44-point swing on one recording" is the
finding; "+2.71 points" is that finding with the interesting part removed.

    uv run --group benchmark python paper/benchmark/analyze_diarization.py \
        paper/results/diarization-ami16_corpus-der.json \
        paper/results/diarization-ami16_corpus-maxspk4.json
"""
from __future__ import annotations

import json
import sys
from math import comb
from pathlib import Path

import numpy as np

#: Resamples for the paired bootstrap. 10 000 is enough for a 95 % interval to be
#: stable to about a hundredth of a point at this sample size, and the whole thing is
#: pure arithmetic over sixteen stored rows, so there is no reason to economise.
N_BOOT = 10_000

#: Fixed seed. A confidence interval that moves when the script is re-run cannot be
#: quoted, and a published number has to be re-derivable from the committed artifact.
SEED = 20260824

ALPHA = 0.05


def exact_sign_test(better: int, worse: int) -> float:
    """Two-sided exact binomial p-value for `better` of `better + worse` fair trials.

    Ties are excluded rather than split. A recording where the two runs scored
    identically -- which happens when the free clustering already found exactly the
    permitted number of speakers, so the constraint did nothing -- is not weak evidence
    either way; it is the constraint not having applied. Returns 1.0 when nothing
    changed, because 0/0 is not a test result.
    """
    n = better + worse
    if n == 0:
        return 1.0
    k = min(better, worse)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / (2 ** n))


def _rows(path: Path) -> dict[str, dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {m["id"]: m for m in data["meetings"]}, data


def _weighted(rows: list[dict], key: str) -> float:
    """Time-weighted DER over *rows*: total error time over total scored time.

    Recomputed here from the per-meeting percentages and their `scored_seconds` rather
    than read from the summary, so a bootstrap resample -- which the summary knows
    nothing about -- is aggregated exactly the way the published figure is.
    """
    num = sum(r[key]["der"] / 100.0 * r[key]["scored_seconds"] for r in rows)
    den = sum(r[key]["scored_seconds"] for r in rows)
    return round(num / den * 100, 3) if den else 0.0


def compare(a_path: Path, b_path: Path, key: str = "strict") -> dict:
    a_rows, a_data = _rows(a_path)
    b_rows, b_data = _rows(b_path)
    ids = sorted(set(a_rows) & set(b_rows))
    if sorted(a_rows) != sorted(b_rows):
        raise ValueError(
            "the two runs do not cover the same recordings; a paired test over "
            f"the intersection would silently answer a different question "
            f"({len(a_rows)} vs {len(b_rows)}, {len(ids)} shared)"
        )

    deltas = [round(b_rows[i][key]["der"] - a_rows[i][key]["der"], 2) for i in ids]
    better = sum(1 for d in deltas if d < 0)
    worse = sum(1 for d in deltas if d > 0)
    ties = sum(1 for d in deltas if d == 0)

    rng = np.random.default_rng(SEED)
    n = len(ids)
    idx = rng.integers(0, n, size=(N_BOOT, n))
    mean_d, weighted_d = [], []
    a_list = [a_rows[i] for i in ids]
    b_list = [b_rows[i] for i in ids]
    for row in idx:
        ra = [a_list[j] for j in row]
        rb = [b_list[j] for j in row]
        mean_d.append(
            sum(x[key]["der"] for x in rb) / n - sum(x[key]["der"] for x in ra) / n
        )
        weighted_d.append(_weighted(rb, key) - _weighted(ra, key))

    def ci(v):
        return [round(float(np.percentile(v, 2.5)), 2),
                round(float(np.percentile(v, 97.5)), 2)]

    return {
        "a": {"path": a_path.name, "argv": a_data["provenance"].get("argv", "")},
        "b": {"path": b_path.name, "argv": b_data["provenance"].get("argv", "")},
        "collar": key,
        "n_recordings": n,
        "per_meeting_delta": dict(zip(ids, deltas)),
        "b_better_on": better,
        "b_worse_on": worse,
        "unchanged_on": ties,
        "sign_test_p": round(exact_sign_test(better, worse), 4),
        "delta_min": min(deltas),
        "delta_max": max(deltas),
        "mean_delta": round(sum(deltas) / n, 2),
        "mean_delta_ci95": ci(mean_d),
        "time_weighted_delta": round(_weighted(b_list, key) - _weighted(a_list, key), 2),
        "time_weighted_delta_ci95": ci(weighted_d),
        "n_bootstrap": N_BOOT,
        "seed": SEED,
        "verdict": (
            "b is worse" if exact_sign_test(better, worse) < ALPHA and worse > better
            else "b is better" if exact_sign_test(better, worse) < ALPHA
            else "no difference the sample can resolve"
        ),
    }


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    a, b = Path(sys.argv[1]), Path(sys.argv[2])
    out = {k: compare(a, b, k) for k in ("strict", "collar250ms")}
    print(json.dumps(out, indent=2))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _common import write_result

    name = f"{b.stem}-vs-{a.stem.split('-')[-1]}-significance"
    print("wrote", write_result(name, {"result": out}))


if __name__ == "__main__":
    main()
