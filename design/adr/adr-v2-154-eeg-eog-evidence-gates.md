# ADR-v2-154 — EEG/EOG research must pass artifact-origin and real-world safety gates before any activation integration

**Status:** Proposed — research-only; not an implementation authorization  
**Date:** 2026-11-03  
**Decision required:** Maintainer review; no change to accepted feature policy  
**Context:** [Issue #696](https://github.com/MSKazemi/yazses/issues/696), [evidence review](../hci-huggingface/EEG_EOG_EVIDENCE_REVIEW_2026-11-03.md), [existing feasibility protocol](../hci-huggingface/EEG_EOG_FEASIBILITY_PROTOCOL.md), [ADR-v2-129](adr-v2-129-killer-features-10x.md), [ADR-v2-152](adr-v2-152-biosignal-artifact-switches.md), [ADR-030](adr-030-agent-era-direction.md), [ADR-011](adr-011.md)

## Context

YazSes already contains an off-by-default biosignal stack for artifact-grade events (squeeze, blink, jaw clench), and the accepted ADR-v2-129 rejects consumer-EEG *thought triggers*. A standalone #696 script deterministically replays Python-generated three-channel bursts and measures known injected events. These synthetic results cannot establish that an actual scalp EEG signal independently detects deliberate intent, let alone that it meets the low false-activation cost of a voice typing tool. BrainFlow BoardShim's synthetic-board interface is distinct from the script's seeded Python signal generator and has not been exercised by that script.

The team needs a decision that (1) does not duplicate approved artifact-switch engineering; (2) protects the boundary between an event *candidate* and real desktop *action*; (3) prevents mislabeled “EEG control” evidence; and (4) records when the project should stop investigating a modality.

## Proposed decision

**Choose bounded, non-actuating research with explicit stage gates; preserve the current NO-GO for a runtime EEG activation feature.** This proposal is a research-evidence policy, **not** a reversal of ADR-v2-129 and **not** an exception to ADR-030's feature freeze.

1. **Synthetic observations are only plumbing evidence (G0/G1).** Keep research generators, board-interface probes, model evaluation and replay outside the product runtime; no new default feature, network path, base dependency, permission, or daemon activation. Use the canonical #699/#139 event/intent structure instead of another public contract. Do not infer neurological origin from an `eeg` channel label.
2. **The proposed research question is a falsifiable comparison.** Evaluate whether a proposed *neural* activation adds reliable value over separately measured ocular EOG, muscle EMG, existing physical/software switches and sham control. Require independently sourced artifact references when feasible; compare EEG-only, EOG-only, EMG-only and combined approaches with a held-out session/participant evaluation. Inability to distinguish neural versus artifact origin forces the label **unknown origin** and **abstain**, not “brain command.”
3. **No silent action.** Every investigational candidate is non-actuating; even a later approved feature cannot directly execute an OS action without the existing hands-free safety, scope and confirmation rules. Stale/low-quality/contradictory or stopped input never produces a candidate, pending events are invalidated when stop/pause occurs, and resumption requires deliberate user input. A synthetic replay must not be conflated with a safe daemon.
4. **Human testing is a separate decision.** No P2 pilot without an independent and applicable research/ethics determination, named investigator, valid informed consent, minimal data/retention plan, accessible stop path, equipment safety review, preregistered tasks/splits/thresholds and owner approval. Use passive/shadow output with **no system actuation**. No photosensitive SSVEP/flicker without a distinct risk review. Public artifacts remain synthetic; do not upload raw EEG/EOG/EMG, health-adjacent records, voice or camera inputs.
5. **Acceptance thresholds must be fixed before observation.** Separately report usable no-intent exposure and uncertainty bounds for false activations by context; intentional-hit/miss counts; latency p50/p95; abstention, loss of signal, recovery burden, calibration time, CPU/RAM, and accessibility/comfort. Record excluded/poor-quality exposure. The existing provisional exposure floor is not proof of adequate statistical precision. The maintainer/research team must set acceptable error bounds in advance on the intended use case; **this ADR does not invent numerical success thresholds**.
6. **No promotion without a new decision.** A real-human positive result is still insufficient by itself for delivery: maintainers must explicitly revisit ADR-030, evaluate whether a measured user need justifies the maintenance burden, and approve a separate runtime ADR with device/platform validation and fallback. Until then, the verdict remains **research-only / NO-GO for integration**.

## Stage gates and current evidence

| Gate | Required evidence | Status as of 2026-11-03 | Allowed outcome |
|---|---|---|---|
| G0: synthetic deterministic baseline | Current script/protocol/tests demonstrate seeded signal/replay logic, all simulated | Code and tests inspected; not re-executed as part of this research review | Continue documentation and code research |
| G1: adversarial replay + interface validation | Independent BrainFlow synthetic BoardShim smoke test, adverse conditions, contract mapping, exact version/provenance, held-out synthetic seeds | Not demonstrated by existing #696 script | Continue only as offline research, not a feature |
| G2: passive hardware/human feasibility | Pre-approved study, independent EOG/EMG controls, frozen uncertainty-aware safety budget, held-out sessions, accessible physical stop | Not authorized; no pilot evidence | **No-go** until separately approved |
| G3: YazSes runtime decision | Strong G2 evidence, real-user demand, cross-platform device matrix, maintainable stop/fallback path, ADR-030 amendment and new accepted runtime ADR | Not met | **No-go** |

## Alternatives considered

**A. Integrate consumer EEG now using existing BrainFlow/biosignal pipeline — rejected.** An electrode and a software connector do not validate neurological control. False activations while speaking could open the microphone unintentionally; existing artifact-grade switches do not validate EEG-specific claims. It would contradict ADR-v2-129 and ADR-030.

**B. Pursue EEG classification using only public datasets — not sufficient as a product gate.** Dataset benchmarks may be useful for offline evaluation under verified licenses, but they generally do not measure naturalistic asynchronous false activations or end-to-end YazSes usability. Adjacent epochs and reused participant/session baselines risk leakage.

**C. Abandon all EEG/EOG study — not selected for research.** A small falsifiable offline study can produce valuable negative evidence, improve artifact rejection and document precisely why EEG adds no value. Stop research if the evidence repeatedly shows no material benefit or the required governance cannot be met.

**D. Focus on EOG/EMG artifact switches instead — preferred baseline, not an EEG result.** Already represented by the existing biosignal stack and ADR-v2-152; a future comparison may confirm these are adequate without implementing neural EEG control.

## Consequences

- **Positive:** Honest scientific claims, clean stop/recovery and consent boundaries, no increase in production runtime/dependency surface, reproducible falsifiable comparisons.
- **Costs:** More validation, potentially no EEG feature, extra consent/hardware study work, and inconclusive results where neural/artifact origin cannot be separated.
- **Failure/stop criteria:** Data cannot distinguish source origin; upper false-trigger uncertainty exceeds the pre-agreed budget; calibration or dropout undermines a complete task; unsafe recovery; inaccessible controls; missing ethics/privacy authorization; or no meaningful advantage over existing simpler controls. Report these failures rather than modifying post-hoc thresholds.

## Verification and next review

A maintainer should review the [dated evidence memo](../hci-huggingface/EEG_EOG_EVIDENCE_REVIEW_2026-11-03.md) alongside the accepted and proposed ADRs before accepting this research-only policy. Next engineering work can improve G1 synthetic/BoardShim evidence without starting a human study, changing the daemon, or promising a production feature. Any actual P2 protocol must be approved independently under the existing research-consent programme.

**Open decisions:** assign the eligible ethics/review authority; choose a preregistered intended-use safety budget and exposure plan before recruitment; identify the first independently measured hardware comparator; decide whether repeated negative findings warrant closing #696 as no-go.

## Sources

- [BrainFlow supported boards and BoardShim API](https://brainflow.readthedocs.io/en/stable/SupportedBoards.html) · [BrainFlow releases](https://github.com/brainflow-dev/brainflow/releases)
- [MNE: ICA artifact correction](https://mne.tools/stable/auto_tutorials/preprocessing/40_artifact_correction_ica.html)
- [MOABB cross-session evaluation](https://moabb.neurotechx.com/docs/generated/moabb.evaluations.CrossSessionEvaluation.html) · [cross-subject evaluation](https://moabb.neurotechx.com/docs/generated/moabb.evaluations.CrossSubjectEvaluation.html)
- [OECD responsible neurotechnology recommendation](https://legalinstruments.oecd.org/en/instruments/OECD-LEGAL-0457)
- [ACM human-participant research policy](https://www.acm.org/publications/policies/research-involving-human-participants-and-subjects)
