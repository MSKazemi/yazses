"""Per-label speech totals for one meeting at several cluster thresholds.

Writes JSON only -- the plausibility verdict is computed off-box against the shipped
module, which this checkout predates.
"""
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, "paper/benchmark")
import bench_diarization as bd  # noqa: E402

from yazses.config import RecimportConfig  # noqa: E402
from yazses.recimport.diarizer import SherpaDiarizer  # noqa: E402

corpus = Path(sys.argv[1])
mid = sys.argv[2]
out = {}
audio = bd._load_wav(corpus / f"{mid}.wav")
for thr in (0.5, 0.9, 1.0, 1.1, 1.2, 1.3):
    diar = SherpaDiarizer(replace(RecimportConfig(), cluster_threshold=thr))
    totals = {}
    for t in diar.diarize(audio, 16000):
        if t.end > t.start:
            totals[t.speaker] = totals.get(t.speaker, 0.0) + (t.end - t.start)
    out[str(thr)] = totals
    print(f"[guard] thr={thr}: {len(totals)} labels", flush=True)
Path(sys.argv[3]).write_text(json.dumps(out, indent=1))
print("GUARD_PROBE_DONE", flush=True)
