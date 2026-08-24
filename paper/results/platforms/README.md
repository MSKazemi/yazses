# The same harness, five machines

One directory per GitHub Actions runner, from a single `benchmark.yml` dispatch
(`wer_n=60`, `lat_n=15`, `vad_n=120`, `stream_n=6`). Every file is exactly what that
runner wrote, provenance included.

This is the first time the benchmark workflow had ever executed. It exists so that a
number on [`docs/benchmarks.md`](../../../docs/benchmarks.md) can be checked against a
machine nobody here owns.

## What the four completed legs say

| Model | Linux x86_64 | Linux arm64 | macOS arm64 | Windows x86_64 |
|---|---|---|---|---|
| | AMD EPYC 9V74 | Neoverse-N2 | Apple M1 | AMD EPYC 7763 |
| `tiny.en` | 3.39 % | 3.60 % | 3.74 % | 3.88 % |
| `base.en` | 3.32 % | 3.32 % | 3.25 % | 3.39 % |
| `small.en` | **2.05 %** | **2.05 %** | **2.05 %** | **2.05 %** |

Same 60 utterances, same checkpoints, same CTranslate2 4.8.1, four instruction sets.
The spread narrows as the model grows — 0.49 points on `tiny.en`, 0.14 on `base.en`,
**zero** on `small.en` — which is what the run-to-run section of the benchmarks page
predicted from thread-count experiments on one laptop, now confirmed across
architectures rather than across thread counts.

Read the timings with the `load_average_1m` field open. The macOS runner reported
**30.44** on three logical CPUs; its RTF numbers describe a contended host and belong
in no comparison.

## The missing leg

`macos-15-intel` is absent because it could not install: `uv.lock` pins onnxruntime
1.28.0, which upstream publishes for macOS arm64 only, and `faster-whisper` requires
onnxruntime unconditionally. The workflow's `continue-on-error` turned that into a
silent absence rather than a red job — a matrix row that looked measured and never was.
It is fixed to resolve unlocked, as `scripts/build-macos.sh` already does, but this
dispatch predates the fix.

## What these numbers are not

They are **not** the published table. 60 utterances, not 200, on shared CI hardware of
unknown neighbours. `docs/benchmarks.md` quotes the 200-utterance runs from a dedicated
box. These are here to answer a narrower question — *does the same code produce the same
accuracy on a different instruction set* — and they answer it.
