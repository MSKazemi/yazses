# Small and quantized ASR models and GGUF-class runtimes — what can be compared fairly

**Date:** 2026-11-05  
**Status:** Research note (not a decision). ADR-030 freeze unchanged; no default is changed.  
**Tracking:** [NEXT-ASR-03 #794](https://github.com/MSKazemi/yazses/issues/794), parent [#787](https://github.com/MSKazemi/yazses/issues/787); siblings [#792](https://github.com/MSKazemi/yazses/issues/792), [#793](https://github.com/MSKazemi/yazses/issues/793), [#795](https://github.com/MSKazemi/yazses/issues/795), [#797](https://github.com/MSKazemi/yazses/issues/797), [#798](https://github.com/MSKazemi/yazses/issues/798)  
**Repository snapshot:** main at a241a77b6c59d65fb9265a0475d42f1a97fdfe6a (YazSes 2.48.1)  
**Builds on, and does not repeat:** the [pinned evaluation protocol](2026-11-03-pinned-offline-asr-evaluation-protocol.md), the [runtime and model provenance snapshot](state-of-the-art/2026-11-03-local-asr-runtime-provenance.md) (NeMo-Speech.cpp, parakeet.cpp, Moonshine Voice, onnx-asr runtime rows and Nemotron/Parakeet licence rows live there), and [Proposed ADR-033](../adr/adr-033-reproducible-asr-evaluation-gate.md).

> Labels: **[Verified-primary-source]** read on the upstream page on 2026-11-05; **[Upstream-claim]** a number or promise by the upstream author that YazSes has not reproduced; **[Verified-in-code]** read in this repository at the snapshot; **[Assumption]**; **[Unknown]**. Fetches were text summaries of each page, so every upstream page is "**not read in full**". No model was downloaded or run, and this note contains **no measurement of its own**. Upstream figures are quoted with the page they came from and are never YazSes results.

## 1. Answer to the issue question

Question (#794): do 4/8-bit or mixed-precision inference reduce download and RSS without unacceptable regression on names, code, accented speech or long prompts?

- **Download size: yes, as an upstream claim.** Every runtime read below publishes quantized files that are smaller than their float counterparts (section 3). [Upstream-claim]
- **RSS: [Unknown] for YazSes.** No source read reports peak RSS under a method that satisfies ADR-033 (process tree, sampled maximum, labelled method). The one upstream RSS figure found (faster-whisper README, small, int8, 1477 MB, "8 threads on an Intel Core i7-12700K", beam 5) is a different machine, model, decoder setting and method from YazSes's. [Upstream-claim]
- **Regression on names, code, accented speech, long prompts: [Unknown].** None of the pages read measures those slices for a quantized-versus-float pair. The only quantized-versus-float accuracy table found is Moonshine's, on LibriSpeech test-clean (read speech). [Upstream-claim]
- **The quantization recipe matters more than the bit-width label.** Moonshine states that Tiny Streaming scored 7.57% before 2026-07-30 because one scale factor was used per weight tensor, and 4.83% after per-channel scales; its float reference is 4.52% (reproduced) / 4.49% (paper). [Upstream-claim] CTranslate2 says int8 quantizes "only embedding and linear layers" and claims "little to no degradation" without giving a measurement. [Verified-primary-source for the wording; Upstream-claim for the effect]
- **Recommendation (adopt / defer / reject):** *defer* any new engine; *adopt* a configuration-only quantization grid over engines YazSes already ships as the first measured study (section 6, option A). Whether that study is worth running is the owner's call.

## 2. What YazSes already has (so "new" means something)

| Fact | Evidence |
|---|---|
| Three engines only: `faster-whisper`, `parakeet`, `moonshine`; an unknown name warns and falls back to faster-whisper | [Verified-in-code] `src/yazses/stt/factory.py` |
| A missing optional package raises `ModuleNotFoundError` inside the lazy import and the factory falls back with an honest log line; a language the pairing cannot do is refused, not fallen back from | [Verified-in-code] `factory.py` |
| faster-whisper already runs CTranslate2 quantized: `[stt] compute_type` defaults to `int8`; an unsupported value surfaces as `ComputeTypeUnsupportedError` | [Verified-in-code] `config.py`, `stt/faster_whisper.py`, `stt/errors.py` |
| `[stt] model` is passed to `WhisperModel(...)` unchanged, tried with `local_files_only=True` first, then downloaded once; a local directory is accepted | [Verified-in-code] `stt/faster_whisper.py`, `docs/models.md` |
| Parakeet loads through `onnx_asr.load_model(name, quantization="int8")` when `compute_type` contains `int8`, cache-first | [Verified-in-code] `stt/parakeet.py` |
| `parakeet` extra = `onnx-asr[cpu,hub]>=0.12`; `moonshine` extra = `useful-moonshine-onnx>=20251121`; enabled by `yazses features enable stt-parakeet` / `stt-moonshine` | [Verified-in-code] `pyproject.toml`, `system/features.py` |
| `sherpa-onnx>=1.13.6` and `sherpa-onnx-core` are already an optional extra (`diarization`), used for diarization only, never for ASR | [Verified-in-code] `pyproject.toml`, `recimport/diarizer.py` |
| No code mentions whisper.cpp, GGUF ASR, Vosk or distil-whisper as an engine | [Verified-in-code] grep of `src/` |
| Installed licences of the shipped runtimes: faster-whisper 1.2.1 MIT, ctranslate2 4.8.1 MIT, useful-moonshine-onnx 20251121 MIT, onnxruntime 1.28.0 MIT | [Verified-in-code] `importlib.metadata` in the synced environment (package metadata, not the upstream licence page) |
| Existing measured baselines (historical, private harness, not ADR-033 compliant) | see [docs/benchmarks.md](../../docs/benchmarks.md) and [docs/models.md](../../docs/models.md); not repeated here |

**Consequence.** Any candidate that is not one of those three engines needs a `factory.py` branch, a config value, a feature-registry entry and an extra: all `src/` changes, forbidden by the RESEARCH class under ADR-030. They are *measurable* only by an out-of-tree harness until a decision says otherwise. Two kinds of candidate need no code at all: a different `compute_type`, and a different CTranslate2 checkpoint named in `[stt] model`. [Verified-in-code; the second is an Assumption until a run resolves the model through the factory, per ADR-033's resolved-engine rule]

## 3. Candidate grid (new rows only)

Columns: licence is **as stated by the upstream page**, not legal advice. "Size" is an **[Upstream-claim]** and mixes MiB and MB as the page does. Format is what the page says it is.

| # | Candidate (upstream landing page) | Licence as stated | Quantization offered / size claims | Languages (claim) | Runtime and YazSes fit |
|---|---|---|---|---|---|
| C1 | **whisper.cpp quantized Whisper** ([repo](https://github.com/ggml-org/whisper.cpp), [HF files](https://huggingface.co/ggerganov/whisper.cpp), [models README](https://github.com/ggml-org/whisper.cpp/blob/master/models/README.md)); repo lists v1.9.5 as latest (read 2026-11-05, year not shown on the release list) | MIT (repo badge); HF card tag `mit` | Integer quantization via a `quantize` tool. HF files: tiny q5_1 31 MiB / q8_0 42 MiB; base q5_1 57 / q8_0 78; small q5_1 181 / q8_0 252. README disk/mem table (unquantized): tiny 75 MiB / ~273 MB, base 142 MiB / ~388 MB, small 466 MiB / ~852 MB. Models README lists `large-v3-turbo-q5_0` 547 MiB | Multilingual unless name has `.en` (models README) | C/C++; Python bindings are third-party (four listed, none read). **Format is ggml `.bin`, not GGUF**: the README and models README describe a "custom `ggml` format" and neither mentions GGUF. [Verified-primary-source for the wording] Fit: a new engine (`src/` change) with a new native dependency; offline-cache fit is straightforward (a file on disk) but would need its own download/hash path. Same Whisper weights as the shipped engine, so this is a *runtime and quantization* comparison, not a new model |
| C2 | **CTranslate2 quantization grid** ([doc](https://github.com/OpenNMT/CTranslate2/blob/master/docs/quantization.md)) | CTranslate2 package MIT [Verified-in-code]; page text not read for licence | Conversion types int8, int8_float32, int8_float16, int8_bfloat16, int16, float16, bfloat16, float32; load-time `compute_type` can differ from the stored type; int8 CPU needs Intel MKL/oneDNN (x86-64) or Ruy (AArch64); 4-bit AWQ is GPU-only (CC >= 7.5). Doc says conversion-time quantization "reduce[s] its size on disk" | As the Whisper model | Already shipped. The *axis* is new: compare int8 against int8_float32/float32 on the same checkpoint. Unsupported combos fall back silently inside CTranslate2 (page: weights are converted to a fallback type), so ADR-033's "resolved" identity must record the effective compute type |
| C3 | **distil-small.en** ([HF card](https://huggingface.co/distil-whisper/distil-small.en); CT2 conversion [Systran/faster-distil-whisper-small.en](https://huggingface.co/Systran/faster-distil-whisper-small.en)) | MIT (card: "inherits the MIT license from OpenAI's Whisper"; CT2 repo tag `mit`) | 166M parameters, "49% smaller", "5.6x faster" than large-v2; short-form WER 12.1 vs large-v3 8.4 in the card's table (dataset not named in the extract); card says small.en uses four decoder layers; 8/4-bit marked "Coming soon". CT2 repo stored at float16 via `--quantization float16`; file sizes not shown | English only (card) | Loadable by the **existing** faster-whisper path in principle. [Assumption] Card says its recommended long-form algorithm is chunked/sequential and that distil-medium.en or distil-large-v2 suit most applications |
| C4 | **distil-large-v3** ([card](https://huggingface.co/distil-whisper/distil-large-v3)) | MIT (card) | 756M parameters (table), F16 safetensors; "6.3x faster than large-v3"; ggml file `ggml-distil-large-v3.bin` in a separate repo; 4/8-bit "Coming soon" | English (card positions it as an English large-v3 replacement) | Named in the faster-whisper README as designed for its algorithm. Not "small" (756M); a quality-ceiling comparator for English, not a footprint candidate |
| C5 | **whisper large-v3-turbo** ([card](https://huggingface.co/openai/whisper-large-v3-turbo)) | MIT (card tag) | 809M parameters; decoder layers cut 32 to 4; "minor quality degradation"; ggml `large-v3-turbo-q5_0` 547 MiB (models README) | Tagged 99 languages; the card also says "strong ASR results in ~10 languages" and lower accuracy on low-resource languages, hallucination and repetition | Not small. Relevant to #797 as the multilingual quantized reference; Persian/Mandarin support is **not** established by the card |
| C6 | **Moonshine, quantization axis only** ([repo](https://github.com/moonshine-ai/moonshine), [models](https://github.com/moonshine-ai/moonshine/blob/main/docs/models/available-models.md), [accuracy](https://github.com/moonshine-ai/moonshine/blob/main/docs/models/accuracy.md), [licence](https://github.com/moonshine-ai/moonshine/blob/main/docs/license.md)) | MIT by default "in every language and at every size"; legacy non-streaming non-English models: non-commercial Moonshine Community License (list called exhaustive) | English non-streaming Tiny 26M / Base 58M; streaming English Tiny 34M / Small 123M / Medium 245M. Shipped streaming models are "8-bit quantized `.ort`"; LibriSpeech test-clean quantized vs reproduced float: Tiny 4.83 vs 4.52, Small 2.61 vs 2.55, Medium 2.17 vs 2.16 | English plus ar, de, ja, zh, es, tl, vi streaming rows; Korean and Ukrainian only under the Community licence | Streaming toolkit is the provenance doc's row; **new here**: it is the only candidate with a published float-versus-quantized table, and the shipped `useful-moonshine-onnx` checkpoints are the older non-streaming ones (pip package licence MIT [Verified-in-code]). Disk sizes: not on the pages read. [Unknown] |
| C7 | **sherpa-onnx ASR models** ([repo](https://github.com/k2-fsa/sherpa-onnx), [model index](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/index.html)) | Runtime Apache-2.0 (repo). **Per-model licences: [Unknown]**; the index page gave none | int8 variants listed for Parakeet TDT 0.6b-v2, Moonshine tiny, Zipformer CTC zh, TeleSpeech; Whisper tiny.en and large-v3 with a "CPU (int8)" recipe; Paraformer fp32/int8. No file sizes or memory figures on the index | Model dependent (zh/en/ja/ko/yue SenseVoice, ru NeMo, etc.) | Same ONNX Runtime family YazSes already ships; the package is **already an optional extra** for diarization (Verified-in-code), so no new dependency *class*, but no ASR adapter exists. Offers one runtime hosting several model families, which isolates model effects from runtime effects. Qwen3-ASR and other newer entries appear only as sidebar names and were not read |
| C8 | **Vosk-class (Kaldi) models** ([repo](https://github.com/alphacep/vosk-api), [models](https://alphacephei.com/vosk/models)) | Code Apache-2.0 (repo link). Models differ: most Apache-2.0, others AGPL, LGPL-3.0, GPL-3.0, MIT, and some **CC-BY-NC-SA** (e.g. French small, Filipino, Dutch) | "Small model typically is around 50Mb... about 300Mb of memory". vosk-model-small-en-us-0.15 40M, WER 9.85 (LibriSpeech test-clean); vosk-model-en-us-0.22-lgraph 128M, 7.82; vosk-model-en-us-0.22 1.8G, 5.69. Persian small fa-0.42 53M, WER 14.0 (Fleurs) / 23.4 (CV17); Chinese small-cn-0.22 42M | 20+ languages claimed, incl. Persian and Chinese rows | Not an ONNX/GGML runtime; own native library and Python binding. Its value is as a **floor reference** for footprint and for #797's low-resource languages, not as an accuracy contender: its published English WERs are higher than most other rows' upstream claims, but datasets and normalisers differ, so no ranking follows. Word-timestamp and prompt features: [Unknown] (not read) |
| C9 | **parakeet.cpp quantization grid** ([repo](https://github.com/mudler/parakeet.cpp), [licences](https://github.com/mudler/parakeet.cpp/blob/master/docs/licenses.md)); runtime already tabled in the provenance note, quantization is new here | Code MIT; weights keep source licences (Parakeet CC-BY-4.0 rows) | GGUF types f16, q8_0, q6_k, q5_k, q4_k for ASR models. `tdt_ctc-110m-q8_0.gguf` "178 MB"; `parakeet-bundle-standard` 1.1 GB (0.6B v3); q8_0 "37% of the f32 size". Claimed "WER 0 against NeMo" with quant level unstated | `tdt_ctc-110m` English; v3 25 European languages | **GGUF-class**. The 110M English hybrid model is the smallest NVIDIA row found and the one genuine "small model" lead: licence CC-BY-4.0 per the licences page. [Upstream-claim] Fit as in the provenance note (native, new engine, `src/` change) |

Rows already covered in the provenance note (not repeated): NeMo-Speech.cpp (Q8_0 is the only quantization it names, CPU row "27 ms per 160 ms chunk", CPU model unnamed, per the repo page) and Moonshine Voice runtime/streaming behaviour.

### 3.1 How each would sit in the optional-extra / lazy-import / offline-cache model

This restates AGENTS.md rules 2, 3 and 6 against each row; it is a design note, not a plan to build.

- **C1 whisper.cpp.** [Assumption] Shape of an adapter: an `SttEngine` implementation under `stt/`, imported inside `build_engine` so a missing package raises `ModuleNotFoundError` and the factory falls back with its existing log line; a new optional extra and a `stt-*` feature entry. Offline cache: a single `.bin` file, hashable, verified before use; a Hub download would be a separate operator step (the evaluation protocol's rule), never a silent fetch. A native binary or third-party binding adds a platform matrix YazSes would own.
- **C2 CTranslate2 types.** [Verified-in-code] Nothing to add: `compute_type` already flows to the loader. The open item is only that an unsupported value raises `ComputeTypeUnsupportedError` with a message naming valid types, which makes an "unsupported" cell recordable as such rather than as an error rate.
- **C3, C4, C5 Whisper variants.** [Assumption] Same engine, different `[stt] model`; no extra needed. The language guard treats a custom name ending in `.en` as English-only and reports other custom names as `unknown` rather than refusing, so a multilingual claim for C5 would be unchecked by the guard. [Verified-in-code] `language/capability.py`
- **C6 Moonshine.** [Verified-in-code] The adapter accepts only names starting `moonshine/` and otherwise uses `moonshine/base`; it ignores `initial_prompt` and returns no word timings. The streaming checkpoints are not reachable through this adapter.
- **C7 sherpa-onnx.** [Assumption] The `diarization` extra shows the pattern for naming `sherpa-onnx-core` explicitly (the `pyproject.toml` comment records an install failure when it was omitted), which any ASR use would inherit. Model files would be local-directory loads, matching the cache-first rule.
- **C8 Vosk.** [Assumption] Would be a separate native dependency family (not ONNX), so it carries the largest new-packaging cost per unit of expected benefit among the rows.
- **C9 parakeet.cpp.** [Assumption] As C1, with GGUF weights fetched from a Hub repo that the upstream page names; per-file licences must be recorded, since conversion does not change them.

## 4. Excluded or held back, and why

| Item | Verdict | Reason (rule) |
|---|---|---|
| Moonshine legacy non-English checkpoints (Arabic, Japanese, Korean, Mandarin, Spanish, Ukrainian, Vietnamese) | **Exclude** | Non-commercial Community License per Moonshine's licence page; incompatible with YazSes distribution without separate approval |
| Vosk models under CC-BY-NC-SA, AGPL or GPL | **Exclude from any candidate set** | Licence class; the per-model licence column on the models page decides, and NC rows are out |
| Phonon-2.5, parakeet-ultra, parakeet-redux (packed ternary, "242 MB"/"213 MB") | **Hold** | Provenance note already defers these to #794; the licences page states Phonon training audio "includes CHiME-6 (CC-BY-SA-4.0) and SPGISpeech (Kensho terms)" and says whether share-alike reaches the weights is "a legal question that this project does not settle". Redux packed kernels use AVX2/AVX-512 VNNI or aarch64 dotprod; other targets "use a slow scalar kernel". Needs a legal read before any arm. [Upstream-claim] |
| Nemotron 3.5 (OpenMDW-1.1) and nemotron-speech-streaming (NVIDIA Open Model License) at Q8_0 | **Hold** | Licence review pending per the provenance note; a different model, not a smaller build |
| Any server mode, HTTP/WebSocket listener or auto-downloader around a runtime | **Exclude** | ADR-019 egress inventory; the evaluation protocol already rules this out |
| Any cloud or API transcription as a "small model" comparator | **Exclude** | AGENTS.md rule 1 (nothing leaves the machine) |
| Any new default, new extra, feature-registry entry or `src/` adapter | **Out of this issue's class** | ADR-030 freeze; AGENTS.md rules 2, 3 and 7 apply only if a later accepted decision authorises delivery |
| 4-bit AWQ in CTranslate2 | **Not applicable on CPU** | The page says GPU only (CC >= 7.5); the CPU-first goal gets int8 only from this runtime |

## 5. What is missing to compare each candidate fairly under ADR-033

Common to all rows (the ADR's own gate, restated only to say what is absent):

- **Revision pin:** no row has been resolved to an immutable model revision and file SHA-256; "latest" release names (whisper.cpp v1.9.5, parakeet.cpp v0.6.1, Moonshine Voice v0.1.5) are not full commit SHAs. [Unknown]
- **Normaliser:** upstream WERs use their own (Open ASR Leaderboard average for Moonshine English; LibriSpeech test-clean for Vosk and the distil usage snippet; Fleurs and CV17 for Vosk Persian). None is the ADR-033 pinned Whisper `EnglishTextNormalizer` profile. Upstream numbers must not be pooled with each other or with YazSes's. [Verified-primary-source for the dataset names; Assumption that the normalisers differ]
- **Corpus and leakage:** nothing is established about which candidates trained on LibriSpeech or Common Voice. [Unknown]
- **Hardware:** all upstream speed and memory figures came from other machines (e.g. an i7-12700K; "8 threads on a 20-core x86 host" for parakeet.cpp; an unnamed CPU for NeMo-Speech.cpp). Nothing exists for the 8 GB / 16 GB CPU-first laptops ADR-033 names. [Verified-primary-source for the stated hardware]

Per-row gaps:

| # | Gap that blocks a fair comparison |
|---|---|
| C1 | Same-weight pairing needs the **same checkpoint** in CTranslate2 and ggml form and a record that quantization schemes differ (q5_1/q8_0 versus CT2 int8); decoder settings (beam, temperature fallback, long-form algorithm) are not equivalent by default. Third-party Python bindings unread, so the in-process memory method is [Unknown]; ADR-033 needs process-tree peak RSS, which an external binary makes harder |
| C2 | Effective compute type after CTranslate2's fallback; CPU ISA (MKL/oneDNN vs Ruy) per machine |
| C3, C4 | Short-form versus chunked long-form behaviour (card text); the card's WER dataset is unnamed in the extract; distil-small.en has no int8 reference measurement anywhere read |
| C5 | Per-language evidence for the languages YazSes cares about (#797); hallucination on silence (the evaluation protocol's silence-stress slice) |
| C6 | Disk sizes for quantized files; the float-vs-quantized table covers streaming checkpoints, not the non-streaming Tiny/Base that YazSes ships |
| C7 | Per-model licence, size and exact revision for every model; which of those the ONNX files are redistributable |
| C8 | Normaliser-comparable English numbers; word-timing behaviour; per-model licence filter |
| C9 | Which quant levels the "WER 0" claim covers; the quantization.md page (cited by the README) was not read; Linux/Windows/macOS binary requirements for the exact build |

Names, code and accent slices are absent from **every** row: no upstream page read states a measurement on spoken identifiers, accented English or prompts longer than 30 s for any quantized build. That is the issue's core question and it can only be answered by the P4 constructed-stress and P1/P2 slices in the evaluation protocol, plus a code/identifier set that does not yet exist (belongs to #793/#797). [Unknown]

### 5.1 Sketch of the pinned grid, if an owner authorises a run (design only, nothing executed)

Factors are separate columns so that no result credits the wrong cause:

| Factor | Levels to pin | Rule |
|---|---|---|
| Model weights | one checkpoint per block (e.g. base.en; distil-small.en) with immutable revision and file SHA-256 | A conversion is a different artifact; record its hash |
| Quantization | the upstream-named type (int8, int8_float32, q5_1, q8_0, q4_k, ...) | One factor varied per block; effective type after any fallback is recorded |
| Runtime | CTranslate2, ONNX Runtime, ggml, ... | Varied only in blocks that hold weights fixed |
| Hardware | named CPU, RAM, threads, power profile | Speed compared only on the same machine |
| Slices | P1 read English, P4 stress (silence, long pauses), plus a to-be-built identifier/code set and an accent slice from #797 | The last two do not exist yet and are not available from any source read |

Negative cases to keep as first-class rows (ADR-033 item 3): unsupported compute type on a CPU, load failure, factory fallback, empty output, catastrophic insertion, a model licence that blocks the arm.

Stop/go thresholds are **not** proposed here. The only placeholders in the repository are ADR-033's +0.5 percentage-point and 20% p95 margins, which that ADR itself marks as unapproved; this note neither adopts nor adjusts them.

## 6. Decision options for the owner (no recommendation to ship anything)

| Option | What it is | Cost / class | Why it might deserve a measured ADR-033 run |
|---|---|---|---|
| **A. Configuration-only quantization grid** | Existing faster-whisper base.en/small.en at int8 versus a higher-precision `compute_type` on the same CPU; existing Parakeet with and without `quantization="int8"` if onnx-asr offers the non-quantized variant [Unknown] | No `src/` change; model downloads are a separate operator step | Answers the issue question for the engines users already run; the cheapest valid pairing (same weights, one factor). Rows C2 (and C6 for Moonshine if a float path exists, [Unknown]) |
| **B. One smaller-model arm via the existing path** | `Systran/faster-distil-whisper-small.en` (C3) in `[stt] model`, against tiny.en/base.en/small.en | No `src/` change [Assumption: confirm the factory resolves it, with fallback treated as INVALID] | A model-size and architecture comparison with an already-licensed MIT checkpoint; English only |
| **C. External runtime arm, same Whisper weights** | whisper.cpp q5_1/q8_0 versus CT2 int8 (C1), out-of-tree harness | Needs a native build and a harness outside the product; not an engine | The only way to test the GGML-quantization half of the issue; but the pairing is weak unless exact-weight equivalence and decode-policy equivalence are shown |
| **D. sherpa-onnx as a single host for several int8 families** | Parakeet v2 int8, Moonshine tiny int8, Whisper int8 under one runtime (C7) | Out-of-tree harness; package already an optional extra | Separates model effects from runtime effects; blocked until per-model licences are read |
| **E. parakeet.cpp 110M/0.6B quant ladder** | q8_0/q6_k/q5_k/q4_k on `tdt_ctc-110m` and v3 (C9) | Out-of-tree harness; GGUF-class | The one genuine 4-bit-ish ladder with a CC-BY-4.0 English small model; defer behind #792's comparator work |
| **F. Do nothing now** | Wait for ADR-033 acceptance and the #793 analyzer | None | Valid: ADR-033 is only Proposed, and running options C-E before the analyzer exists would produce exactly the uninspectable results the ADR rejects |

**Reading of the evidence, labelled as such.** [Assumption] A is the lowest-cost, highest-validity first step, B the next; C-E should wait for the #793 analyzer and a second-machine rerun. Owner decision needed on: (1) whether A/B are authorised as RESEARCH-class runs on named hardware, (2) which English slice is primary (ADR-033 acceptance question), (3) whether any candidate beyond MIT/Apache/CC-BY-4.0 licence classes is admissible.

## 7. Evidence that would change the ranking

- A same-checkpoint, same-machine int8 versus float32 result on the P4 stress and identifier slices showing a **large** regression (that would demote A's premise and raise the value of per-channel or mixed recipes, as Moonshine's own history suggests).
- A resolved confirmation that onnx-asr can run Parakeet unquantized (or that only int8 files exist), which changes whether A's Parakeet half is a valid pair.
- Per-model licences for sherpa-onnx families (promotes or removes D).
- An independent reproduction of the "WER 0 against NeMo" claim at q4_k/q5_k (promotes E), or a counter-example.
- A legal determination on Phonon/Redux weights (reopens the Hold row).
- A confirmed GGUF loader in whisper.cpp (upstream pages read describe ggml `.bin` only), which would merge C1 and C9 into one format family; absence of that is the current status. [Unknown beyond the pages read]
- Real user need: evidence from consented, non-telemetry channels (for example volunteered issue reports) that disk size or RSS blocks installs; none was consulted for this note, so the value of a footprint win is currently a hypothesis. [Unknown]

## 8. Primary sources read (2026-11-05, text summaries, not read in full)

whisper.cpp [README](https://github.com/ggml-org/whisper.cpp), [releases](https://github.com/ggml-org/whisper.cpp/releases), [models README](https://github.com/ggml-org/whisper.cpp/blob/master/models/README.md), [HF ggml files](https://huggingface.co/ggerganov/whisper.cpp); CTranslate2 [quantization doc](https://github.com/OpenNMT/CTranslate2/blob/master/docs/quantization.md); [faster-whisper](https://github.com/SYSTRAN/faster-whisper); Distil-Whisper cards for [small.en](https://huggingface.co/distil-whisper/distil-small.en) and [large-v3](https://huggingface.co/distil-whisper/distil-large-v3) and the [CT2 conversion](https://huggingface.co/Systran/faster-distil-whisper-small.en); [whisper-large-v3-turbo](https://huggingface.co/openai/whisper-large-v3-turbo); Moonshine [repo](https://github.com/moonshine-ai/moonshine), [available models](https://github.com/moonshine-ai/moonshine/blob/main/docs/models/available-models.md), [accuracy](https://github.com/moonshine-ai/moonshine/blob/main/docs/models/accuracy.md), [licence](https://github.com/moonshine-ai/moonshine/blob/main/docs/license.md); [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) and its [pretrained model index](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/index.html); Vosk [repo](https://github.com/alphacep/vosk-api) and [models page](https://alphacephei.com/vosk/models); [onnx-asr](https://github.com/istupakov/onnx-asr) (README and docs home; the quantization parameter is not documented there) and the [Parakeet v2 ONNX card](https://huggingface.co/istupakov/parakeet-tdt-0.6b-v2-onnx) (file list and sizes not visible); [parakeet.cpp](https://github.com/mudler/parakeet.cpp) and its [licences page](https://github.com/mudler/parakeet.cpp/blob/master/docs/licenses.md); [NeMo-Speech.cpp](https://github.com/NVIDIA/NeMo-Speech.cpp).

**Not obtained:** the PyPI page for `useful-moonshine-onnx` failed to load (licence taken from installed metadata instead); parakeet.cpp `quantization.md`, NeMo-Speech.cpp `BENCHMARK.md`, Moonshine's quantization doc, and the full GitHub release notes for whisper.cpp were not read. A web search found no evidence that whisper.cpp reads GGUF, but it returned mirrors and forks and is not conclusive.

**Status line.** Research note (not a decision). ADR-030 freeze unchanged; no default is changed. No model downloaded, no benchmark run, no `src/` change; every number above is an upstream claim attributed to its page.
