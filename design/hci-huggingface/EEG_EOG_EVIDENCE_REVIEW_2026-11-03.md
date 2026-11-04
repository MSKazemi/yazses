# EEG/EOG activation feasibility: evidence review and decision gates

**Date:** 2026-11-03  
**Status:** Research synthesis for review; **no human/device study conducted in this review**, no accepted new runtime decision.  
**Issue:** [#696](https://github.com/MSKazemi/yazses/issues/696), under [#692](https://github.com/MSKazemi/yazses/issues/692).  
**Companion:** [Existing protocol](EEG_EOG_FEASIBILITY_PROTOCOL.md); [proposed ADR-v2-154](../adr/adr-v2-154-eeg-eog-evidence-gates.md).

## Summary and recommendation

**Continue narrowly as offline, non-actuating feasibility research; do not add a consumer-EEG activation source to YazSes.** The current repository proves that a **hand-authored synthetic signal generator and detector** can be replayed deterministically and scored against injected events. It does **not** provide evidence of human EEG intentional-control performance, comparative advantage over EOG/EMG, or tolerable false activations in everyday dictation. Proposed ADR-v2-154 records the corresponding review gates; it does not supersede accepted ADR-v2-129 or the ADR-030 feature freeze.

A first useful research result would be a *falsification*: can the apparent EEG switch signal be explained equally well by EOG or EMG? Until this is tested with independently recorded channels, classify the output as an **electrode-derived candidate with unknown physiological origin**, never a decoded intention. This distinction matters particularly when YazSes users speak: jaw and facial muscle activity may confound scalp channels.

## 1. Repository baseline: inspected on 2026-11-03

| Existing artifact | What it already establishes | What is **not** established |
|---|---|---|
| [EEG/EOG feasibility protocol](EEG_EOG_FEASIBILITY_PROTOCOL.md) | Defines P0 (synthetic), P1 (injected artifacts), P2 (gated human pilot), non-goals and privacy safeguards | No pilot approval, preregistered real-hardware acceptance thresholds or participant evidence |
| [Synthetic replay script](../../scripts/hci_eegeog_replay.py) and [tests](../../tests/test_hci_eegeog_replay.py) | Seeded, deterministic 100 Hz generated Gaussian three-channel streams; calibration-only thresholds; causal envelope; refractory; injected blink/clench/speaking/intended bursts; separate naive/artifact-aware counts | **Does not open BrainFlow's synthetic board**; injected EEG “intended” burst is a modeling choice, not a validated motor-imagery, P300 or other neurophysiological signature |
| [BrainFlow sources](../../src/yazses/biosignal/sources.py) | A separate, already existing synthetic source and optional BrainFlow source with explicit default-off/failure behavior | No demonstration that #696's standalone replay exercises the BrainFlow BoardShim device interface |
| [Biosignal validation spec](../specs/biosignal-validation-protocol.md) and [ADR-v2-152](../adr/adr-v2-152-biosignal-artifact-switches.md) | Existing artifact-switch evaluation, usable-exposure accounting and a proposed false-positive budget approach | EEG-specific comparative hardware evidence or automatic approval for brain-derived control |
| [Synthetic fixture issue #699](https://github.com/MSKazemi/yazses/issues/699) (closed) and [fusion #700](https://github.com/MSKazemi/yazses/issues/700) | Canonical synthetic multimodal contract and replay work to reuse | No reason to invent a second signal/event schema or actuation path |
| [ADR-v2-129](../adr/adr-v2-129-killer-features-10x.md) and [ADR-030](../adr/adr-030-agent-era-direction.md) | Consumer EEG “thought” triggers rejected; new hands-free capability waves frozen | No policy exception for an EEG adapter |

**Precise reconciliation of current protocol:** Its P0 wording calls the source “BrainFlow's synthetic board and generated signals”, but the #696 replay *currently uses Python's seeded random generator only*. BrainFlow officially provides a distinct synthetic hardware-free board (board id -1) and a playback-file board, which could be independently smoke-tested later. Do **not** report a BrainFlow integration test as completed because the Python generator is green. BrainFlow's synthetic board is a development signal source; deterministic, byte-identical runs require either an independently seeded fixture or verified recording/playback, not an assumption about the live synthetic stream.

**Other concrete gaps (not defects proven in production):**
- The replay emits activation times and score aggregates, not the proposed full timestamp / quality / confidence / age / abstention **candidate contract**. Do not confuse this with the canonical #699 multimodal schema.
- The protocol asks for median and p95 latency, but the script currently reports median and **maximum** for matched synthetic events, not p95; no timings from physical devices are measured.
- The generator's noise/leakage amplitudes and event spacing are chosen parameters; it has no genuine electrode movement, neurological variations, between-day drift, real speaking, or real hardware clocks.
- No head-motion or quiet-reading test block is present in the #696 replay's fixed block list despite being identified as desired controls by the protocol.
- There is no preregistered real-world pass/fail threshold, no held-out person or session comparison, and no evidence of independently observed EEG-only benefit.

## 2. Primary-source research findings (checked 2026-11-03)

| Source | Verified finding | Relevance and limit |
|---|---|---|
| [BrainFlow supported boards](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html), [board API](https://brainflow.readthedocs.io/en/stable/UserAPI.html), [data format](https://brainflow.readthedocs.io/en/stable/DataFormatDesc.html) | Synthetic board id -1 requires no hardware; playback id -3 replays device files. Board metadata exposes sampling rate, signal indices and channel types. | Board compatibility is not evidence of signal quality; the synthetic board marks several channels as EEG/EMG/EOG, which must **not** be interpreted as independently measured physiology. |
| [BrainFlow releases](https://github.com/brainflow-dev/brainflow/releases) and [MIT license](https://github.com/brainflow-dev/brainflow/blob/master/LICENSE) | Release 5.23.0 listed as latest at review; BrainFlow source is MIT-licensed. | Pin an exact version and installation provenance for any separate bench run. Board firmware, drivers and recording licenses need individual checks. |
| [MNE artifact repair / ICA](https://mne.tools/stable/auto_tutorials/preprocessing/40_artifact_correction_ica.html) | Ocular and muscle activity can contaminate EEG; an ICA approach may separate some components when channels and assumptions permit it. | Artifact removal is not proof of neural signal origin. Offline artifact inspection is suitable for analysis; causal online latency must be measured separately. |
| [MOABB cross-session](https://moabb.neurotechx.com/docs/generated/moabb.evaluations.CrossSessionEvaluation.html) and [cross-subject](https://moabb.neurotechx.com/docs/generated/moabb.evaluations.CrossSubjectEvaluation.html) evaluation docs | Different splits test transfer across sessions and people rather than reusing temporally adjacent samples. | Public BCI leaderboard performance does not predict a YazSes asynchronous switch, its unintended-activation rate, or comfort; use an appropriately licensed dataset only for offline methods checks. |
| [OECD recommendation on responsible neurotechnology](https://legalinstruments.oecd.org/en/instruments/OECD-LEGAL-0457), [NIH neuroethics](https://www.ninds.nih.gov/current-research/focus-tools-topics/focus-neuroethics) | Emphasize autonomy, safety, minimization and privacy of neural data, and caution moving research methods into consumer use. | Governance guidance, not an ethics-board approval or legal compliance determination. The repository's [data-sharing policy](../eye-control/DATA_SHARING.md) still governs. |

**Source-status note:** These are documentation/library and governance sources, not a performed literature meta-analysis or head-to-head empirical review. Any quantitative third-party EEG claims must be checked against the original paper's population, equipment, task, confidence intervals and false-activation measurement before using them in YazSes product decisions.

## 3. Competing hypotheses, baseline and falsifiers

| Hypothesis | Competing explanation / control | Observation that would refute a claimed EEG benefit |
|---|---|---|
| H1: a deliberate *neural* signal provides useful asynchronous activation | EOG-only switch, EMG-only switch, non-actuating sham, shuffled cue labels | EEG benefit disappears after controlling ocular/muscle channels or fails on a held-out session |
| H2: artifact-aware suppression keeps unintentional triggers tolerable | Naive classifier, rest, speaking, chewing/clenching, natural blinks, head motion, cable movement, electrode dropout | Upper confidence bound for false-activation rate exceeds **pre-agreed** safety budget on any important control condition |
| H3: detector is usable across days/devices | Train on calibration only; evaluate held-out later sessions and different placements/boards | Frequent recalibration, drift, device-dependent collapse, or unacceptable abstention / miss rate |
| H4: any EEG path meaningfully helps an underserved workflow | Same task with existing keyboard/voice/face/EMG/EOG options, where accessible | No meaningful improvement in task completion, recovery or user preference at comparable error cost |

Explicitly separate **neural EEG** from **ocular EOG** and **muscular EMG**, including ambiguous mixtures. A detection on a scalp electrode is **not by itself** evidence of cerebral origin. Results should label the physical origin as *unresolved* unless the study design supports the distinction.

## 4. Repeatable work plan, without new runtime privileges

### S0 — Static reproducibility and source separation (permission: ordinary offline engineering)

1. Run the existing #696 Python replay and tests without a sensor, record the repo SHA, Python version, seed, complete parameter table and output hash. Run multiple predeclared seeds; report counts, not inferred human accuracy. These commands are **instructions for future reproduction**, not a claim that this review executed them:

       uv run python scripts/hci_eegeog_replay.py --seed 0
       uv run python -m pytest tests/test_hci_eegeog_replay.py -q

2. In a **separate research-only script** (not imported by the daemon), create BrainFlow BoardShim SYNTHETIC_BOARD and check device lifecycle, channel metadata, units, timestamp monotonicity and shutdown; test PLAYBACK_FILE_BOARD with an explicitly permitted local synthetic file. Pin BrainFlow 5.23.0 as the *initial version to verify*, not a newly added project dependency. Do not assert that BrainFlow's synthetic signal has a controllable seed.
3. Compare the #696 candidate-output shape with the actual #699 fixture and #139 intent vectors; write a compatibility mapping, **not** a new public contract.
4. Add missing adversarial fixtures: reading quietly, head motion, electrode pop, flatline/dropout, clock jump/out-of-order samples, stale source, loss of quality and simultaneous stop request. No OS calls.
5. Reconcile protocol-versus-script metrics (p95 vs maximum) and expose “unknown confidence/quality” rather than inventing calibrated probabilities.

### S1 — Synthetic stress and provenance (permission: no sensor)

Freeze parameters before each batch; sweep signal-to-noise, EEG/EOG/EMG leakage, threshold, refractory, hold duration and drift independently. Use distinct seeds for calibration/development/evaluation and retain all failed cases. Report per-condition numerator/denominator, missed switches, wrong-origin attribution, abstentions, latency percentiles, CPU/RSS, and reproducibility metadata. **Never convert the synthetic event schedule into “false activations per hour of real usage.”** Include a default-off and no-actuation assertion.

### S2 — Public/previously licensed human datasets (only after separate provenance review)

Optionally reproduce a MOABB-compatible baseline on a dataset with an audited license and consent scope, entirely in an isolated local analysis environment. No automatic downloads; acquisition must be explicit and logged. Predefine subject/session split, channel montage, preprocessing, causal vs offline transformations and leakage checks. This step tests analysis methods, **not** in-the-wild safety or permission for a consumer feature. Do not commit any participant recordings or derived sensitive time series.

### P2 — Real-hardware shadow-mode study (NOT AUTHORIZED BY THIS REVIEW)

Proceed only after an independent ethics/review determination, named responsible investigator, accessible consent and withdrawal materials, risk/retention plan, hardware/electrical-safety assessment, and explicit owner approval under #425/#427 and ADR-v2-150. No flashing/SSVEP stimulation without its own photosensitivity review. Use a physical/independent stop, an observer stop, and a passive UI with **no OS action injection**.

Pre-register:
- The exact intended activation task and population, inclusion/accessibility accommodations, hardware/firmware/montage, calibration time, exclusion criteria and whether data can leave a participant's device (default: no).
- Separate idle, speaking, reading, natural blink, deliberate blink, clench/chew, head motion and recovery phases; log **usable** exposure after quality gating, plus excluded time and its reasons, so discarding difficult periods cannot make a detector appear safer.
- An independent EOG and/or EMG reference when physically feasible, artifact-label adjudication rules and an EEG-only / EOG-only / EMG-only / combined ablation.
- Frozen event-matching window, refractory, max stale age, quality thresholds, session/participant holdouts, handling of overlapping events and a rule that unknown origin means abstain.
- Primary outcomes: accidental *proposed* activations per usable hour by phase (count, denominator and interval), cue hit/miss, p50/p95 end-to-end latency including acquisition, silent/paused failure response and confirmation/recovery burden. Secondary: setup time, fatigue/discomfort (voluntary report), CPU/RSS and accessibility.
- One-sided upper uncertainty bound for unintended activations as a decision statistic, with an agreed false-activation budget established **before recruitment**, in addition to a lower uncertainty bound for hit rate. Under a stationary Poisson approximation, zero events over T hours gives an approximate 95% upper limit of 3/T events/hour; correlated bursts or drift require more conservative treatment. **The budget remains undecided**, and this formula is not a claim that current YazSes meets it.

Do not aggregate different hardware/person/session conditions into a single flattering mean. Report failures and dropout separately.

## 5. Threat and failure review

| Failure | Observable hazard | Required response in a possible future **shadow** evaluator |
|---|---|---|
| Blink/clench while speaking | Spurious candidate / accidental microphone state change | Abstain when ocular/muscle origin cannot be ruled out; count it as a negative-control failure |
| Stale sample, non-monotonic timestamps, disconnect | Old event appears intentional | No candidate on invalid/faulted input; release any simulated hold and require deliberate recovery |
| Calibration drift, high noise, electrode displacement | Increasing phantom events or missed triggers | Explicit low-quality/unknown decision, no silent threshold-learning on evaluation data |
| Session pause/stop request | An outstanding event races the stop | Stop always has priority; queued events expire; no silent resume |
| Biometric leakage / third-party artifact sharing | Exposure of brain/health-adjacent data | Keep raw samples on-device; never post a recording or participant row to a GitHub issue or HF Space |
| Inaccessible recovery or significant fatigue | User loses agency despite “good” accuracy | Record accessible stop/recovery success and voluntary comfort, with an alternative control path |

## 6. Decision ledger and next actions

| Gate | Evidence required | Current state (2026-11-03) | Verdict |
|---|---|---|---|
| G0: replay code and honest synthetic claims | P0/P1 scripts, tests, protocol and no-action boundary | **Present** in repo; **not executed again in this review** | Suitable for continued offline research |
| G1: robustness and BrainFlow interface check | Independent BoardShim smoke test, adverse control fixtures, schema mapping and provenance | **Not established by the inspected #696 script** | Research follow-up |
| G2: ethically approved passive real-world comparison | Reviewed and consented protocol, prespecified error budget, independent artifact controls, held-out sessions | **Not authorized / no evidence reviewed** | **NO-GO** for pilot until approved |
| G3: software/product integration | G2 evidence, accessibility co-design, hardware OS matrix, maintained fallback, explicit ADR-030 change and separate accepted runtime ADR | **Not met** | **NO-GO** for YazSes runtime feature |

Suggested handoff: review proposed ADR-v2-154; if accepted as a *research policy*, file narrowly scoped G1 work against #696 rather than reopening completed fixture work (#699); identify an eligible research review authority before considering P2. **Do not close #696 based solely on this review**; no new human/device evidence is supplied here.

## References

- [BrainFlow supported boards](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html), [User API](https://brainflow.readthedocs.io/en/stable/UserAPI.html), [data-format metadata](https://brainflow.readthedocs.io/en/stable/DataFormatDesc.html), [releases](https://github.com/brainflow-dev/brainflow/releases), [MIT license](https://github.com/brainflow-dev/brainflow/blob/master/LICENSE).
- [MNE-Python: repairing artifacts with ICA](https://mne.tools/stable/auto_tutorials/preprocessing/40_artifact_correction_ica.html).
- [MOABB cross-session](https://moabb.neurotechx.com/docs/generated/moabb.evaluations.CrossSessionEvaluation.html) and [cross-subject](https://moabb.neurotechx.com/docs/generated/moabb.evaluations.CrossSubjectEvaluation.html) evaluations.
- [OECD recommendation on responsible innovation in neurotechnology](https://legalinstruments.oecd.org/en/instruments/OECD-LEGAL-0457) and [NIH BRAIN neuroethics guiding principles](https://www.ninds.nih.gov/current-research/focus-tools-topics/focus-neuroethics).

All external sources were inspected 2026-11-03. This document contains **no new empirical measurements**.
