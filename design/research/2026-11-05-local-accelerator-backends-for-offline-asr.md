# Research: local accelerator backends (CPU, CUDA, ROCm, OpenVINO, Apple, QNN, DirectML, Vulkan) for offline ASR

**Status:** Research note (not a decision). ADR-030 freeze unchanged; no default is changed.
**Issue:** [NEXT-ASR-04 #795](https://github.com/MSKazemi/yazses/issues/795); parent [#787](https://github.com/MSKazemi/yazses/issues/787); siblings [#792](https://github.com/MSKazemi/yazses/issues/792), [#793](https://github.com/MSKazemi/yazses/issues/793), [#794](https://github.com/MSKazemi/yazses/issues/794), [#797](https://github.com/MSKazemi/yazses/issues/797); synthesis [#798](https://github.com/MSKazemi/yazses/issues/798).
**Snapshot:** YazSes `main` at `a241a77b6c59d65fb9265a0475d42f1a97fdfe6a`; upstream pages read 2026-11-05.
**Reuses vocabulary from:** [runtime/provenance snapshot](state-of-the-art/2026-11-03-local-asr-runtime-provenance.md), [pinned evaluation protocol](2026-11-03-pinned-offline-asr-evaluation-protocol.md), Proposed [ADR-033](../adr/adr-033-reproducible-asr-evaluation-gate.md) ("resolved engine", "system comparison" vs "runtime comparison", "negative result"). Binding policy: [ADR-030](../adr/adr-030-agent-era-direction.md), [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md).
**Not done:** no measurement, no GPU/NPU job, no model or wheel download, no `src/` change. The only command run on a machine was a read-only capability probe (section 4).

## Evidence labels

- **[Verified-primary-source]** the statement appears in the cited vendor/upstream page as returned by the fetch tool. Every fetch was a **text summary, not a full read**; a page marked "not read in full" may say more or less than recorded here.
- **[Upstream-claim]** a vendor performance, "best-in-class" or "x3 faster" assertion. Never a YazSes result.
- **[Verified-in-code]** read in this repository at the snapshot, or observed by running read-only code locally.
- **[Assumption]** my inference; named so it can be struck. **[Unknown]** not established by anything read.

## 1. Executive answer

**Defer every accelerator backend; adopt a no-hardware "truthful device reporting" hardening as a candidate for the owner; reject any mandatory or default accelerator.** This is a recommendation for the owner, not a decision.

- Upstream documentation shows a real but **fragmented** accelerator landscape: each runtime supports a different subset of {OS x vendor x driver}, and **no row of the matrix below is supported by one runtime on all three desktop OSes** (section 3). [Verified-primary-source, from the cells cited there]
- The shipped default (CPU, int8, faster-whisper) already works on all three OSes with no driver. Any accelerator adds a driver surface YazSes cannot control. [Verified-in-code, section 4]
- The one thing YazSes can fix and test without hardware is **honesty**: today `yazses status` reports engine and checkpoint but **not** the device or compute type actually running (section 4). [Verified-in-code]
- Every statement about speed, power or thermals is [Unknown] here. #795 asks for "repeatable wins"; nothing in this note shows one.

## 2. Primary sources (all read 2026-11-05; all "not read in full", fetched as text summaries)

| ID | Source | ID | Source |
|---|---|---|---|
| S1 | [CTranslate2 hardware support](https://opennmt.net/CTranslate2/hardware_support.html) | S13 | [ORT MIGraphX EP](https://onnxruntime.ai/docs/execution-providers/MIGraphX-ExecutionProvider.html) |
| S2 | [CTranslate2 README](https://github.com/OpenNMT/CTranslate2) | S14 | [OpenVINO system requirements (repo source, master)](https://github.com/openvinotoolkit/openvino/blob/master/docs/articles_en/about-openvino/release-notes-openvino/system-requirements.rst) |
| S3 | [CTranslate2 Transformers guide (Whisper)](https://opennmt.net/CTranslate2/guides/transformers.html) | S15 | [OpenVINO NPU device (repo source, master)](https://github.com/openvinotoolkit/openvino/blob/master/docs/articles_en/openvino-workflow/running-inference/inference-devices-and-modes/npu-device.rst) |
| S4 | [ctranslate2 on PyPI](https://pypi.org/project/ctranslate2/) | S16 | [openvino.genai README](https://github.com/openvinotoolkit/openvino.genai) |
| S5 | [faster-whisper README](https://github.com/SYSTRAN/faster-whisper) | S17 | [intel/linux-npu-driver](https://github.com/intel/linux-npu-driver) |
| S6 | [ORT execution providers index](https://onnxruntime.ai/docs/execution-providers/) | S18 | [whisper.cpp README](https://github.com/ggml-org/whisper.cpp) |
| S7 | [ORT CUDA EP](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html) | S19 | [MLX install](https://ml-explore.github.io/mlx/build/html/install.html) |
| S8 | [ORT DirectML EP](https://onnxruntime.ai/docs/execution-providers/DirectML-ExecutionProvider.html) | S20 | [mlx-examples whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) |
| S9 | [ORT OpenVINO EP](https://onnxruntime.ai/docs/execution-providers/OpenVINO-ExecutionProvider.html) | S21 | [onnx-asr README](https://github.com/istupakov/onnx-asr) |
| S10 | [ORT CoreML EP](https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html) | S22 | [Windows ML overview](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/overview) |
| S11 | [ORT QNN EP](https://onnxruntime.ai/docs/execution-providers/QNN-ExecutionProvider.html) | S23 | [Windows ML execution providers](https://learn.microsoft.com/en-us/windows/ai/new-windows-ml/supported-execution-providers) |
| S12 | [ORT ROCm EP](https://onnxruntime.ai/docs/execution-providers/ROCm-ExecutionProvider.html) | | |

**Could not read:** the OpenVINO Intel-GPU and NPU configuration pages on docs.openvino.ai returned only site navigation, so **GPU driver minima and NPU driver install steps from OpenVINO's own setup pages are [Unknown]**; S15 (repo source of the NPU page) and S17 were read instead. S14/S15 are `master`, not a pinned release; the docs-site "2025" version may differ. [Assumption] CUDA/cuDNN redistribution licence terms (EULA) were not read: [Unknown].

## 3. Support matrix: backend x OS x runtime

Cell = what the cited page says; "unknown" = the page(s) read are silent. "Speech" = whether the runtime's docs state speech-model support. All cells are [Verified-primary-source] unless a cell says [Upstream-claim] or [Assumption].

| Backend | Runtime (speech-model statement) | Linux | Windows | macOS |
|---|---|---|---|---|
| CPU x86 (AVX/AVX2/AVX-512) | CTranslate2 (Whisper via converter, S3) | x86-64 with SSE4.1 min.; AVX/AVX2/AVX512 picked automatically (S1) | same (S1); `win_amd64` wheel (S4) | `macosx_11_0_x86_64` wheel (S4); ISA unknown |
| | whisper.cpp (Whisper, S18) | AVX listed; AVX-512 not stated (S18) | AVX listed; MSVC/MinGW (S18) | Intel macOS listed (S18) |
| | ONNX Runtime default CPU EP (Whisper listed by onnx-asr, S21) | ISA behaviour unknown (S6 silent) | unknown | Intel wheels stopped after ORT 1.23.x in this repo's lock ([Verified-in-code], section 5) |
| CPU Arm (NEON) | CTranslate2 | AArch64; prebuilt aarch64 wheels are CPU-only (S1, S4) | unknown (no win-arm64 wheel in S4) | `macosx_11_0_arm64` wheel; Accelerate named as a backend (S2, S4) |
| | whisper.cpp | NEON listed (S18) | unknown | NEON, Accelerate (S18) |
| NVIDIA CUDA | CTranslate2 / faster-whisper | CC >= 3.5 (S1); latest ct2 needs CUDA 12 + cuDNN 9, older pins for 11/8 (S5) | same libs; third-party archive offered (S5) | none stated (S1, S5 silent) |
| | ONNX Runtime CUDA EP | CUDA 13.0 default (>=1.27), CUDA 12.8 packages, cuDNN 9 (S7); OS list not captured | not captured; `preload_dlls` names Windows DLLs (S7) | none stated |
| | whisper.cpp (`-DGGML_CUDA=1`) | requires CUDA toolkit (S18) | requires CUDA toolkit (S18); per-OS detail unknown | n/a |
| | MLX CUDA (speech via `mlx-whisper`, S20) | CUDA 12/13, SM >= 7.5, driver 550.54.14+ for CUDA 12 (S19); speech on this backend unknown | not mentioned (S19) | n/a |
| AMD ROCm | CTranslate2 | RDNA 2/3 wheels from GitHub releases, exposed as `device="cuda"` (S1, S2) | source-build guide only (S1) | n/a |
| | ONNX Runtime | ROCm EP removed since 1.23; use MIGraphX; Ubuntu + ROCm 7.x wheel matrix (S12, S13). S6 still labels ROCm "deprecated" | MIGraphX via Windows ML, RDNA 3+ and driver 25.10.13.09+, **"not supported for GenAI scenarios today"** (S23) | n/a |
| | whisper.cpp (`-DGGML_HIP=1`) | requires ROCm (S18) | unknown | n/a |
| Intel CPU/iGPU/NPU (OpenVINO) | ORT OpenVINO EP (no speech statement; onnx-asr's README does not mention OpenVINO, S21) | Ubuntu wheels; NPU on Ubuntu 24.04 "preview" (S9, S14) | Windows 10/11; NPU on Win 11 22H2+ (S9, S14) | CPU only, macOS 12.6+ Arm64 (S14) |
| | openvino.genai ("Whisper models", CPU/GPU/NPU; [Upstream-claim] as a scenario list, S16) | Ubuntu (S14, S16) | Windows (S14, S16) | CPU (S14) |
| | whisper.cpp (`-DWHISPER_OPENVINO=1`) | **encoder only**, x86 CPU and Intel GPU; NPU not stated (S18) | same (S18) | unknown |
| | NPU specifics | dynamic shapes from Lunar Lake, Linux NPU driver 1.30+, "preview, limited to vision models"; **Whisper not mentioned** (S15) | NPU driver 32.0.100.4621+ for dynamic shapes (S15) | n/a |
| Apple silicon | whisper.cpp Core ML (`-DWHISPER_COREML=1`) | n/a | n/a | **encoder only**; first run slow while ANE service compiles; "more than x3 faster" [Upstream-claim] (S18) |
| | whisper.cpp Metal | n/a | n/a | "fully on the GPU" [Upstream-claim] (S18) |
| | MLX / `mlx-whisper` | n/a (CPU build only, S19) | not mentioned (S19) | Apple silicon, macOS >= 14, Python >= 3.10 (S19); Whisper 39M-1.5B (S20); Intel Mac not supported (S19) |
| | ORT CoreML EP | n/a | n/a | macOS 10.15+, MLProgram needs 12+; ANE not guaranteed; dynamic shapes may hurt; speech unknown (S10) |
| Qualcomm / Arm NPU | ORT QNN EP (`onnxruntime-qnn`) | not a general target (S11) | Windows ARM64, Snapdragon X; **quantized models only, fixed shapes, no Loop/If** (S11); Windows ML QNN needs NPU driver 30.0.140.0+ (S23) | n/a |
| | whisper.cpp | no QNN flag in README (S18) | same | same |
| AMD Ryzen AI NPU | whisper.cpp (`-DWHISPER_VITISAI=1`) | Ubuntu 24.04, Python 3.12 (S18) | Windows 11 (S18) | n/a |
| DirectML / Windows ML | ORT DirectML EP | n/a | DX12 GPU; Windows 10 1903+; **"sustained engineering"**, new work moved to Windows ML (S8) | n/a |
| | Windows ML | n/a | NPU/GPU EPs "downloaded on demand", Windows 11 24H2+, installed via Windows Update (S22, S23); speech unknown | n/a |
| Vulkan | whisper.cpp (`-DGGML_VULKAN=1`) | needs a Vulkan graphics driver (S18) | same (S18) | unknown |
| | ORT / CTranslate2 / OpenVINO / MLX | no Vulkan EP in the S6 table; S1, S19 silent | same | same |

**Source disagreements recorded, not resolved:** (1) S6 calls the ORT ROCm EP "deprecated" while S12 says "removed since 1.23"; S21 still lists ROCm as supported by onnx-asr, so that README line cannot be read as a promise for current ORT. (2) S1 states CC >= 3.5 but S5 requires CUDA 12 / cuDNN 9 for current ctranslate2; the effective minimum GPU generation is therefore [Unknown] (not read). (3) S2 names Apple Accelerate but not Metal; S18 documents Metal for ggml. The two runtimes do not share an Apple GPU story. [Assumption] a statement of "supports speech models" for a generic runtime (ORT, OpenVINO NPU) does not imply the Whisper/Parakeet graphs run efficiently on it; the NPU and QNN pages describe static-shape, quantized or vision-first constraints that Whisper-style autoregressive decoders may not meet [Unknown].

### 3.1 Three structural findings from the matrix

1. **Encoder-only offload is the common speech pattern.** whisper.cpp documents Core ML, OpenVINO and the Ryzen AI NPU path as accelerating the Whisper **encoder** only (S18). The autoregressive decoder, which dominates short hold-to-talk utterances, stays on the CPU unless the runtime says otherwise. Whether the encoder dominates a 1-10 s dictation burst is [Unknown]; it is exactly the kind of claim section 8 must measure rather than assume.
2. **NPUs and QNN reward static, quantized graphs.** S11 (fixed shapes, quantized-only HTP) and S15 (dynamic shapes bounded and "limited to vision models") describe constraints that conflict with variable-length dictation unless utterances are padded or bucketed. Bucketing would be a new design, not a flag. [Assumption on the consequence; the constraints themselves are Verified-primary-source]
3. **Vendor lock follows the OS.** The cross-vendor rows are Vulkan (whisper.cpp only, S18) and Windows ML's dynamic EP catalogue (S23); every other row is single-vendor. [Assumption] A hardware-profile-targeted doc ("if you have X, set Y") is therefore more honest than a generic "GPU support" claim.

**Hypotheses about who might benefit (not findings):** long-form `yazses transcribe` and meeting capture on a CUDA workstation, where throughput matters more than hold-to-talk latency, and large multilingual checkpoints that are slow on CPU. The CPU int8 default targets short bursts on ordinary laptops. [Assumption, untested]

## 4. Current YazSes behaviour (read in code, snapshot above)

- **Default:** `[stt] engine = faster-whisper`, `device = "cpu"`, `compute_type = "int8"`; `"cuda"` is described in-config as "supported but unmeasured" and `auto` is mentioned in a comment only (`src/yazses/config.py` L56-69). [Verified-in-code]
- **Only CTranslate2 reads the device.** `stt/factory.py` passes `device`/`compute_type` to `FasterWhisperEngine` only; the Parakeet adapter maps `compute_type` to an int8 flag and the Moonshine adapter has no device argument (`stt/parakeet.py`, `stt/moonshine.py`). Neither passes ONNX execution providers, so which provider onnx-asr/ORT picks is decided by the installed wheel. [Verified-in-code]
- **Heavy dependencies stay optional.** `onnx-asr[cpu,hub]` is the `parakeet` extra, lazily imported, and a missing extra falls back to faster-whisper with a logged reason (`pyproject.toml`, `stt/factory.py`). A GPU wheel (`onnxruntime-gpu`, `onnxruntime-qnn`, `openvino`) would be a **different distribution of the same import name** as CPU `onnxruntime`; coexistence in one environment is [Unknown] for the pages read. [Assumption]
- **Failure reporting gap 1, device is not validated.** `[stt] device` is absent from the closed-set validation table in `configcheck.py` (it lists `stt.engine` only). A misspelled device surfaces as a load exception. [Verified-in-code]
- **Gap 2, a device failure is reported as a missing model.** In `_load_model`, only messages containing "compute type" become `ComputeTypeUnsupportedError`; any other exception from `WhisperModel(device="cuda")` (for example a missing cuDNN) ends as `ModelUnavailableError` ("model unavailable"), and there is **no CPU fallback** (`stt/faster_whisper.py` L66-84). What the real CUDA error strings are on a broken driver is [Unknown] without hardware. [Verified-in-code for the control flow]
- **Gap 3, `yazses status` cannot say where it runs.** The status reply carries `engine`, `engine_model` and `engine_fallback` (#644) but no device, compute type or accelerator (`core/daemon.py` `_active_engine_fields`; grep finds no `compute_type`/`stt.device` in the status path). The device appears only in a log line "Loading STT model ... on cuda (...)". So configured and resolved device are indistinguishable to the user, the same class of defect #644 fixed for engine fallback. [Verified-in-code]
- **Read-only probe on this host** (Linux, AVX2 CPU, no NVIDIA tool, ctranslate2 4.8.1, onnxruntime 1.28.0, run with the project venv, no network): `get_cuda_device_count() == 0`; `get_supported_compute_types("cpu")` returned `float32, int8, int8_float32`; `get_supported_compute_types("cuda")` **raised** `RuntimeError: CUDA failed with error CUDA driver version is insufficient for CUDA runtime version`; `onnxruntime.get_available_providers()` listed `AzureExecutionProvider` and `CPUExecutionProvider`. [Verified-in-code, observed once on one host]
- **ORT provider-list egress question.** The CPU wheel lists an Azure provider (S6 marks it "preview", cloud). YazSes selects none today. Whether any provider contacts a network without explicit session options is [Unknown]; the ADR-019 egress review must cover it **before** any code passes an ORT provider list through.
- **Existing evidence about GPU:** `docs/how-to/cpu-and-battery.md` says "`[stt] device = "cuda"` exists and is untested for power"; `docs/install-cost.md` records the lesson that PyPI's PyTorch CUDA stack was 7x the size of YazSes until a CPU-only index was forced on 2026-10-21. [Verified-in-code]

## 5. The "offline + no new mandatory dependency" constraint

- A new accelerator must be an **optional extra**, lazily imported, with the CPU path unchanged (AGENTS.md rules 2-3). ORT is already resolved at two versions in `uv.lock` (1.23.2 for Intel macOS, 1.28.0 elsewhere) because Intel macOS wheels stopped at 1.23.x; an accelerated ORT wheel adds a third axis to that fork. [Verified-in-code]
- **Install size.** Recorded in `docs/install-cost.md`: installed `ctranslate2` 135 MB, `onnxruntime` 53 MB. For the same release PyPI lists a Linux x86-64 wheel of roughly 42 MB (S4, fetch summary; the page also showed implausibly small macOS figures, so wheel sizes are not used further). The size of CUDA/cuDNN runtime libraries (S5 pip route), `onnxruntime-gpu`, `openvino` and the NPU driver stack was **not measured**: [Unknown]. [Assumption] CUDA libraries alone could exceed the current base install, as the PyTorch precedent did.
- **Driver surface (what YazSes cannot ship or fix).** Each backend needs a vendor driver outside the package: NVIDIA driver matched to the CUDA major (S5, S7, S19), Intel NPU/GPU drivers "not included" with OpenVINO (S14), a Vulkan ICD (S18), Qualcomm NPU driver (S23), Windows 11 24H2 for hardware EPs (S22, S23). Version coupling is explicit upstream: cuDNN 8 vs 9 are mutually incompatible (S7); faster-whisper pins ct2 by CUDA/cuDNN generation (S5). [Verified-primary-source]
- **Offline first run.** Core ML and OpenVINO compile the model to a device-specific blob on first run (S18); the NPU page warns pre-compiled blobs are "not recommended ... in production" (S15); Windows ML downloads EPs on demand and via Windows Update (S23). The last conflicts with a no-network-after-install promise unless the EP is provisioned deliberately; it would need an ADR-019 classification as a new egress path. [Verified-primary-source for the upstream text; the ADR consequence is an Assumption]
- **Crash and security surface.** A GPU/NPU runtime puts vendor user-mode driver code inside the dictation process; a hang or reset takes down the hold-to-talk path. Subprocess isolation is a design option, not evidence. [Assumption]
- **Hybrid laptops, suspend/resume, driver updates mid-session, a missing GPU after docking:** none is addressed in the pages read. [Unknown]

## 6. What can be verified without hardware, and what cannot

| Verifiable offline (pure/fake tests) | Needs named hardware |
|---|---|
| `device`/`compute_type` resolution and pass-through (cf. `tests/test_file_transcription_honours_the_config.py`) | Any latency, RTF, RSS or VRAM figure, cold vs warm |
| A closed-set check for `[stt] device`; a device-failure message distinct from "model missing" (cf. `tests/test_compute_type_is_not_a_missing_model.py`) | Any energy, battery or thermal claim (ADR-033 point 5 allows energy only if instrumented) |
| Fallback to CPU recorded and shown in status (cf. `tests/test_status_reports_active_engine.py`) with a fake engine that fails to load on `cuda` | Real driver error strings and their `looks_like_*` classifiers |
| `get_supported_compute_types` raising on a CPU-only host (observed above) is handled, not crashed | Numerical drift of fp16/int8 on GPU vs int8 CPU on WER (paired, per ADR-033) |
| Egress inventory: no new provider/network primitive registered | Wheel/library install size, first-run compile time, hybrid-GPU and sleep/resume behaviour |

## 7. Options for the owner (all inside ADR-030's freeze unless stated)

| Option | Verdict | Why |
|---|---|---|
| A. Keep CPU int8 default; leave `cuda` documented as unmeasured | **Adopt (status quo)** | No evidence of a win; avoids driver burden |
| B. Truthful device reporting: expose resolved device/compute type in status, validate `[stt] device`, name device failures as such, record a CPU fallback | **Candidate; needs owner authorization (src change, so outside this RESEARCH item)** | Closes gaps 1-3 in section 4 without hardware; matches the #644 honesty pattern |
| C. NVIDIA CUDA through the existing CTranslate2 path, documented for users who already have CUDA 12 + cuDNN 9 | **Defer** | Already reachable via config; promote only with section 8 evidence |
| D. Optional ORT execution-provider extra (CUDA/OpenVINO/CoreML/QNN) for Parakeet | **Defer** | Provider-specific static-shape/quantization limits (S9-S11), wheel-name conflicts, ORT egress review pending |
| E. whisper.cpp (Vulkan/Core ML/OpenVINO encoder) as a separate runtime | **Defer to #792/#794** | A new engine, partial offload (encoder only), native-build burden; Vulkan is the only cross-vendor row but depends on a driver YazSes cannot ship |
| F. DirectML / Windows ML | **Reject for now** | DirectML in sustained engineering (S8); Windows ML EP download breaks the offline invariant (S23) |
| G. Any default, auto-detect-and-enable, or mandatory accelerator | **Reject** | Violates issue #795 scope, AGENTS.md rules 1-3 and ADR-030 |

## 8. Evidence required under ADR-033 before any backend is promoted

1. **Resolved-backend attestation.** The run asserts the device and provider actually executing (not the requested one); a silent CPU fallback is a recorded failure, never a scored accelerator row (ADR-033 points 1 and 3). Needs gap 3 closed first.
2. **Pinned environment manifest.** Runtime and wheel versions with hashes, driver and firmware versions, OS build, GPU/NPU model, power profile; add driver fields to the provenance record from the 2026-11-03 snapshot.
3. **Same-weights discipline.** Separate the effect of device from the effect of precision (int8 vs fp16) and conversion, as the snapshot did for runtime vs model; otherwise label a "system comparison".
4. **Paired quality and latency on a named machine class.** Matched-corpus WER/CER with the paired non-inferiority framing of ADR-033, plus key-release-to-final p50/p95 and cold load including first-run compile; sampled peak RSS **and** device memory (the current harness reads process RSS only [Assumption]).
5. **Negative cases as data.** No driver, wrong driver major, GPU absent, driver reset or suspend/resume mid-hold, hybrid GPU, NPU busy, unsupported shape; each must yield a typed, user-fixable error and a CPU path.
6. **Energy/thermal** only with instrumentation (wall power meter or vendor counters); otherwise "CPU seconds, a proxy", as `cpu-and-battery.md` already says.
7. **Offline and egress.** Install and first run with egress blocked; any download (EP, blob, compile cache) registered in ADR-019 first.
8. **Footprint.** Measured install size and licence review of every redistributed library (CUDA/cuDNN, OpenVINO, QNN, Vulkan loader); this note did not read those terms.
9. **Hardware testers.** At least one named owner per row (Linux NVIDIA, Windows Intel NPU, Apple silicon, Snapdragon X); a row with no tester stays "unknown".

## 9. Unresolved questions

- Effective minimum NVIDIA generation for current ctranslate2 + CUDA 12 / cuDNN 9; ORT CUDA EP OS support list.
- Whether Whisper-style decoders run on OpenVINO NPU or QNN at all (S15, S11 are silent or restrictive).
- Whether OpenVINO or ORT GPU wheels can coexist with CPU `onnxruntime` required by `onnx-asr[cpu]`, `useful-moonshine-onnx` and `kokoro-onnx`.
- Whether the ORT Azure provider (or any provider) can transmit without explicit options.
- The Intel GPU/NPU driver minima from OpenVINO's setup pages (unreadable here).

## 10. Checklist against #795

- [x] Current implementation audited (section 4). [x] Upstream docs consulted, dated, with fetch limits stated (sections 2-3). [ ] Repeatable method: delegated to #793/ADR-033, applied in section 8. [x] Costs/egress/licences recorded where read; licences of redistributed libraries NOT read. [x] Adopt/defer/reject given (section 7). No ADR text proposed: ADR-033 already carries the gate.
