# Dysfluency-fidelity study: evidence audit and preregistration worksheet

**Prepared:** 2026-11-03 · **Version:** proposed v0.2 (NOT registered / frozen) · **Status:** research only  
**Primary protocol:** [2026-11-03 dysfluency-fidelity evaluation](2026-11-03-dysfluency-fidelity-evaluation-protocol.md)  
**Canonical issue:** [#255](https://github.com/MSKazemi/yazses/issues/255) · **Review PR:** [#825](https://github.com/MSKazemi/yazses/pull/825)  
**Scope:** pre-participant, no audio downloads, no user/speaker data and no new product behavior.

> **Research-integrity warning:** This worksheet is *not* a completed preregistration. It contains proposed methods and intentionally empty decision fields. Do not call the analysis preregistered, the corpus licensed, the sample frozen, or the evaluation complete until those fields are resolved **before outcome inspection**. A research design is not a measured result.

## 1. What the evidence actually supports

| Source and verified publication landing page | Evidence class | Result / implication for YazSes | Transfer limit |
| --- | --- | --- | --- |
| [Lea et al., CHI 2023](https://machinelearning.apple.com/research/user-perceptions-technical) ([DOI](https://doi.org/10.1145/3544548.3581224)) | Human-participant / intervention study | Survey of 61 people who stutter; recorded speech from 91; combined recognition and endpointing interventions reduced cutoffs by 79.1% and reduced WER from 25.4% to 9.9% **in their setup**. | **Not a YazSes measurement.** The figures cannot be attributed to a stand-alone regex/text filter. YazSes hold-to-talk ends at release, unlike a voice assistant endpointer. |
| [Lea et al., SEP-28k, ICASSP 2021](https://arxiv.org/abs/2102.12394) and [official dataset](https://github.com/apple-aiml-research/ml-stuttering-events-dataset) | Dataset / event detection | ~28k short clips labeled with five disfluency types; each clip has multiple human event labels, potentially overlapping. | The original release is **event annotation**, not a word-aligned dictation reference. Podcast recordings remain owned by their speakers/publishers; dataset annotations are CC BY-NC 4.0. |
| [Bayerl et al., TSD 2022](https://arxiv.org/abs/2206.03400) and [SEP-28k-E](https://github.com/th-nuernberg/ml-stuttering-events-dataset-extended) | Dataset-partition methodology | Original SEP-28k is concentrated among a small number of speakers; **speaker-exclusive vs non-exclusive splits change outcomes**. SEP-28k-E supplies semi-automated speaker annotations and proposed speaker-aware splits. | Generated identities are estimates with quality scores, not unambiguous verified speaker IDs. SEP-28k-E inherits CC BY-NC annotations and podcast audio rights. Do not infer a population-representative rate. |
| [Sridhar and Wu, Interspeech 2025](https://www.isca-archive.org/interspeech_2025/sridhar25_interspeech.html), [research companion](https://github.com/aimpowered/stuttered-speech-benchmark) | Independent benchmarking on stuttered podcast speech | Whisper shows disproportionate errors for sound repetitions and hallucinations in over 20% of *sound-repetition cases in their study*. Companion records list both **literal and semantic** transcripts for manually transcribed samples. | Not YazSes; not proof that cleaned text matches a speaker's personal preference. **MIT code licence does not automatically permit reusing bundled podcasts, labels, or transcripts.** Inspect file-level rights first. |
| [Kordt et al., Interspeech 2026](https://www.isca-archive.org/interspeech_2026/kordt26_interspeech.html) ([DOI](https://doi.org/10.21437/Interspeech.2026-2080)) | Adaptation research | Explicit disfluency markers and continual-learning methods trade off marker retention and general-domain ASR performance. | Does not validate changing YazSes defaults or training a personalization adapter. ADR-v2-021's independent holdout gate remains necessary. |
| [Husain et al., Interspeech 2026](https://www.isca-archive.org/interspeech_2026/husain26_interspeech.html) ([DOI](https://doi.org/10.21437/Interspeech.2026-786)) | ASR evaluation in accented conversational speech | Shows why named-entity and disfluency recall can matter beyond overall WER. | Different population and task; borrow **metric design**, not a performance number or general claim about dysarthria. |
| [UA-Speech](https://speechtechnology.web.illinois.edu/uaspeech/) | Restricted dysarthric speech corpus | Useful comparator for possible later dysarthria research. | Academic/government lab restriction, non-commercial terms and no redistribution. **Not** a ready-to-download general-purpose open dataset. |
| [Speech Accessibility Project](https://speechaccessibilityproject.beckman.illinois.edu/conduct-research-through-the-project) and [FAQ](https://speechaccessibilityproject.beckman.illinois.edu/conduct-research-through-the-project/faq-on-using-our-data) | DUA-controlled atypical-speech corpus | Provides actual speech with transcribed responses and potential relevant conditions. | Signed organizational data-use agreement and institutional authorization; no anonymous access or GitHub redistribution. |
| [FluencyBank](https://talkbank.org/fluency/) and [TalkBank terms](https://talkbank.org/0share/rules.html) | Partly restricted speech corpus | Potential future research collaboration. | Clinical FluencyBank access is restricted; do **not** treat a linked podcast sample as permission to pull FluencyBank participant media. |

**Evidence hierarchy:** synthetic text fixtures = regression only; locally rights-cleared podcast audio = exploratory real-speech *mechanism* evaluation; independent participant study = actual user benefit / correction effort. Neither may be substituted for the next.

## 2. Questions and comparisons — keep the causal claim narrow

**Q1 (primary mechanism question):** Given the *same* frozen ASR hypothesis, does the enabled postfilter introduce a new meaning-destructive edit relative to disabled filtering? A confirmed negative example shows the filter can harm; absence of examples in one enriched sample cannot establish safety in the broader population.

**Q2 (secondary mechanism question):** What is the fraction of proposed edits that preserve the available reference meaning? What fraction of **fluent controls** is edited at all? Report intervention counts and false changes, not just recall on stuttered clips.

**Q3 (separate decoder question):** Against a verbatim audio reference, what does the frozen offline decoder emit before postprocessing, by type of disfluency, and on clean controls? This includes omissions, hallucination-like insertions and segment truncation. This is *not* isolated by filter-on/off comparisons.

**Q4 (human-centered question, deferred):** For people who stutter and **separately** for people with dysarthria, how do transcript representation and correction effort affect task success, autonomy, fatigue and preference? The speaker—not a transcript editor—determines what counts as a useful final message.

### Minimum causal comparison matrix

| Condition | Audio / input | Perturbation | Permitted claim |
| --- | --- | --- | --- |
| F0 | Identical saved raw hypothesis | Filter disabled | Baseline text postfilter control |
| F1 | **Byte-identical** saved raw hypothesis from F0 | Filter enabled, exact effective config pinned | *Only* the marginal effect of the text filter |
| R0 | Locally rights-cleared, identical audio | Fixed decoder once, before filter | Decoder errors relative to verbatim reference; only if audio permitted |
| UX-A/UX-B | Same participants and matched/counterbalanced tasks | Verbatim vs optional cleaned/reviewable presentation | Utility, fatigue and correction cost; **requires study approval and consent** |

The word 'semantic reference' means an **annotator-produced normalization under a written policy**. It must not be reported as literal access to the speaker's unexpressed intent. For a speaker-preference claim, ask the speaker. A 3-second podcast clip may begin/end mid-utterance; label these cases *incomplete or unassessable*, not “wrong speech.”

## 3. Sampling: selection is not outcome analysis

**Proposed exploratory sample** inherited from #255: up to **40 items each** from sound repetition, word repetition, interjection and fluent controls (**160 candidate clips total**). This is an intentionally enriched, fixed-size *feasibility pilot*, **not** a sample representing the real frequency of disfluencies. It omits block and prolongation as independent strata; **declare an extension before sampling** if those are required for a claim.

Pending freeze fields:

| Field | Prespecified rule / status |
| --- | --- |
| Rights/consent review, permitted use and export | **UNAPPROVED** — record each source audio, event-label set, literal transcript and semantic transcript separately. |
| Eligible sampling frame | **UNFROZEN** — choose a specified version of the reference-bearing subset, *not* a mixture of unlabeled SEP-28k clips and handpicked failure examples. |
| Source snapshot and provenance | **UNFROZEN** — tag/commit, schema, SHA-256 of locally licensed metadata. Do not publish restricted records. |
| Primary stratum assignment | **UNFROZEN** — use an explicitly documented rule for clips with multiple labels; preserve all original labels as separate covariates. |
| Annotator threshold | Candidate rule: at least **two of three** event-label votes; document how “no event,” uncertainty and conflicts are handled. |
| Units for clustering and deduplication | Record **episode** and only **credible speaker** identifiers. Avoid overlapping clips, repeated adjacent context and repeated speaker dominance. |
| Leakage boundary | Don't choose items based on ASR output or a prior model's failure; keep within-episode items together for any later train/dev/test split. No tuning on the final holdout. |
| Stratified sample feasibility | **UNVERIFIED** — 2025 companion transcription subset may not have 40 eligible/rights-cleared items in every stratum. Declare shortages; do not silently replace clips with favorable ones. |
| Deterministic sample | **UNFROZEN** — fixed seed, canonical sort, selection algorithm, inclusion/exclusion log and local manifest hash **before** loading outcome columns. |
| Exclusion rule | Exclude only predeclared rights or technical unavailability; do not exclude poor acoustic quality *after seeing the recognizer output*. Retain invalid/unassessable counts and reasons. |
| Source publication decision | **UNAPPROVED** — a public hash is not permission to publish source IDs, participants, utterances or audio. Hashing low-entropy transcripts is not sufficient anonymization. |

**Speaker identities from SEP-28k-E are semi-automatic**, so report the number of reliable groups, uncertain assignments and episodes. When identities are not reliable, use episode-level grouping as a conservative proxy, not as proof of speaker independence. Don't use inferred gender as a quality or eligibility gate.

## 4. Annotation and adjudication protocol

### Source and condition presentation

Prepare an encrypted/local evaluation workspace only **after** authorizing the source data. Provide two reviewers with access to licensed audio, both reference types where available, and *two de-identified condition labels in randomized order*; order and source metadata are held separately. They should **not** see other benchmark model outputs, aggregate results or the rationale for the candidate before independent scoring. Blinding condition labels is possible; perfect masking of the kind of cleaned transcript is not. Report this limitation.

1. Review the speech segment and boundaries; note incomplete phrases, overlapping talk, music and uncertain meaning. Do not force an intent label for ambiguous audio.
2. Record whether the **difference F1 - F0** is content deletion/substitution, wrong correction direction, invented/unsupported structure, safe cleanup, benign retention or no material edit. Retain the affected verbatim span **locally only**, with a rule citation and severity code.
3. Before discussion, assign one **primary** code and any secondary attributes (negation, numbers, hedges, proper nouns, timing/cutoff, repetition type, code token). Record independent reviewer IDs, timestamp, confidence and whether they used the literal or semantic reference.
4. If reviewers disagree, a predesignated third reviewer applies the frozen rubric. If still unresolvable, label **UNASSESSABLE / DISPUTED**. An unresolved case never becomes a safety pass by being excluded.
5. Publish an anonymized *aggregate* disagreement table (initial agreement, adjudicated agreement, unresolved count) and a confusion matrix only when row counts cannot identify a participant. Do not publish raw speech or per-case excerpts absent explicit rights.
6. Use a **negative control** set of fluent/ordinary-content phrases, plus synthetic adversarial sentinels (negation, hedges, dosage-like quantities, URLs, identifiers). Do not add these deliberately hard synthetic examples to the random real-speech denominator.

**Observer agreement:** calculate nominal Cohen's kappa if two complete ratings exist, or an appropriate multi-rater coefficient where necessary. Also report percent raw agreement and the confusion matrix. A low kappa in heavily unbalanced samples does not automatically imply incompetence; report prevalence and uncertainty.

**Important ambiguity:** punctuation changes can be benign; the main harmful endpoint is confirmed loss/change of communicated meaning, **not** any byte difference. Conversely, an unchanged hypothesis may still be wrong because the decoder hallucinated or omitted speech; that is a *decoder error* rather than filter damage.

## 5. Statistical analysis without misleading confidence

The proposed 160-item sample is a **pilot and failure-finding study**. Report all numerator/denominator counts by strata, all disputed/unassessable outcomes, and the exact effective YazSes config. Avoid claims about prevalence, clinical benefit, or a statistically proven low harm rate.

### Mandatory outcomes

| Outcome | Numerator | Denominator | Interpretation |
| --- | --- | --- | --- |
| New destructive filter edit | Distinct paired clips with a confirmed harmful F1-only change | All **assessable paired** clips; report *all selected* and unresolved counts separately | Primary safety/failure-detection outcome, **not** field prevalence |
| Unassessable/disputed | Incomplete, ambiguous or unresolved clips | All selected clips | Selection/annotation attrition |
| Fluent intervention rate | Fluent samples modified at all | All fluent controls with both outputs | Upper bound on how often the filter needlessly intervenes |
| False *harmful* intervention on fluent clips | Fluent samples with confirmed destructive change | Assessable fluent controls | Not equivalent to “any change” |
| Safe-cleanup yield | Nonfluent clips with independently confirmed safe and useful cleanup | Assessable nonfluent clips | Can improve even while a distinct harmful failure blocks validation |
| Verbatim WER, literal reference | Total S+D+I | Sum of actual verbatim-reference words | Decoder + filter effect; must specify normalization and zero-word cases |
| Semantic-reference WER | Total S+D+I | Sum of available, policy-documented edited reference words | A *reference-dependent proxy*, not the speaker's preference |
| Named-entity/negation/quantity preservation | Preserved source-supported entities/negations/quantities | All source-supported examples in each category | Exploratory metric motivated by beyond-WER literature; report low denominators |

**Important:** `S+D+I` above denotes the minimum edit distance over substitution, deletion and insertion. The current standalone synthetic runner returns only *total* edit distance (not a decomposed S/D/I breakdown); never claim it already computes each error type.

### Why zero events do not prove an acceptably low error rate

For **zero observed events among n *independent* Bernoulli trials**, the simple exact **one-sided 95% upper bound** is `1 - (0.05)^(1/n)`. Even under that overly favorable independence assumption:

- `0 / 40` fluent controls has an upper bound about **7.22%**.
- `0 / 160` clips has an upper bound about **1.85%**.
- For an upper bound *under 1%*, the independence model needs **at least 299** event-free observations, before accounting for clustering.

In SEP-28k podcast audio, **clips are not independent speakers**, and the enriched four-stratum sample is not a random sample of real-world dictation. These simple bounds are *illustrations of insufficient precision*, not inferential intervals to publish as field error rates. Repeated clips from one speaker/episode make the effective sample size smaller; disclose episodes, speakers with reliable IDs, maximum clips per group and concentration.

A real future study would report cluster-aware uncertainty (resampling entire speakers, or episodes if speaker IDs are unavailable) only with enough independent groups; otherwise report descriptive rates and state that the evidence does not support a population inference. Predeclare any paired hypothesis test and multiplicity strategy in the human study, **not after** seeing preliminary WER.

### Decision rule (engineering vs statistical claim)

- **One or more confirmed harmful F1-only edit:** **FAIL** for the studied filter configuration; document reason and create a bounded fix only if reproduced. A larger safe-cleanup yield **does not cancel** the failure.
- **No confirmed harmful edit but one or more unresolved cases, missing rights, broken references or unreliable output:** **INCONCLUSIVE/HOLD**; no safety or efficacy claim.
- **No confirmed harmful edit, all selected cases assessed, rights valid:** **NO FAILURE OBSERVED IN THIS SAMPLE**. Continue evidence gathering; it is **not** a clinical benefit finding, default-enable decision or proof that the hazard rate is small.
- **Participant-level usability claim:** only after approved, voluntary, appropriate co-designed evaluation; record correction time, unwanted edits, satisfaction with verbatim/cleaned output, fatigue and participant ability to recover/delete a mistaken output.

## 6. Human study design — proposal, separate from the pilot

The first participant-facing study should **not** recruit until an institution has recorded its applicable ethics/IRB determination and plain-language consent documents. Reuse the methodological checks in [eye-control study #425](https://github.com/MSKazemi/yazses/issues/425) (unit of analysis, counterbalancing, exclusions and ethics), without claiming those eye-study documents authorize speech research.

A candidate within-person design: each person completes matched dictation tasks under a **reviewable verbatim** vs **reviewable cleaned** transcript condition, with randomized/counterbalanced order, a standard warm-up, breaks and an accessible way to stop or skip. Include personally meaningful as well as standardized text only when consent/privacy procedures allow it. Predefine the primary participant-level outcome as **time to accepted final text including correction** (or words/minute *after* correction), plus error-recovery count; collect participant preference/effort as co-primary or secondary only after co-design and an appropriate sample-size calculation.

Do not pool stuttering and dysarthria as a single homogeneous population; if recruited, analyze them separately or transparently as exploratory strata. A convenience pilot of n=2 checks instructions/feasibility, **not** effect size. No speech recording, consent record, health information or preference survey belongs in the public repository or ordinary GitHub issues.

## 7. Actual registration/freeze form — unfilled on purpose

Record **before the first real-speech evaluation**:

- **Study registration permalink / timestamp:** NOT FILED.
- **Institutional ethics/review determination, scope and owner:** NOT DETERMINED.
- **Dataset and audio/annotation/transcript rights ledger approved by:** NOT APPROVED.
- **Exact dataset subset and versions (rights cleared):** NOT SELECTED.
- **Speaker/episode overlap, cluster definitions, multi-label tie-break:** NOT FROZEN.
- **Chosen 160-item stratification and shortage/quality rules:** NOT FROZEN.
- **Random selection algorithm, seed, ordered manifest SHA-256:** NOT FROZEN.
- **Review rubric, independent annotators and blinded-order scheme:** NOT FROZEN.
- **ASR engine, model digest, quantization, prompt, language, beam and all postprocessing options:** NOT FROZEN.
- **Primary estimand, statistic, unit and missing-data rule:** PROPOSED; NOT FROZEN.
- **Release/dissemination and deletion procedures:** NOT APPROVED.
- **Confirmatory sample-size or precision target:** NOT CALCULATED; 160 is only an exploratory pilot.
- **Signed-off preregistration version and responsible researcher:** NONE.

An unfilled field is a blocker, **not** permission to improvise after examining outputs. Do not modify this form to claim a retrospective pre-registration once the first held-out result is visible; publish changes with dates and rationale.

## 8. Immediate work packages and acceptance

1. **Engineering / CI:** fix the previous test import dependency failure, run the targeted suite and confirm GitHub cross-platform CI; keep production code, defaults and extras untouched.
2. **Pre-analysis metadata-only feasibility:** check the *schema and publicly documented counts* of the reference-bearing 2025 companion corpus and speaker grouping; **do not** download participant speech or transcripts to an AI tool. Record whether 40-item strata are even possible before outcomes are revealed.
3. **Data rights:** document audio, annotation, reference-text and derived-output permissions separately. This is a human approval gate; absence of prohibition is not consent.
4. **Study protocol freeze:** human reviewers approve assignment, ambiguity rules, sample methodology and rights; then freeze an eligible random manifest *locally* with a reproducible hash before decoding.
5. **Evaluation:** once permitted, assess both filter marginal harm and decoder baseline errors; report grouped uncertainty and failure examples in rights-safe form.
6. **Decision:** publish a negative result if warranted, discuss semantics and user preference with affected people; propose an ADR only if the evidence requires a behavior change.

**Current result:** A methods/evidence audit and proposed measurement plan; **no real-speech accuracy, privacy claim about source rights, participant outcome, model improvement, or corpus-derived effect size has been measured here.**
