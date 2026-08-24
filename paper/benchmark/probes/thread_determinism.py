"""Is the non-determinism thread scheduling rather than the temperature fallback?

Two observations from the decode-arm work do not fit the story that sampling is the
whole cause:

* `base.en` is bit-identical across five baseline decodes on test-other, yet
  `decode-mechanism-base.en-test-clean.json` shows it *does* reach the temperature
  fallback. Reaching a sampled step without moving is possible (a fully rejected ladder
  ends by taking the best average-logprob result it saw), so that alone is only odd.
* Running that mechanism probe twice, unchanged, counted **6** rejected decode attempts
  and then **4**.

The second observation is what this file was built to explain, on a premise that turned
out to be wrong. I read the rejection as happening on the *first*, greedy, temperature-0
attempt -- before anything is sampled -- so that a varying count meant something below
the decoder was already varying, with CTranslate2's multi-threaded reduction order the
obvious candidate: int8 accumulation makes thread completion order visible in the low
bits, and an utterance sitting near the compression-ratio threshold would then fall on
different sides of it between runs.

Only the *first* rejection per utterance is greedy. `generate_with_fallback` iterates
`options.temperatures`, which begins at 0.0 and then climbs, and every rung above 0.0
samples. So an utterance rejected at 0.0 is re-decoded **with sampling**, and how far up
the ladder it climbs before something passes is free to differ between runs -- a moving
count with no thread-order effect required. And if every rung is rejected the ladder
ends by taking the best average-logprob result it saw, which can be the temperature-0
decode, so the final text need not move at all.

The measurement stands whether or not the premise did, so it is kept: it tests the
thread hypothesis at the one seam a user can actually set, `[stt] cpu_threads`, and the
rejection counts are now split by temperature so the two explanations are separated by
evidence rather than by argument.

  default   `cpu_threads=0` -- CTranslate2 picks, which is what ships
  single    `cpu_threads=1` -- one thread, so no cross-thread reduction order to vary

If pinning to one thread makes the hypotheses bit-identical across repeats while the
default does not, the cause is thread scheduling and the fix is a config key, not a
decode setting. If *both* are stable the corpus is simply too easy to show it, and if
neither is, something else is varying and this file has not found it. Independently: if
the temperature-0 rejection count is constant across runs while the count above 0.0
moves, the sampled rungs explain the variation on their own and no thread effect is
needed.

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
    by_temp = counter.fallbacks_by_temperature
    row["fallback_events_by_temperature"] = dict(sorted(by_temp.items()))
    # 0.0 is the greedy rung and is deterministic; everything above it samples.
    row["greedy_rejections"] = by_temp.get("0.0", 0)
    row["sampled_rejections"] = sum(v for k, v in by_temp.items() if k != "0.0")
    row["decode_seconds_total"] = round(elapsed, 1)
    return row


def summarise(runs: list[dict]) -> dict:
    hashes = [r["hypothesis_sha256_16"] for r in runs]
    fallbacks = sorted({r["fallback_events"] for r in runs})
    greedy = sorted({r["greedy_rejections"] for r in runs})
    sampled = sorted({r["sampled_rejections"] for r in runs})
    return {
        "greedy_rejections_range": [greedy[0], greedy[-1]] if greedy else [0, 0],
        "greedy_rejections_vary": len(greedy) > 1,
        "sampled_rejections_range": [sampled[0], sampled[-1]] if sampled else [0, 0],
        "sampled_rejections_vary": len(sampled) > 1,
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
    # Which arms showed the count moving at all. The first version asked only the
    # default arm, and a re-run put the variation in the *single* arm instead -- where
    # it is the stronger evidence, since a count that moves with one thread cannot be
    # thread-reduction order. Reading one arm turned that run into "cannot separate the
    # two causes" while it was sitting in the other column.
    varying = [k for k, v in arms.items() if v["summary"]["fallback_events_vary"]]
    sampled_only = [
        k for k, v in arms.items()
        if v["summary"]["sampled_rejections_vary"] and not v["summary"]["greedy_rejections_vary"]
    ]
    greedy_varying = [k for k, v in arms.items() if v["summary"]["greedy_rejections_vary"]]
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
            "rejection_count_varies_in": varying,
            "sampled_rungs_only_vary_in": sampled_only,
            "greedy_rung_varies_in": greedy_varying,
            "count_varies_single_threaded": "single" in varying,
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
                    f" The rejected-attempt count varies across identical runs in: "
                    f"{', '.join(varying)}."
                    if varying
                    else " The rejected-attempt count was identical in every run."
                )
                + (
                    " It varies with `cpu_threads=1`, where there is no cross-thread "
                    "reduction order to differ, so thread scheduling cannot be what "
                    "moves it."
                    if "single" in varying
                    else ""
                )
                + (
                    (
                        f" Split by temperature, the greedy rung at 0.0 is rejected the "
                        f"same number of times in every run and only the sampled rungs "
                        f"above it move ({', '.join(sampled_only)}). An utterance "
                        f"rejected greedily is re-decoded with sampling, so how far up "
                        f"the ladder it climbs before something passes is free to "
                        f"differ -- and when every rung is rejected the ladder returns "
                        f"the best average-logprob result it saw, which can be the "
                        f"deterministic temperature-0 decode. That is a moving count "
                        f"over unmoved text, and it needs no thread effect."
                    )
                    if sampled_only
                    else ""
                )
                + (
                    f" The greedy rung at temperature 0.0 is itself rejected a differing "
                    f"number of times in {', '.join(greedy_varying)}. That rung does not "
                    f"sample, so something below the decoder is varying there and "
                    f"sampling cannot account for it."
                    if greedy_varying
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
