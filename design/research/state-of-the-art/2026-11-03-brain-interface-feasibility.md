# Brain-computer interface feasibility for YazSes — 2026-11-03

> **Status:** research and design snapshot, **not** a released capability, clinical claim, approved human study or permission to alter production.  
> **Tracking:** [#696 (EEG/EOG feasibility; closed 2026-11-03)](https://github.com/MSKazemi/yazses/issues/696) under [#692 (multimodal HCI)](https://github.com/MSKazemi/yazses/issues/692); complementary research under [#790 (accessible hands-free workspace)](https://github.com/MSKazemi/yazses/issues/790), especially [#814 (study/review gates)](https://github.com/MSKazemi/yazses/issues/814), [#815 (multimodal arbitration)](https://github.com/MSKazemi/yazses/issues/815), [#816 (stop/recovery)](https://github.com/MSKazemi/yazses/issues/816), and [#817 (task evaluation)](https://github.com/MSKazemi/yazses/issues/817).  
> **Date and evidence:** 2026-11-03. Third-party findings below are cited to upstream scientific articles and library documentation; **no new device, human, or EEG-model benchmark was run** for this report.  
> **Scope:** [ADR-030](../../adr/adr-030-agent-era-direction.md) (Accepted); [ADR-v2-152](../../adr/adr-v2-152-biosignal-artifact-switches.md) (Proposed, not yet binding); [biosignal validation protocol](../../specs/biosignal-validation-protocol.md) and [HCI lab roadmap](../../hci-huggingface/ROADMAP.md).

## Executive recommendation

Investigate **non-invasive scalp EEG as a very low-bandwidth intentional switch**: one deliberate event versus rest, optionally combined with YazSes voice and gaze. **Do not** describe muscle or ocular artifacts on an EEG headset as a decoded thought. **Do not** pursue free-form consumer EEG thought-to-text as an integration promise in 2026. Carefully distinguish synthetic feasibility, published offline dataset accuracy, real-time detection, and everyday assistive usability.

**Decision now:** (1) keep the existing, off-by-default EMG/EOG/blink/jaw-clench pipeline as the practical control baseline; (2) perform a *research-only* neural motor-imagery (MI) **rest-versus-activate** offline replay evaluation when lawful datasets and channel montage permit; (3) require robust rejection of unrelated states, false-trigger exposure estimates and repeated-session evidence before *considering* a live neural input adapter; (4) leave P300/SSVEP stimuli and invasive speech BCIs out of product scope. No new `src/` entrypoint, model download, network listener, runtime feature, public dataset of user signals or hardware capability claim results from this report.

## 1. What exactly is being decoded?

| Signal and method | Physiological source | Honest potential role | Critical boundary |
| --- | --- | --- | --- |
| EMG squeeze, jaw clench | **Muscle activity** measured on a muscle electrode or leaked into EEG | Low-bandwidth on/off or discrete switch already handled by YazSes | **Not brain-activity decoding**; speech itself can cause jaw artifacts |
| EOG/blink | **Eye movement/eye muscle** potential, sometimes visible at frontal EEG sites | Deliberate blink/double-blink switch, already in the biosignal path | Natural blinks, face movement and electrode drift cause false triggers; not imagined words |
| Sensorimotor EEG motor imagery (MI) | Scalp-recorded correlates of imagined movement, typically motor-cortex channel montage | Experimental binary neural `ACTIVATE` versus `REST` suggestion, never automatic action | Low signal-to-noise, subject/session variation and out-of-distribution states; *not* free-text decoding |
| P300 event-related potential | Evoked EEG response to attended stimuli | Experimental target selection with structured visual/auditory interface | Stimulus dependency, attention, calibration and false-selection rate; not passive thought reading |
| SSVEP (steady-state visual evoked potential) | EEG response to periodic visual stimulation | Experimental selection among known on-screen targets | Requires flashing/flickering stimuli and suitable occipital channels; photosensitivity concerns |
| Imagined/covert speech from non-invasive EEG/MEG | Weak, distributed neural patterns during attempted internal speech | **Research horizon only** | Free-form EEG accuracy and generalization inadequate for consumer dictation; EEG and MEG are not interchangeable |
| Intracortical speech BCI | Surgically implanted electrodes in specialized medical studies | Scientific reference for severe paralysis communication | Not usable with consumer EEG; not a plausible YazSes plugin or DIY feature |

The currently shipped YazSes **biosignal switch** uses artifacts, not motor-imagery brain decoding: [user guide](../../../docs/how-to/biosignal-switch.md) and [biosignal spec](../../specs/biosignal-pipeline.md). The explicit exclusion of neural motor imagery and cortical decoders is recorded in [ADR-v2-152](../../adr/adr-v2-152-biosignal-artifact-switches.md), which is Proposed, so it is not yet a binding decision. BrainFlow hardware acquisition support alone does **not** imply that the app decodes thoughts.

## 2. Important findings available by 2026-11-03

**Non-invasive language decoding is advancing but remains limited.** The 2026 *Nature Neuroscience* Brain2Qwerty study tested 35 volunteers typing briefly memorized sentences. Mean character-error rate was **65% on EEG** and **29% on MEG** (lower is better), with 18% in the best participants on the more informative modality. These are **sentence-production during overt keyboard typing** experiments with dedicated equipment, not a consumer headset silently reconstructing arbitrary internal speech. [Lévy et al., 2026](https://www.nature.com/articles/s41593-026-02303-2). Do **not** quote the best-case score as a generic YazSes or consumer-EEG performance estimate.

**Motor imagery EEG still struggles with user/session variability.** A 2026 review identifies low signal-to-noise, cross-subject/cross-session variability and nonstationarity as persistent hurdles for practical motor-imagery BCIs. [Wang et al., *Frontiers in Neuroscience*, 2026-09-08](https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2026.1899645/full). An October 2026 *Journal of Neural Engineering* study specifically reports difficulty rejecting unfamiliar movement classes using uncertainty estimates, showing that generic confidence/OOD gating cannot be **assumed** to work for all users. [Mulder et al., 2026-10-09](https://pubmed.ncbi.nlm.nih.gov/42790484/).

**Invasive speech BCIs are a different class of technology.** A 2025 *Nature Neuroscience* clinical-trial study streamed brain-to-voice synthesis from **high-density cortical recordings** in a participant with severe paralysis. [Littlejohn et al., 2025](https://www.nature.com/articles/s41593-025-01905-6). A separate implant study reported a voice-synthesis interface using **256 intracortical microelectrodes**. [Wairagkar et al., *Nature*, 2025](https://www.nature.com/articles/s41586-025-09127-3). A June 2026 *Nature Medicine* single-participant study demonstrated nearly two years of independent home use of an intracortical BCI for speech/cursor control. [Card et al., 2026-06-15](https://www.nature.com/articles/s41591-026-04414-6). These establish real clinical research progress, **not** a general-purpose non-invasive brain-to-text decoder.

**Open, reproducible tooling exists.** [BrainFlow's supported-board documentation](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html) documents a synthetic board with no actual hardware, and a common acquisition API for supported real boards. [MOABB's documentation](https://moabb.neurotechx.com/docs/README.html) provides EEG benchmark pipelines and stresses reproducibility; its 2026 v1.6.0 update added imagined-speech dataset categories. [MOABB v1.6.0 release notes](https://github.com/NeuroTechX/moabb/releases/tag/v1.6.0) ([Zenodo record](https://zenodo.org/records/22112474)) and [v1.7.1](https://github.com/NeuroTechX/moabb/releases/tag/v1.7.1) ([Zenodo record](https://zenodo.org/records/22215752)) document versions, but **dataset rights are separately determined**. [MNE-Python EEGBCI](https://mne.tools/stable/auto_tutorials/index.html) and the [PhysioNet EEG Motor Movement/Imagery dataset](https://physionet.org/content/eegmmidb/1.0.0/) are potential subject-level research resources, subject to review of exact dataset terms.

**Visual stimulation is not a neutral accessibility option.** A 2025/2026 Epilepsy Foundation working-group consensus identifies hazards from certain bright flickering patterns and recommends caution for visual media. [Fisher et al., *Epilepsia*, 2026](https://pubmed.ncbi.nlm.nih.gov/41283196/). Therefore **no P300/SSVEP flashing prototype or participant exposure** is proposed by this document; any future study needs a specialized safety and accessibility review.

## 3. Reuse the existing YazSes architecture

There is no reason to build a second biosignal acquisition or activation system. The already documented implementation encompasses:

- `yazses.biosignal`: quality gating for missing/flat/saturated/noisy signals; sample dropout and clock integrity; conservative blink, clench and squeeze events; cancellation / false-positive governor; optional BrainFlow, LSL, local replay and synthetic sources. See [v2.48.0 release evidence](../../../docs/releases/v2.48.0.md). Its device paths were tested with fakes/fixtures, **not** real hardware.
- `platform/emg/` and activation-source seam: existing physical-switch event routing, not a cortical decoder.
- `design/hci-huggingface/` research tasks #692/#696/#699/#700: shared synthetic samples, offline replay, uncertainty/abstention/confirmation tests.
- `design/eye-control/` research and review: target semantics, safety, consent and device testing.
- [biosignal field protocol](../../specs/biosignal-validation-protocol.md): baseline measured **phantom activations/hour** and hit rates, not an ambiguous classifier 'accuracy'.

A hypothetical **separate research adapter** could output **candidate events, not commands**, with this *conceptual-only* envelope:

```text
NeuralActivationCandidate (RESEARCH ONLY)
  source_kind: "eeg_motor_imagery"      # NOT "blink" or "jaw"
  candidate_kind: "activate" | "rest" | "abstain"
  timestamp_monotonic_ns: integer
  confidence: float                   # calibrated estimate, not assumed accuracy
  quality: "valid" | "invalid"
  model_revision: immutable identifier
  calibration_session: local opaque identifier
  expires_after_ms: bounded integer
```

**Hard rules:** a candidate does not type, click, open the mic, call an agent, or send text. Missing channel quality, old timestamps, clipped frames, unrecognized state or low confidence produces **abstain**. No activation across restart without explicit opt-in; user controls pause, kill, re-enable. No recordings or derived neural features in text logs. This is a **design proposal only**; it is **not** a new production wire format and does not amend ADR-030/ADR-v2-152.

## 4. A feasible staged, falsifiable research protocol

### Stage R0 — inventory and synthetic signals (no people, hardware, or model download)

1. Audit existing `biosignal`, `activation`, BrainFlow, dataset schemas and #696, #699, #700 before adding files.
2. Specify **distinct metadata tags** for neural EEG, EOG artifact and EMG artifact; never recast a blink as brain decoding.
3. Replay deterministic synthetic scenarios with timestamp jitter, channel dropout, out-of-order samples, flatline, saturation, mains interference, natural blink/jaw movement, stale model scores and stream interruption.
4. Score quality-gate abstention, stop/recovery invariants and false-positive accounting without executing desktop actions.
5. **Important limitation:** BrainFlow synthetic board samples are valid for testing acquisition plumbing and failure handling; they **cannot prove motor imagery decoding** or user intent.

**R0 exit:** 100% reproducible no-hardware, no-egress event/abstention tests; no backend added.

### Stage R1 — offline public-dataset neural study (after provenance review)

Use an appropriately licensed EEG *motor imagery* dataset with documented motor-cortex channels, task labels, rest trials, sample rate, timestamps, participant boundaries and repeated sessions. A generic frontal consumer EEG band must **not** be assumed adequate for motor imagery. Freeze dataset id/version/license, inclusion/exclusion, participant grouping and normalization **before** model selection; never mix windows from the same contiguous recording across train/test splits.

**Suggested baselines** (compare, do not assert superiority):

- Classical bandpower and common spatial patterns (CSP) + shrinkage LDA or regularized logistic regression.
- Riemannian covariance methods for MI feature comparison.
- Lightweight EEGNet-style classifier only as an explicitly justified candidate, with parameter and compute parity noted.
- Negative controls: shuffled event labels, signal-only artifacts, no-intent rest, unfamiliar movements, speaking, blink/jaw activity and channel dropout.

Evaluate within-participant held-out sessions, and separately leave-one-participant-out transfer. Treat any absence of repeated sessions as an **inconclusive generalization study**, not evidence of a ready-to-use interface. Report data leakage checks, imbalance, held-out failure cases and class-conditional abstentions.

### Stage R2 — streaming pseudo-online replay (no live UI actions)

Turn offline EEG windows into a causally ordered stream. Fit any normalization and calibration only on *past* training data. Require a predeclared decision threshold and refractory period; never compute future samples when scoring latency. Evaluate:

- **True intentional triggers** per labelled cue; missed activations / recall and precision.
- **False activations per usable idle hour**, including negative controls for speech, natural blinking and head motion. Report a one-sided 95% upper bound (Poisson model with assumptions disclosed); zero events in a short test is not proof of safety.
- Time from cue/onset to **confirmed stable candidate** (median and p95), including sensor buffering and inference.
- **Calibration time** and degradation from one session to the next; per-person failures, not just pooled means.
- Unknown/OOD state detection, threshold sensitivity, signal quality failure rate, abstention rate and false "activation" during disconnection.
- CPU and peak RSS on a normal Linux laptop and impact on simultaneous YazSes dictation.

A nominally high within-epoch classification accuracy is **not** an acceptable replacement for continuous idle exposure. Report an **always-rest** and **random/shuffled** baseline. Pre-register the acceptable error/false-trigger budget, then estimate the amount of idle exposure needed to substantiate it; do not choose thresholds after looking at final test data.

### Stage R3 — future hardware and human feasibility gate (NOT AUTHORIZED)

Requires (a) demand evidence, (b) explicit ADR-030/ADR-v2-152 scope decision, (c) owner-approved hardware and license/privacy review, (d) proper institutional ethics/review determination where applicable, accessible consent and withdrawal, (e) a participant safety and stopping protocol, (f) an independent desktop test with **actions still disabled** at first. The human-study process belongs to [#425](https://github.com/MSKazemi/yazses/issues/425), [#427](https://github.com/MSKazemi/yazses/issues/427), [#814](https://github.com/MSKazemi/yazses/issues/814) and the proposed research-consent guardrails in ADR-v2-150, not to a new informal participant pool.

Do not collect diagnoses, psychological or cognitive traits; do not upload raw EEG, EMG, recordings, biometric features or calibration profiles. Explicit public opt-in is **not automatically informed research consent**. Any research on neural signals should have an appropriate security and retention review.

## 5. Three design alternatives and decision

| Proposal | 2026 recommendation | Why |
| --- | --- | --- |
| Keep **EMG / EOG artifact switches** and improve documented safety/field validation | **Prioritize existing work** | Stronger signal pathway for intentional physical switch; already integrated, but not yet verified on real hardware |
| Add **EEG motor-imagery binary input**, research-only with synthetic and licensed offline evaluation | **Investigate** | Meaningful neural question and potential value when muscle activation is not an option; viability, OOD and real-world false activations entirely unverified |
| Provide consumer **EEG mind-to-text**, intent reading, emotion/fatigue diagnosis, or an implant bridge | **No production proposal** | Evidence does not support general-purpose consumer interpretation and introduces unjustified safety, privacy and/or clinical requirements |

**Stopping conditions (research)**: absent adequate EEG channels/labels or dataset rights; unsupported/offline-unavailable model; detectable label leakage; refusal/abstain mechanism fails on missing/unknown signal; poor across-session generalization; false-activation upper confidence bound remains unacceptably high; comfort/calibration effort outweighs ordinary assistive input; or any data transfer incompatible with ADR-011/019. Report negative findings and **close the candidate**, not just tune until the numbers look good.

## 6. Provenance and reproducibility fields

Each research run should record: source dataset ID and URL; rights/provenance and explicitly permitted use; immutable dataset version and local SHA-256; participants and sessions represented (pseudonymous grouping only); montage, sampling rate, signal modality, event labels, preprocessing steps, epoching/causality, sample exclusions; algorithm/library versions and exact full git revisions, seed, hyperparameter protocol, window split rules, confidence calibration, threshold and refractory period; offline-only dependency/egress check; device hardware/OS; metrics and uncertainty for all negatives. **Do not commit participant-level signal files or person-identifiable metadata.**

For reproducible software examples use [BrainFlow synthetic board](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html), a supported MNE pipeline and vetted MOABB datasets. Downloading a package or dataset is a separate step requiring a lawful provenance and license decision. If a scientific paper is later written, use public aggregate tables and code where licenses permit; determine authorship, data permissions, ethics and declarations independently.

## 7. Suggested project-specific sequence

1. **#699 (closed) / #696 (closed):** both issues are closed, so this review is a follow-up that needs a maintainer decision to reopen one of them or to open a new issue: review the shared synthetic fixture contract and publish *documentation-only* neural-versus-artifact tag definitions. No forked schema.
2. **#696 (closed; same follow-up caveat):** specify causal rest-versus-MI evaluation design and public-dataset eligibility; use MOABB's existing benchmark conventions where appropriate.
3. **#817 / #816 / #815:** agree task-success, false-trigger, abstention and kill-switch metrics applicable to an eventual hands-free interface.
4. **#814 / #425 / #427:** determine participant research requirements before any live testing.
5. **#819 / #790:** after research evidence exists, prepare a narrow **proposed** ADR only if continued work is justified. Record the reason to reject as readily as a reason to proceed.

**This document makes no claim of mind-reading, medical validity, generalizable BCI performance or user-tested functionality.** It does not create a new delivery task or alter approved product direction.

## Selected primary sources (as at 2026-11-03)

1. Lévy J. et al. (2026-06-29). *Noninvasive decoding of typed sentences from human brain activity.* Nature Neuroscience. https://www.nature.com/articles/s41593-026-02303-2
2. Wang L. et al. (2026-09-08). *Cross-variability decoding for motor imagery EEG signals: a comprehensive review.* Frontiers in Neuroscience. https://doi.org/10.3389/fnins.2026.1899645
3. Mulder M.Q. et al. (2026-10-09). *The challenge of out-of-distribution detection in motor imagery BCIs.* Journal of Neural Engineering. https://pubmed.ncbi.nlm.nih.gov/42790484/
4. Card N.S. et al. (2026-06-15). *Long-term independent use of an intracortical brain-computer interface for speech and cursor control.* Nature Medicine. https://doi.org/10.1038/s41591-026-04414-6
5. Littlejohn K.T. et al. (2025-03-31). *A streaming brain-to-voice neuroprosthesis to restore naturalistic communication.* Nature Neuroscience. https://doi.org/10.1038/s41593-025-01905-6
6. Wairagkar M. et al. (2025-06-12). *An instantaneous voice-synthesis neuroprosthesis.* Nature. https://doi.org/10.1038/s41586-025-09127-3
7. Fisher R.S. et al. (2026-02). *Visually-provoked seizures: Consensus of the Epilepsy Foundation Working Group.* Epilepsia. https://pubmed.ncbi.nlm.nih.gov/41283196/
8. BrainFlow. *Supported boards and synthetic board.* https://brainflow.readthedocs.io/en/stable/SupportedBoards.html
9. MOABB. *Quickstart and reproducible benchmark mission.* https://moabb.neurotechx.com/docs/README.html ; *release v1.7.1* https://github.com/NeuroTechX/moabb/releases/tag/v1.7.1 (Zenodo record: https://zenodo.org/records/22215752)
10. PhysioNet. *EEG Motor Movement/Imagery Dataset.* https://physionet.org/content/eegmmidb/1.0.0/



## Update: executable synthetic motor-imagery negative control (2026-11-03)

The repo already had a tested P0/P1 synthetic EOG/EMG artifact replay in [the HCI protocol](../../hci-huggingface/EEG_EOG_FEASIBILITY_PROTOCOL.md). To avoid duplicating it, this research branch adds a **separate**, standalone [synthetic motor-imagery stress experiment](../../hci-huggingface/EEG_MI_SYNTHETIC_STRESS_RESULTS.md), [script](../../../scripts/hci_eeg_mi_synthetic.py) and [13 regression tests](../../../tests/test_hci_eeg_mi_synthetic.py).

**Key negative finding (authored signals only):** the toy 10 Hz power detector generated two proposals for two deliberately easy imagery blocks, **but also one false candidate on a rest interval with lower synthetic baseline power**. Blink, muscle, missing-data and flatline scenarios produced no proposals in that seed. This is **not a human EEG result**; all data and thresholds were invented, and no false-activation/hour rate is inferred. It demonstrates why a potential neural switch must be evaluated for across-session drift and continuous idle false-trigger exposure rather than only epoch-level classification.

The new artifacts were executed in a separate offline Python workspace: **13/13 isolated tests passed,** with byte-for-byte Git blob verification against the branch. The full YazSes suite, Ruff and real-device checks have not been run. No production code or approved ADR changed. The next gate remains a license-reviewed, session/participant-separated public neural EEG dataset protocol and causal replay (#696 is closed, so this follow-up needs a maintainer decision to reopen it or to open a new issue; evaluation metrics sit under #817), with any actual human study separately gated.
