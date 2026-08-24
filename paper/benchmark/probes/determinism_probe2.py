"""Does seeding CTranslate2 make the decode reproducible?

determinism_probe.py showed 1 of 200 utterances decoding differently between two
passes in ONE process -- same weights, same threads, same audio. faster-whisper's
default `temperature=[0.0, 0.2, ..., 1.0]` retries a segment that fails the
compression-ratio or log-prob threshold, and a retry above 0.0 SAMPLES. CTranslate2's
sampler draws from a global RNG that nothing seeds, so the retry is a coin flip.

This runs the same two passes with `ctranslate2.set_random_seed(seed)` called before
each pass. If the difference disappears the mechanism is confirmed and the fix is one
line in the benchmark harness; if it survives, the cause is elsewhere and the finding
has to be published as unexplained.
"""
import sys, time
from pathlib import Path

sys.path.insert(0, "$HOME/yazses/paper/benchmark")

import ctranslate2                                          # noqa: E402
from _common import librispeech_subset, load_audio          # noqa: E402
from yazses.stt.factory import build_engine                 # noqa: E402
from yazses.config import SttConfig                         # noqa: E402

model = sys.argv[1]
n = int(sys.argv[2])
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 20260823

subset = librispeech_subset(n)
engine = build_engine(SttConfig(engine="faster-whisper", model=model))
print(f"[det2] {model}: {len(subset)} utts, seed={seed}, ct2={ctranslate2.__version__}", flush=True)

runs = []
for p in range(2):
    ctranslate2.set_random_seed(seed)
    t0 = time.time()
    runs.append([engine.transcribe(load_audio(path)) for _, path, _, _ in subset])
    print(f"[det2] seeded pass {p}: {time.time()-t0:.1f}s", flush=True)

diff = [i for i in range(len(runs[0])) if runs[0][i] != runs[1][i]]
print(f"[det2] SEEDED: {len(diff)}/{len(subset)} utterances differ", flush=True)
for i in diff[:3]:
    print(f"    {subset[i][0]}\n      a: {runs[0][i][:140]}\n      b: {runs[1][i][:140]}", flush=True)

# Control: an unseeded third pass against the first seeded one. If seeding is what
# fixed it, this one must differ again -- otherwise the two seeded passes agreeing
# proves nothing (the run may simply have been lucky).
third = [engine.transcribe(load_audio(path)) for _, path, _, _ in subset]
ctrl = [i for i in range(len(runs[0])) if runs[0][i] != third[i]]
print(f"[det2] CONTROL (unseeded pass vs seeded): {len(ctrl)}/{len(subset)} differ", flush=True)
print("DET2_DONE", flush=True)
