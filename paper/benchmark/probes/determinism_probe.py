"""Is a faster-whisper decode reproducible run-to-run on ONE box?

Two full runs of the same 200-utterance subset measured `large-v3` at 3.98% and then
3.41% WER on the same VM, same code, same data -- a 0.57-point move, larger than the
gap the docs claim over Parakeet. `tiny.en` moved too (4.93 / 4.95 / 5.18 / 5.25);
`base.en`, `small.en`, `medium.en` and Parakeet did not move at all.

This decodes the same subset TWICE inside ONE process, so the thread count, the ISA
dispatch and the loaded weights are held fixed by construction. Anything that differs
is decode-time non-determinism, not the machine.
"""
import sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "$HOME/yazses/paper/benchmark")

from _common import librispeech_subset, load_audio          # noqa: E402
from yazses.stt.factory import build_engine                 # noqa: E402
from yazses.config import SttConfig                         # noqa: E402

model = sys.argv[1]
n = int(sys.argv[2])
passes = int(sys.argv[3]) if len(sys.argv) > 3 else 2

subset = librispeech_subset(n)
print(f"[det] {model}: {len(subset)} utterances, {passes} passes", flush=True)

cfg = SttConfig(engine="faster-whisper", model=model)
engine = build_engine(cfg)
print(f"[det] engine={type(engine).__name__}", flush=True)

runs = []
for p in range(passes):
    t0 = time.time()
    hyps = []
    for i, (utt, path, ref, dur) in enumerate(subset):
        hyps.append(engine.transcribe(load_audio(path)))
    runs.append(hyps)
    print(f"[det] pass {p}: {time.time()-t0:.1f}s", flush=True)

base = runs[0]
for p in range(1, passes):
    diff = [i for i in range(len(base)) if base[i] != runs[p][i]]
    print(f"[det] pass 0 vs pass {p}: {len(diff)}/{len(base)} utterances differ", flush=True)
    for i in diff[:5]:
        print(f"    utt {subset[i][0]}", flush=True)
        print(f"      a: {base[i][:160]}", flush=True)
        print(f"      b: {runs[p][i][:160]}", flush=True)
print("DET_DONE", flush=True)
