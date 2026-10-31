# Mandarin ASR model decision and reproducible evaluation protocol

**Status:** Proposed P1 baseline; no new model promoted without recorded evidence.
**Governing:** ADR-v2-141, `design/chinese/model-strategy.md`, [model evidence issue #503](https://github.com/MSKazemi/yazses/issues/503).
**Snapshot:** [current main, 2026-10-29](https://github.com/MSKazemi/yazses/tree/4fda34030b0cf6e269edad78f8e03ea0d91b0324).

## Recommendation and license decision

**Use multilingual OpenAI Whisper `small` through the existing faster-whisper / CTranslate2 CPU-int8 path as the first recommended Mandarin profile.** This is a starting point for a measured release, not a claim that `small` has the best Chinese accuracy. The project's default English `base.en` is **not** changed. The Chinese profile only selects `small` when its current checkpoint cannot transcribe Mandarin or the user explicitly requests the recommended model.

The recognizer must support `language="zh"`. The desired script (Simplified/Traditional) is an **output postprocessor selection**; it does not require two sets of recognizer weights. First-use download of model weights is explicitly user-authorized and must be possible to replace with offline provisioning; inference after cache/setup must be local.

| Model / artifact | Role | Upstream license position | Runtime/product cost question | Decision |
|---|---|---|---|---|
| OpenAI Whisper `small` multilingual | P1 CPU baseline | OpenAI states code **and weights** are MIT; faster-whisper runtime is MIT | Actual Mandarin CER, memory and latency on supported CPUs | **Recommended baseline to validate** |
| Whisper `base` multilingual | Low-resource probe only | MIT family | May trade too much accuracy for CPU savings | Test before offering a fast preset |
| Whisper `large-v3-turbo` | Same-runtime higher-capacity contender | MIT family | Memory, long-form stability, p95 latency | Benchmark, not P1 default |
| Whisper `large-v3` | Same-runtime quality ceiling | MIT family | Large RAM/CPU budget and repeat/conditioning issues | Optional benchmark, not default |
| Qwen3-ASR-0.6B (pin exact checkpoint/revision) | Chinese/dialect research contender | Official model card declares Apache-2.0; verify selected weights and dependent components | New Transformers stack, CPU viability, streaming and timestamps; optional forced aligner | Isolated probe, **no base dependency** |
| Paraformer-zh / Paraformer-zh-streaming | Chinese/streaming research contender | Model card declares Apache-2.0; for streaming pin the explicitly licensed immutable `apache-2.0-20260804` snapshot or audit a newer revision | New FunASR/PyTorch stack, timestamp contract, Linux/macOS/Windows packaging | Isolated probe; no promotion without evidence |
| SenseVoiceSmall | Comparison only | Custom FunASR Model Open Source License on published weights, not automatically MIT/Apache/BSD | Licensing and runtime/adapter review | **Do not bundle/recommend** under permissive-only policy without explicit legal/maintainer approval |

Model-weight terms take precedence over toolkit source-code labels. A permissive `license_id` entry in benchmark JSON is a recorded assertion, not a legal certification. For every candidate, record weight repository, resolved **immutable commit**, model card/license link, file hashes, dependency licenses, copy/redistribution conditions, and any separate aligner or tokenizer model licenses. Recheck when switching revisions.

**Authoritative starting points (landing pages):**

- [Whisper repository and license](https://github.com/openai/whisper#license)
- [faster-whisper project](https://github.com/SYSTRAN/faster-whisper)
- [Qwen3-ASR repository](https://github.com/QwenLM/Qwen3-ASR) and [Qwen3-ASR-0.6B model](https://huggingface.co/Qwen/Qwen3-ASR-0.6B)
- [Paraformer-zh model](https://huggingface.co/funasr/paraformer-zh) and [licensed streaming snapshot](https://huggingface.co/funasr/paraformer-zh-streaming/tree/apache-2.0-20260804)
- [SenseVoiceSmall weight page](https://huggingface.co/FunAudioLLM/SenseVoiceSmall) (custom model license)

Do not use upstream leaderboard CER as a YazSes release result: their audio, normalization, decoding settings and runtime may differ.

## Preservation of existing architecture

All production candidates must implement the existing `SttEngine` protocol behind `src/yazses/stt/factory.py`. A hypothetical Qwen/Paraformer adapter cannot be a mandatory import; add a tested optional extra, lazy import inside its builder, and the correct capability table entry only after model/runtimes are independently qualified. Keep the original English path free of new startup imports, dependency downloads, CPU/memory overhead and egress primitives.

Do not add model auto-selection by unmeasured RAM heuristics. If a probe wins, propose a **superseding ADR** with named hardware profiles, fallback behavior, weight hash, packaging proof and a migration plan. An isolated research adapter is not an endorsement.

## Scorer and dataset contract (already implemented)

The current scoring instrument is `benchmark/bench_mandarin.py` and pure `mandarin_metrics.py`. The schema is `yazses.bench.mandarin/1`; the evaluation normalization is **`zh-eval-v1`**. Its manifest mode requires per-row data provenance and declared checkpoint license, runs the shipping engine configured for `zh` with production script conversion disabled, and records four CER views:

1. `cer_raw` — exact code-point difference, including punctuation, spaces, and script mismatch;
2. `cer_punct` — NFC, explicit width folding, Latin case folding and whitespace removal but **keeps** punctuation;
3. `cer_normalized` — as above with punctuation removed;
4. `cer_script_normalized` — normalized after OpenCC folding to the reference script, only when converter actually loaded. If it was not available, report **null**, not an invented equal score.

Numerals (e.g. `2026` vs `二零二六`) remain meaningfully different. `zh-eval-v1` deliberately does **not** perform full NFKC or numeral conversion. It measures code points, not linguistically segmented Chinese words. Freeze this normalization for a benchmark version; if it changes, create `zh-eval-v2` and do not overwrite the older results.

For model comparison, hold constant: evaluation set/split, resampling, audio selection, decode settings, forced-language policy, model-device profile, script target, decoder conditioning flags and hardware when comparing latency. Seed/hash-selected subsets must be identical across arms. Use no private recordings in a public repo unless provenance/consent explicitly permits redistribution; public benchmark harness and aggregate JSON alone do not authorize publishing audio/transcripts.

## Corpus design and coverage

The initial **pilot** may reuse the small ASCEND probe solely to find pipeline issues. It is too small and accent-skewed for a product-wide Mandarin support claim. The release corpus should have a fixed manifest, independent speakers and a frozen test split across these slices:

| Slice | Why | Required reporting |
|---|---|---|
| Mainland Mandarin, everyday short utterances | Main `zh-CN` use | CER median/aggregate, error inventory |
| Taiwan Mandarin and Traditional-script reference | `zh-TW` workflow, lexical differences | Separate raw/script-aware CER |
| Northern/southern Mandarin accents (where licensed data available) | Accent robustness | By-accent CER, no universal coverage claim |
| Mixed Mandarin + Latin app names and code tokens | Dictation into code/editor/office | ASCII tokens, spaces and punctuation |
| Numbers, dates, addresses, IDs, currency, URLs | High-cost semantic transcription errors | Exact-match and critical-token errors; no automatic normalisation |
| Short hold-to-talk (1–8 s) | Primary UX | p50/p95 end-to-end elapsed |
| Long recordings (30–120+ min where legally available) | Repetition/hallucination stability | CER by interval, omissions, repeats |
| Moderate background noise and mic variance | Real user conditions | CER and failure-to-transcribe frequency |
| Silence/no-speech/repeated audio | Safety | Hallucination rate and no-output handling |

**Pre-register counts** per slice and the minimum speaker count before the final run; record speaker leakage checks, exclusions and reason codes. Results on data with missing license/consent must be excluded, not labelled “public”. No audio belongs in the GitHub repo by default.

## Execution steps and examples

CI smoke, with no model, audio or network:

```sh
uv run python benchmark/bench_mandarin.py --smoke --out /tmp/mandarin-smoke.json
uv run python -m pytest tests/test_bench_mandarin.py -q
```

A real authorized benchmark, run locally by an evaluator with lawful access to corpus audio, only **after** the manifest is reviewed:

```sh
uv run python benchmark/bench_mandarin.py \
  --manifest /path/to/mandarin-test.jsonl \
  --audio-root /path/to/authorized-audio \
  --model small --script simplified \
  --model-license MIT \
  --license-source https://github.com/openai/whisper#license \
  --model-revision VERIFIED_IMMUTABLE_REVISION \
  --threads 4 --seed 2026 \
  --out /path/to/aggregate-mandarin-small.json
```

The paths and revision are placeholders. A manifest has a `.meta.json` sidecar and uses the existing `benchmark/persian_manifest.py` license/consent gate (generic despite its name). Do not copy a local manifest, raw utterances, hidden test labels or private audio into a public PR. The runtime must record actual revision and hash, not silently trust the operator-supplied name. To compare Qwen/Paraformer, first establish an **isolated probe adapter** capable of emitting the same schema; `--model` alone does not make the current factory support an unimplemented engine.

## Required measurement record

Every scored run must contain:

- Git commit, model artifact ID, immutable revision, license source/verdict, weights checksums, CTranslate2/Whisper or probe runtime version;
- corpus manifest SHA-256, split/seed/selection rule, per-slice counts and excluded files;
- host OS/architecture/CPU model/RAM, thread count, compute type, power/governor if available;
- CER raw/punctuation/normalized/script-normalized, S/D/I, critical-token failure counts and error exemplars that are permitted to share;
- cold model load time, p50/p95 decode latency, real-time factor, RSS/peak RSS, CPU core-seconds, disk/runtime closure;
- source language, output-script target, OpenCC version and whether script conversion actually occurred;
- timestamps/word alignment, streaming partial/final stability, meeting/file compatibility, recovery after cache, and logs/egress audit.

Current harness includes many aggregate fields (`metrics`, `runtime`, `model_license`, `provenance`, `manifest`), but **it is not a complete end-to-end product benchmark**. Add separate surface metrics rather than stuffing unverifiable fields into `yazses.bench.mandarin/1`.

## Promotion and rejection decision

**P1:** choose `small` when it satisfies a pre-registered minimum usability threshold on representative CPU devices and the release validation matrix. If it does not, do **not** mislabel Mandarin generally supported: either narrow the supported hardware/surfaces or reconsider model selection through ADR review.

**New model:** require a material measured improvement over the same-data baseline: as an initial rule of thumb, >=20% relative CER reduction, >=30% lower latency/core-cost at non-inferior CER, or significant *validated* added language capability. Such a win is necessary but not sufficient: weight-license permission, offline cache, memory, optional packaging on all claimed OSes, timestamps, command safety, and long-form regressions must all clear. If the model is better in CER but unusable on CPU, label it an opt-in quality preset on supported hardware, not the new default.

Use a dated decision record with verdict `promote` / `stay with small` / `research only` / `reject` and reasons. **Do not publish a benchmark winner without its evaluated model revision, corpus hash and host profile.**
