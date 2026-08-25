"""Score the implausible-attribution guard from a saved diarizer dump.

`bench_plausibility.py` re-runs the diarizer to get per-label speech durations. That
is the expensive half and it is also the only half that needs a GPU-class box, a
corpus and the `diarization` extra. Everything after it is arithmetic over a dict.

This scores that arithmetic from a dump of `{id: {true_speakers, totals}}` --
exactly what the AMI @ 1.2 sweep left on the measurement VM and never analysed. It
imports the shipped rule rather than restating it, so a change to `FRAGMENT_RATIO`,
`MIN_LABELS` or `fragment_threshold` moves this the same way it moves the product;
a reimplementation here would score a rule the user never runs.

Output is the schema `bench_plausibility.py` writes, so the AMI cell drops straight
into the same table as the VoxConverse ones.

    python paper/benchmark/probes/score_plausibility_from_dump.py \
        <dump.json> <cluster_threshold> <corpus_source> [out-name]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _fires(totals: dict[str, float], threshold: float) -> bool:
    from yazses.recimport.plausibility import FRAGMENT_RATIO, MIN_LABELS

    if len(totals) < MIN_LABELS:
        return False
    fragments = [s for s in totals.values() if s < threshold]
    return len(fragments) / len(totals) >= FRAGMENT_RATIO


def run(dump: dict, cluster_threshold: float, corpus_source: str) -> dict:
    from yazses.recimport.plausibility import FRAGMENT_SECONDS, fragment_threshold

    rows = []
    for mid, meta in sorted(dump.items()):
        totals = {k: float(v) for k, v in meta["totals"].items()}
        speech = sum(totals.values())
        scaled = fragment_threshold(speech)
        rows.append({
            "id": mid,
            "true_speakers": meta["true_speakers"],
            "labels_found": len(totals),
            "total_speech_seconds": round(speech, 1),
            "over_split": len(totals) > meta["true_speakers"],
            "scaled_threshold_seconds": round(scaled, 1),
            "fires_flat": _fires(totals, FRAGMENT_SECONDS),
            "fires_scaled": _fires(totals, scaled),
            "label_seconds": {k: round(v, 1) for k, v in sorted(totals.items())},
        })

    def tally(key: str) -> dict:
        fired = [r for r in rows if r[key]]
        return {
            "fires": len(fired),
            "correct": sum(1 for r in fired if r["over_split"]),
            "false_alarms": sum(1 for r in fired if not r["over_split"]),
        }

    return {
        "config": {
            "corpus": "ami16_corpus",
            "corpus_source": corpus_source,
            "cluster_threshold": cluster_threshold,
            "flat_fragment_seconds": FRAGMENT_SECONDS,
            "scored_from": "saved diarizer dump; the diarizer was not re-run",
        },
        "summary": {
            "recordings": len(rows),
            "genuinely_over_split": sum(1 for r in rows if r["over_split"]),
            "flat": tally("fires_flat"),
            "scaled": tally("fires_scaled"),
            "verdicts_agree": sum(1 for r in rows if r["fires_flat"] == r["fires_scaled"]),
        },
        "rows": rows,
    }


if __name__ == "__main__":
    from _common import provenance, write_result

    if len(sys.argv) < 4:
        raise SystemExit(__doc__)
    dump = json.loads(Path(sys.argv[1]).read_text())
    out = run(dump, float(sys.argv[2]), sys.argv[3])
    out["provenance"] = provenance(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    out["provenance"]["argv"] = " ".join(
        ["paper/benchmark/probes/score_plausibility_from_dump.py", *sys.argv[1:]]
    )
    out["probe"] = {
        "measured": (
            "how often the implausible-attribution guard fires on real AMI meetings and "
            "how often it is right, at the shipped clustering threshold, scored from the "
            "saved diarizer dump rather than by re-running diarization"
        ),
        "produced_by": "probes/score_plausibility_from_dump.py",
    }
    name = sys.argv[4] if len(sys.argv) > 4 else f"plausibility-ami16-{sys.argv[2]}"
    write_result(name, out)
