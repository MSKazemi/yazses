# Android on-device ASR: device-tier measurement protocol and low-memory model policy

**Date:** 2026-11-06
**Status:** Research note and protocol design (not a decision). **Synthetic and unrun:** no device was used, no APK was built, no Gradle task or Android test was run, no model was downloaded, and this note contains **no measurement**. ADR-030 freeze unchanged. No ADR is edited or accepted by this note.
**Tracking:** [NEXT-MOBILE-03 #808](https://github.com/MSKazemi/yazses/issues/808), parent [#789](https://github.com/MSKazemi/yazses/issues/789); implementation epic [#81](https://github.com/MSKazemi/yazses/issues/81); feeds [#92](https://github.com/MSKazemi/yazses/issues/92) (`:bench` harness and device matrix) and [#87](https://github.com/MSKazemi/yazses/issues/87) (`:core:stt` + `:native:whispercpp`); related spike [#97](https://github.com/MSKazemi/yazses/issues/97) (90-minute microphone FGS).
**Repository snapshot:** main at 4695e49a.
**Builds on, and does not repeat:** the [pinned offline ASR evaluation protocol](2026-11-03-pinned-offline-asr-evaluation-protocol.md) (metric definitions, statistics, result contract), the [small and quantized ASR models note](2026-11-05-small-quantized-asr-models-and-gguf-runtimes.md) (candidate grid C1-C9), the [local accelerator backends note](2026-11-05-local-accelerator-backends-for-offline-asr.md) (resolved-backend attestation, energy rule), the [runtime and model provenance snapshot](state-of-the-art/2026-11-03-local-asr-runtime-provenance.md) (licences and the per-run provenance record), the [Android API-level and OEM IME note](2026-11-05-android-api-levels-and-oem-ime-microphone-restrictions.md) (constraints C1-C20 and device-test checklist T1-T12), and Proposed [ADR-033](../adr/adr-033-reproducible-asr-evaluation-gate.md). Binding mobile decisions: [ADR-MOB-005](../../docs/mobile/adr/adr-mob-005-stt-runtime.md), [ADR-MOB-006](../../docs/mobile/adr/adr-mob-006-model-distribution.md).

> Labels: **[Verified-in-code]** read in this repository at the snapshot; **[Verified-in-doc]** stated by a repository document (ADR or research note) that is cited; **[Assumption]** my inference, named so it can be struck; **[Unknown]** not established by anything read. Android platform APIs named in sections 3-5 as *candidate* measurement methods were **not** re-read against developer.android.com for this note; each is an [Assumption] until #92 confirms it on a device.

## 1. Answer to the issue question

Question (#808): which pinned whisper.cpp / sherpa / Parakeet or quantized configurations merit tests on budget phones after M1 works?

- **Only two configurations are pinned today**, and they are the first matrix. The in-APK catalogue holds exactly two entries, both for the whisper.cpp engine, both at Hugging Face commit `5359861c739e955e79d9a303bcbc70fb988958b1` of `ggerganov/whisper.cpp` [Verified-in-code, [`models.json`](../../android/app/src/main/assets/models.json)]:

  | Catalogue id | File at the pinned commit | sizeBytes | SHA-256 | Licence as recorded |
  |---|---|---|---|---|
  | `tiny.en` | `ggml-tiny.en.bin` | 77704715 | `921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f` | MIT |
  | `base.en` | `ggml-base.en.bin` | 147964211 | `a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002` | MIT |

  The MIT licence is the catalogue's recorded value; the small-quantized note records the same files' Hugging Face card tag as `mit` (row C1). No licence determination is made here.
- **Every other candidate is unpinned and cannot enter the matrix yet.** Quantized ggml Whisper files (small-quantized note row C1), sherpa-onnx int8 families (C7), Moonshine streaming checkpoints (C6) and the parakeet.cpp GGUF ladder (C9) have no immutable revision and file SHA-256 in this repository. The small-quantized note section 5 already says no row has been resolved to a revision [Verified-in-doc]. Under ADR-MOB-006 decision 7 a model addition is "a reviewable PR with a checksum in the diff" [Verified-in-doc], so a candidate enters this protocol only after it has a catalogue row.
- **Licence gate before any arm:** Parakeet TDT v2/v3 weights are CC-BY-4.0, Nemotron 3.5 is OpenMDW-1.1 and needs review, nemotron-speech-streaming is under the NVIDIA Open Model License, and Moonshine legacy non-English checkpoints are non-commercial; all four rows are from the [provenance snapshot section 3](state-of-the-art/2026-11-03-local-asr-runtime-provenance.md) [Verified-in-doc]. A non-commercial or unreviewed row is not a candidate.
- **Recommendation (for the owner, not a decision):** first device run = `tiny.en` and `base.en` at the pinned commit, one engine, across the tiers in section 3. Quantized and second-engine arms wait for (a) a pinned catalogue row and (b) the schema additions in section 4. This keeps to #808's "avoid a mandatory second engine" constraint.

## 2. What the Android tree has today (so the protocol targets real seams)

| Fact | Evidence |
|---|---|
| `:bench` (the on-device harness of ADR-MOB-005 decision 7) is a placeholder object only; no harness code exists | [Verified-in-code] [`android/bench/.../Placeholder.kt`](../../android/bench/src/main/kotlin/com/yazses/bench/Placeholder.kt) |
| `:core:bench` defines record schema `yazses.bench.android/1` with device, SoC, Android version, engine id, model id, model SHA-256, threads, per-clip `audioS`/`wallS`/`rtf`, and `peakRssBytes` | [Verified-in-code] [`BenchResult.kt`](../../android/core/bench/src/main/kotlin/com/yazses/core/bench/BenchResult.kt) L4, L15-41 |
| "Not measured" is a typed state with a reason (`Reading.NotMeasured`), never a zero | [Verified-in-code] `BenchResult.kt` L6-13 |
| RTF = wall / audio seconds, null when there is no audio; the validator rejects an `rtf` that disagrees with the durations | [Verified-in-code] [`Rtf.kt`](../../android/core/bench/src/main/kotlin/com/yazses/core/bench/Rtf.kt) L6; [`BenchValidator.kt`](../../android/core/bench/src/main/kotlin/com/yazses/core/bench/BenchValidator.kt) L38-120 |
| WER and CER exist; `TextNormalizer.WHISPER_ENGLISH` is the port of whisper-normalizer that the desktop benchmark uses, and its KDoc records 614 of 614 vectors passing | [Verified-in-code] [`ErrorRate.kt`](../../android/core/bench/src/main/kotlin/com/yazses/core/bench/ErrorRate.kt) L17-30, L140, L155; [`EnglishTextNormalizer.kt`](../../android/core/bench/src/main/kotlin/com/yazses/core/bench/EnglishTextNormalizer.kt) |
| The default normaliser is `SIMPLE`, which the code says is **not** comparable with the desktop | [Verified-in-code] `ErrorRate.kt` L17-24 |
| `ErrorRate` carries total errors and reference length only, not separate S/D/I | [Verified-in-code] `ErrorRate.kt` L7 |
| `corpusWer` skips a pair whose normalised reference is empty, as the desktop does | [Verified-in-code] `ErrorRate.kt` L159-172 |
| `:core:stt` has the engine seam (`transcribe`, `decodeWindow`, `close`) and a pure factory with no concrete engine; cancellation "is NOT part of this interface yet" | [Verified-in-code] [`SttEngine.kt`](../../android/core/stt/src/main/kotlin/com/yazses/core/stt/SttEngine.kt) L14-41, `SttEngineFactory.kt` |
| `:native:whispercpp` and `:native:sherpaonnx` are placeholders | [Verified-in-code] `android/native/*/src/main/kotlin/.../Placeholder.kt` |
| `minSdk 26`, `targetSdk 34`, `compileSdk 34`; no `abiFilters` and no `ndkVersion` anywhere in the Gradle files | [Verified-in-code] `android/gradle/libs.versions.toml` L9-13; grep of `android/**/*.kts` |
| The catalogue parser checks 64-hex SHA-256, unique SHA-256 per entry and an `https://` URL | [Verified-in-code] [`ModelCatalogue.kt`](../../android/core/model/src/main/kotlin/com/yazses/core/model/ModelCatalogue.kt) L102-147 |

**Consequence.** The protocol below is runnable only after #87 (an engine behind the seam) and #92 (a harness in `:bench`) land. Until then every number in the matrix is [Unknown], and the doc and app state performance as "measure it on your device" (ADR-MOB-005 decision 7) [Verified-in-doc].

## 3. Device tiers

Tiers are defined by properties the harness reads from the device, never by brand or price, so a report places itself and a reviewer can check the placement.

| Tier | Defining properties (all recorded per run) | Purpose |
|---|---|---|
| **T0 low-RAM** | device reports itself low-RAM, or total RAM at or below the T0 bound | Exercises the fallback policy of section 6; may legitimately end as "refused to load" |
| **T1 budget arm64** | arm64-v8a, RAM above T0 and at or below the T1 bound | The tier #808 names ("budget phones") |
| **T2 mid arm64** | arm64-v8a, RAM above T1 and at or below the T2 bound | Checks whether `base.en` is a sensible default |
| **T3 high-end** | arm64-v8a, RAM above T2 | Upper bound only; never used to state a default |
| **Emulator / CI** | x86_64 or arm64 emulator | **CI-only.** Checks that the harness runs and the record validates; never a device result, never in the device matrix |

The RAM bounds are **deliberately left blank**: no source read gives a per-device model budget (API note Q7 and C14: "unknown numbers") [Verified-in-doc]. [Assumption] The owner sets them after the first T1-T3 reports, using measured peak RSS, not marketing RAM.

Properties to record for tier placement, all candidate APIs [Assumption]: total and available memory and the low-RAM flag from `ActivityManager`; `getMemoryClass()` (named in the API note Q7 [Verified-in-doc]); supported ABIs from `Build.SUPPORTED_ABIS`; SoC name (already `DeviceInfo.soc`); Android version and patch level, OEM skin version and install source (API note section 7 run record [Verified-in-doc]); page size (4 KB or 16 KB, API note Q8 and C16 [Verified-in-doc]).

**ABI rule.** A device without arm64-v8a, or a 16 KB-page device given a library not aligned for it, is an **unsupported row**, not a WER of 100% and not a missing latency (the pinned protocol's rule for a machine that lacks a backend [Verified-in-doc]). Whether 32-bit `armeabi-v7a` is built at all is undecided in the tree (no `abiFilters`) [Verified-in-code]; the protocol records it, it does not decide it.

## 4. Metrics and where each one lives

Definitions are the pinned protocol's section 5; this table only maps each #808 metric to an Android method and to a field that does or does not exist in schema `/1`.

| Metric (#808) | Definition used | Candidate on-device method | In schema `/1`? |
|---|---|---|---|
| WER | Pooled corpus WER with `TextNormalizer.WHISPER_ENGLISH` for English; the normaliser name is part of the record | `Wer.corpusWer(..., WHISPER_ENGLISH)` | **No WER field**, no normaliser field. Gap G1 |
| S/D/I | Reported separately (pinned protocol section 5) | Needs an alignment that returns the three counts | **No.** `ErrorRate` has totals only. Gap G2 |
| Silence false positives | Words emitted for an empty reference, scored separately (pinned protocol; never divided by zero) | Count hypothesis tokens where the reference is empty | **No.** `corpusWer` drops those pairs, so a hallucination on silence is invisible to WER. Gap G3 |
| CER | NFC code points without whitespace/punctuation, as `Wer.cer` | `Wer.cer` | No field. Part of G1 |
| Decode latency p50/p95 | Wall time of the engine call only | Monotonic clock around `transcribe` | Per-clip `wallS` exists; percentiles are derived, never stored. p95 needs n >= 20 per device (pinned protocol) |
| Release-to-final p50/p95 | `t_final - t_release` | Harness-simulated release on recorded PCM; a real IME release is a T-series device test | **No.** Gap G4 |
| Cold load | New process to model ready, and first decode, separately; page-cache state stated | Timestamps around engine construction | **No.** Gap G4 |
| Peak memory | Sampled maximum during decode, method named | [Assumption] process high-water mark from `/proc/self/status` (`VmHWM`) or a native-heap reading; the method string is recorded | `peakRssBytes` exists as a `Reading`; **no method field**. Gap G5 |
| Heat | Thermal state before and after each arm, plus a throttling flag | [Assumption] `PowerManager` thermal status (API 29+); below API 29 the reading is `NotMeasured` with that reason | **No.** Gap G6 |
| Battery | Energy only with external instrumentation; otherwise process CPU seconds per audio minute, labelled a compute proxy (pinned protocol; accelerator note section 8 item 6) | [Assumption] CPU time of the process; a battery-percentage delta is recorded but never reported as energy | ADR-MOB-005 names "battery delta" [Verified-in-doc] but schema `/1` has none. Gap G6 |
| Storage | Model bytes on disk and the free space left; must equal catalogue `sizeBytes` | File length after the SHA-256 check | `modelSha256` exists; size and free space do not. Gap G7 |
| ABI | Device ABIs and the ABI and page alignment of the loaded native library | Read at load time | **No.** Gap G7 |
| Coverage / failures | `ok`, `unsupported`, `load_failure`, `low_memory_refused`, `killed`, `timeout`, `crash`, `fallback` | Harness outcome | **No status field.** Gap G8 |

**Schema rule.** `BENCH_SCHEMA`'s KDoc says to bump the suffix on any incompatible change [Verified-in-code, `BenchResult.kt` L3]. Gaps G1-G8 therefore belong to a schema `/2` under #92, with every new value a `Reading` so "not measured" stays distinct from zero. This note does not change the schema.

## 5. Run procedure (per device, per arm)

1. **Provenance first.** Record the per-run provenance list of the [provenance snapshot](state-of-the-art/2026-11-03-local-asr-runtime-provenance.md) ("Provenance record required for each experimental run"), plus the catalogue id, pinned commit and file SHA-256, and the whisper.cpp source commit of the build. A model whose SHA-256 does not match the catalogue is not run (ADR-MOB-006 decision 3 treats a mismatch as a security event) [Verified-in-doc].
2. **Offline.** Network access for the app denied before the first clip; ADR-MOB-006 decision 4 already requires the app to work that way [Verified-in-doc]. A run with network allowed is invalid.
3. **Corpus.** Licensed public or synthetic clips only, from the frozen manifest of #793 and the pinned protocol section 3. No private dictation, no user audio (#808 and AGENTS.md). Include the pinned protocol's silence and long-pause stress slices, since G3 is otherwise unobservable.
4. **State recorded, not controlled away:** charge state and charger connected or not, screen on, battery-optimisation state, standby bucket (`adb shell am get-standby-bucket`, API note section 7 [Verified-in-doc]), thermal state at start.
5. **Cool-down gate.** An arm starts only at the coolest thermal state the device reports [Assumption about the state name]; if that state is not reached within a fixed wait, the arm is recorded as `not_started: thermal` rather than run hot.
6. **Repetitions.** At least 3 independent process launches per arm, one recorded warm-up, shuffled clip order, model order randomised per device (pinned protocol section 5). Each run is kept; none is discarded as an outlier.
7. **Cold versus warm.** "New process, warm page cache" and "first run after reboot" are separate labelled conditions, because a ggml model file is memory-mapped and unmodified mmapped pages can be reclaimed (API note Q7 [Verified-in-doc]).
8. **Soak.** One sustained arm per device (repeat the corpus for a fixed wall time) records thermal state and per-clip `wallS` over time, so throttling shows as drift rather than as noise. The 90-minute FGS question stays with #97.
9. **Paired comparisons only on the same device.** Cross-device rows are descriptive. No leaderboard mixes tiers, normalisers or failed cells (pinned protocol section 6).

## 6. Low-memory safe fallback policy (design proposal)

The failure being designed against: a model too large for the device either fails to load, or loads and is then killed by lmkd mid-burst, which on an IME takes the keyboard with it (API note C14; ADR-MOB-005 notes a native crash takes the IME process) [Verified-in-doc]. Rules, in order:

1. **Measured admission, not an assumed budget.** Before loading, compare available memory against the **measured** peak RSS for that catalogue id on the device's tier, from `:bench` reports. With no measurement for the pair, the app loads and records the outcome; it does not invent a threshold. [Assumption: the margin above measured peak RSS is an owner decision after T0/T1 data]
2. **Refuse visibly, never degrade silently.** If admission fails, the burst does not start and the user sees a typed reason ("this model needs more free memory than the device has now") with the storage/model screen one tap away. This is the honesty rule the desktop applied to engine fallback in #644 (a recorded `engine_fallback` in status) [Verified-in-doc, accelerator note section 4].
3. **Fallback goes down the catalogue, same engine, with consent.** The only automatic suggestion is a smaller model that is **already downloaded and verified** (for the current catalogue, `base.en` to `tiny.en`). The switch needs a user tap and is recorded; it is never silent, and the app says the smaller model is less accurate (ADR-MOB-005 consequence on honest expectations) [Verified-in-doc].
4. **No download as a fallback.** A missing smaller model is offered for download only through the normal chooser after an explicit tap (ADR-MOB-006 decisions 2-3) [Verified-in-doc].
5. **No second engine as a fallback.** Falling back from whisper.cpp to sherpa-onnx would make the second engine mandatory, which #808 rules out and ADR-MOB-005 decision 3 keeps optional [Verified-in-doc].
6. **No cloud fallback,** ever (ADR-MOB-005 Rejected) [Verified-in-doc].
7. **Killed mid-decode.** If the process dies or the engine reports an allocation failure during a burst, no partial text is committed, the PCM is not persisted, and the next IME start shows that the last burst was lost. [Assumption: how the IME detects its own prior death is a design question for #87]
8. **Residency is measured, not decided here.** API note C15 records the conflict between releasing large allocations when the IME hides and keeping a model hot; the protocol measures both sides (cold reload latency against resident memory per tier) so the owner can decide with numbers [Verified-in-doc for the conflict].
9. **In the bench record,** a refusal is `low_memory_refused`, a lmkd kill is `killed`, and a consented smaller model is `fallback` with `fallback_from`; none of them contributes a WER or latency number (pinned protocol result contract) [Verified-in-doc].

Rules 1-3 and 7 would change product behaviour described by ADR-MOB-005/006. Whether that needs a **Proposed** amendment is an owner decision; this note proposes no ADR text.

## 7. Failure and edge cases kept as first-class rows

Low-RAM refusal; lmkd kill during decode; model file evicted from page cache between bursts; SHA-256 mismatch; 16 KB-page device with a 4 KB-aligned library; device without arm64-v8a; thermal throttling mid-arm; empty transcript on speech; words emitted on silence; decode longer than the clip (RTF above 1); app network access denied (must still work); battery saver enabled; restricted standby bucket (API note C12-C13 [Verified-in-doc]). Each yields a typed status, never a dropped row.

## 8. CI-only versus verified-on-device

| Can be checked without a device (JVM unit tests) | Needs a named real device |
|---|---|
| Schema `/2` round-trip and validator rules for every new field, including `NotMeasured` reasons | Every latency, RTF, cold-load, peak-memory, thermal and battery value |
| S/D/I counting and the silence false-positive counter against synthetic vectors | Real lmkd behaviour and OEM memory tuning (API note C14) |
| Admission logic of section 6 as a pure function of (available memory, measured peak, catalogue) | Whether the IME survives a refusal and a kill the way rule 7 needs |
| Catalogue ordering for "next smaller downloaded model" | 16 KB alignment of the actual built `.so` (API note C16; builds do not exist) |
| Percentile derivation refusing p95 below n = 20 | Thermal states reached and how fast |

Emulator runs belong in the left column only.

## 9. Links back to #81 implementation issues

- **#92** owns the harness, schema `/2` (gaps G1-G8) and the community device matrix.
- **#87** owns the engine, the allocation-failure error type and the cancellation gap noted in `SttEngine.kt`.
- **#97** owns long-duration FGS survival; this protocol's soak arm (step 8) is shorter and does not answer it.
- The [API note](2026-11-05-android-api-levels-and-oem-ime-microphone-restrictions.md) section 7 device tests (T1-T12) run on the same devices and should share the run record of section 3. Its T7 (peak RSS and PSS per model, C14/C15) is the same measurement as this protocol's peak-memory row and should be run once, under this protocol's method field, not twice.

## 10. Owner decisions needed

1. RAM bounds for T0-T2 (section 3), after the first reports.
2. Whether `armeabi-v7a` is a supported ABI at all.
3. The admission margin of section 6 rule 1, and whether rules 1-3 and 7 need a Proposed ADR-MOB amendment.
4. Which quantized or second-engine candidate, if any, gets a pinned catalogue row and so enters the matrix (small-quantized note section 6 options apply).
5. Whether energy is instrumented on any device, or the CPU-seconds proxy is the only battery metric.

## 11. What would change this protocol

- A first T1 report showing `base.en` refused or killed: `tiny.en` becomes the T1 default question, and section 6 moves from design to priority.
- A device test showing the IME is not treated as foreground while recording (API note Q4): every hold-to-talk latency arm would need a foreground service, which changes the battery and thermal arms.
- A pinned quantized ggml row with a measured lower peak memory at a measured WER cost: it becomes the first arm after the two current models.

**Status line.** Protocol design only: synthetic and unrun. No device, emulator, Gradle build, Android test or model download was used. No number in this note is a YazSes measurement; every performance value it would produce is [Unknown] until #87 and #92 land and a named device is run.
