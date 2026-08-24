"""Does the silence lead-in before decode recover the opening word?

`[accessibility] pre_speech_padding_ms` prepends synthetic silence to every burst
before it reaches the decoder. The reason written beside it was that faster-whisper
"drops/clips the first word when a clip starts abruptly mid-utterance". This measures
that claim.

Two arms, because they answer different questions:

* **intact** — the clip's leading room tone is trimmed away so speech starts at sample
  0, then the lead-in is swept. This asks whether the decoder needs a run-up. It must
  be trimmed first: LibriSpeech clips open with a beat of silence, which would supply
  the run-up for free and make every row agree.
* **clipped** — a further slice of *speech* is removed, simulating a hotkey caught
  after the voice has started. This is the case the setting exists for, and no
  prepended silence can put back what was never captured; the question is whether a
  clean onset boundary helps the decoder guess.

The headline metric is **first-word accuracy**, not WER. WER is the whole-utterance
number and mostly measures things this setting cannot touch; empirically it moves by
up to a full point between identical runs of the clipped arm while the first-word
counts reproduce exactly. `--repeat` runs the whole sweep more than once so that claim
is in the artifact rather than in a commit message.
"""
from __future__ import annotations

import time

import numpy as np

from _common import librispeech_subset, load_audio

SAMPLE_RATE = 16000
LEADS_MS = (0, 100, 300, 600, 1000)
CUTS_MS = (40, 120, 240)
#: A 10 ms frame whose peak clears this counts as speech. Chosen well above
#: LibriSpeech's noise floor and well below any voiced sample.
TRIM_PEAK = 0.01


def trim_leading_silence(audio: np.ndarray, frame: int = 160, thresh: float = TRIM_PEAK):
    """Drop everything before the first frame whose peak clears `thresh`."""
    for i in range(len(audio) // frame):
        if np.max(np.abs(audio[i * frame:(i + 1) * frame])) >= thresh:
            return audio[i * frame:]
    return audio


def _first_token(text: str) -> str:
    parts = text.split()
    return parts[0] if parts else ""


def run(n: int, repeat: int = 1, model: str = "base.en") -> dict:
    import jiwer
    from whisper_normalizer.english import EnglishTextNormalizer

    from yazses.config import SttConfig
    from yazses.stt.factory import build_engine

    normalize = EnglishTextNormalizer()

    subset = librispeech_subset(n, stratified=True, split="test-clean")
    raw = [(utt, load_audio(flac), ref) for utt, flac, ref, _ in subset]
    trimmed = [(utt, trim_leading_silence(a), ref) for utt, a, ref in raw]

    dropped = [len(a) - len(t) for (_, a, _), (_, t, _) in zip(raw, trimmed)]
    # An arm that trimmed nothing is the same experiment twice, and every row would
    # agree for a reason that has nothing to do with the setting under test.
    if not np.median(dropped) > 0:
        raise SystemExit("no clip had leading silence to trim -- the probe is inert")

    engine = build_engine(SttConfig(model=model, language="en", compute_type="int8"))

    def score(clips, lead_ms: int) -> dict:
        lead = np.zeros(int(lead_ms * SAMPLE_RATE / 1000), dtype=np.float32)
        refs, hyps = [], []
        t0 = time.monotonic()
        for _utt, audio, ref in clips:
            a = np.concatenate([lead, audio]) if lead.size else audio
            refs.append(normalize(ref))
            hyps.append(normalize(engine.transcribe(a)))
        pairs = [(r, h) for r, h in zip(refs, hyps) if r]
        hits = [_first_token(r) == _first_token(h) for r, h in pairs]
        return {
            "lead_ms": lead_ms,
            "wer_pct": round(jiwer.wer([r for r, _ in pairs], [h for _, h in pairs]) * 100, 2),
            "first_word_ok": sum(hits),
            "n": len(pairs),
            # The per-utterance outcome, not just the count. Two cells of this grid
            # differ by four utterances in 200, and whether that is a real effect or
            # sampling noise can only be answered by a *paired* test -- McNemar over
            # the utterances that changed verdict between the two conditions. A count
            # cannot be paired with another count, so the first version of this bench
            # made the question unanswerable without a full re-run. One character per
            # utterance, in the fixed order `librispeech_subset` returns.
            "first_word_hits": "".join("1" if h else "0" for h in hits),
            "empty_hyps": sum(1 for _, h in pairs if not h.strip()),
            "decode_seconds": round(time.monotonic() - t0, 1),
        }

    rows: list[dict] = []
    for run_index in range(repeat):
        for lead_ms in LEADS_MS:
            row = {"run": run_index, "arm": "intact", "cut_ms": 0, **score(trimmed, lead_ms)}
            rows.append(row)
            print(f"[onset] run{run_index} intact  cut=   0ms lead={lead_ms:4d}ms  "
                  f"WER {row['wer_pct']:5.2f}%  first word {row['first_word_ok']}/{row['n']}",
                  flush=True)
        for cut_ms in CUTS_MS:
            cut = int(cut_ms * SAMPLE_RATE / 1000)
            clipped = [(u, a[cut:], r) for u, a, r in trimmed]
            # A clip shorter than the cut would score as a false null rather than a
            # measurement, so refuse instead of reporting one.
            if not all(len(a) > SAMPLE_RATE for _, a, _ in clipped):
                raise SystemExit(f"a clip is shorter than the {cut_ms} ms cut")
            for lead_ms in LEADS_MS:
                row = {"run": run_index, "arm": "clipped", "cut_ms": cut_ms,
                       **score(clipped, lead_ms)}
                rows.append(row)
                print(f"[onset] run{run_index} clipped cut={cut_ms:4d}ms lead={lead_ms:4d}ms  "
                      f"WER {row['wer_pct']:5.2f}%  first word {row['first_word_ok']}/{row['n']}",
                      flush=True)

    return {
        "config": {
            "n": len(raw),
            "model": model,
            "compute_type": "int8",
            "leads_ms": list(LEADS_MS),
            "cuts_ms": list(CUTS_MS),
            "repeat": repeat,
            "trim_peak": TRIM_PEAK,
            "median_trimmed_ms": round(float(np.median(dropped)) / SAMPLE_RATE * 1000, 1),
            "max_trimmed_ms": round(float(max(dropped)) / SAMPLE_RATE * 1000, 1),
        },
        "rows": rows,
    }


if __name__ == "__main__":
    import sys

    from _common import provenance, write_result

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    repeat = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    out = run(n, repeat)
    out["provenance"] = provenance(stamp)
    write_result("onset", out)
