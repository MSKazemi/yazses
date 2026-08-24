"""How often does the implausible-attribution warning fire, and how often is it right?

`recimport/plausibility.py` warns when a diarization result looks like fragments rather
than people. A warning is only worth having if it is rare and correct, and neither had
been measured -- the guard shipped, then fired on nearly half of VoxConverse and
misdiagnosed three of those firings, which is how the constant behind it was found to be
a meeting-length number applied to three-minute clips.

This scores a diarized corpus (`<id>.wav` + `manifest.json`, the same layout
`bench_diarization.py` reads) at one clustering threshold and reports, per recording:
the true speaker count, the label count the diarizer produced, and whether each rule
fires. A firing is **correct** when the result really is over-split -- more labels than
speakers -- and a **false alarm** otherwise, because the sentence the user is shown says
one person's speech was split apart.

Both rules are scored side by side on purpose. The flat one is what every number in
`docs/benchmarks.md` was taken at, so an argument that the new rule leaves those numbers
alone is checkable here rather than taken on trust.
"""
from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import bench_diarization as bd


def _fires(totals: dict[str, float], threshold: float) -> bool:
    from yazses.recimport.plausibility import FRAGMENT_RATIO, MIN_LABELS

    if len(totals) < MIN_LABELS:
        return False
    fragments = [s for s in totals.values() if s < threshold]
    return len(fragments) / len(totals) >= FRAGMENT_RATIO


def run(corpus: Path, cluster_threshold: float) -> dict:
    from yazses.config import RecimportConfig
    from yazses.recimport.diarizer import SherpaDiarizer
    from yazses.recimport.plausibility import FRAGMENT_SECONDS, fragment_threshold

    manifest = bd._read_manifest(corpus)
    diarizer = SherpaDiarizer(replace(RecimportConfig(), cluster_threshold=cluster_threshold))

    rows = []
    for meta in manifest["meetings"]:
        mid = meta["id"]
        audio = bd._load_wav(corpus / f"{mid}.wav")
        totals: dict[str, float] = {}
        for turn in diarizer.diarize(audio, 16000):
            if turn.end > turn.start:
                totals[turn.speaker] = totals.get(turn.speaker, 0.0) + (turn.end - turn.start)

        speech = sum(totals.values())
        scaled = fragment_threshold(speech)
        over_split = len(totals) > meta["n_speakers"]
        row = {
            "id": mid,
            "true_speakers": meta["n_speakers"],
            "labels_found": len(totals),
            "total_speech_seconds": round(speech, 1),
            "over_split": over_split,
            "scaled_threshold_seconds": round(scaled, 1),
            "fires_flat": _fires(totals, FRAGMENT_SECONDS),
            "fires_scaled": _fires(totals, scaled),
            "label_seconds": {k: round(v, 1) for k, v in sorted(totals.items())},
        }
        rows.append(row)
        print(f"[guard] {mid}: {len(totals)} labels (true {meta['n_speakers']})  "
              f"flat={row['fires_flat']} scaled={row['fires_scaled']}", flush=True)

    def tally(key: str) -> dict:
        fired = [r for r in rows if r[key]]
        return {
            "fires": len(fired),
            "correct": sum(1 for r in fired if r["over_split"]),
            "false_alarms": sum(1 for r in fired if not r["over_split"]),
        }

    summary = {
        "recordings": len(rows),
        "genuinely_over_split": sum(1 for r in rows if r["over_split"]),
        "flat": tally("fires_flat"),
        "scaled": tally("fires_scaled"),
        "verdicts_agree": sum(1 for r in rows if r["fires_flat"] == r["fires_scaled"]),
    }
    print(f"[guard] {summary}", flush=True)
    return {
        "config": {
            "corpus": corpus.name,
            "corpus_source": manifest.get("source", "unknown"),
            "cluster_threshold": cluster_threshold,
            "flat_fragment_seconds": FRAGMENT_SECONDS,
        },
        "summary": summary,
        "rows": rows,
    }


if __name__ == "__main__":
    import sys

    from _common import provenance, write_result

    if len(sys.argv) < 3:
        raise SystemExit("usage: bench_plausibility.py <corpus-dir> <cluster_threshold>")
    corpus = Path(sys.argv[1])
    threshold = float(sys.argv[2])
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = run(corpus, threshold)
    out["provenance"] = provenance(stamp)
    name = sys.argv[3] if len(sys.argv) > 3 else f"plausibility-{corpus.name}-{threshold}"
    write_result(name, out)
