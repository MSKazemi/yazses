# Local ASR runtime and model provenance — 2026-11-03

**Status:** research snapshot / architecture input only; not an approved backend, benchmark result, or ADR.  
**Tracking:** [NEXT-ASR-01 #792](https://github.com/MSKazemi/yazses/issues/792), parent [#787](https://github.com/MSKazemi/yazses/issues/787); follow-ups [#793](https://github.com/MSKazemi/yazses/issues/793) (measurements), [#794](https://github.com/MSKazemi/yazses/issues/794) (quantization), [#795](https://github.com/MSKazemi/yazses/issues/795) (accelerators), [#798](https://github.com/MSKazemi/yazses/issues/798) (decision).  
**Read on:** 2026-11-03. The descriptions of third-party projects are *upstream claims* unless explicitly described as a review of YazSes code. No external model was downloaded or run for this report. Upstream version numbers can change after this snapshot.  
**Binding product direction:** [ADR-030](../../adr/adr-030-agent-era-direction.md), which freezes unrelated capabilities and changes to defaults pending evidence.

## Executive finding

There are **two independent questions**: (1) whether a new *runtime* executes the **same model** better; and (2) whether a different *model and runtime together* yield better user results. Comparing the two as if they are identical would produce a misleading engine recommendation.

- **Existing YazSes:** three SttEngine choices: faster-whisper / CTranslate2, Parakeet TDT v2 through onnx-asr / ONNX Runtime, and older Moonshine through useful-moonshine-onnx / ONNX Runtime. The two latter choices are optional and lazy loaded. This is verified by the source links below, not a fresh hardware test.
- **NeMo-Speech.cpp:** official NVIDIA C++/ggml runtime with support for Parakeet v3 and Nemotron streaming models. An attractive **research-only first candidate**, because a native C interface and vendor model/feature matrix are available. A Parakeet-v3 experiment can compare **runtime against runtime**; a Nemotron-3.5 experiment is a **different-model** study.
- **parakeet.cpp:** a separate C++/ggml implementation of several *overlapping NVIDIA Parakeet checkpoints*. This is an **alternative runtime**, not automatic evidence of a new recognizer. It also offers converted/quantized weights and newer derivative models, which need separate attribution, accuracy and licensing review.
- **Moonshine Voice:** a newer Moonshine native streaming toolkit with its own streaming checkpoint family, speculative decoding and domain/keyterm customization. It is **not equivalent** to YazSes's older useful-moonshine-onnx dependency or its moonshine/base checkpoint, so benchmark it as a *new combined system*, not a transparent library upgrade.
- **Decision now:** investigate these candidates, but **defer all default changes, new production dependencies, feature-registry entries and public accuracy claims**. Validate actual usefulness before reopening an ADR.

## 1. YazSes as-built inventory (code-reviewed)

| Component | Shipped path / model | Confirmed interface and limitations | Primary local source |
| --- | --- | --- | --- |
| Engine routing | faster-whisper by default, optional parakeet and moonshine | Dynamic dispatch in factory; unknown/missing engines warn and fall back; unsupported languages are explicitly refused | [stt/factory.py](../../../src/yazses/stt/factory.py) |
| Engine seam | SttEngine | transcribe, transcribe_words and decode_window; no native push-stream API in this seam | [stt/base.py](../../../src/yazses/stt/base.py) |
| Whisper | faster-whisper/CTranslate2, base.en default | Multilingual only with non-.en model; source already measures CPU latency and memory on one machine | [docs/models.md](../../../docs/models.md) |
| Parakeet | onnx-asr, nemo-parakeet-tdt-0.6b-v2 | Existing adapter returns no word-timestamp list; accepts but ignores initial_prompt; decode_window re-decodes a window, not a stateful streaming API | [stt/parakeet.py](../../../src/yazses/stt/parakeet.py) |
| Moonshine | useful-moonshine-onnx, moonshine/base | Adapter returns no per-word timings; ignores initial_prompt; enforces upstream short/64-second bounds by splitting long utterances | [stt/moonshine.py](../../../src/yazses/stt/moonshine.py) |
| Dependency policy | onnx-asr[cpu,hub] >=0.12 optional; useful-moonshine-onnx >=20251121 optional; faster-whisper >=1.2.1 base | Minimum package constraints **are not** an exact lock snapshot. The evaluator must record actual resolved versions and hashes. | [pyproject.toml](../../../pyproject.toml) |

A model's upstream word-timestamp capability must not be advertised as a YazSes feature when the **adapter** discards it. Likewise a runtime supporting streaming is not proof that YazSes's existing LocalAgreement window decoder uses stateful streaming.

## 2. Upstream runtime comparison (primary-source snapshot)

| Candidate and research revision | Execution and platform claims | Model family / important distinction | Streaming, timestamps, and UX caveats | Code license / evidence level |
| --- | --- | --- | --- | --- |
| **Existing faster-whisper**; YazSes >=1.2.1 | Python + CTranslate2, CPU-int8; existing cross-platform package | Whisper; baseline, **not a new model family** | Existing YazSes word output; current model and profile determine language support | faster-whisper MIT; code-reviewed as integration; local measured baselines in docs |
| **Existing onnx-asr**; YazSes >=0.12 | Python + ONNX Runtime; upstream claims Windows/Linux/macOS CPU and multiple optional accelerators | NVIDIA Parakeet v2 model in YazSes; onnx-asr also supports v3 and other NeMo model architectures | Existing adapter re-decodes windows and does not return words even if upstream model family can provide timestamps | onnx-asr MIT; upstream capabilities not hardware-verified in YazSes |
| **NeMo-Speech.cpp v0.3.0** (release 2026-10-30; release displays commit prefix 20999cc) | C++/ggml; upstream documents CPU/CUDA/Vulkan/Metal, Linux/Windows and Apple-silicon macOS packages; native C SDK, optional server | Parakeet TDT v3 / CTC 1.1B and Nemotron Speech Streaming / Nemotron 3.5; the latter are **different checkpoints**, not faster execution of Parakeet v2 | Native cache-aware RNNT streaming and decoder-grid word times; Parakeet TDT in its documented matrix has **no streaming endpointing or word boosting**; distinguish from buffered re-decode | NVIDIA-authored code Apache-2.0, third-party notices apply; upstream claim only |
| **parakeet.cpp v0.6.1** (release 2026-10-07/08; prefix 5c9b0fb) | C++/ggml/GGUF; CPU, CUDA, Metal, Vulkan advertised, C API; published Linux/Windows/macOS release artifacts | Overlaps with Parakeet v2/v3; also custom conversions and derivative Phonon/Ultra/Redux models; **same checkpoint does not become a different model when converted** | Upstream has live streaming paths for supported models, but support varies by checkpoint; published README flags unvalidated GPU paths and some specialized-model restrictions | MIT code; original model licenses survive conversion; upstream claim only |
| **Moonshine Voice v0.1.5** (release 2026-08-24; prefix 234f60f) | Native streaming toolkit; upstream lists Python, JS/WASM, Android, iOS, Linux, Windows, macOS | New streaming Moonshine checkpoints (34M Tiny, 123M Small, 245M Medium English listed upstream). **Not** a drop-in package upgrade of useful-moonshine-onnx | Streaming with speculative decoding, keyterms/context customization; verify words, chunking, long-pauses and the final-commit contract against YazSes | MIT core, third-party notices and per-checkpoint terms; upstream claim only |

**Version-source discrepancy:** parakeet.cpp's README still states that v0.5.0 is the latest tagged release, while its *releases* page shows v0.6.1. For any experiment, use the release/tag reference plus its resolved full commit SHA, **not** an unpinned branch or a stale README assertion. Phonon-2.5 announcements dated 2026-10-24 are on the post-v0.6.1 branch history, and therefore are not presumed part of the v0.6.1 binary.

### Upstream release and capability sources

- [NeMo-Speech.cpp releases](https://github.com/NVIDIA/NeMo-Speech.cpp/releases/tag/v0.3.0); [runtime README](https://github.com/NVIDIA/NeMo-Speech.cpp); [supported ASR models](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/asr/models.md); [feature matrix](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/asr/customization.md); [SDK / server design](https://github.com/NVIDIA/NeMo-Speech.cpp/blob/main/docs/clients.md). Release tag and commit prefix were inspected; full SHA remains a required freeze artifact.
- [parakeet.cpp releases v0.6.1](https://github.com/mudler/parakeet.cpp/releases/tag/v0.6.1); [README](https://github.com/mudler/parakeet.cpp); [per-model licenses](https://github.com/mudler/parakeet.cpp/blob/master/docs/licenses.md).
- [Moonshine Voice releases v0.1.5](https://github.com/moonshine-ai/moonshine/releases/tag/v0.1.5); [streaming changelog](https://github.com/moonshine-ai/moonshine/blob/main/CHANGELOGS.md); [available models](https://github.com/moonshine-ai/moonshine/blob/main/docs/models/available-models.md); [license exceptions](https://github.com/moonshine-ai/moonshine/blob/main/docs/license.md).
- [onnx-asr source, supported models and runtime backends](https://github.com/istupakov/onnx-asr); [faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## 3. Model and redistribution provenance — independent of the runtime

Do not equate **Apache-2.0/MIT application code** with unrestricted **model weights**. GGUF conversion and quantization are derivative artifacts: original model conditions, notices, attribution, and any separate dataset terms still need review. This is a technical inventory, **not legal approval**.

| Checkpoint / artifact | Published model license at review | Status for YazSes | Required before distribution or model promotion |
| --- | --- | --- | --- |
| nvidia/parakeet-tdt-0.6b-v2 (current optional Parakeet baseline) | **CC-BY-4.0** | Already referenced through onnx-asr; do not assume the PyPI runtime license applies to weights | Exact model/cache revision, source and attribution notice; compatible redistribution workflow |
| nvidia/parakeet-tdt-0.6b-v3 (candidate same-weight cross-runtime comparison) | **CC-BY-4.0** | Candidate; separate from v2 accuracy baseline | Freeze a single model revision, same acoustic inputs and decoding conditions; pin each ONNX/GGUF conversion hash |
| nvidia/nemotron-3.5-asr-streaming-0.6b | **OpenMDW-1.1** | **Review required**, not permissive by assumption; new streaming model | Owner/legal license review, full model files and tokenizer hashes, deployment terms and dependencies |
| nvidia/nemotron-speech-streaming-en-0.6b | Upstream references OpenMDW terms for the Nemotron family; exact checkpoint terms must be verified | Research candidate only | Read exact checkpoint card and full governing terms before download/use |
| Moonshine Voice new streaming ASR checkpoints | **MIT** per Moonshine's documented streaming-model license; third-party components separately licensed | Candidate; don't conflate with older non-streaming checkpoints | Pin exact English/multilingual model version, runtime assets, tokenizer/ORT file hashes and required notices |
| Moonshine **legacy** non-English non-streaming checkpoints | Moonshine Community License (non-commercial) for specifically listed models | Do **not** infer these are MIT | Check exact language/architecture and obtain separate approval if proposed |
| Phonon-2.5 / packed GGUF derivative | **CC-BY-4.0** listed upstream, with dataset provenance caveats | Secondary #794 research, **not** an automatically approved small-model recommendation | Review model card, training-data restrictions, converted weights and 242 MB packed variant separately |

Primary license evidence: [Parakeet v2 model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2), [Parakeet v3 model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), [Nemotron 3.5 model card](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b), [Moonshine licenses](https://github.com/moonshine-ai/moonshine/blob/main/docs/license.md), [parakeet.cpp conversion provenance](https://github.com/mudler/parakeet.cpp/blob/master/docs/licenses.md). A claim that a *model is available* does not establish that all required model and dataset rights are compatible with YazSes packaging.

### Provenance record required for **each** experimental run

At setup time record: runtime repository, **full source commit SHA**, build flags and toolchain, package versions, runtime license and transitive notices; checkpoint repository and **immutable model revision**, list of file SHA-256s, tokenizer/normalizer/aligner revisions, published weight license and attribution terms; conversion pipeline and quantization type (if any); device OS/architecture/CPU/GPU/NPU/driver, RAM, number of threads and power profile. Save only a **local** provenance manifest until reviewed for publication. Do not publish cache directories, personal recordings or private transcripts.

## 4. Feasible experimental design (handoff to #793)

Do not run a one-dimensional leaderboard and call the fastest recognizer the winner. Evaluate two explicit experiments:

**A — Controlled runtime comparison, same weights.** Obtain exactly the same permitted Parakeet-v3 checkpoint and run the equivalent ONNX and native GGUF paths on **the same machine and fixed clip set**. Compare matched decoding policies; vary quantization as a second labelled factor. Include the existing Parakeet v2 implementation separately, so model-generation changes cannot be credited to the runtime. If exact conversion/model parity cannot be established, label the comparison as *system comparison*, not pure runtime speedup.

**B — End-to-end candidate comparison, different models.** Compare Nemotron 3.5 and Moonshine streaming candidates against shipped faster-whisper, onnx-asr/Parakeet v2 and useful-moonshine-onnx on the identical permitted workload. Include short utterances (0.5–10 seconds), long prompts with deliberate pauses, spoken code/identifiers, silence/noise, and language-specific licensed material. The dataset selection and release-grade metrics belong to [#793](https://github.com/MSKazemi/yazses/issues/793) and [#797](https://github.com/MSKazemi/yazses/issues/797); this is **not** an already-executed benchmark.

Suggested per-run metrics: WER/CER (with fixed normalizer and error inventory), critical-token exact match (commands, filenames, numbers), time-to-first-stable-partial, time-to-final-commit, partial rollback/churn and accidental text injection, p50/p95 latency, real-time factor, cold load, peak RSS, model download size and cold-start friction. Report results by OS and device; do not transfer an upstream 4090 result to a 4-core laptop. Capture failures, non-booting binaries, unsupported languages and missing timestamps as negative results.

**Offline/privacy invariant:** model provisioning must be deliberate and cache-first; once installed, run with egress blocked. The preferred candidate uses an **in-process native SDK** or narrowly controlled local process with no listening socket. NeMo-Speech.cpp's optional HTTP/WebSocket server is **not** a suitable YazSes default integration. No telemetry, background auto-download, arbitrary remote endpoint, silent transcript logging or captured private user data.

**Safety and ABI:** a future adapter would need to honor SttEngine's transcribe, transcribe_words and decode_window or explicitly propose a versioned streaming seam for review. Missing word timings must remain an honest empty list; unsupported language must refuse, not silently yield English; finalization must never delete text not previously typed. Native crashes, model failures and backend fallback need actionable user-facing diagnostics. A new backend also brings platform/architecture packaging, native ABI and optional-dependency maintenance cost.

## 5. Research decision and work routing

| Option | Verdict | Why / next gate |
| --- | --- | --- |
| Keep current engines and improve verified reliability | **Adopt now** (already in approved Pillar 1) | No new feature wave; existing validation work and [#645](https://github.com/MSKazemi/yazses/issues/645) remain canonical |
| NeMo-Speech.cpp v0.3.0 as **research-only baseline** | **Investigate first** | Broad model coverage, C SDK, cross-platform intent; validate same-weight Parakeet comparison and code/weight licensing separately |
| Moonshine Voice streaming as **distinct model + runtime** | **Investigate next** | Streaming and contextual keyterms are plausible user benefits; validate API/language/latency on consumer CPUs |
| parakeet.cpp as a second native-runtime comparator | **Investigate selectively** | Useful controlled GGUF/quantization comparator; duplicate Parakeet model family and packaging surface is an adoption cost |
| Phonon-2.5 packed / Ultra / Redux derivatives | **Defer to #794** | Complicated model/data provenance, specialized limits and model-specific evidence; don't infer a speed/accuracy win from a smaller download |
| Nemotron 3.5 **as a new default** | **Reject for now** | Different checkpoint, unreviewed OpenMDW model terms, no YazSes CPU/accuracy evidence, violates default-change decision gate |
| Add NeMo server HTTP, an auto-downloader or a mandatory runtime | **Out of scope** | Contradicts privacy/egress, dependency and breadth boundaries |

**No ADR is necessary merely to conduct this audit**. A future optional integration or change of default, if experiments and genuine users justify it, belongs under [#798](https://github.com/MSKazemi/yazses/issues/798) and the existing Parakeet decision [#645](https://github.com/MSKazemi/yazses/issues/645), with a **proposed** ADR and an explicit ADR-030 authorization before delivery.

## 6. Unverified items / next evaluator's checklist

- [ ] Resolve the **full immutable runtime commit SHA** for NeMo-Speech.cpp v0.3.0, parakeet.cpp v0.6.1 and Moonshine Voice v0.1.5. The short commit prefixes above are release-page identifiers **not sufficient for a reproducible build**.
- [ ] Resolve each exact model-weight revision, file SHA-256, conversion path and full license obligations; obtain a licensing determination before shipping weights.
- [ ] Confirm Linux glibc baseline, Intel/Apple-silicon Mac runtime support and Windows DLL/CPU instruction requirements against the **exact selected binary**, not the project's broad README.
- [ ] Verify Python/C ABI integration and initial-prompt/timestamps behavior, including model-dependent NeMo RNNT vs TDT constraints.
- [ ] Acquire authorized, clearly licensed audio fixtures; keep private recordings and unlicensed speech out of GitHub. Use a frozen script/manifest from #793.
- [ ] Benchmark at least one ordinary CPU-first Linux machine, then macOS/Windows via named hardware testers before making cross-platform claims.
- [ ] Record a negative-result/no-go decision if actual final-dictation quality, deployment cost or licensing does not improve.

## Relationship to existing decisions

This research does **not** modify [ADR-030](../../adr/adr-030-agent-era-direction.md), the default-engine [#645](https://github.com/MSKazemi/yazses/issues/645), Mandarin candidate evaluation [#503](https://github.com/MSKazemi/yazses/issues/503), Android engine ownership [#81](https://github.com/MSKazemi/yazses/issues/81), or the shipped feature registry. A claim based on primary upstream documentation is a **candidate property**, not an experimentally verified YazSes product property.
