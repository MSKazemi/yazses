# Pinned and privacy-safe evaluation of offline ASR in YazSes

**Date:** 2026-11-03  
**Status:** Research result and proposed protocol v0.1; **not an implemented benchmark or a release decision**  
**Tracking:** [NEXT-ASR-02 #793](https://github.com/MSKazemi/yazses/issues/793), [research epic #787](https://github.com/MSKazemi/yazses/issues/787)  
**Repository snapshot:** MSKazemi/yazses, main at 1598e65b708b86c2f8d5fa51749407e4a18740be (YazSes 2.48.1)  
**Policy:** [ADR-030](../adr/adr-030-agent-era-direction.md), [ADR-011](../adr/adr-011.md), [milestone policy](../milestone-policy.md)  
**Related proposed decision:** [ADR-033](../adr/adr-033-reproducible-asr-evaluation-gate.md)

> Evidence legend: **[R]** directly inspected repository code/documentation at the snapshot; **[P]** primary upstream publication or specification, not re-measured by YazSes; **[D]** research design choice requiring review; **[U]** unverified. No model was downloaded or benchmarked in this study. Numerical examples are mathematical test vectors, not model results.

## Executive answer

**Adopt the protocol as the research reference; defer any recommendation to change an engine/default; reject comparisons based only on one WER number or an uninspectable result archive.** [D]

The immediate bottleneck is not absence of model candidates. It is that published accuracy, practical final-commit latency, memory, and robustness are not all measured on the same version-pinned, independently inspectable evidence boundary. Better comparisons would directly serve ADR-030 Pillar 1, the English default-engine decision [#645](https://github.com/MSKazemi/yazses/issues/645), new-runtime screening [#792](https://github.com/MSKazemi/yazses/issues/792), multilingual evaluation [#797](https://github.com/MSKazemi/yazses/issues/797), and the synthesis [#798](https://github.com/MSKazemi/yazses/issues/798). [R]

This is a **methodology result**. It does not claim that Parakeet, Whisper, Moonshine, or any 2026 runtime wins on unmeasured hardware or multilingual dictation.

## 1. The precise gap in the current repository

| Evidence inspected | What exists | What is insufficient for a new public comparative claim |
| --- | --- | --- |
| [docs/benchmarks.md](../../docs/benchmarks.md) [R] | Historical CPU measurements on LibriSpeech, including speaker-stratified 200-utterance samples, CIs on some runs, failure analyses, decode controls, and explicit caveats | The page says that the principal paper benchmark harness and raw result files live in a private archive and are **not in this repository**. These historical results must be labelled as such, not represented as newly reproducible by this study |
| [data/librispeech-sample](../../data/librispeech-sample) [R] | One JFK audio/reference pair for a local smoke test | One clip cannot estimate population WER, variance across speakers, or p95 |
| [scripts/bench-stt.py](../../scripts/bench-stt.py) [R] | Available community WAV/TXT harness: normalized WER, decode-only RTF, and a memory readout | No pinned corpus manifest/revisions, no per-utterance scores, no CI, no partial/final latencies; skips missing or failed inputs; model load excluded; no resolved-engine assertion |
| Same harness [R] | Uses Whisper EnglishTextNormalizer when installed | Without it, falls back to lowercasing and prints a warning. Results from the two profiles cannot be pooled |
| Same harness [R] | Attempts to report peak RSS | With psutil on Linux, reads **current** process RSS at end, not necessarily peak. External-tool subprocess memory is deliberately N/A. Cross-platform peak comparison is not established |
| Same harness [R] | Calls build_engine for in-project models | [factory.py](../../src/yazses/stt/factory.py) can log and **fall back to faster-whisper** on engine load failure. The benchmark must attest to the **resolved** engine/model, not merely the requested one |
| [stt/base.py](../../src/yazses/stt/base.py) and [stt/streaming.py](../../src/yazses/stt/streaming.py) [R] | Shared transcribe, transcribe_words, decode_window seam and LocalAgreement streaming wrapper | Rolling-window work/partial text is distinct from final whole-utterance decode; existing offline WER/RTF alone cannot claim streaming UX |
| [stt/latency.py](../../src/yazses/stt/latency.py) [R] | Recent per-model decode p50/p95 in memory, p95 only after 20 samples | Decoder-only, not microphone-release-to-final-ready or actual text-delivery timing |
| [docs/models.md](../../docs/models.md) [R] | Identifies current Whisper/faster-whisper, Parakeet and Moonshine options; English-only limits of some weights | Model ranking on one reading corpus is not generalized to accent, code-switching, typing into apps, or hardware beyond that test |

**Important distinction:** The project has meaningful historical measurements and identified decoder instability, including insertion-heavy fallback behavior; it is *not* accurate to say YazSes has no measurements. But claims about new candidates or new platforms need a public, pinned, independently rerunnable experimental contract. [R]

## 2. Research questions and pre-registration

1. **Q1 (quality):** For the *same fixed licensed audio* and references, how do supported models differ in corpus WER/CER, deletions, substitutions, insertions, empty outputs, and catastrophic insertions? Does the result change across clean read speech, harder read speech, and independently sourced spontaneous speech?
2. **Q2 (user experience):** For the same audio/host and stage policy, how long does it take from **key release** to correct, committed text? What are p50, p95, first stable partial, final-ready, and delivery-done delays, with no misleading interchange of these terms?
3. **Q3 (resource cost):** What are isolated-process cold load, first inference, warmed decode, peak RSS including child processes, model bytes on disk, and CPU-time proxy on modest computers? What is unsupported instead of slow?
4. **Q4 (trustworthiness):** Do rankings survive speaker-clustered paired uncertainty estimates, repeats, a second hardware class, code-switch/Unicode and no-speech stress tests? Can another researcher reconstruct every compared row?

Pre-register: candidate + baseline, exact corpora/slices, primary metric per slice, normalizer version and configuration, bootstrap unit and seed, replicate schedule, failure handling, thresholds, exclusion rules, and all secondary outcomes **before looking at candidate scores**. Any changes are dated amendments, not silent post-hoc edits. [D]

## 3. Corpus plan and provenance

| Tier | Data / provenance | Purpose and constraints |
| --- | --- | --- |
| P0: synthetic | Version-controlled, text-only fake references/hypotheses, invented IDs and timestamps. No voice or participant data | Validate scoring, Unicode handling, timing equations, paired joins, failure policy; **not an ASR accuracy score** |
| P1: public, read English | LibriSpeech SLR12 test-clean AND test-other, official [OpenSLR corpus](https://www.openslr.org/12/), CC BY 4.0 [P] | First same-input CPU engine comparison. Start with the **existing fixed 200-utterance per-split manifests only if their exact ID lists can be recovered**; otherwise publish new deterministic speaker-stratified ID manifests with seed. For publication-quality comparisons, report full available test splits when feasible, including speaker counts |
| P2: public, multilingual | [FLEURS](https://huggingface.co/datasets/google/fleurs), official pinned dataset revision, CC BY 4.0 [P] | Per-language test split; include Persian and Mandarin only after verified dataset locale IDs, transcription conventions, and actual engine language capability. Do not treat different languages as interchangeable |
| P3: public, spontaneous | Mozilla [Common Voice](https://commonvoice.mozilla.org/) **Spontaneous Speech v5.0** or a later fixed, explicitly identified release; v5.0 was [announced 2026-09-18](https://discourse.mozilla.org/t/common-voice-scripted-speech-v27-0-and-spontaneous-speech-v5-0-released/149490) [P] | Challenge read-speech bias. Verify each language's official available splits, speaker IDs, per-release licence/terms and exclusion rules before use; do not assume test-set size, speaker separation or availability |
| P4: synthetic stress audio | Concatenations of **permitted** public speech segments with generated silence/noise plus an exact construction manifest | Long prompts, 1/3/8-second thinking pauses, silence, repeated phrases, abrupt starts, temperature fallback and sample-boundary effects; report as **constructed stress tests**, never real spontaneous-speech evidence |
| Future: research | An independent consented participant study if justified | Separate ethical/protocol review, explicit purpose and withdrawal process. Do not repurpose GitHub community QA reports as research data (proposed [ADR-v2-150](../adr/adr-v2-150-evaluation-evidence-and-research-consent.md)) |

**Licence and privacy:** OpenSLR identifies LibriSpeech as CC BY 4.0; FLEURS' dataset card says CC BY 4.0; Mozilla says its Common Voice contributions are offered under CC0, but the **exact downloaded release and its applicable use terms must be checked**. Permissive audio licensing does not imply the model was not trained on it. Record known or suspected training/test overlap and classify a model evaluated on a training-family corpus as *possibly in-domain*, not a valid zero-shot claim. [P/D]

For each corpus, store a locally reproducible *manifest* (UTF-8/JSONL): dataset ID, upstream revision/tag, landing URL, license, split, audio SHA-256, reference SHA-256, sample ID, speaker/group ID when legitimately available, language, condition, duration and sample rate, and inclusion/exclusion reason. The public version may contain these for explicitly licensed public corpora, but **not** private audio, transcripts, health, participant or identifying metadata. Record corpus count and SHA-256 for the **entire sorted manifest**; do not only cite a mutable “latest” URL. [D]

**Data leakage controls:** Dedupe on audio digest and normalized reference; enforce speaker/group separation when the corpus supports it; inspect model cards for disclosed training datasets; keep development/pilot and locked evaluation sets distinct. A corpus's declared train/test split is necessary but not proof a pretrained external model never saw that test item. If overlap cannot be excluded, label it [U] and report it. No benchmark prompt, vocabulary list, fine-tuning or hyperparameter search may use the held-out test references. [D]

## 4. Comparison arms and exact control

**Initial controlled arms:** shipping faster-whisper base.en (baseline), the existing Parakeet TDT English backend, and the existing Moonshine English backend only after recording the exact model checkpoint actually resolved. These are a *study design*, not a tested recommendation. Additional experimental candidates belong to [#792](https://github.com/MSKazemi/yazses/issues/792); engine selection stays in [#645](https://github.com/MSKazemi/yazses/issues/645) / [#798](https://github.com/MSKazemi/yazses/issues/798). [R/D]

Every **run** must record:

- Repository 40-character SHA, branch/tag, Python version, OS kernel/build, CPU model/ISA/core count, RAM, power profile, thermal/CPU-load measurements, GPU/backend if used, and benchmark-tool source SHA.
- Requested engine AND **resolved active engine/model** using the existing factory's description; fallback-from/reason. Any fallback makes that candidate cell **INVALID**, not a victory for the fallback model.
- Model repository ID, immutable upstream revision, weight-file SHA-256, weight bytes, model license separately from runtime license, cache location provenance, tokenizer/config hashes, runtime package versions, quantization, CPU thread count and affinity.
- All decoder knobs as effective values: language/task, beam size, temperature/fallback, condition_on_previous_text, VAD, endpointing, streaming enabled, audio chunk length, initial prompt, vocabulary correction, normalizer, postprocessor and output path. “Default” is not an exact parameter if upstream can change it.
- Preprocessing: same audio bytes for every model; pin conversion tool and input/source hashes. Feed each engine identical mono 16 kHz float32 PCM where supported, with no candidate-specific hidden gain/noise changes; preserve a copy or digest of the transformed PCM for audit.
- Study mode from the proposed community/research evidence separation: synthetic or ci for automation; community_qa for volunteered engineering validation; research only under a versioned participant protocol. Never infer this from the results after collection.

Model and dataset downloads are **separate, explicit preparation** steps by the operator. Inference and scoring operate on verified local artifacts, with networking disabled (e.g. HF_HUB_OFFLINE=1, together with a checked local-only firewall/container); a missing model fails closed rather than triggering a silent download. This maintains [ADR-011](../adr/adr-011.md) / [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md). Primary Hugging Face documentation confirms HF_HUB_OFFLINE disables Hub HTTP access; this does **not** by itself prove every external tool has no other network path. [P/D]

## 5. Metrics: definitions, not interchangeable labels

### Recognition correctness

- **Normalized corpus WER** = (sum substitutions + deletions + insertions) / sum reference word count. Use **pooled edit counts**, never the unweighted mean of per-clip percentages. WER may exceed 100% due to insertions; do not cap it. Report S, D, I, N separately. [P]
- **CER** = Levenshtein character edits / reference character count. Define “character” in the scorer contract: NFC-normalized Unicode code point for the primary reported CER, with an optional separately labelled grapheme-cluster analysis. Do not silently delete Persian U+200C (ZWNJ), Han-script variants, or code punctuation. [D]
- **Two explicitly different text views:** (1) recognition-normalized WER/CER, with the *same pinned normalizer and locale/tokenization per cell*; (2) raw user-visible output/error, including punctuation, case, technical identifiers and script preservation. Do **not** substitute a lowercasing fallback when a normalizer is unavailable. English reference profile: pinned OpenAI Whisper EnglishTextNormalizer; non-English profiles developed and frozen under #797. [P/D]
- **Technical/error costs:** exact identifier preservation, punctuation/case, number and symbol preservation; ZWNJ and Han-script character preservation; no-speech hallucinated token count per silence minute; and catastrophic insertion events (e.g. output exceeds twice the reference token count, a provisional engineering threshold). Report each separately, never hide them by a fluent normalized WER. [D]
- **Invalid/empty cases:** empty output for a nonempty reference counts as N deletions **if the engine ran successfully**; a missing file, model load failure, timeout, crash or unexpected engine fallback is a separately visible *coverage/reliability failure*, **not** a silently skipped utterance and **not** silently scored as an ASR error. A zero-word reference/silence is never divided by zero: score false-positive words/characters separately. Record both coverage and WER on the prespecified completed set; do not compare accuracy across unequal successful subsets without a matched-subset sensitivity analysis. [D]

NIST's [SCTK/sclite documentation](https://github.com/usnistgov/SCTK) specifies S/D/I accounting; Hugging Face's [audio evaluation guide](https://huggingface.co/learn/audio-course/chapter5/evaluation) explains corpus aggregation and normalization; [JiWER](https://jitsi.github.io/jiwer/) implements WER/CER, but its exact package release and transformations must be pinned. [P]

### Latency and resource cost

Record monotonic timestamps in *each* run: mic-start/audio-present (for real path tests), end-of-input/key-release (t_release), first tentative partial, first stable partial, last partial, final transcript ready (t_final), and safe test-sink delivery done (t_delivered).

| Metric | Definition and interpretation |
| --- | --- |
| Decode latency | Measured time for the backend transcribe call only, after input PCM exists. This is closest to current YazSes status |
| Release-to-final | t_final − t_release; user-visible wait for authoritative text, **including** any release-path overhead |
| Release-to-delivered | t_delivered − t_release using a controlled local test sink; **not** a claim that arbitrary application injection succeeds |
| First stable partial | t_first_stable − t_audio_present, or N/A if streaming disabled; never silently equal first tentative text |
| Partial churn | Retracted/replaced characters and repeated/duplicate committed content per utterance; does not substitute for final WER |
| Real-time factor (RTF) | Total relevant decode seconds / total audio duration seconds; document whether per-clip warmed, cold process, or repeated windows |
| Cold load / first decode | New isolated process load time and first decode separately, with cache/OS-page-cache state documented |
| Memory | Idle/import baseline, after-model-load RSS, sampled maximum RSS during decode (process and descendants, sampler interval recorded); note shared-memory double counting risk, and whether OS high-water memory is available |
| Energy | Joules only with calibrated/supported package counters and background correction; otherwise **process CPU seconds per minute of audio** as an explicitly named *compute proxy*, never watt-hours |

**Repetition:** per arm and hardware, aim for at least 3 independent process launches, a recorded warm-up, and 3 shuffled warm measurement passes; preserve each run separately rather than reporting only a lucky one. Keep CPU concurrency and power profile fixed, report saturation/thermal throttling, and randomize model execution order. A true cold disk-cache run must be explicitly distinguished from “new process with warm OS page cache.” p95 is not reported for tiny samples (the shipped latency module requires at least 20), and a publishable tail estimate should use many more observations and uncertainty. [D]

**Hardware matrix (planned, not measured):** one ordinary 8-GB CPU-first laptop, one 16-GB CPU laptop, and at least one different architecture/OS if available; add Apple silicon, Windows and Intel NPU only with actual verified hardware. A machine that lacks a backend is an *unsupported* row, not WER 100% and not an invented latency. Cross-hardware speed comparisons are descriptive; a paired speed comparison is on the **same machine**, not across different CPUs. [D]

### Streaming and long pauses

Apply a **separate** protocol branch for #796: deterministic audio chunks at a fixed cadence, 1/3/8-second silent thinking pauses, 5/30/60-second speech sessions, pauses near punctuation, partial hypothesis logs, and a final release. For every commit require that no already committed text is silently deleted/duplicated and no final result is submitted to a client automatically. Synthetic-silence experiments establish an engineering invariant, not spontaneous human performance. Do not compare a full-buffer final backend against a rolling-window backend's single-step RTF as if they did equal work. [D]

## 6. Statistical analysis and honest uncertainty

1. **Units:** report corpus-level WER per pre-registered split/language/condition, number of clips, distinct speakers/groups, total reference words and total seconds. A model with no coverage in a language gets “unsupported”, not an interpolated score.
2. **Paired comparisons:** require **identical sample IDs and input PCM hashes** for baseline and candidate. Compute ΔWER = WER(candidate) − WER(baseline), in percentage points, from recomputed pooled edit counts, not average per-clip deltas. Report ΔCER alongside it where appropriate.
3. **Dependence:** use a **speaker/group-block bootstrap** within each split/language, resampling speaker blocks with replacement, keeping both model scores paired. Use a preregistered 10,000 replicates and fixed recorded RNG seed, a percentile 95% interval as the initial analysis; include a sensitivity analysis for groups of different lengths and a known non-overlap result. This follows the dependency problem documented in [Liu & Peng, INTERSPEECH 2020](https://ai.meta.com/research/publications/statistical-testing-on-asr-performance-via-blockwise-bootstrap/). When speakers are unknown, state the inferential limitation; do not pretend utterances are independent.
4. **Repeatability:** report between-process spread, deterministic/non-deterministic decode counts, worst-case insertion outliers and any instability attributable to temperature fallback. Pin exact settings rather than treating library defaults as experimental controls.
5. **Multiplicity:** predeclare primary comparisons; exploratory language slices and many candidates are labelled exploratory or use a stated familywise adjustment. No “win” from overlapping marginal CIs alone; analyze paired differences.
6. **Tail latency:** report p50/p95 separately per device with n and process repeats. Model load failures, timeouts and censored waits stay visible, never dropped before percentile calculation. Do not claim statistically resolved p95 changes from an underpowered sample.
7. **Decision margins:** proposed engineering **discussion thresholds, not known user preferences:** a new candidate should show no materially worse recognition (e.g. upper 95% paired ΔWER ≤ +0.5 percentage point in a designated English slice), and if sold as “faster”, demonstrate ≥20% p95 release-to-final reduction on at least two target CPU profiles without a reliability regression. These values are **unapproved placeholders**; benchmark pre-registration and user error-cost evidence must set real thresholds before testing. No automatic default switch follows a statistical result.

**Decision rule:** No cross-device leaderboard that mixes different corpora, normalization, decode temperatures, missing outputs, or model-fallback cells. A candidate may dominate one condition and lose another; publish the Pareto trade-off with uncertainty. For an engine-default change, the separately approved ADR must weigh quality, tail latency, failure rate, model size, license and dependency cost. [D]

## 7. Machine-readable result contract (proposed v1)

Each scored attempt produces **one record per expected sample per run per arm**. A run summary is derived from those records, never typed into a Markdown table by hand. Minimum fields, with no secrets, paths or transcript bodies in a public export:

| Group | Fields |
| --- | --- |
| IDs | protocol_version, run_id, candidate_id, corpus_id, corpus_manifest_sha256, sample_id, split, language, group_id (public licensed data only), repeat_index |
| Provenance | repo_commit, benchmark_commit, model_revision, weight_sha256, package_lock_sha256, actual_engine, actual_model, fallback_from, normalizer_name/version/config_sha256 |
| Conditions | device/hardware profile ID, PCM SHA-256, reference SHA-256, audio_duration_ms, threads, device, compute_type, task, decode_parameters_sha256, environment/reproducibility policy |
| Outcome | status (ok / unsupported / missing / load_failure / timeout / crash / fallback), failure_category (sanitized), ref_word_count, sub, del, ins, ref_char_count, char_sub, char_del, char_ins |
| Timing/resources | decode_ms, release_to_final_ms, release_to_delivery_ms, first_stable_partial_ms or null, sampled_peak_rss_bytes or null, cpu_time_ms or null, energy_joules or null, measurement_method |
| Evidence | study_mode, data_license, dataset_revision, source_provenance, known_training_overlap, local_only=true, source_id where allowed |

Record field validity rules: status != ok never contributes a fabricated accuracy number; for ok and ref_word_count > 0, S+D ≤ N and all edit counts are nonnegative; result rows unique by (run_id, candidate_id, sample_id, repeat_index); denominator and cohort counts fixed by the locked manifest; exact candidate/fallback identity verified; if a timestamp does not exist, value is null plus reason, not zero. Raw audio/transcripts/participant IDs are **not** in this export. A full publishable package contains the manifest, schema, source code + lockfile, all row-level **licensed-public or synthetic** error counts, run environment and a generated summary with a cryptographic manifest digest. [D]

### Synthetic unit-test vectors (these are **not** experiment results)

| Reference | Hypothesis | Expected score / reason |
| --- | --- | --- |
| “open the repo” | “open a repo” | WER 1/3: one substitution |
| “open the repo” | “open the repo now” | WER 1/3: one insertion |
| “open the repo” | empty text | WER 3/3: three deletions if the decoder ran normally |
| empty text (silence) | “hello” | WER undefined: one false-positive token; no division by zero |
| Persian “می‌روم” (contains U+200C) | “میروم” | Under NFC code-point CER: 1 deleted code point out of 6 = 1/6; preservation metric must flag missing ZWNJ |
| Chinese “你好世界” | “你好” | CER 2/4 = 50%; word-tokenization conventions still require language policy |
| Any candidate cell with requested Parakeet but actual faster-whisper | Not scored | Fallback status; report coverage failure even if text appears correct |
| One expected clip missing or decode aborted | Not scored silently | Run completeness check fails; publish failure rate and matched-set sensitivity |

Require synthetic unit tests for: byte order/Unicode, empty references, duplicate sample IDs, missing manifests, normalized profile mismatch, model fallback, p95 with n<20, block bootstrap preserving pairs, late partials, repeated text, timeouts, and memory measurement method labels. A corpus smoke test can use the existing JFK sample, but no WER paper claim follows from it. [D]

## 8. Failure taxonomy and research security gates

| Failure | Required action |
| --- | --- |
| Missing/corrupted model; different weight hash | Stop arm; mark unavailable/invalid; never download implicitly |
| Requested engine fell back to Whisper | Reject candidate-arm score; record actual engine and reason |
| Test ID/reference absent or duplicate | Reject run completeness and report coverage |
| Inconsistent normalizer/version or locale mapping | Reject cross-arm comparison |
| Speech output on silence | Count false-positive words/chars per silence duration |
| Huge repeated/hallucinated transcript | Count S/D/I and catastrophic insertion event; do not trim to look better |
| CPU saturation, thermal throttling, change of power mode | Tag affected run; rerun in controlled conditions if possible; preserve discarded run as negative evidence |
| Unsupported language or platform | “Unsupported”; no extrapolation from English or another OS |
| Unexpected network access | Fail privacy gate and document attempted destination; no captured speech content |
| Public artifact contains voice, transcript, health or participant data | Do not publish; review and remediate offline |
| Vendor benchmark without reproducible conditions | Record as [P] claim, never upgrade to YazSes [R] measurement |

No external service, cloud transcription, new default, new telemetry or user-data collection is authorized. On-device speech files and reference text are processed locally; public publication is **aggregate and licensed-public/synthetic evidence only**. Privacy and research/engineering QA are different classes. [D]

## 9. Concrete execution plan

1. **Protocol review (#793).** Freeze data schema, metrics, explicit normalizer profiles and preregistration form; get a maintainer-approved proposed ADR-033 decision. No production code change.
2. **Synthetic analyzer proof (#793).** Add a pure deterministic, no-network script and tests that consume synthetic v1 JSONL, enforce manifest completeness/fallback/normalizer invariants, produce counts + paired speaker-block bootstrap and privacy-safe summary. Make its versioned source public.
3. **Reproducible English pilot (#793 with #792).** Pin a small controlled matrix: shipping faster-whisper base.en vs Parakeet and Moonshine where licenses support the arm; lock LibriSpeech test-clean/test-other sample manifests, weight hashes and exact dependency lockfiles. Measure on one isolated CPU and independently rerun on a second machine. **These data are not collected by this document.**
4. **Broader data (#797).** FLEURS and Common Voice with per-language normalization, training overlap and coverage register; never test an English-only engine on Persian and call the result language support.
5. **Pauses/streaming (#796).** Execute separately controlled LocalAgreement, pause, no-duplicate-commit and safe test-sink latency replay.
6. **Governance (#798 / #645).** Present evidence, negative results, paired intervals, resource trade-offs and a clear adopt/defer/reject *engine* decision in a distinct accepted ADR if warranted. Until then maintain existing defaults.

**Explicit status at 2026-11-03:** Architecture and protocol researched; public datasets/licences and benchmark metrics checked against primary sources; repo limitations inspected. **No new WER, CER, latency, RSS, streaming stability or power measurements were run**; no participant data acquired; runtime/default remains unchanged. The next step is an independently reproducible implementation of the measurement protocol, not a promotional performance claim.

## Primary sources and reproducibility pointers

1. [YazSes public benchmark page](../../docs/benchmarks.md) and [current community harness](../../scripts/bench-stt.py); code snapshot listed above. [R]
2. [YazSes SttEngine protocol](../../src/yazses/stt/base.py), [engine factory](../../src/yazses/stt/factory.py), [streaming wrapper](../../src/yazses/stt/streaming.py), [latency aggregation](../../src/yazses/stt/latency.py), and [models guide](../../docs/models.md). [R]
3. [OpenSLR 12 — LibriSpeech](https://www.openslr.org/12/) (CC BY 4.0, separate test-clean/test-other). [P]
4. [Google FLEURS dataset card](https://huggingface.co/datasets/google/fleurs) (CC BY 4.0, language/split details and read-speech limitations). [P]
5. [Mozilla Common Voice legal terms](https://commonvoice.mozilla.org/terms/en.html) and [2026-09-18 v27.0/v5.0 announcement](https://discourse.mozilla.org/t/common-voice-scripted-speech-v27-0-and-spontaneous-speech-v5-0-released/149490). [P]
6. [NIST SCTK](https://github.com/usnistgov/SCTK), [Hugging Face ASR evaluation](https://huggingface.co/learn/audio-course/chapter5/evaluation), [JiWER documentation](https://jitsi.github.io/jiwer/) (WER/CER and normalization context). [P]
7. [Liu & Peng — Statistical Testing on ASR Performance via Blockwise Bootstrap, INTERSPEECH 2020](https://ai.meta.com/research/publications/statistical-testing-on-asr-performance-via-blockwise-bootstrap/) (dependence across utterances and resampling blocks). [P]
8. [Hugging Face Hub offline environment variables](https://huggingface.co/docs/huggingface_hub/main/package_reference/environment_variables) (HF_HUB_OFFLINE and its scope). [P]
9. [faster-whisper upstream project](https://github.com/SYSTRAN/faster-whisper) (decoding/fallback setting semantics; exact release must be frozen per run). [P]
10. [ADR-030](../adr/adr-030-agent-era-direction.md), [ADR-019](../adr/adr-019-egress-inventory-and-escalation.md), [ADR-v2-150](../adr/adr-v2-150-evaluation-evidence-and-research-consent.md), [#792](https://github.com/MSKazemi/yazses/issues/792), [#796](https://github.com/MSKazemi/yazses/issues/796), [#797](https://github.com/MSKazemi/yazses/issues/797), [#798](https://github.com/MSKazemi/yazses/issues/798). [R]
