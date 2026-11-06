# Motor-imagery EEG synthetic stress experiment — 2026-11-03

> **Every number on this page is synthetic.** Each figure comes from hand-authored waveforms and pseudorandom noise. None of them is evidence of human EEG performance, physiology or brain decoding.

**Status:** research-only synthetic software experiment. **Not** BCI efficacy evidence, human EEG classification, a benchmark on real devices, a shipped feature, a clinical/medical claim or an approved ADR.

**Tracking:** [#696 — EEG/EOG feasibility (closed 2026-11-03)](https://github.com/MSKazemi/yazses/issues/696), [#692 — HCI lab](https://github.com/MSKazemi/yazses/issues/692), [#790 — accessible workspace research](https://github.com/MSKazemi/yazses/issues/790), [#817 — evaluation](https://github.com/MSKazemi/yazses/issues/817).

**Existing research to reuse, not duplicate:** [P0/P1 artifact study](EEG_EOG_FEASIBILITY_PROTOCOL.md), [existing EEG/EOG synthetic replay](../../scripts/hci_eegeog_replay.py), [multimodal fixture schema](../../examples/hci-hf-lab/fixtures.schema.json) (#699), [2026 brain interface feasibility report](../research/state-of-the-art/2026-11-03-brain-interface-feasibility.md).

**Executable artifacts:** [Synthetic motor-imagery stress script](../../scripts/hci_eeg_mi_synthetic.py), [30 isolated regression tests](../../tests/test_hci_eeg_mi_synthetic.py).

## Scientific question

The existing P0/P1 work tests burst detection and rejection of injected eye/muscle artifacts, not neural motor imagery. This separate, standalone experiment asks a **software-only negative-control** question:

> When we invent a 10 Hz motor-cortex-like signal whose amplitude deliberately falls during a labelled "imagery" interval, will a causal rest-calibrated detector also fire when **rest amplitude drifts** or a sensor disconnects?

All signal shapes, amplitude changes, correlations, thresholds and scenarios were hand-authored. There are **no human signals and no device recordings**, so any apparent imagery detection is built into the generator. This is *not* a neural decoder and does not use/alter the existing HCI fixture contract.

## Run and reproduce

The code uses **Python standard library only**, requires no hardware, network, model download or additional package.

    python scripts/hci_eeg_mi_synthetic.py --seed 0
    python scripts/hci_eeg_mi_synthetic.py --seed 0 --stop-at-s 33
    python scripts/hci_eeg_mi_synthetic.py --seed 0 --drift-amplitude 0.85
    python scripts/hci_eeg_mi_synthetic.py --sweep-drift 0.30,0.50,0.75,0.85 --sweep-seeds 20
    python scripts/hci_eeg_mi_synthetic.py --seed 0 --no-reference-channel
    python scripts/hci_eeg_mi_synthetic.py --sweep-leakage 0,1,2,4,8,16,17,18,19,20,24,28,32 --sweep-seeds 20
    python scripts/hci_eeg_mi_synthetic.py --reliability --train-seeds 10 --sweep-seeds 20
    python -m pytest tests/test_hci_eeg_mi_synthetic.py -q

Within a fully installed YazSes checkout, use its usual test runner instead:

    uv run python -m pytest tests/test_hci_eeg_mi_synthetic.py -q

`--drift-amplitude` overrides only the authored `drift_rest` amplitude; without it the output is byte-identical to the original script (golden-hash tested, see below). `--sweep-drift` prints the seed-count sweep reported in the next section.

Stop is a **simulated independent external stop**, not a brain-triggered action. The experiment prints JSON with a synthetic-data notice and no OS action. It never uses an activation-source adapter or YazSes daemon code.

### Generator — invented parameters, not physiological estimates

- 100 samples/second, two independent C3/C4-like oscillatory channels, plus separate EOG and EMG artifact streams.
- One 6-second rest calibration segment, then 13 short scripted intervals (8 seconds each): rest, two imagery blocks, amplitude-drift rest, blink, jaw-clench, speaking, missing data, flatline and recovery.
- 10 Hz sine/cosine amplitude 1.00 at rest, 0.30/0.32 during artificial imagery; **0.48 for drifted rest**, which deliberately resembles imagery.
- Pseudorandom noise with a frozen per-run seed. No participants, real equipment, real field sessions or independent recording sessions.

### Causal pseudo-online rule

- Extract 10 Hz quadrature power from **trailing** 1-second windows at 250 ms hops. No future-sample lookahead.
- Estimate initial baseline only during the 6-second calibration; require feature power less than 55% of it for two consecutive windows to emit a **candidate proposal**.
- Re-arm only after observing 80% of initial rest power. The emitted suppression score is a heuristic, **not** calibrated confidence/probability.
- Mark windows missing or nonfinite, recently flatlined, high EOG or high EMG as unusable and abstain. After a signal failure require a new observed rest before rearming.
- An external stop disables all later candidate proposals. **No text, click, microphone or app action is ever performed**.
- Ground-truth segment labels are only read by the post-hoc scorer, never by inference.

## Local observed results — synthetic by construction

The figures are from the **seed 0** script run. The original run of this experiment recorded CPython 3.13.5; that exact patch release was not available when this document was revised. The seed-0 output was re-run on CPython 3.12.3, 3.13.15 and 3.14.7 and was byte-identical (same sha256 below), so the numbers do not depend on those versions, but a 3.13.5 run was not repeated.

| Report field | Seed-0 value | Interpretation |
| --- | --- | --- |
| Artificial imagery candidate hits | 2 / 2 | The generator was intentionally made easy; **not** human EEG sensitivity |
| Artificial onset-to-candidate latency | 750 ms, 750 ms | Simulated, given fixed 1-second trailing windows and selected thresholds |
| False candidate during drifted *rest* | **1** | **Primary negative finding:** a baseline shift can mimic a desired imagery event |
| False candidates in blink, clench and speaking blocks | 0 / 0 / 0 | Only these scripted controls. At the authored leakage they stay at 0 with or without the EOG/EMG reference gate (see the ablation below); not real human artifact rejection |
| False candidates in dropout and flatline blocks | 0 / 0 | The negative tests rejected these cases with recent-sample quality checks |
| Total false candidates | **1** | An error occurs despite the deliberately easy imagery example |
| Synthetic control-block duration | 88 seconds | Includes simulated blocked/unusable periods; not a reliable real idle-time denominator |
| False activations per hour | **null / not estimated** | Fabricating an hourly rate from a short artificial sequence would mislead |

Seeds **0–7** were also executed locally. Each had two artificial hits and one false candidate in drifted rest. Seeds change **only the pseudorandom noise** of one fixed authored waveform, so this agreement says little: it reflects the fixed authored generator, **not** subject/session generalization or a confidence interval. In a real system, a false activation is much more consequential than a good-looking synthetic hit rate.

**Reproducibility fingerprint.** The stdout of `python scripts/hci_eeg_mi_synthetic.py --seed 0` has sha256 `64ad91e04d8c732a6c4661470a37134c69b11d3d94793e9a762ff7edb556d9b6`. The test suite pins this value, so a change to the default output fails loudly. It was identical on CPython 3.12.3, 3.13.15 and 3.14.7.

### How much rest drift is needed? Drift-amplitude sweep

The single hand-picked drift point (0.48) hides the real tolerance. Rest amplitude is 1.00 and the detector candidate threshold is 55% of calibrated 10 Hz power, with power scaling roughly as amplitude squared, so the authored arithmetic puts the boundary near an amplitude of sqrt(0.55) ≈ 0.74. Only the `drift_rest` amplitude was varied; every other block, the thresholds and the noise model are the authored defaults. Output of `--sweep-drift ... --sweep-seeds 20` (seeds 0-19):

| Drift amplitude (rest = 1.00) | Seeds with a false candidate in `drift_rest` (of 20) |
| --- | --- |
| 0.30 | 20 |
| 0.40 | 20 |
| 0.48 (authored default) | 20 |
| 0.50 | 20 |
| 0.55 | 20 |
| 0.60 | 20 |
| 0.65 | 20 |
| 0.70 | 20 |
| 0.72 | 20 |
| 0.74 | 19 |
| 0.75 | 13 |
| 0.76 | 2 |
| 0.78 | 0 |
| 0.80 | 0 |
| 0.85 | 0 |
| 0.90 | 0 |
| 1.00 | 0 |

Reading: in this synthetic setup a rest-amplitude drop of about 26% (to ~0.74) is already enough to false-trigger, and the transition from "always fires" to "never fires" happens inside a band of roughly 0.74-0.78. This follows **from the authored thresholds and the authored waveform, not from physiology**: it says nothing about how large real rest-state mu variation is in people, and it does not transfer to real EEG. Over seeds 0-19 at the default, 0.50 and 0.85 amplitudes the two artificial imagery hits stayed 2 / 2 and no control block other than `drift_rest` produced a candidate; the other amplitudes were not checked for this. Because seeds only vary noise, the 0-19 range tests noise sensitivity near the boundary, not between-session or between-person variability.

### Dependence on a clean reference channel, and abstention

- **Correction (2026-11-06).** An earlier version of this page said blink, clench and speaking show 0 false candidates *only because* a clean EOG/EMG reference channel feeds the quality gate. The ablation below shows that is not what this generator does. At the authored leakage the three blocks stay at 0 with the gate removed too. The authored artifacts are *added* to C3/C4: blink is a slow bump, clench alternates at the 50 Hz Nyquist rate and speaking is broadband noise. Only a fall in 10 Hz power can produce a candidate, and an added artifact changes that power only through its own 10 Hz component, which can add to or cancel the mu rhythm depending on phase. At the authored leakage that component is negligible or absent. The clench alternation has no 10 Hz component over a whole 1 s window, and in every scored window (250 ms hops) its contribution is zero to floating-point precision. The blink bump reaches at most about 0.008 in 10 Hz amplitude on C3, and speaking about 0.013 on average. The rest mu amplitude is 1.00 on each channel, and a candidate needs the window's 10 Hz power, averaged over C3 and C4, to fall below 55% of the calibrated rest power. So the 0 / 0 / 0 row is a property of the generator, not evidence that the gate rejects artifacts. A contaminated reference channel and artifacts that *suppress* 10 Hz power were not modelled.
- **Abstention is large.** In the seed-0 run, 96 of 416 post-calibration windows (23.1%) were rejected as unusable (flatline 32, muscle artifact 40, missing or non-finite 19, ocular artifact 5), leaving 320 eligible windows. Across seeds 0-19 the figure is 95-96 of 416 (about 23%); it is driven by the scripted blocks, so it is not an estimate of real-world usable time. A real evaluation must report this fraction beside any hit or false-candidate figure.

### Reference-channel ablation — synthetic only (2026-11-06)

`--no-reference-channel` removes the EOG/EMG quality gate, and the detector then never reads those channels. `--artifact-leakage` scales the authored coupling of EOG/EMG into C3/C4, where 1.0 means the authored 0.14/0.10. `--sweep-leakage` runs both gate settings over seeds 0-19, with 20 seeds × 8 s = 160 s of each artifact block per cell. The "per hour" column is arithmetic only: count × 3600 / 160 s of scripted block. It is **not** an estimate of a real false-activation rate, and the per-run report still sets `false_activations_per_hour` to null.

| Leakage × authored | Gate | Blink / clench / speaking false candidates (20 seeds) | Arithmetic per hour (blink / clench / speaking) | Imagery hits (of 40) | Abstention rate | Unknown-state rate |
| --- | --- | --- | --- | --- | --- | --- |
| 0, 1, 2, 4, 8, 16 | on | 0 / 0 / 0 | 0 / 0 / 0 | 40 | 23.05% | 1.8-2.0% |
| 0, 1, 2, 4, 8, 16 | off | 0 / 0 / 0 | 0 / 0 / 0 | 40 | 12.26% | 1.9-2.8% |
| 17, 18, 19, 20, 24, 28, 32 | on | 0 / 0 / 0 | 0 / 0 / 0 | 40 | 23.05% | 1.7-1.8% |
| 17, 18, 19, 20 | off | 0 / 0 / **1** | 0 / 0 / **22.5** | 40 | 12.26% | 2.9-3.0% |
| 24, 28, 32 | off | 0 / 0 / **3** | 0 / 0 / **67.5** | 40 | 12.26% | 3.1-3.4% |

How to read it. With the gate removed, the first artifact false candidate appears at 17× the authored leakage, in `speaking` only. Over seeds 0-19 the onset lies between 16× (0 false candidates) and 17× (1). Only whole-number leakage values were run there, so the onset is bracketed to that interval, not located more finely, and a different seed set could move it. The count rises to 3 by 24× and stays at 3 up to 32×. Blink and clench give 0 at every leakage run. The likely mechanism is chance cancellation. The speaking noise reaches C3 and C4 through the same EMG channel, and its 10 Hz component grows in proportion to the leakage, to about 0.21 in amplitude on average at 16× and 0.32 at 24×. An occasional window where that component is large and in the opposing phase pulls the averaged power under the threshold. The gate's measurable effect at the authored leakage is abstention: removing it lifts eligible time from about 77% to about 88% of post-calibration windows. None of this describes real ocular or muscle artifacts.

### Reliability of the suppression score — synthetic only

`--reliability` labels each usable post-calibration window after inference, never during it. A window counts as imagery (1) or not (0) only when its whole 1 s span lies inside one block. Windows that straddle a boundary are left out (301 per 10 seeds). The raw score is `clip(1 - ratio, 0, 1)`. **That score is an uncalibrated heuristic, not a probability.** A histogram-binning map was fitted on seeds 0-9 only and scored on held-out seeds 10-19. There are 10 equal-width bins; an empty training bin falls back to the training base rate.

Held-out raw reliability, 2,900 windows of which 580 are imagery:

| Score bin | Windows | Mean score | Imagery fraction |
| --- | --- | --- | --- |
| 0.0-0.1 | 2,030 | 0.005 | 0.00 |
| 0.1-0.7 | 0 | — | — |
| 0.7-0.8 | 290 | 0.768 | 0.00 |
| 0.8-0.9 | 225 | 0.895 | 1.00 |
| 0.9-1.0 | 355 | 0.909 | 1.00 |

| Held-out ECE (10 bins) | Value |
| --- | --- |
| Raw heuristic score | 0.0995 |
| Binned map fitted on seeds 0-9 | 0.0000 |

How to read it. The 0.7-0.8 bin is the authored `drift_rest` block: a mean score of 0.77 with no imagery in it. The raw score is therefore overconfident exactly where the documented false candidate sits. The perfect binned ECE is a construct of the generator. Imagery (amplitude 0.30/0.32) and drift (0.48) never overlap in score, so any binning separates them. Seeds vary only the noise, so seeds 0-9 against 10-19 is **not** a cross-session or participant-disjoint split. The result shows how the reliability table and ECE are computed and how a heuristic can be miscalibrated. It does not calibrate any EEG measurement.

### Unknown-state abstention rate

`state_summary` sorts every post-calibration window (416 per seed) into four groups: *abstained* (quality gate), *candidate band* (ratio < 0.55), *unknown band* (0.55 ≤ ratio < 0.80, where the detector neither proposes imagery nor confirms rest) and *rest band* (ratio ≥ 0.80). On held-out seeds 10-19 with the gate on, abstention was 22.8-23.1% and the unknown band was 1.7-2.2% of windows. In total, about a quarter of the scripted time gave no usable rest or imagery decision. The scripted blocks drive these fractions, so they are not estimates of real usable time.

### Controls not covered

| Condition | Status |
| --- | --- |
| Head motion | **NOT TESTED** - no block, no motion channel; absence of a result is not zero errors |
| Quiet reading / sustained attention | **NOT TESTED** - no block; real task-related mu variation was not modelled |
| Other real-world confounds (fatigue, electrode drift, mains interference, real eye or jaw movement spectra) | **NOT TESTED** |

**Tests:** the isolated Pytest module has 30 cases: 13 original, 6 for the golden hash, default-equivalence, drift-sweep monotonicity, determinism and the drift CLI flags, and 11 added on 2026-11-06. The new 11 cover the reference-channel ablation, the leakage sweep's hourly arithmetic, gate-off 0 / 0 / 0 artifact false candidates at the authored leakage (seeds 0-1), the clench alternation's zero 10 Hz power, the four-way state partition, train/test seed disjointness, ECE on toy inputs and the new CLI flags. The seed-0 default output hash did not change. Checks include reproducibility, a pinned seed-0 output hash, synthetic notices, mandatory false drift case, blink/clench/speaking/dropout/flatline refusal, causality under future-data mutation, independent stop, NaN/missing handling, inference independence from labels, CLI JSON output and bounded timestamps. For the original 13-test version, the blob hashes of script/tests uploaded to the research branch matched the locally tested files.

**Not run:** full project test suite, Ruff/CI, real EEG, BrainFlow hardware, real participants, cross-session independent data or publication-grade analysis. Do **not** imply the isolated tests establish whole-repository correctness.

## Interpretation and design consequences

1. **No practical EEG switch has been demonstrated.** The detector merely recognizes a signal constructed for it, and fails on an equally constructed rest-drift case.
2. **Baseline drift is a critical false-trigger risk.** Avoid treating binary offline classification scores as real continuous-use reliability. Collect independent sessions, real rest activity and unfamiliar negative conditions before estimating safety.
3. **Signal quality and stop must be fail-closed.** A recent flatline window initially produced a false candidate; adding a short recent-sample quality check prevented that case in this synthetic test, but does **not** solve baseline drift or all unknown states.
4. **Report proper denominators on real data.** The scripted 88 seconds is not real usable idle exposure. Only a sufficiently long, predeclared prospective evaluation can estimate false activations per usable hour with uncertainty.
5. **A drop of about a quarter in rest power already crosses the authored threshold.** Any real baseline must be shown to be stable well beyond that, per person and per session, before a candidate is trusted; this synthetic sweep cannot say how stable real baselines are.
6. **Do not confuse neural EEG with blink/jaw artifacts.** The existing EMG/EOG paths remain the appropriate practical baseline; this is a separate experimental motor-imagery question.
7. **Keep neural candidates out of product actions.** No model, recording, calibration profile or signal stream may be uploaded or silently sent. ADR-030 (Accepted) governs; the biosignal-switch scope in ADR-v2-152 is still Proposed, so it is a boundary this experiment respects rather than a binding decision.

## Next gate: independent neural dataset study, not yet started

Before any real motor-imagery inference is claimed:

1. Review a specific public EEG motor-imagery dataset (potentially PhysioNet EEG Motor Movement/Imagery or a MOABB-indexed dataset), its exact licensing, participant rights, channels, sample rates, true rest labels, recordings and session structure **before** downloading or training anything.
2. Freeze a participant/session-disjoint split. Never split overlapping windows from one continuous recording across train and test. Perform preprocessing, calibration and model fitting **only on training data**.
3. Compare always-rest with elementary bandpower/CSP and a regularized linear classifier; a covariance-based method is a secondary reference. Declare metrics and thresholds in advance, not after seeing the test set.
4. Perform **causal** replay and report misses, correct intentional cues, false candidates per *usable* idle exposure, latency p50/p95, abstention/quality-failure fraction, unknown-class and artifact negatives, sensor interruptions, session drift and performance on normal CPU.
5. No dataset may be interpreted as having measured speech/blink/head-motion rejection unless it explicitly contains those labelled controls. Missing classes must be reported as **not tested**, not as zero errors.
6. Human use of hardware, photosensitive stimuli, participant data or live interaction remains separately gated by review/consent, accessibility and safety requirements under #425/#427/#814, plus the accepted ADR-030 direction.

**Recommendation:** #696 is closed (2026-11-03), so this follow-up is not tracked on an open issue. Reopening #696, or opening a new research issue, is a maintainer decision. Until independent cross-session results and user-demand evidence exist, do not open a production neural-activation task, claim mind reading, or propose an ADR change.
