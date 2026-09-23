# Chinese support — model strategy

**Status:** Proposed decision framework, current as of 2026-09-20  
**P1 decision:** Keep the existing faster-whisper runtime and use multilingual `small` as the supported baseline candidate. Benchmark alternatives behind `SttEngine`; do not add a second mandatory runtime before it wins on measured product criteria.

## 0. Model-license gate

For this programme, "free/open-source model" is not enough by itself. A model that becomes a
recommended YazSes profile must have an auditable model-weight license that is acceptable for
redistribution and normal downstream use.

**Default policy for production profiles:** prefer permissive weight licenses such as MIT,
Apache-2.0 or BSD. Record the exact model repository, immutable revision/commit and license
source in benchmark metadata. A toolkit's code license does **not** prove that its model weights
carry the same license.

Current verified examples:

- OpenAI Whisper states that its **code and model weights are MIT-licensed**:
  https://github.com/openai/whisper#license
- Qwen3-ASR-0.6B's official Hugging Face model card declares **Apache-2.0**:
  https://huggingface.co/Qwen/Qwen3-ASR-0.6B
- The current `funasr/paraformer-zh` model card declares **Apache-2.0**; the streaming
  repository also publishes an immutable `apache-2.0-20260804` tag that explicitly covers
  its weights and accompanying files:
  https://huggingface.co/funasr/paraformer-zh
  https://huggingface.co/funasr/paraformer-zh-streaming/tree/apache-2.0-20260804
- SenseVoiceSmall currently declares a custom **FunASR Model Open Source License**, not
  MIT/Apache/BSD:
  https://huggingface.co/FunAudioLLM/SenseVoiceSmall
  https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE

SenseVoiceSmall may still be benchmarked as research evidence, but under the project's
permissive-license preference it must not become a bundled/recommended production model without
an explicit maintainer/legal review of that exact weight revision. The current custom agreement
contains attribution requirements, conduct-based termination language, and automatic acceptance
of future revisions, so treating it as interchangeable with Apache-2.0 would be incorrect.

---

## 1. Why model choice is an architecture decision

A Chinese recognizer is not just an accuracy number. In YazSes it affects:

- cold-start time;
- hold-to-talk latency;
- CPU saturation;
- RAM and disk footprint;
- streaming behavior;
- word timestamps;
- file and meeting transcription;
- model download/cache behavior;
- packaging on Linux/macOS/Windows;
- air-gapped setup;
- optional dependency size;
- model-weight license;
- whether the existing `SttEngine` seam can contain it cleanly.

A benchmark improvement that requires making PyTorch/vLLM a mandatory dependency or drops word-timestamp functionality is not automatically a product improvement.

---

## 2. P1 baseline: multilingual Whisper `small`

Recommended initial profile:

```toml
[stt]
engine = "faster-whisper"
model = "small"
language = "zh"
chinese_script = "simplified" # or traditional
```

### Why this is the first supported baseline candidate

1. **Zero new recognition runtime.** It uses the engine already shipped and tested.
2. **All existing decode paths already honor language.**
3. **The downloader/cache/offline behavior already exists.**
4. **The Han-script wrapper already covers it.**
5. **The repository already has Chinese measurements on this model.**
6. **CPU int8 is aligned with YazSes' default hardware philosophy.**
7. **Changing back to English does not require changing architecture.**

The repository’s current ASCEND probe reported, on 20 clean Mandarin/code-switched utterances, `small` at 16.9% CER after Simplified normalization versus 35.9% before normalization. This is useful evidence that the model and script layer work, but the sample is too small to be a release-quality benchmark.

Therefore `small` is a **baseline to beat**, not an assertion that it is the globally best Chinese model.

---

## 3. Whisper candidates to benchmark without a new engine

### `base`

Potential “fast/low-resource” preset.

Pros:

- same runtime;
- lower resource footprint than `small`.

Unknowns that must be measured for Chinese:

- CER delta versus `small`;
- whether lower latency is material in interactive use;
- script inconsistency rate;
- robustness to accents/noise.

Do not publish it as a Chinese preset until measured.

### `large-v3`

The existing Chinese page reports 11.3% normalized CER on the same small ASCEND sample versus 16.9% for `small`, but it is much heavier.

It also interacts with the repository’s existing `condition_on_previous_text` finding: large-v3 has shown repetition instability in other benchmarks, so Chinese evaluation must include long-form/meeting behavior, not only short utterance CER.

### `large-v3-turbo` / `turbo`

Attractive because it remains inside faster-whisper while reducing the large-v3 parameter/latency burden.

It is a **benchmark candidate**, not the default, until Chinese CER, latency, RAM and long-form stability are measured on YazSes hardware.

---

## 4. Alternative Chinese ASR candidates

These candidates are current upstream options worth evaluating. They are not P1 dependencies.

### 4.1 SenseVoiceSmall

Current FunASR documentation describes SenseVoiceSmall as a 234M-parameter checkpoint supporting Chinese, English, Japanese, Korean and Cantonese, with a CPU usage path and GGUF edge checkpoint.

Why it is interesting:

- Chinese-first ecosystem;
- size is plausible for CPU/edge deployment;
- Cantonese support creates a future path distinct from Mandarin;
- a GGUF route may permit a lightweight optional backend.

Integration concerns:

- new runtime and model cache conventions;
- timestamp semantics need mapping to `transcribe_words`;
- streaming behavior must be verified for the exact backend chosen;
- model-weight license must be reviewed separately from FunASR toolkit licensing;
- packaging impact must be measured.

**Priority:** research-only benchmark candidate under the current custom model-weight license. Do not bundle or recommend it under the permissive-license policy without explicit approval of the exact revision.

### 4.2 Paraformer-zh / Paraformer-zh-streaming

Current FunASR model zoo lists:

- `Paraformer-zh`: 220M, zh/en, timestamps;
- `Paraformer-zh-streaming`: 220M, streaming variant.

Why it is interesting:

- explicit Chinese/English focus;
- separate streaming checkpoint;
- comparatively compact parameter count.

Integration concerns:

- offline and streaming checkpoints may not be interchangeable;
- a single YazSes `SttEngine` instance must satisfy batch and `decode_window` behavior coherently;
- new FunASR/PyTorch dependency surface;
- pin the exact Hugging Face revision whose weights are explicitly Apache-2.0; do not infer a checkpoint license from the FunASR toolkit license.

**Priority:** permissively licensed Chinese-optimized streaming candidate, after exact-revision pinning and product measurements.

### 4.3 Qwen3-ASR-0.6B

The official Qwen3-ASR repository states that the 0.6B and 1.7B models support language identification/ASR across 52 languages and dialects, including Mandarin, Cantonese and many Chinese regional varieties, with offline and streaming inference.

Why it is interesting:

- broad Chinese dialect coverage;
- current upstream development;
- one model for multilingual/dialect expansion;
- explicit streaming/offline unification.

Integration concerns:

- official examples center on `qwen-asr` with Transformers/vLLM and bfloat16/GPU-oriented acceleration paths;
- even 0.6B may impose a materially larger runtime/RAM/package footprint than current CTranslate2 int8;
- timestamp support may involve the separate forced-aligner model;
- dependency isolation may be advisable upstream itself;
- CPU interactive latency must be measured, not inferred from high-concurrency throughput claims.

**Priority:** permissively licensed quality/dialect candidate (official model card: Apache-2.0); do not make it a base dependency without a CPU/product benchmark.

### 4.4 Qwen3-ASR-1.7B

Same coverage advantages, larger capacity.

For YazSes' CPU-first interactive path, treat this as an experimental accuracy ceiling unless tests prove acceptable latency/resource use. It is more plausible for optional GPU or file-transcription workloads than as the default hold-to-talk engine.

### 4.5 Fun-ASR-Nano

Current FunASR documentation lists an ~800M base checkpoint covering Chinese, English, Japanese and Chinese dialects/accents, with a native Transformers CPU path.

It is worth benchmarking if it offers better Chinese/dialect quality than compact candidates, but it carries a much larger dependency/model footprint than simply staying on faster-whisper.

---

## 5. Candidate matrix

This table records integration facts and questions, **not an accuracy ranking**.

| Candidate | Existing YazSes runtime? | Chinese focus/coverage | CPU path | Streaming | Timestamp story | New dependency risk | P1 role |
|---|---:|---|---|---|---|---|---|
| Whisper `small` | Yes | Multilingual, Mandarin | Yes, CTranslate2 int8 | Existing YazSes rolling decode | Existing word timestamps | None | Baseline/recommended candidate |
| Whisper `large-v3` | Yes | Multilingual | Yes but heavy | Existing | Existing | None | Accuracy reference |
| Whisper `large-v3-turbo` | Yes | Multilingual | Needs YazSes measurement | Existing | Existing | None | Strong same-runtime candidate |
| SenseVoiceSmall | No | zh/en/ja/ko/yue | Upstream documents CPU path | Backend-specific | Must map/test | Medium | First compact alternative prototype |
| Paraformer-zh | No | zh/en | Upstream CPU/GPU toolkit | Separate streaming checkpoint | Upstream timestamps | Medium/high | Streaming/Chinese prototype |
| Qwen3-ASR-0.6B | No | 52 languages/dialects incl. Chinese varieties | Must benchmark on target CPU | Upstream supports streaming | Forced aligner may be separate | High | Dialect/quality research candidate |
| Qwen3-ASR-1.7B | No | Same broad coverage | Likely heavy; benchmark required | Upstream supports | Forced aligner may be separate | High | Accuracy ceiling / optional GPU candidate |
| Fun-ASR-Nano | No | zh/en/ja + dialects/accents | Upstream documents native CPU route | Backend-specific | checkpoint/path dependent | High | Research candidate |

---

## 6. Model promotion protocol

No alternative engine becomes a recommended Chinese preset because an upstream leaderboard says it is better.

It must pass the same YazSes harness against the current supported baseline.

### Required benchmark dimensions

#### Recognition quality

- Mandarin character error rate (CER);
- punctuation-aware and punctuation-stripped CER;
- digit/number accuracy;
- named entity / technical-term subset;
- long-utterance deletion/insertion rate;
- hallucination/repetition incidence;
- Simplified and Traditional output after normalization;
- Mandarin-English mixed-token stress set (reported separately, not called code-switch support).

#### Interactive performance

On the project’s declared reference CPU:

- model cold-load wall time;
- first-decode warm-up;
- p50/p95 RTF;
- p50/p95 release-to-final-text latency for 2 s / 5 s / 10 s speech;
- peak RSS;
- CPU core-seconds per burst.

#### Product capability

- `transcribe`;
- `transcribe_words`;
- `decode_window`;
- file transcription;
- meeting post-pass;
- streaming finalization;
- script normalization;
- deterministic/offline startup from cache;
- air-gapped model provisioning.

#### Operational

- artifact size;
- runtime dependency size;
- supported Python/OS architectures;
- package install conflicts;
- model license;
- toolkit license;
- redistribution terms;
- source/download availability in regions relevant to contributors.

---

## 7. Proposed quantitative gates

These are engineering gates for deciding whether a candidate is worth integrating; they are not marketing claims.

### P1 supported baseline gate

For the selected baseline model:

- no catastrophic decode/hallucination on the validation corpus;
- normalized Mandarin CER target agreed before final release run and reported with corpus details;
- p95 RTF <= 0.60 on the reference CPU;
- p95 release-to-final-text <= 3.0 s for a 5 s utterance on the reference CPU;
- no new mandatory dependency beyond the existing base path except the small OpenCC script extra;
- model can be predownloaded and run with network disabled;
- all `SttEngine` methods exercised successfully.

If corpus results make these thresholds unrealistic, change the gate **before** looking at final test results and record the rationale.

### Alternative model promotion gate

A new engine should provide at least one material advantage:

- >=20% relative CER reduction on the primary Mandarin corpus, **or**
- materially better validated dialect coverage, **or**
- >=30% latency/core-cost reduction at non-inferior quality, **or**
- a capability the baseline cannot supply (for example validated Cantonese).

And it must not create an unacceptable regression in packaging, privacy or interactive performance.

A model that improves 3% relative CER while adding gigabytes of mandatory runtime is not a default candidate.

---

## 8. Corpus strategy

Use more than one source because a single Mandarin corpus can hide domain bias.

Recommended evaluation buckets:

1. **Read Mandarin, clean microphone** — establishes basic recognition ceiling.
2. **Spontaneous/conversational Mandarin** — realistic dictation disfluencies.
3. **Regional-accent Mandarin** — at least several accent groups if licensing permits.
4. **Noisy/far-field speech** — robustness.
5. **YazSes command set** — short imperative utterances.
6. **Numbers/dates/addresses/code terms** — dictation pain points.
7. **Long form** — file/meeting stability.
8. **Native-speaker private acceptance clips** — product realism, not redistributed by default.

The existing ASCEND 20-utterance sample remains a regression microset, not the sole benchmark.

Every public corpus must have:

- exact version/split;
- license;
- download procedure;
- normalization rules;
- checksum/manifest;
- scoring code;
- no committed third-party audio if redistribution is not permitted.

---

## 9. Script-normalization benchmark rule

Recognition CER and script-rendering errors must be reported separately.

For a Simplified reference:

1. score raw model output;
2. score the same output after the configured OpenCC conversion;
3. report the delta.

That prevents a correct Traditional transcription from being counted as an ASR failure while still showing what a mainland user would actually see without normalization.

Do the symmetric test for Traditional references.

---

## 10. Licensing gate

Before any non-Whisper model becomes a documented option, record:

- code/toolkit license;
- exact model-weight license;
- whether commercial use is permitted;
- whether redistribution is permitted;
- whether converting/quantizing weights changes obligations;
- required attribution;
- download host and checksum.

Do not infer model license from repository/toolkit license. FunASR explicitly warns that model licenses are checkpoint-specific.

---

## 11. Dependency policy

P1 must not add Qwen/FunASR/PyTorch to the base installation.

Alternative engines, if implemented, use optional extras and lazy imports, following the existing Parakeet/Moonshine pattern:

```text
base install
  -> faster-whisper only

optional Chinese-specialized engine
  -> explicit feature/extra
  -> lazy import
  -> own model preflight
  -> safe fallback or clear refusal
```

If an engine cannot be packaged cleanly on all desktop platforms, advertise its actual matrix rather than degrading the core installation.

---

## 12. Source notes for future implementers

Model facts in this document were checked against current upstream repositories on 2026-09-20:

- QwenLM/Qwen3-ASR — official repository and model description.
- modelscope/FunASR — official toolkit/model-zoo documentation.
- YazSes `src/yazses/stt/download.py` — currently supported faster-whisper short names.

Re-check upstream model cards, versions and licenses at implementation time. Model ecosystems change too quickly for this design record to serve as a permanent version pin.

---

## 13. Decision summary

- **P1:** multilingual Whisper `small` through current faster-whisper engine.
- **Same-runtime benchmark:** `large-v3-turbo` and `large-v3`.
- **First compact alternative prototype:** SenseVoiceSmall.
- **Chinese streaming candidate:** Paraformer-zh-streaming.
- **Dialect/broad-coverage research candidate:** Qwen3-ASR-0.6B.
- **No second runtime becomes mandatory** unless it beats the baseline on a predeclared product metric and passes licensing/packaging gates.
