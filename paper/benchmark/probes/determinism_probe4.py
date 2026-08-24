"""One utterance in two hundred flips. Which one, how often, and why?

determinism_probe2.py showed that seeding CTranslate2 changes nothing: the same single
utterance (7176-88083-0001) decodes either to the full sentence or to the bare word
"The". A truncation, not a re-wording -- so the suspect is faster-whisper's fallback
loop rather than arithmetic noise. This decodes that one clip N times and reports the
distribution, then repeats it with the fallback disabled (`temperature=0.0`) and with
`condition_on_previous_text=False`, to name the mechanism instead of guessing at it.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "$HOME/yazses/paper/benchmark")

from _common import librispeech_subset, load_audio        # noqa: E402
from faster_whisper import WhisperModel                   # noqa: E402

utt_id = sys.argv[1] if len(sys.argv) > 1 else "7176-88083-0001"
MODEL = sys.argv[3] if len(sys.argv) > 3 else "tiny.en"
reps = int(sys.argv[2]) if len(sys.argv) > 2 else 40

row = next(r for r in librispeech_subset(200) if r[0] == utt_id)
_, path, ref, dur = row
audio = load_audio(path)
print(f"[p3] model={MODEL} {utt_id}  {dur:.2f}s\n[p3] ref: {ref[:120]}", flush=True)

model = WhisperModel(MODEL, device="cpu", compute_type="int8")


def decode(**kw) -> str:
    segments, _ = model.transcribe(audio, **kw)
    return " ".join(s.text.strip() for s in segments).strip()


for label, kwargs in (
    ("defaults", {}),
    ("temperature=0 (no fallback)", {"temperature": 0.0}),
    ("no prev-text conditioning", {"condition_on_previous_text": False}),
    ("beam_size=1", {"beam_size": 1}),
):
    counts = Counter(decode(**kwargs) for _ in range(reps))
    print(f"\n[p3] {label}: {len(counts)} distinct output(s) in {reps} decodes", flush=True)
    for text, n in counts.most_common():
        print(f"      {n:3d}x  {text[:110]}", flush=True)
print("\nP3_DONE", flush=True)
