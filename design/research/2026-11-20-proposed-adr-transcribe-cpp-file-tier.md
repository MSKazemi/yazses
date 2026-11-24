# Proposed ADR — transcribe.cpp as an opt-in accuracy tier for files and meetings

**Status:** Proposed, NOT accepted, design only during the [ADR-030](../adr/adr-030-agent-era-direction.md) breadth freeze (2026-11-20)  
**Item:** M2 in the [start plans](2026-11-19-landscape-start-plans.md) · Source: [Offline voice tech landscape, November 2026](2026-11-19-offline-voice-tech-landscape.md)  
**Governing records:** [ADR-019 egress inventory](../adr/adr-019-egress-inventory-and-escalation.md), [ADR-016 dependency budget](../adr/adr-016-dependency-budget.md), [ADR-033 reproducible ASR evaluation gate](../adr/adr-033-reproducible-asr-evaluation-gate.md) (itself Proposed), [ADR-v2-125 diarized recording import](../adr/adr-v2-125-diarized-recording-import.md), [model-manifest licence gaps](2026-11-06-model-manifest-licence-gaps.md)  
**Repository snapshot:** `research/landscape-2026-11` at `af322ca1` (main `8ecfd4ae`)  
**Scope:** `yazses transcribe` and meeting-mode transcription of finished audio. **Never hold-to-talk.**

This is an **ADR candidate in the research directory**, deliberately **not a numbered accepted
ADR**. ADR-030 §3 says a new capability proposed during the freeze "is written down as a
*Proposed* ADR … and stops there". Nothing under `src/`, `pyproject.toml`, the model manifest
or any default is changed by this record. It becomes a numbered ADR only if a maintainer
adopts it in a separate reviewed change, together with an ADR-030 amendment or a freeze lift.

Labels: **[Fact]** a cited primary source says so on 2026-11-20 · **[Inference]** drawn from
facts, stated as such · **[U]** not verified · **[Proposal]** a suggestion for the reviewer.

## Context

Today every file and meeting transcript goes through one engine. `recimport/pipeline.py`
`_build_engine` constructs `FasterWhisperEngine` directly and calls
`transcribe_words(audio, sample_rate, task=…)`, which returns `(text, words)` with per-word
`start`/`end` seconds. Those words feed `recimport/align.py`, which assigns each word to the
diarizer turn it overlaps most, and `recimport/subtitles.py`, which builds SRT/VTT cues from
word timestamps. **Word timestamps are therefore a hard input** to the diarized path and to
subtitle output; a plain-text transcript does not need them.

The 2026 accuracy leaders (Granite Speech 4.1, Qwen3-ASR) are permissively licensed but are
documented for GPU through torch or vLLM, which conflicts with the lean-install rule in
[docs/install-cost.md](../../docs/install-cost.md). transcribe.cpp is an MIT C/C++ runtime on
ggml that runs those families, plus a diarizer and a VAD, from GGUF files on CPU
([GitHub](https://github.com/handy-computer/transcribe.cpp)). The landscape note left one
question open: does its Python binding install as a wheel everywhere YazSes runs?

One correction to the start plan: `recimport/factory.py` is the **diarizer** factory
(`build_diarizer`, `diarization_status`). The STT seam for files is
`recimport/pipeline.py::_build_engine`. The build plan below names both.

## Spike results (web only, 2026-11-20, no install, no weights downloaded)

### 1. Wheels: yes for the five mainstream targets, by a two-package split

- **[Fact]** The binding is PyPI `transcribe-cpp` (MIT, `requires_python >=3.9`), latest
  **0.4.2**, uploaded 2026-11-12, 24 releases since 2026-06-09. It is a 47,640-byte
  `py3-none-any` wheel (sha256 `dbbdef5f…bb2e`, recomputed locally from the PyPI file) that
  holds only Python: a ctypes layer with load-time ABI-layout verification
  ([PyPI](https://pypi.org/project/transcribe-cpp/)).
- **[Fact]** It requires `transcribe-cpp-native==0.4.2.*` (MIT), which ships the shared
  library as wheels tagged `py3-none-<platform>`: `manylinux_2_28_x86_64`,
  `manylinux_2_28_aarch64`, `macosx_11_0_arm64`, `macosx_11_0_x86_64` and `win_amd64`, plus an
  sdist (4.5 MB). Every native release from 0.0.3 onward has the same five wheels
  ([PyPI](https://pypi.org/project/transcribe-cpp-native/)). A CUDA extra points at
  `transcribe-cpp-native-cu12`, which is an empty 0.0.0 placeholder.
- **[Inference]** Because the library is loaded through ctypes and the wheel tag is `py3-none`,
  one wheel serves every CPython version, so **Python 3.11, 3.12, 3.13 and 3.14 resolve the
  same wheel** on those five platforms. The trove classifiers stop at 3.13; 3.14 is
  undeclared, not excluded. **[U]** No install was performed on any interpreter.
- **[Fact]** No wheel exists for Windows ARM64, musl Linux, glibc older than 2.28, or
  FreeBSD. There pip falls back to the sdist, which needs CMake and a C++17 compiler.
- **[Fact]** The binding README still says "Until wheels are published, use a locally built
  `libtranscribe`"; the PyPI file list contradicts it. The pure binding contains no network
  code (scan of the 0.4.2 wheel for `urllib`, `requests`, `socket`, `huggingface`, `download`
  found none; it loads only a local `.gguf` path or `TRANSCRIBE_LIBRARY`). **[U]** The native
  wheel's contents were not inspected.

### 2. Release tags: they exist now

**[Fact]** The repository has tagged GitHub releases `v0.2.0` (2026-08-17) through `v0.4.2`
(2026-11-12), each with per-platform native tarballs, a `catalog.db` and a SHA-256 file
([releases](https://github.com/handy-computer/transcribe.cpp/releases)). The landscape note's
"no release tag" is out of date. The API is still pre-1.0 and churns: 0.2 shipped a migration
guide that replaced `gpu_device=` with device objects.

### 3. Licences

| Component | Licence | Source |
|---|---|---|
| transcribe.cpp runtime, `transcribe-cpp`, `transcribe-cpp-native` | MIT (vendored ggml and miniz also MIT) | [GitHub](https://github.com/handy-computer/transcribe.cpp), PyPI metadata |
| Granite Speech 4.1 2B (and `-plus`), upstream and GGUF | Apache-2.0; GGUF repo carries `LICENSE` + `NOTICE` ("converted … at commit 8f4bb5f … not retrained") | [IBM card](https://huggingface.co/ibm-granite/granite-speech-4.1-2b), [GGUF](https://huggingface.co/handy-computer/granite-speech-4.1-2b-gguf) |
| Qwen3-ASR 0.6B, upstream and GGUF | Apache-2.0; `NOTICE` names upstream commit `5eb1441` | [Qwen card](https://huggingface.co/Qwen/Qwen3-ASR-0.6B), [GGUF](https://huggingface.co/handy-computer/Qwen3-ASR-0.6B-gguf) |
| Streaming Sortformer 4spk v2.1 | **NVIDIA Open Model License** (card: `license: other`) | [NVIDIA card](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1), [licence](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/) |
| Silero VAD v6.2 GGUF | MIT | [GGUF](https://huggingface.co/handy-computer/silero-vad-v6.2-gguf) |

**[Inference]** Apache-2.0 obliges YazSes to pass on the `NOTICE` only if it redistributes the
weights; like every manifest row today, YazSes would download, not redistribute. The
manifest schema's licence enum (`mit`, `apache-2.0`, `cc-by-4.0`, `bsd-3-clause`,
`cc-by-nc-sa-4.0`) **cannot express the NVIDIA Open Model License**, so Sortformer stays out
until the licence process in the 2026-11-06 note clears it and the schema gains an id.

### 4. Word timestamps: only from the Granite `-plus` variant

- **[Fact]** The Python result carries `words: tuple[Word, ...]` with `text`, `t0_ms`,
  `t1_ms`; `Capabilities.max_timestamp_kind` reports what a model can give.
- **[Fact]** In the transcribe.cpp model docs, base `granite-speech-4.1-2b` lists
  capabilities "translate" only; **word timestamps come from `granite-speech-4.1-2b-plus`**
  (parsed from the model's `[T:N]` centisecond markers; English, French, German, Spanish,
  Portuguese, no Japanese, no translation). `-nar` has none.
- **[Fact]** The Qwen3-ASR doc says the family does **not** support "timestamps" in
  transcribe.cpp. Upstream timestamps need a separate Qwen3-ForcedAligner, which the runtime
  does not list.
- **[Inference]** So the start plan's pair does not fit `align.py` as written. Granite 4.1 2B
  and Qwen3-ASR could serve **plain transcripts only** (no `--diarize`, no SRT/VTT). The
  diarized and subtitle paths need `granite-speech-4.1-2b-plus`. A word list with
  `t0_ms`/`t1_ms` maps onto `postprocess.prosody.Word` by dividing by 1000.

### 5. GGUF hashes: stable, published per file, usable by the manifest

**[Fact]** Each GGUF repo is a Hugging Face git repo whose files are LFS objects with a
published sha256 (Hub API, `?blobs=true`). Observed today:

| File | Repo commit | Size (bytes) | sha256 (reported by source) |
|---|---|---:|---|
| `granite-speech-4.1-2b-Q4_K_M.gguf` | `6c6a92dfc36d2b9eda767ef2fb2320237672c4b6` | 1,602,904,896 | `c63e6d7e2f4811a732f3870b48d122e38d5d19c6b60c9c0eee731b2be911916c` |
| `granite-speech-4.1-2b-plus-Q4_K_M.gguf` | `d511bd6c8ea27005eeb4865ab2545480a3e9541d` | 1,489,663,552 | `4324dece3cc7f4d877e335f9d90a86e4ddf55a4d0976ee1c7293be7677dd8a74` |
| `Qwen3-ASR-0.6B-Q4_K_M.gguf` | `7e7c69a577fa2725dfedbe34b5e999336e30a19b` | 589,560,480 | `5b58f32a58ffa2c8783e0b0963485623e286e6272d953dfc9e28bc3447dee0c0` |

**[Inference]** The fit is direct: `revision.kind = git-commit` with the repo commit,
`artifacts[].sha256_status = reported-by-source` until a human downloads and recomputes
(`computed-locally`), `runtime_format = "transcribe.cpp / GGUF"`, `redistributed_by_yazses =
false`. Unlike today's 54 rows, these could be loaded **by exact revision and verified by
hash**, so `pinned_by_yazses` could be `true` from the first row. **[U]** No file was
downloaded, so no hash was recomputed. The quantised files are third-party conversions
(handy-computer), so the row must name both the upstream commit (from `NOTICE`) and the
conversion repo.

## Proposed decision (conditional, not yet binding)

1. **Scope.** transcribe.cpp may become an **opt-in second engine for finished audio only**:
   `yazses transcribe` and meeting mode's post-capture transcript. It never serves
   hold-to-talk, streaming dictation, `ask_human` or any latency-bound path, whatever its
   streaming models claim. The default stays faster-whisper.
2. **Models exposed at first.** `granite-speech-4.1-2b-plus` (word timestamps, so diarization
   and subtitles work) and, for plain transcripts only, `granite-speech-4.1-2b` and
   `qwen3-asr-0.6b`. Requesting `--diarize` or `.srt`/`.vtt` with a model whose
   `max_timestamp_kind` is not `word` is refused before the model loads, naming the `-plus`
   model, rather than producing an unattributed transcript.
3. **Licences.** Only models whose licence is in the manifest's licence enum and stated by
   both the upstream card and the conversion repo. Sortformer is excluded until the NVIDIA
   Open Model License is reviewed; Silero v6.2 via transcribe.cpp is not needed while M5
   loads the Silero ONNX file directly.
4. **Manifest first.** Every exposed GGUF gets a manifest row with repo commit, file name,
   size and sha256 before any code can load it. The loader passes that revision and checks
   the sha256 after download; a mismatch is a refusal, not a warning.
5. **Fallback.** If the extra, native library or model is missing, or the ABI check fails,
   the transcript is **not silently** produced by faster-whisper. ADR-033 point 3 and
   ADR-030 Pillar 1.3 both say a silent fallback hides the engine that ran. The command
   fails with the one action that fixes it, and the user can rerun with the default engine.
   The transcript header records the resolved engine and model.
6. **No new egress.** Weights download through the existing registered model-download path
   (Hugging Face Hub, ADR-019 inventory) on explicit request; the runtime itself loads only a
   local file. A design that needs a tenth egress path stops and returns to ADR-019.
7. **No adoption by implication.** This record authorises no dependency, extra, config key,
   default, manifest row or release.

## Single-maintainer and native-build risk

- **[Fact]** About 2.2k stars and 580 commits; the contributor graph did not render and the
  GitHub API was rate-limited, so the contributor count is **[U]**. The landscape note's
  secondary source says maintenance is concentrated in the Handy maintainer. CI is donated
  (Blacksmith runners, Modal WER checks per the README).
- **Mitigations [Proposal].** Pin `transcribe-cpp` and `transcribe-cpp-native` to one minor
  (`>=0.4.2,<0.5`), because pre-1.0 minors have broken the API; keep faster-whisper as the
  default so an abandoned upstream costs an opt-in tier, not the product; keep the adapter
  thin (one module) so removal is one PR; the model files are plain GGUF with recorded
  hashes, so another ggml runtime could read them.
- **Who owns a native build.** For the five wheel targets, nobody: YazSes consumes upstream
  wheels. For Windows ARM64, musl, glibc < 2.28 and FreeBSD, **YazSes does not build or
  ship the native library.** The extra is documented as unsupported there and the feature
  reports "no prebuilt transcribe.cpp for this platform". A user may build from the sdist or
  point `TRANSCRIBE_LIBRARY` at their own build, unsupported. If a maintainer later wants one
  of those platforms, owning that build matrix is a separate decision with a named owner.
  The FreeBSD CI leg simply never installs the extra, as with faster-whisper today.

## Measurement a human must run (ADR-033, before any acceptance)

This record runs no benchmark. On the ADR-033 reference machine, with the ADR-033 file set,
normaliser and manifest fields (YazSes commit, resolved engine and model, file sha256,
`transcribe-cpp`/`-native` versions, CPU, OS, threads, decoder settings):

| Arm | Report |
|---|---|
| faster-whisper, current `[stt] model` (baseline) | WER/CER with S/D/I, RTF, peak RSS, cold load |
| `granite-speech-4.1-2b-Q4_K_M` | same, plus "word timestamps present: no" (expected) |
| `granite-speech-4.1-2b-plus-Q4_K_M` | same, plus word-timestamp coverage and, on the multi-speaker fixtures, attribution agreement through `align.py` against the baseline |
| `Qwen3-ASR-0.6B-Q4_K_M` | same, plus "word timestamps present: no" (expected) |

Per-sample failures stay in the denominator; peak RAM is sampled RSS of the whole process,
including mmap'd weights; warmed decode is reported apart from cold load. Use only synthetic
or explicitly consented audio. A negative or inconclusive result is a valid outcome and is
recorded here.

## Build plan (only when the freeze allows it)

1. **Extra.** `transcribe-cpp = ["transcribe-cpp>=0.4.2,<0.5"]` in
   `[project.optional-dependencies]` (pulls `transcribe-cpp-native`); added to the mypy
   missing-import list; nothing in the base install changes.
2. **Adapter.** `src/yazses/recimport/transcribe_cpp_backend.py`, importing `transcribe_cpp`
   inside the constructor only. It implements `transcribe_words(audio, sample_rate, task)`
   by running a session and mapping `Word(t0_ms, t1_ms)` to `postprocess.prosody.Word`
   (seconds). Model identity and sha256 are checked before `Model(path)`.
3. **Seam.** `recimport/pipeline.py::_build_engine` gains an engine selection from a
   dormant `[recimport]`/`[meeting]` key (L3: maintainer sign-off, `gen-docs.py`); the
   word-timestamp refusal lives in a pure function beside `file_decoder_settings`.
   `recimport/factory.py` is untouched in the first PR: diarization stays sherpa or pyannote.
4. **Pure tests** with a fake `transcribe_cpp` module: ms-to-seconds mapping, the refusal
   for non-word models, the hash-mismatch refusal, the no-silent-fallback error, and the
   extra-missing advice. `tests/decoder_stack.py` markers keep the FreeBSD leg skipping.
5. **Manifest and docs.** Manifest rows first (licence, revision, sha256), then
   `docs/features.md`, `docs/configuration.md`, `CHANGELOG.md`, and
   `design/architecture.md` for the new module.

## Alternatives

| Alternative | Position | Why |
|---|---|---|
| Stay faster-whisper only | Default until measured | Zero new risk; forgoes the leaderboard models |
| Granite/Qwen through torch or vLLM | Reject | GPU-first documentation, torch-sized install ([docs/install-cost.md](../../docs/install-cost.md)) |
| whisper.cpp | Reject for this tier | Whisper only, ggml `.bin`, no new accuracy |
| sherpa-onnx re-exports (already an extra) | Measure alongside | Has Qwen3-ASR ONNX; may give the tier with no new dependency |
| Vendor or build transcribe.cpp ourselves | Reject | Moves the single-maintainer risk onto YazSes |

## Unknowns

Whether `-plus` word timestamps are accurate enough for `align.py` on overlapping speech; CPU
RTF and peak RAM of a 2B decoder at Q4_K_M on the reference laptop; whether the native wheel
makes any network call; contributor count; whether Python 3.14 actually loads the library.

## Review / acceptance gate

Requires a maintainer decision, an ADR-030 amendment or freeze lift naming this item, the
ADR-033 measurement above, and manifest rows for each model. If accepted, allocate an ADR
number with its generator and open one scoped delivery issue. **Until then this is a proposed
research document; runtime behaviour has not changed.**
