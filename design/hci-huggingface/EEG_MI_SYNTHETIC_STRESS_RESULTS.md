# Motor-imagery EEG synthetic stress experiment — 2026-11-03

**Status:** research-only synthetic software experiment. **Not** BCI efficacy evidence, human EEG classification, a benchmark on real devices, a shipped feature, a clinical/medical claim or an approved ADR.

**Tracking:** [#696 — EEG/EOG feasibility](https://github.com/MSKazemi/yazses/issues/696), [#692 — HCI lab](https://github.com/MSKazemi/yazses/issues/692), [#790 — accessible workspace research](https://github.com/MSKazemi/yazses/issues/790), [#817 — evaluation](https://github.com/MSKazemi/yazses/issues/817).

**Existing research to reuse, not duplicate:** [P0/P1 artifact study](EEG_EOG_FEASIBILITY_PROTOCOL.md), [existing EEG/EOG synthetic replay](../../scripts/hci_eegeog_replay.py), [multimodal fixture schema](../../examples/hci-hf-lab/fixtures.schema.json) (#699), [2026 brain interface feasibility report](../research/state-of-the-art/2026-11-03-brain-interface-feasibility.md).

**Executable artifacts:** [Synthetic motor-imagery stress script](../../scripts/hci_eeg_mi_synthetic.py), [13 isolated regression tests](../../tests/test_hci_eeg_mi_synthetic.py).

## Scientific question

The existing P0/P1 work tests burst detection and rejection of injected eye/muscle artifacts, not neural motor imagery. This separate, standalone experiment asks a **software-only negative-control** question:

> When we invent a 10 Hz motor-cortex-like signal whose amplitude deliberately falls during a labelled "imagery" interval, will a causal rest-calibrated detector also fire when **rest amplitude drifts** or a sensor disconnects?

All signal shapes, amplitude changes, correlations, thresholds and scenarios were hand-authored. There are **no human signals and no device recordings**, so any apparent imagery detection is built into the generator. This is *not* a neural decoder and does not use/alter the existing HCI fixture contract.

## Run and reproduce

The code uses **Python standard library only**, requires no hardware, network, model download or additional package.

    python scripts/hci_eeg_mi_synthetic.py --seed 0
    python scripts/hci_eeg_mi_synthetic.py --seed 0 --stop-at-s 33
    python -m pytest tests/test_hci_eeg_mi_synthetic.py -q

Within a fully installed YazSes checkout, use its usual test runner instead:

    uv run python -m pytest tests/test_hci_eeg_mi_synthetic.py -q

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

Ran in a standalone Python 3.13.5 environment; the figures are from the **seed 0** script run:

| Report field | Seed-0 value | Interpretation |
| --- | --- | --- |
| Artificial imagery candidate hits | 2 / 2 | The generator was intentionally made easy; **not** human EEG sensitivity |
| Artificial onset-to-candidate latency | 750 ms, 750 ms | Simulated, given fixed 1-second trailing windows and selected thresholds |
| False candidate during drifted *rest* | **1** | **Primary negative finding:** a baseline shift can mimic a desired imagery event |
| False candidates in blink, clench and speaking blocks | 0 / 0 / 0 | Only these scripted controls, not real human artifact rejection |
| False candidates in dropout and flatline blocks | 0 / 0 | The negative tests rejected these cases with recent-sample quality checks |
| Total false candidates | **1** | An error occurs despite the deliberately easy imagery example |
| Synthetic control-block duration | 88 seconds | Includes simulated blocked/unusable periods; not a reliable real idle-time denominator |
| False activations per hour | **null / not estimated** | Fabricating an hourly rate from a short artificial sequence would mislead |

Seeds **0–7** were also executed locally. Each had two artificial hits and one false candidate in drifted rest. This consistency reflects the fixed authored generator, **not** subject/session generalization or a confidence interval. In a real system, a false activation is much more consequential than a good-looking synthetic hit rate.

**Tests:** 13 of 13 new isolated Pytest cases passed locally. Checks include reproducibility, synthetic notices, mandatory false drift case, blink/clench/speaking/dropout/flatline refusal, causality under future-data mutation, independent stop, NaN/missing handling, inference independence from labels, CLI JSON output and bounded timestamps. The exact Git blob hashes of script/tests uploaded to the research branch matched locally tested files. Syntax compilation also passed.

**Not run:** full project test suite, Ruff/CI, real EEG, BrainFlow hardware, real participants, cross-session independent data or publication-grade analysis. Do **not** imply the 13 isolated tests establish whole-repository correctness.

## Interpretation and design consequences

1. **No practical EEG switch has been demonstrated.** The detector merely recognizes a signal constructed for it, and fails on an equally constructed rest-drift case.
2. **Baseline drift is a critical false-trigger risk.** Avoid treating binary offline classification scores as real continuous-use reliability. Collect independent sessions, real rest activity and unfamiliar negative conditions before estimating safety.
3. **Signal quality and stop must be fail-closed.** A recent flatline window initially produced a false candidate; adding a short recent-sample quality check prevented that case in this synthetic test, but does **not** solve baseline drift or all unknown states.
4. **Report proper denominators on real data.** The scripted 88 seconds is not real usable idle exposure. Only a sufficiently long, predeclared prospective evaluation can estimate false activations per usable hour with uncertainty.
5. **Do not confuse neural EEG with blink/jaw artifacts.** The existing EMG/EOG paths remain the appropriate practical baseline; this is a separate experimental motor-imagery question.
6. **Keep neural candidates out of product actions.** No model, recording, calibration profile or signal stream may be uploaded or silently sent. ADR-030 and the existing biosignal-switch scope remain binding.

## Next gate: independent neural dataset study, not yet started

Before any real motor-imagery inference is claimed:

1. Review a specific public EEG motor-imagery dataset (potentially PhysioNet EEG Motor Movement/Imagery or a MOABB-indexed dataset), its exact licensing, participant rights, channels, sample rates, true rest labels, recordings and session structure **before** downloading or training anything.
2. Freeze a participant/session-disjoint split. Never split overlapping windows from one continuous recording across train and test. Perform preprocessing, calibration and model fitting **only on training data**.
3. Compare always-rest with elementary bandpower/CSP and a regularized linear classifier; a covariance-based method is a secondary reference. Declare metrics and thresholds in advance, not after seeing the test set.
4. Perform **causal** replay and report misses, correct intentional cues, false candidates per *usable* idle exposure, latency p50/p95, abstention/quality-failure fraction, unknown-class and artifact negatives, sensor interruptions, session drift and performance on normal CPU.
5. No dataset may be interpreted as having measured speech/blink/head-motion rejection unless it explicitly contains those labelled controls. Missing classes must be reported as **not tested**, not as zero errors.
6. Human use of hardware, photosensitive stimuli, participant data or live interaction remains separately gated by review/consent, accessibility and safety requirements under #425/#427/#814, plus the accepted ADR-030 direction.

**Recommendation:** leave #696 open as a research issue; do not open a production neural-activation task, claim mind reading, or propose an ADR change until independent cross-session results and user-demand evidence exist.
