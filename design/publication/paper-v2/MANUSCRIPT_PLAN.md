# YazSes paper v2 — manuscript architecture, experiments, and validation plan

## 1. Proposed paper type

The evidence supports an **expanded empirical systems paper / arXiv v2** now. It can become a stronger standalone HCI/systems submission if a controlled human study is added.

Do not structure the manuscript as a changelog. Features are only relevant when they instantiate or respond to a measurable research question.

## 2. Proposed title and positioning

Recommended working title:

> **YazSes v2: Reproducible Offline Voice Input Across Engines, Hardware, and Meeting Conditions**

Alternative focused title if the decoder study is expanded:

> **When Bigger ASR Models Fail to Stop: Reproducibility and Tail Failures in Offline Dictation**

Recommended positioning:

> The first YazSes paper demonstrated a privacy-first offline dictation architecture and measured clean-speech CPU performance on one Linux laptop. The second paper asks whether those conclusions survive harder speech, alternative local ASR engines, repeated decoding, heterogeneous CPU/OS environments, and real meeting diarization. The central result is that several apparently reasonable conclusions fail under this broader evaluation, and those failures change configuration guidance and product defaults.

## 3. Research questions

### RQ1 — Accuracy/robustness
How do local ASR engines and checkpoints compare when the same product pipeline is evaluated on clean and harder speech?

**Primary outcomes:** WER, 95% interval, error decomposition, RTF.

### RQ2 — Reproducibility
Are repeated decodes of the same utterances stable, and when they are not, which error component changes?

**Primary outcomes:** distinct hypothesis sets, WER distribution, substitutions/deletions/insertions, per-utterance concentration.

### RQ3 — Decoder mechanism
How do beam width, temperature fallback, and previous-text conditioning interact with checkpoint size?

**Primary outcomes:** paired WER difference, distinct outputs, catastrophic repetition rate, decode-pass/fallback counts.

### RQ4 — Hardware portability
How much do decoded outputs and installability change across CPU ISA and operating system?

**Primary outcomes:** cross-platform WER spread, dependency-resolution success, platform-specific unsupported extras.

### RQ5 — Interactive latency assumptions
Do synthetic onset padding and streaming provide the benefits the product rationale claims under CPU constraints?

**Primary outcomes:** paired first-word correctness, speech-end→final text, time to first partial, visible-at-release fraction.

### RQ6 — Meeting diarization
Does the shipped diarization configuration transfer to real meetings, and what do threshold and known speaker count actually control?

**Primary outcomes:** time-weighted DER, per-recording mean DER, collar DER, speaker-count error, paired condition differences.

### RQ7 — Research infrastructure
Does preserving provenance, failed rows, and displaced reruns alter conclusions compared with a conventional “latest result wins” benchmark workflow?

**Outcome:** documented cases where retained contradictory runs triggered new experiments or withdrew claims.

## 4. Contributions section draft

The paper can claim the following contributions if the final evidence freeze passes:

1. **Expanded common-harness evaluation.** A reproducible CPU benchmark of multiple local ASR engines/checkpoints under a single product integration path on clean and harder LibriSpeech conditions.
2. **Tail-failure reproducibility analysis.** A repeated-decode study that localises measured `large-v3` WER variance to insertions/runaway continuation rather than substitutions.
3. **Checkpoint-dependent decoder analysis.** A controlled study of previous-text conditioning, beam width, and fallback behaviour showing that configuration effects do not transfer monotonically across model sizes.
4. **Cross-platform measurement.** Decode artifacts across four OS/ISA environments plus dependency-resolution analysis across optional feature sets.
5. **Real-meeting evaluation.** Full AMI-test-split diarization results that reveal and correct a severe clustering-default mismatch and distinguish speaker-count correctness from DER.
6. **Negative-results-driven design.** Direct measurements showing that several intuitive interventions—synthetic pre-speech silence, generic CPU streaming, and simple centroid merge—are not generally beneficial.
7. **Auditable benchmark artifact design.** A result archive with per-run provenance, command/corpus identity, displaced-run retention, and paired statistical analyses that prevent contradictory reruns from being silently overwritten.

## 5. Suggested manuscript structure

### 1. Abstract

Four-part structure:

1. problem: offline voice input is attractive for privacy but benchmark claims are often clean-speech, single-run, and single-machine;
2. method: evaluate YazSes across local engines, clean/hard speech, repeated runs, four platforms, and real AMI meetings;
3. results: hard speech changes conclusions; `large-v3` variance is insertion-driven; conditioning is checkpoint-dependent; old diarization default fails on AMI; several intuitive latency heuristics fail;
4. implication: robust offline voice input needs reproducibility/tail-risk evaluation beyond one WER.

Avoid putting too many point estimates in the abstract. Use 2–3 memorable numbers maximum.

Candidate abstract numbers:
- Parakeet 2.06% clean / 2.88% hard point estimates;
- `large-v3` insertion count 101–184 with substitutions fixed at 87;
- AMI old-vs-new clustering mean DER 75.21% → 26.71%.

### 2. Introduction

Narrative:

- local ASR has crossed the threshold where CPU-only systems are practical;
- but an interactive dictation system is sensitive to different failures than offline leaderboard transcription;
- one bad continuation can destroy a document even if average WER changes little;
- clean-speech rankings may not transfer to hard audio;
- a meeting system can “transcribe correctly” while assigning almost every word to the wrong speaker;
- therefore evaluate robustness, reproducibility, hardware dependence, and interaction-specific failure modes.

End with research questions and contributions.

### 3. System overview

Keep concise because v1 already describes architecture.

Include only architecture needed to understand experiments:
- capture → STT engine seam → post-processing → command/text routing → injection;
- pluggable `SttEngine`;
- Meeting Mode diarization path;
- streaming path;
- provenance/result harness.

Explicitly identify what changed from v1:
- alternative local engines;
- recording/meeting pipeline;
- benchmark/archive infrastructure;
- configuration seams used by experiments.

Do not spend pages re-documenting every feature.

### 4. Experimental methodology

Subsections:

#### 4.1 Evidence freeze and software versions
- exact manuscript commit/tag;
- Python, faster-whisper, CTranslate2, engine versions;
- CPU/int8 policy.

#### 4.2 Speech corpora
- LibriSpeech test-clean selection;
- LibriSpeech test-other selection;
- why neither equals real desk dictation.

#### 4.3 Meeting corpora
- AMI reference;
- VoxConverse role;
- synthetic TTS fixture role.

#### 4.4 Hardware
- reference laptop;
- Azure Standard_D16s_v6 host(s);
- GitHub-hosted cross-platform runners;
- why RTF should not be compared across dissimilar loaded hosted runners.

#### 4.5 Metrics
- WER + error decomposition;
- RTF;
- paired bootstrap;
- distinct hypothesis count;
- first-word correctness + McNemar;
- DER definitions, collar, time-weighted vs per-recording mean;
- speaker-count error;
- streaming latency metrics.

#### 4.6 Reproducibility protocol
- deterministic corpus selection;
- per-artifact provenance;
- command line;
- failure rows rather than dropped engines;
- history/displaced artifacts.

### 5. Results I — engine accuracy and robustness

Table 1: eight engine/checkpoint clean matrix.

Table 2: clean vs hard WER and degradation multiplier.

Text should emphasise:
- point estimates and intervals;
- Parakeet robustness;
- Moonshine speed;
- ranking instability across conditions;
- why clean-only evaluation is insufficient.

### 6. Results II — repeated decoding and failure mechanism

This is potentially the paper's most distinctive section.

Figure 1: `large-v3` repeated WER vs insertion count; substitutions/deletions as flat reference lines.

Table 3: repeated models/splits and number of distinct outputs.

Figure 2: checkpoint ladder for conditioning ON vs OFF.

Explain:
- a single rerun contradicted an earlier conclusion;
- archive retained both;
- repeated experiments isolated insertions;
- `temperature=0` removes rescue, not cause;
- disabling previous text removes the measured tail failure on `large-v3` but is detrimental/superfluous below it.

Critical nuance:
- distinguish average WER significance from catastrophic tail risk;
- state that 95.7% of the measured aggregate `large-v3` gain is concentrated in three clips;
- avoid “conditioning causes hallucinations generally.”

### 7. Results III — hardware and platform portability

Table 4: cross-platform WER for tiny/base/small.

Figure or compact table: platform dependency resolution (92 total, 84 resolve).

Discuss:
- small model completely stable in this subset;
- tiny shows larger spread;
- installability failures are often packaging/upstream-wheel constraints, not decoder accuracy;
- benchmark decode != full end-to-end platform certification.

### 8. Results IV — interaction-specific assumptions

Subsection A: beam width.
- greedy penalty on default model;
- beams 2/5/8 largely indistinguishable on tested sample.

Subsection B: onset padding.
- grid;
- paired multiplicity-corrected result;
- synthetic silence cannot restore missing captured speech.

Subsection C: streaming.
- tiny vs base;
- final latency cost;
- partial visibility;
- model/compute dependency.

This section is valuable because it shows product assumptions being falsified, not only model scores being compared.

### 9. Results V — real meeting diarization

Table 5:
- old 0.5 estimated;
- old 0.5 exact count;
- current 1.2 estimated;
- current 1.2 exact count.

Figure 3:
- threshold sweep on representative AMI meeting or aggregate;
- overlay synthetic/Vox/AMI preferred regions to visualise non-transfer.

Text:
- old default catastrophically over-splits;
- clustering dominates error;
- time-weighted current DER = 27.37%;
- exact count reliably fixes count, not established DER;
- threshold is domain-dependent;
- centroid merge negative result.

### 10. Discussion

Organise by lessons, not features.

#### 10.1 Average WER hides interactive tail risk
One catastrophic repetition can matter more than a 1-point mean difference.

#### 10.2 Bigger is not monotonically safer
Large recogniser can have fewer substitutions but worse continuation behaviour.

#### 10.3 Configuration is model-specific
Context and beam decisions cannot be copied blindly between checkpoints.

#### 10.4 “Cross-platform” has layers
Installability, decode output, hotkey/capture, and injection are separate claims.

#### 10.5 Negative results improve the product
Padding/streaming/centroid examples.

#### 10.6 Measurement infrastructure is part of the scientific method
The displaced-run archive changed the conclusion.

### 11. Threats to validity

Must be explicit and substantial.

#### Construct validity
- WER does not measure correction burden, command errors, or catastrophic edit cost.
- LibriSpeech is not spontaneous dictation.
- hosted runner load invalidates direct latency comparisons.
- synthetic TTS meeting corpus is not human diarization evidence.

#### Internal validity
- some probes were post-hoc after observing anomalies;
- dependency/library versions differ across dates;
- possible hardware load interactions remain unresolved;
- some results use small n (streaming, dysfluency, onset).

#### External validity
- English-centric ASR evaluation;
- no representative accent/noise study;
- AMI headset mix is easier than far-field meetings;
- no GPU evaluation;
- no human usability study.

#### Statistical validity
- multiple exploratory comparisons;
- overlapping intervals;
- means dominated by rare utterances;
- diarization meeting count only 16 for paired analysis.

### 12. Related work

Update from v1 in five clusters:

1. offline/on-device ASR and efficient transducers;
2. streaming ASR and partial-stability methods;
3. Whisper decoding/fallback/context behaviour;
4. speaker diarization and clustering calibration;
5. reproducible systems benchmarking / benchmark provenance.

For every novelty sentence, add a literature-verification checkbox in the authoring issue.

### 13. Future work

Prioritise experiments that change what the paper can claim.

#### F1 — controlled typing vs dictation study
Highest value for HCI contribution.

Design:
- within-subject;
- transcription + composition tasks;
- final corrected text as endpoint;
- WPM, uncorrected/corrected error, correction time, workload;
- keyboard and YazSes counterbalanced;
- report learning.

#### F2 — spontaneous speech robustness corpus
Record consenting participants across:
- quiet/loud rooms,
- laptop/headset microphones,
- accents/non-native English,
- technical vocabulary.

Do not train on the evaluation set.

#### F3 — replicate `large-v3` mechanism
At minimum:
- one second public corpus;
- another faster-whisper/CTranslate2 version;
- two CPUs;
- enough repeated decodes to estimate tail-event frequency.

#### F4 — full end-to-end OS validation
Automate or record:
- global activation;
- capture;
- model load;
- injection;
- clipboard fallback;
- recovery after target loss.

#### F5 — real accessibility evaluation
Partner with target users; do not infer benefit from synthetic dysfluency transformations.

#### F6 — far-field meeting evaluation
AMI headset results should be complemented by table-mic/far-field meetings.

#### F7 — energy/core-seconds
CPU wall time alone misses battery cost; measure package energy where supported.

## 6. Figures/tables to generate from artifacts

Do not hand-type publication tables where a JSON generator is feasible.

### Table A — engine matrix
Source: `wer.json`, `wer-test-other.json`.

Columns:
- engine/checkpoint
- parameters
- clean WER [CI]
- hard WER [CI]
- hard/clean multiplier
- clean RTF

### Figure A — robustness slope
x = clean WER, y = hard WER; diagonal reference.
One point per engine/checkpoint.

### Figure B — repeated `large-v3`
x = repeat index; lines/bars:
- WER
- insertions
- substitutions
- deletions

This visually shows that only insertions move.

### Figure C — context interaction by checkpoint
x = checkpoint size/order.
y = WER difference OFF - ON.
Add distinct-output annotation.

### Table B — cross-platform
Source: platform WER artifacts.

### Figure D — onset padding heatmap
Rows = clipped speech; columns = synthetic lead-in; cell = first-word hits.
Mark no comparisons survive multiplicity correction.

### Table C — streaming
Rows = tiny/base.
Columns:
- batch end→text
- streaming end→final
- time to first partial
- visible at release
- no-partial count

### Figure E — diarization threshold/domain
Three domain curves if underlying comparable sweep rows are available. If they are not truly comparable, use three separate panels or a table; do not force one axis.

### Table D — AMI diarization conditions
Include both mean and time-weighted DER, collar result, count error.

## 7. Manuscript data freeze procedure

Before drafting final numbers:

1. create `paper-v2-freeze-YYYYMMDD` tag or equivalent;
2. record the exact SHA in this directory;
3. run result-manifest validation;
4. verify all headline artifacts exist and have provenance;
5. run tests that pin docs to result files;
6. regenerate figures/tables from artifacts;
7. hash generated figure input JSONs;
8. archive environment lockfile;
9. record any artifacts generated on older commits and explain why they remain valid;
10. forbid “quiet replacement” of a contradictory result after freeze.

If a rerun disagrees, add it to the paper. Do not choose the prettier run.

## 8. Minimum additional experiments before arXiv v2

A strong arXiv v2 can proceed with current evidence after:

- rerunning the core engine matrix on the final frozen environment if engine dependencies changed;
- confirming the current platform artifacts still map to supported versions;
- one clean reproduction of the `large-v3` tail mechanism on the frozen code;
- generating all tables from JSON;
- completing current related-work verification.

## 9. Minimum additional experiments before a stronger conference/journal submission

Recommended:

- controlled user study;
- spontaneous/noisy/accented speech;
- independent replication of the decoder-tail finding;
- far-field meeting corpus;
- end-to-end Windows/macOS validation.

## 10. Author/reviewer workflow

This package should feed GitHub issues.

Suggested issue families:

- **PAPER2-LIT-*** — literature verification.
- **PAPER2-REPRO-*** — rerun/freeze central measurements.
- **PAPER2-FIG-*** — artifact-to-figure generation.
- **PAPER2-TEXT-*** — manuscript sections.
- **PAPER2-VALID-*** — claim audit against `CLAIM_LEDGER.md`.
- **PAPER2-HUMAN-*** — ethics/protocol/recruitment for user studies.
- **PAPER2-RELEASE-*** — final artifact/DOI/arXiv submission.

Every text issue should name:
- claim IDs it is allowed to use;
- artifacts it must cite;
- caveats that must appear;
- reviewer responsible for checking numbers.

### Current executable issue map

Umbrella:
- **[#510 PAPER2-EPIC](https://github.com/MSKazemi/yazses/issues/510)** — full research/evidence/manuscript/publication programme.

Evidence freeze / reproducibility:
- **[#495 PAPER2-REPRO-001](https://github.com/MSKazemi/yazses/issues/495)** — freeze and rerun the core ASR engine matrix.
- **[#496 PAPER2-REPRO-002](https://github.com/MSKazemi/yazses/issues/496)** — replicate the `large-v3` insertion/runaway tail failure on a second corpus and CPU.
- **[#507 PAPER2-LIT-001](https://github.com/MSKazemi/yazses/issues/507)** — novelty and related-work verification.
- **[#508 PAPER2-FIG-001](https://github.com/MSKazemi/yazses/issues/508)** — generate tables/figures from committed result artifacts.

External validity / stronger submission:
- **[#498 PAPER2-HUMAN-001](https://github.com/MSKazemi/yazses/issues/498)** — controlled typing-vs-dictation study.
- **[#500 PAPER2-DATA-001](https://github.com/MSKazemi/yazses/issues/500)** — spontaneous-microphone robustness evaluation.
- **[#502 PAPER2-MEETING-001](https://github.com/MSKazemi/yazses/issues/502)** — far-field meeting diarization evaluation.
- **[#504 PAPER2-PLATFORM-001](https://github.com/MSKazemi/yazses/issues/504)** — end-to-end Windows/macOS validation.
- **[#506 PAPER2-ENERGY-001](https://github.com/MSKazemi/yazses/issues/506)** — CPU core-seconds and energy/battery measurements.

Manuscript drafting:
- **[#532 PAPER2-TEXT-001](https://github.com/MSKazemi/yazses/issues/532)** — draft the private manuscript against the claim ledger and frozen evidence.

Publication governance:
- **[#484](https://github.com/MSKazemi/yazses/issues/484)** — contributor authorship consent, manuscript review, unanimous final approval, and publication operations.

The scientific issues do not replace #484. Evidence readiness and publication approval are separate gates.

## 11. Pre-submission validation checklist

### Numbers
- [ ] Every headline number is generated or checked against JSON.
- [ ] Every WER names split and n.
- [ ] Every latency names hardware.
- [ ] Every DER says mean vs time-weighted and collar.
- [ ] No probe/result is counted twice via its significance derivative.
- [ ] Contradictory repeated runs are retained.

### Claims
- [ ] Every central claim has a `CLAIM_LEDGER.md` ID/status.
- [ ] No REFUTED claim appears in abstract/conclusion.
- [ ] “Novel/first” claims have a completed literature search.
- [ ] Point-estimate ranks are not stated as significant superiority without inference.
- [ ] Product decisions are not presented as statistically proven effects.

### Reproducibility
- [ ] Exact manuscript SHA/tag recorded.
- [ ] Lockfile archived.
- [ ] Commands/provenance present.
- [ ] Result manifest current.
- [ ] Figures reproducible from committed data.
- [ ] No private paths, credentials, IPs, or user audio in artifacts.

### Ethics/privacy
- [ ] Public corpora licences/citations checked.
- [ ] Synthetic TTS data clearly labelled.
- [ ] No real user audio from product use included without explicit consent/approval.
- [ ] Human-study work has ethics/IRB review where applicable.

### Cross-platform
- [ ] Decode benchmark claims separated from end-to-end product claims.
- [ ] Unsupported platform extras documented accurately.

## 12. What the conclusion should say

A defensible final conclusion should not be “YazSes is the best dictation system.”

It should say approximately:

> Expanding evaluation beyond one clean-speech WER changed several engineering conclusions. Harder speech altered model trade-offs; repeated decoding revealed a rare large-model continuation failure hidden by aggregate accuracy; context settings behaved differently across checkpoints; the original meeting clustering default failed on real annotated meetings; and several intuitive latency/repair techniques did not survive measurement. These results argue that offline interactive speech systems should report reproducibility, tail failures, hardware dependence, and task-specific metrics alongside conventional WER.

That is a strong scientific contribution and is already supported by the repository.
