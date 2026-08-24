"""Is the non-determinism thread scheduling rather than the temperature fallback?

Two observations from the decode-arm work do not fit the story that sampling is the
whole cause:

* `base.en` is bit-identical across five baseline decodes on test-other, yet
  `decode-mechanism-base.en-test-clean.json` shows it *does* reach the temperature
  fallback. Reaching a sampled step without moving is possible (a fully rejected ladder
  ends by taking the best average-logprob result it saw), so that alone is only odd.
* Running that mechanism probe twice, unchanged, counted **6** rejected decode attempts
  and then **4**. Nothing sampled has run at that point: the rejection happens on the
  *first*, greedy, temperature-0 attempt. A deterministic decode cannot be rejected six
  times in one run and four in the next.

So something below the decoder is already varying, and the temperature fallback is
downstream of it -- an amplifier, not the source. The candidate is CTranslate2's CPU
kernels: a multi-threaded reduction sums in whatever order the threads finish, and
int8 accumulation makes that order visible in the low bits. Utterances sitting near the
compression-ratio or logprob threshold then fall on different sides of it between runs,
which is exactly a rejection count that moves without any sampling.

This tests it at the one seam a user can actually set, `[stt] cpu_threads`:

  default   `cpu_threads=0` -- CTranslate2 picks, which is what ships
  single    `cpu_threads=1` -- one thread, so no cross-thread reduction order to vary

If pinning to one thread makes the hypotheses bit-identical across repeats while the
default does not, the cause is thread scheduling and the fix is a config key, not a
decode setting. If *both* are stable the corpus is simply too easy to show it, and if
neither is, something else is varying and this file has not found it.

Nothing here changes a default: single-threaded decoding is much slower, and the elapsed
time is recorded so that trade is visible rather than asserted.

    python paper/benchmark/probes/thread_determinism.py test-clean base.en 40 4
"""
from __future__ import annotations

import hashlib
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_wer  # noqa: E402
from _common import (  # noqa: E402
    librispeech_subset,
    load_audio,
    subset_digest,
    write_result,
)
from decode_determinism import _release, _score  # noqa: E402
from decode_mechanism import _PassCounter  # noqa: E402

#: `0` is CTranslate2's own choice and is what ships; `1` removes the reduction order.
THREAD_ARMS: dict[str, int] = {"default": 0, "single": 1}


def _digest(hyps: list[str]) -> str:
    return hashlib.sha256("\n".join(hyps).encode("utf-8")).hexdigest()[:16]


def _one_run(model: str, threads: int, subset, audio, refs) -> dict:
    counter = _PassCounter()
    lg = logging.getLogger("faster_whisper")
    prior_level, prior_prop = lg.level, lg.propagate
    lg.setLevel(logging.DEBUG)
    lg.propagate = False
    lg.addHandler(counter)

    engine = bench_wer._build("faster-whisper", model, cpu_threads=threads)
    hyps: list[str] = []
    t0 = time.monotonic()
    try:
        for (utt_id, _, _, _), a in zip(subset, audio):
            counter.current = utt_id
            hyps.append(bench_wer._normalize(engine.transcribe(a)))
    finally:
        elapsed = time.monotonic() - t0
        lg.removeHandler(counter)
        lg.setLevel(prior_level)
        lg.propagate = prior_prop
        _release(engine)

    row = _score(refs, hyps)
    row["hypothesis_sha256_16"] = _digest(hyps)
    row["fallback_events"] = sum(counter.fallbacks.values())
    row["decode_seconds_total"] = round(elapsed, 1)
    return row


def summarise(runs: list[dict]) -> dict:
    hashes = [r["hypothesis_sha256_16"] for r in runs]
    fallbacks = sorted({r["fallback_events"] for r in runs})
    return {
        "repeats": len(runs),
        "distinct_hypotheses": len(set(hashes)),
        "reproducible": len(set(hashes)) == 1,
        "fallback_events_range": [fallbacks[0], fallbacks[-1]] if fallbacks else [0, 0],
        "fallback_events_vary": len(fallbacks) > 1,
        "wer_range": [min(r["wer"] for r in runs), max(r["wer"] for r in runs)],
        "mean_decode_seconds": round(
            sum(r["decode_seconds_total"] for r in runs) / len(runs), 1
        ) if runs else 0.0,
    }


def run(split: str, model: str, n: int, repeats: int) -> dict:
    subset = librispeech_subset(n, stratified=True, split=split)
    refs = [bench_wer._normalize(ref) for _, _, ref, _ in subset]
    audio = [load_audio(flac) for _, flac, _, _ in subset]

    arms: dict[str, dict] = {}
    for arm, threads in THREAD_ARMS.items():
        runs = []
        for r in range(repeats):
            row = _one_run(model, threads, subset, audio, refs)
            row["run"] = r
            runs.append(row)
            print(
                f"  [thr] {arm} run {r}: WER={row['wer']:.2f}% "
                f"fallbacks={row['fallback_events']} "
                f"sha={row['hypothesis_sha256_16']} "
                f"{row['decode_seconds_total']}s",
                flush=True,
            )
        arms[arm] = {"summary": summarise(runs), "runs": runs}

    default, single = arms["default"]["summary"], arms["single"]["summary"]
    pinning_fixes_it = single["reproducible"] and not default["reproducible"]
    both_stable = single["reproducible"] and default["reproducible"]
    slowdown = (
        round(single["mean_decode_seconds"] / default["mean_decode_seconds"], 2)
        if default["mean_decode_seconds"] else None
    )
    return {
        "config": {
            "dataset": f"LibriSpeech {split}",
            "n_utterances": len(subset),
            "corpus_digest": subset_digest([u for u, _, _, _ in subset]),
            "model": model,
            "repeats": repeats,
            "arms": {k: f"cpu_threads={v}" for k, v in THREAD_ARMS.items()},
        },
        "probe": {
            "measured": (
                "Whether run-to-run decode instability is CPU thread scheduling rather "
                "than the temperature fallback: the same utterances decoded repeatedly "
                "at cpu_threads=0 (shipping default) and cpu_threads=1, hashing the "
                "hypotheses and counting rejected decode attempts each time."
            ),
            "produced_by": "paper/benchmark/probes/thread_determinism.py",
        },
        "arms": arms,
        "finding": {
            "default_reproducible": default["reproducible"],
            "single_thread_reproducible": single["reproducible"],
            "pinning_threads_fixes_it": pinning_fixes_it,
            "single_thread_slowdown": slowdown,
            "reading": (
                (
                    f"Pinning `[stt] cpu_threads = 1` makes the decode bit-reproducible "
                    f"({single['repeats']} identical hypotheses) where the shipping "
                    f"default produces {default['distinct_hypotheses']}. The instability "
                    f"is thread-scheduling order in the CPU kernels, not the temperature "
                    f"fallback -- the fallback amplifies it by turning a low-bit "
                    f"difference into a different sentence. It costs {slowdown}x decode "
                    f"time, so it is a knob for someone who needs reproducibility, not a "
                    f"default."
                    if pinning_fixes_it
                    else
                    f"Both arms are reproducible across {default['repeats']} repeats on "
                    f"this corpus and model, so it cannot separate the two causes. A "
                    f"corpus that does not trigger the instability cannot say what "
                    f"drives it; re-run on a model and corpus that do."
                    if both_stable
                    else
                    f"Pinning to one thread did not make the decode reproducible "
                    f"({single['distinct_hypotheses']} distinct hypotheses against the "
                    f"default's {default['distinct_hypotheses']}), so thread-scheduling "
                    f"order is not the whole cause and something else is varying."
                )
                + (
                    f" The rejected-attempt count itself varies across identical "
                    f"default runs ({default['fallback_events_range'][0]}-"
                    f"{default['fallback_events_range'][1]}), which is the observation "
                    f"that started this: rejection happens on the greedy first attempt, "
                    f"before anything is sampled."
                    if default["fallback_events_vary"]
                    else ""
                )
            ),
        },
    }


def main() -> None:
    split = sys.argv[1] if len(sys.argv) > 1 else "test-clean"
    model = sys.argv[2] if len(sys.argv) > 2 else "base.en"
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    repeats = int(sys.argv[4]) if len(sys.argv) > 4 else 4
    payload = run(split, model, n, repeats)
    for k, v in payload["finding"].items():
        print(f"  {k}: {v}", flush=True)
    print(f"wrote {write_result(f'probes/thread-determinism-{model}-{split}', payload)}")


if __name__ == "__main__":
    main()
