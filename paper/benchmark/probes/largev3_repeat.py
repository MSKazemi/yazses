"""How unstable is `large-v3`, and is the instability all in the insertions?

Two full runs of the `test-other` engine matrix on one idle box, half an hour apart,
agreed to the last decimal on six of eight engines and disagreed on `large-v3` by
**2.83 points** (4.86 % then 7.69 %). That is an order of magnitude larger than the
0.75-point spread the same model shows on `test-clean`, and it is large enough that two
published conclusions rested on which run happened to be quoted.

The second run's breakdown says where the errors are: 87 substitutions, 15 deletions
and **184 insertions**. The substitution count is the same 87 the model scores on
`test-clean`, so its *recognition* did not move at all -- everything that moved was text
it added that nobody said. That matches the temperature-fallback mechanism already
documented for `tiny.en`: when the first-choice decode fails faster-whisper's
compression-ratio and log-probability checks, it re-decodes by **sampling**, and a
sampled rescue is a different sentence every time.

What is missing is the first run's breakdown -- that artifact was overwritten before
anyone thought to ask -- so "the instability is entirely in the insertions" is currently
an inference from one run plus a mechanism. This measures it directly: the same model,
the same 200 utterances, N times, recording WER **and the error breakdown** each time.

Writes `probes/largev3-instability-<split>.json`. Deliberately not a `bench_*.py`: it answers a
question about one model on one split, and `bench_wer.py` already owns the matrix -- and
would overwrite `wer-test-other.json` if pointed at a single engine.

    python paper/benchmark/probes/largev3_repeat.py 3 test-other
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))

import bench_wer  # noqa: E402
from _common import RESULTS_DIR, provenance, write_result  # noqa: E402



def summarise(runs: list[dict]) -> dict:
    """Spread of each error class across the repeats.

    **Deletions are summarised alongside substitutions and insertions on purpose.**
    The claim this probe tests is not "large-v3 is noisy" but "large-v3's *recognition*
    is deterministic and only its hallucination is not", and that claim is false unless
    *both* non-insertion classes hold still. Summarising insertions and substitutions
    while leaving deletions to be dug out of the per-run rows would leave the reader
    checking two thirds of the claim and quoting all of it.

    Pure over `runs`, so it can be re-derived from a committed artifact rather than
    re-measured -- which is the point: the numbers cost an hour of decode each.
    """
    out: dict[str, float | int] = {}
    wers = [r["wer"] for r in runs]
    out["wer_min"] = min(wers)
    out["wer_max"] = max(wers)
    out["wer_spread"] = round(max(wers) - min(wers), 2)
    for key, field in (("insertions", "insertions"),
                       ("substitutions", "substitutions"),
                       ("deletions", "deletions")):
        vals = [r[field] for r in runs]
        out[f"{key}_min"] = min(vals)
        out[f"{key}_max"] = max(vals)
        out[f"{key}_spread"] = max(vals) - min(vals)
    out["non_insertion_errors_constant"] = (
        out["substitutions_spread"] == 0 and out["deletions_spread"] == 0
    )
    return out


def main() -> None:
    repeats = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    split = sys.argv[2] if len(sys.argv) > 2 else "test-other"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    specs = bench_wer._parse_specs("faster-whisper:large-v3")

    runs = []
    for i in range(repeats):
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        out = bench_wer.run(n, specs, 0, split)
        row = dict(out["models"]["large-v3"])
        row["run"] = i
        row["started_utc"] = stamp
        runs.append(row)
        print(f"[repeat] run {i}: WER {row['wer']}%  sub {row['substitutions']}  "
              f"del {row['deletions']}  ins {row['insertions']}", flush=True)

    prov = provenance(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    result = {
        "config": {"model": "large-v3", "split": split, "n_utterances": n, "repeats": repeats},
        "runs": runs,
        "summary": summarise(runs),
    }
    # Written in the same envelope every other file under `results/probes/` carries, so
    # `make_results_index.py` can name what produced it. A raw result dropped into that
    # directory would be indistinguishable from a harness output that lost its way.
    payload = {
        "provenance": prov,
        "probe": {
            "measured": (
                "run-to-run spread of large-v3 WER and its error breakdown on "
                f"LibriSpeech {split}, {repeats} full repeats"
            ),
            "produced_by": "probes/largev3_repeat.py",
            "host": f"{prov.get('cpu_model', '?')} ({prov.get('logical_cpus', '?')} vCPU), {prov.get('os', '?')}",
            "run_finished_utc": prov.get("timestamp", ""),
        },
        "result": result,
    }
    # The split is in the *name*, not only in the config block. Writing every split to
    # one filename is how the first `test-other` engine matrix stopped existing: the
    # second run overwrote it, and the two disagreed by 2.83 points. `write_result`
    # archives a displaced file now, but a result that has to be recovered from
    # `history/` to be read is not an archived measurement.
    (RESULTS_DIR / "probes").mkdir(parents=True, exist_ok=True)
    write_result(f"probes/largev3-instability-{split}", payload)
    s = result["summary"]
    print(f"[repeat] WER {s['wer_min']}-{s['wer_max']} (spread {s['wer_spread']}), "
          f"insertions {s['insertions_min']}-{s['insertions_max']}, "
          f"substitutions {s['substitutions_min']}-{s['substitutions_max']}, "
          f"deletions {s['deletions_min']}-{s['deletions_max']}, "
          f"non-insertion errors constant: {s['non_insertion_errors_constant']}")


if __name__ == "__main__":
    main()
