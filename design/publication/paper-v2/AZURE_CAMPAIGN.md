# August 2026 Azure measurement campaign

This document reconstructs the measurement campaign behind most of the new paper-v2 evidence. It is written so an author or reviewer can tell **what ran where, in what order, which artifacts are exploratory, and which conclusions are safe**.

## 1. Campaign window and machines

The main rented-compute window was **2026-08-23 through 2026-08-24**, followed by analysis and a small number of follow-up measurements through **2026-08-26**.

The probe archive states that the exploratory runs were produced during a two-day Azure window on **two rented 16-vCPU Xeon machines in `westeurope`**. The stable artifacts identify the principal host as:

- Azure `Standard_D16s_v6`
- Intel Xeon Platinum 8573C
- 16 logical CPUs
- about 67.4 GB RAM
- Ubuntu 24.04.4 LTS
- Azure kernel
- CPU inference, int8
- faster-whisper 1.2.1
- CTranslate2 4.8.1 for the principal ASR matrix
- YazSes around 2.29.0–2.31.0 during the measurement window, as recorded per artifact

The exact version, load average, command, corpus identity, and library versions must be read from each artifact's `provenance` block. Do not replace those fields with one campaign-wide value.

## 2. Why Azure compute does not contradict the product privacy claim

YazSes' product claim is that normal dictation/transcription can run locally without sending a user's audio to a cloud service.

The research campaign used rented cloud **compute** to evaluate public benchmark corpora and synthetic test material. The paper should state this plainly so readers do not confuse “offline runtime architecture” with “all experiments were physically executed on the author's laptop.”

Recommended wording:

> The evaluated product path is local/offline at runtime. For the expanded benchmark campaign we additionally rented CPU-only Azure VMs to run public and synthetic corpora under controlled, reproducible hardware conditions; no user dictation data were uploaded for these experiments.

Synthetic meeting audio generated with Azure Speech TTS is a benchmark fixture, not evidence about privacy of real user audio and not a substitute for human meeting evaluation.

## 3. Corpora used and the question each one answers

### LibriSpeech `test-clean`

- 200 utterances in the main matrices
- deterministic speaker-stratified selection
- clean read audiobook speech
- useful for model comparison and repeated-decode mechanisms
- **not** a real-world dictation estimate

Question: *Under controlled clean speech, how do local engines/configurations compare?*

### LibriSpeech `test-other`

- 200 utterances
- 33 speakers
- about 23.4 minutes
- same scoring/normalisation family, but harder audio than `test-clean`

Question: *Does the clean-audio ranking and reproducibility survive a harder split?*

It is a robustness stressor, not spontaneous microphone speech.

### AMI test split

- 16 real four-person meeting recordings
- 543.7 minutes of recordings
- 30,714 s / 8.5 h of scored reference speech in the archived aggregate
- human RTTM annotations from the pyannote AMI diarization setup
- headset mix, cleaner than a single far-field table microphone

Question: *Does Meeting Mode's diarization configuration work on real annotated meetings, and what type of error dominates?*

### VoxConverse subset used by the plausibility/threshold work

Used to test whether heuristics tuned on meetings transfer to crowded/broadcast-style speaker distributions.

Question: *Is a clustering threshold or “implausible label” guard domain-general?*

### Synthetic meeting corpus

Generated dialogue + Azure neural TTS, used as a controlled regression fixture and as the earliest diarization probe.

Question: *Does the harness detect gross regressions under known synthetic conditions?*

It must never be averaged with AMI DER or presented as evidence of real-meeting accuracy.

## 4. Campaign chronology — how the questions evolved

The commit and artifact history is scientifically useful because it shows that the campaign changed hypotheses rather than simply confirming them.

### Phase A — make the benchmark capable of falsifying documentation

Before the rented runs, the harness was extended so it could:

- compare engines rather than only YazSes against itself;
- identify the selected corpus and command in provenance;
- survive one engine failure without losing completed rows;
- run `test-other`, not only `test-clean`;
- score real annotated diarization, not only synthetic meetings.

This matters because several later “findings” are actually corrections to claims the old harness could not test.

### Phase B — engine matrix and harder speech

The two main WER matrices established:

- eight engine/checkpoint rows on clean speech;
- the same family on `test-other`;
- confidence intervals;
- real-time factor on the Azure Xeon.

The hard split immediately showed that:
- model degradation is not uniform;
- clean-speech ordering is not enough;
- `large-v3` can move dramatically between identical runs.

### Phase C — repeat the disagreement instead of choosing a convenient run

Rather than replacing the 7.69% `large-v3` result with the earlier 4.86% result, both were kept and the benchmark archive was changed so displaced runs survive under `paper/results/history/`.

This is a core methodological contribution of the campaign: **a contradictory rerun became the research question**.

Follow-up probes measured:
- repeated hypothesis sets;
- insertion/substitution/deletion components;
- temperature fallback behaviour;
- thread-count hypotheses;
- previous-text conditioning;
- per-utterance concentration of the aggregate WER effect.

### Phase D — 2×2 decoder mechanism and checkpoint ladder

The initial hypothesis “temperature fallback is the cause” was too simple. Disabling the fallback made some runs dramatically worse.

The more informative intervention was `condition_on_previous_text=False`, which:
- removes the measured `large-v3` runaway repetition mode;
- slightly harms the default `base.en`;
- has a smaller effect on `small.en`;
- produces byte-identical output at `medium.en`.

That is why paper v2 should present the mechanism as **an interaction among checkpoint behaviour, previous-text conditioning, and the fallback rescue path**, not “sampling is bad.”

### Phase E — test platform portability rather than assuming it

The benchmark workflow was dispatched to:
- Linux x86-64,
- Linux arm64,
- macOS arm64,
- Windows x86-64.

Separately, dependency resolution was probed across platform/extras combinations. This distinguishes:
1. “the decoder yields similar text on this ISA,” from
2. “this optional feature can actually be installed here.”

Those are different claims and should stay different in the paper.

### Phase F — challenge product assumptions

The campaign then tested assumptions that had been encoded as defaults/documentation:

- beam width,
- pre-speech padding,
- streaming,
- diarization clustering threshold,
- supplied speaker count,
- plausibility guards,
- centroid-based repair.

The result is intentionally mixed. Several defaults survived; several rationales did not.

## 5. Stable artifacts vs. probes

### Tier 1 — manuscript-grade stable measurements

Prefer these for headline claims:

- `paper/results/wer.json`
- `paper/results/wer-test-other.json`
- `paper/results/beam-test-clean.json`
- `paper/results/beam-test-other.json`
- `paper/results/onset.json`
- `paper/results/diarization-ami16_corpus-der.json`
- `paper/results/diarization-ami16_corpus-maxspk4.json`
- `paper/results/platform-resolution.json`
- `paper/results/platforms/*`
- `paper/results/plausibility-*.json`
- `paper/results/streaming.json` when its exact run conditions are stated

### Tier 2 — derived statistical analyses

These are analyses of the same observations, not new measurements:

- `paper/results/beam-*-significance*.json`
- `paper/results/onset-significance.json`
- `paper/results/diarization-*-significance.json`

When writing, never count a measurement and its significance file as two independent experiments.

### Tier 3 — exploratory/probe evidence

`paper/results/probes/` contains the mechanism-finding work. Many of the most interesting reproducibility results live here.

A probe may become a central paper result if all of the following hold:

- the question and intervention are explicit;
- corpus and machine provenance are recoverable;
- the result is repeated or has an independent validation condition;
- the probe's conclusion is not contradicted by a later stable harness run;
- any exploratory multiple-testing risk is acknowledged;
- the paper labels it as a follow-up/mechanism experiment, not a preregistered primary endpoint.

### Tier 4 — history and logs

- `paper/results/history/`: displaced result snapshots; scientifically important when disagreement itself is the finding.
- `paper/results/probes/logs/`: operational trace; use to reconstruct runs, not as the sole citation for a headline number.

## 6. Experiment-to-artifact map

| question | primary artifact(s) |
|---|---|
| Which local ASR engine/checkpoint has the best clean point estimate? | `wer.json` |
| Which degrades least on harder speech? | `wer-test-other.json` |
| Is `large-v3` reproducible? | `probes/largev3-instability-test-other.json`, `decode-determinism-*` |
| Which error component moves across repeats? | `largev3-instability-*`, `decode-mechanism-*` |
| Does disabling previous-text conditioning fix the tail failure? | `decode-determinism-*`, `decode-arms-per-utterance-*` |
| Is greedy decoding cheaper in accuracy? | `beam-test-*.json` + significance files |
| Does synthetic leading silence restore missed onset? | `onset.json` + `onset-significance.json` |
| Is streaming a latency win on CPU? | `streaming.json` |
| Does WER move across OS/ISA? | `platforms/*/wer.json` |
| Do optional installs resolve by platform? | `platform-resolution.json` |
| Does Meeting Mode work on real annotated meetings? | `diarization-ami16_corpus-der.json` |
| Does exact speaker count improve DER at the current threshold? | `diarization-ami16_corpus-maxspk4*.json` + significance |
| Does one clustering threshold transfer across domains? | AMI/Vox/synthetic probe + plausibility artifacts |
| Can centroid similarity safely repair split speakers? | `centroid-merge-ami16_corpus-{meeting,recimport}.json` |

## 7. Statistical/reporting rules for this campaign

### WER

- Always name corpus/split and n.
- For cross-engine statements, prefer interval-aware language over rank language.
- Do not treat a tenth of a WER point across different hosts as a finding.
- For repeated unstable models, report a distribution/range rather than silently selecting one run.
- When a mean change is concentrated in a few utterances, say so.

### Paired ASR comparisons

Use the paired bootstrap artifacts when the same utterances are decoded under two conditions. The pairing is the point: independent bootstrap samples answer a different, weaker question.

### Onset / first-word accuracy

Use first-word paired outcomes and the multiplicity-corrected McNemar interpretation. Do not use whole-utterance WER to claim an onset effect the setting cannot directly cause.

### Diarization

Report **both**:
- time-weighted DER for comparison with conventional published diarization results;
- per-recording mean when describing a meeting-level user experience.

Never compare a synthetic-corpus DER directly with AMI DER.

For paired meeting conditions, use per-recording paired inference; do not infer from two corpus means alone.

### Multiple explorations

The campaign contains hypothesis-generating probes. The manuscript must distinguish:
- primary/repeated result,
- post-hoc mechanism probe,
- product decision informed by evidence.

A product decision can be reasonable even when a mean effect is not statistically resolved; it must not be relabelled as a significant scientific effect.

## 8. Claims the campaign supports

The campaign supports these broad statements:

1. **Audio difficulty changes model conclusions.**
2. **Some decoder/model combinations have meaningful run-to-run tail failures not visible in one average WER.**
3. **The measured `large-v3` instability is insertion/continuation variance, not substitution variance.**
4. **A decoder setting can help one checkpoint and hurt another.**
5. **Cross-platform numerical variation is model-dependent.**
6. **Real-meeting diarization required a very different clustering operating point from the original default.**
7. **Known speaker count and better diarization are not the same objective.**
8. **Several intuitive latency/robustness features fail when measured under the actual CPU budget.**
9. **Keeping contradictory reruns and full provenance materially changed the conclusions.**

## 9. Claims the campaign does not support

Do not claim:

- a universal best ASR engine;
- statistical superiority of Parakeet over every other engine from the 200-utterance clean sample;
- real-world spontaneous dictation WER from LibriSpeech;
- that `large-v3` instability is caused by Azure load;
- that disabling conditioning universally lowers WER;
- that beam 5 is uniquely optimal;
- that 300 ms of silence “recovers” a clipped first word;
- that exact speaker count improves DER at the new threshold;
- that 26–27% AMI DER is state-of-the-art or “good”;
- that cross-platform decode artifacts prove all end-to-end interaction paths;
- a productivity, accessibility, or usability advantage over typing without a user study.

## 10. Reproduction before manuscript freeze

Before submission, rerun or verify the central artifacts against a frozen commit/tag and record that freeze in the paper:

1. create a manuscript tag or exact commit SHA;
2. regenerate `paper/results/MANIFEST.md`;
3. ensure every central result carries `argv`, corpus identity, versions, and machine;
4. rerun the main WER matrices if dependency versions changed materially;
5. rerun the `large-v3` mechanism on at least one additional independent corpus if feasible;
6. verify that the platform artifacts were produced by the same manuscript commit or explain differences;
7. keep all contradictory/displaced runs;
8. generate manuscript tables directly from JSON wherever possible rather than copying values by hand.
