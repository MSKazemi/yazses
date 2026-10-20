# Paper v2 claim ledger

This ledger is the control surface for manuscript claims. It prevents three common failures:

1. promoting an exploratory probe into a universal statement;
2. quoting a point estimate without the population/condition that produced it;
3. retaining an attractive claim after a later rerun contradicted it.

Use the status labels literally:

- **SUPPORTED** — current artifacts support the claim in the stated population/condition.
- **SUPPORTED WITH QUALIFICATION** — a narrower version is defensible; wording must preserve the qualification.
- **HYPOTHESIS / MECHANISM** — plausible and evidence-informed, but not established as a general effect.
- **REFUTED / WITHDRAWN** — an earlier interpretation is contradicted or unsupported and must not reappear.
- **OPEN** — important question with no adequate experiment yet.

## A. Core ASR claims

### C-ASR-01 — clean-speech engine comparison

**Status:** SUPPORTED WITH QUALIFICATION

**Claim:** On the measured 200-utterance LibriSpeech `test-clean` subset on the Azure Xeon CPU, Parakeet TDT 0.6B v2 had the lowest WER point estimate (2.06%), while Moonshine/tiny had the lowest RTF (0.016).

**Evidence:**
- `paper/results/probes/wer-vm-clean.json` (current uncontended eight-engine clean matrix; promote/freeze under #495 before submission)
- `paper/results/wer.json` is the older v1 three-checkpoint laptop result and is not the source of this claim

**Required qualification:**
- Parakeet's interval overlaps `large-v3` and `small.en`; do not convert the point estimate into universal statistical superiority.
- RTF is machine-specific.

**Allowed manuscript wording:**
> On the shared CPU harness, Parakeet produced the lowest clean-speech WER point estimate, whereas Moonshine/tiny was the fastest decoder; confidence intervals preclude treating the WER ranking as a universal ordering.

**Do not write:**
> Parakeet definitively beats all Whisper models.

---

### C-ASR-02 — hard audio changes the ranking/robustness picture

**Status:** SUPPORTED

**Claim:** Moving from `test-clean` to `test-other` increased WER for every measured engine, but by materially different factors; Parakeet had the smallest measured multiplier (about 1.4×), while several engines degraded by roughly 2–2.5×.

**Evidence:**
- `paper/results/wer.json`
- `paper/results/wer-test-other.json`

**Required qualification:** `test-other` is harder read speech, not spontaneous microphone dictation.

---

### C-ASR-03 — `large-v3` repeated WER variation is insertion-driven

**Status:** SUPPORTED

**Claim:** In repeated `large-v3` decodes of the measured `test-other` subset, substitutions, deletions, and hits remained fixed while insertion count changed substantially, so the observed WER spread was driven by extra emitted text rather than recognition substitutions.

**Evidence:**
- `paper/results/probes/largev3-instability-test-other.json`
- related decode mechanism artifacts

**Key numbers:**
- substitutions = 87 across the compared repeats
- deletions = 15
- hits = 3619
- dedicated four-repeat probe: insertions = 101–144 and WER = 5.46–6.61%
- the earlier matrix run that triggered the probe reached 184 insertions and 7.69% WER; report it separately from the controlled repeat range

**Required qualification:** this is a finding for the measured software/model/corpus conditions. It is not yet a claim about every Whisper `large-v3` implementation.

---

### C-ASR-04 — high machine load caused the `large-v3` instability

**Status:** REFUTED / WITHDRAWN AS A CAUSAL CLAIM

**Reason:** the 7.69% run was taken under unusually high load, but lower-load repeated runs still vary substantially. Load is a plausible moderator, not an established cause.

**Allowed wording:**
> The highest observed WER coincided with high host load, but similar-load repeats still varied; the experiment therefore does not identify system load as the cause.

---

### C-ASR-05 — previous-text conditioning is checkpoint-dependent

**Status:** SUPPORTED WITH QUALIFICATION

**Claim:** The measured effect of `condition_on_previous_text` changes across checkpoints: it helps `base.en`, has a small benefit on `small.en`, is byte-identical on `medium.en`, and is associated with rare runaway repetition on `large-v3` under the tested conditions.

**Evidence:**
- `paper/results/probes/decode-determinism-base.en-test-other.json`
- `paper/results/probes/decode-determinism-small.en-test-other-baseline-no_context.json`
- `paper/results/probes/decode-determinism-medium.en-test-other-baseline-no_context.json`
- `paper/results/probes/decode-determinism-large-v3-test-other.json`
- `paper/results/probes/decode-determinism-large-v3-test-other-no_context.json`
- decode mechanism artifacts

**Required qualification:** disabling conditioning on `large-v3` should be framed as preventing a rare catastrophic repetition mode, not as a statistically established average-WER improvement.

**Do not write:**
> Turning off context improves Whisper accuracy.

---

### C-ASR-06 — temperature fallback is the root cause and should be disabled

**Status:** REFUTED / WITHDRAWN

**Reason:** the `temperature=0.0` arm removes the rescue path and can make results dramatically worse. The fallback participates in variability but also rescues failed first-choice decodes.

**Allowed wording:**
> The fallback exposes stochasticity after a failed deterministic decode, but disabling it is not a remedy because the failed first-choice decode remains.

---

### C-ASR-07 — greedy decoding is an acceptable free speed-up

**Status:** SUPPORTED WITH QUALIFICATION / GENERALLY FALSE ON DEFAULT MODEL

**Claim:** On `base.en`, beam 1 is measurably worse than modest beam search on both clean and hard splits, for only an 11–16% speed improvement.

**Evidence:**
- `paper/results/beam-test-clean.json`
- `paper/results/beam-test-other.json`
- paired significance artifacts

**Key paired results:**
- clean beam 1 vs beam 5: +0.386 WER points, 95% CI [0.069, 0.726], p=0.0192
- hard beam 1 vs beam 5: +1.102 points, 95% CI [0.305, 2.196], p=0.001

**Qualification:** this is checkpoint-dependent. `small.en` on clean speech does not establish the same penalty.

---

## B. Reproducibility and platform claims

### C-REP-01 — one WER number is not portable across all CPUs

**Status:** SUPPORTED

**Claim:** The same checkpoint/subset can produce slightly different WER across OS/ISA environments; the size of that spread is model-dependent.

**Evidence:**
- `paper/results/platforms/*/wer.json`

**Key figures on the 60-utterance cross-platform subset:**
- `tiny.en`: 3.39–3.88%
- `base.en`: 3.25–3.39%
- `small.en`: 2.05% on all four measured runners

**Allowed conclusion:** cross-platform numerical sensitivity decreases across these three checkpoints in this experiment.

**Do not write:** all models are platform independent.

---

### C-REP-02 — cross-platform decode results prove full cross-platform operation

**Status:** REFUTED AS AN INFERENCE

**Reason:** benchmark decoding does not exercise global hotkeys, actual microphone capture permissions, text injection, GUI behaviour, daemon lifecycle, accessibility APIs, or recovery paths.

**Open validation needed:** end-to-end scripted or human-in-the-loop validation on Windows and macOS.

---

### C-REP-03 — provenance/history changed the scientific conclusion

**Status:** SUPPORTED AS A METHODOLOGICAL SYSTEMS CONTRIBUTION

**Claim:** Retaining displaced benchmark files and recording exact commands/corpus identity exposed contradictions that would otherwise have been overwritten, notably the `large-v3` 4.86% vs 7.69% hard-split disagreement.

**Evidence:**
- `paper/results/probes/logs/x86b-other_wer.log` — matrix run 1, at 4.86%. This is the whole of run 1: the JSON was overwritten before the retention mechanism existed, so the disagreement is evidenced by a console log, not by `history/`.
- `paper/results/wer-test-other.json` — matrix run 2, at 7.69%
- `paper/results/history/` — the retention mechanism that postdates this loss, carrying six later displaced runs
- `paper/results/MANIFEST.md`
- benchmark provenance implementation

**Caveat when writing this up:** the claim is that the *record* of the disagreement survived, not that the mechanism saved it. It did not — it was written because this one nearly was not.

**Writing angle:** reproducibility infrastructure is not administrative metadata; it materially altered the interpretation.

---

## C. Latency and interaction claims

### C-LAT-01 — synthetic pre-speech silence recovers clipped first words

**Status:** REFUTED

**Evidence:**
- `paper/results/onset.json`
- `paper/results/onset-significance.json`

**Finding:** no lead-in condition survives multiplicity correction as better than no lead-in; lost speech cannot be reconstructed by adding silence after the fact.

**Important privacy implication:** genuine pre-key recovery requires buffering real audio before activation, which violates the current “not listening while key is up” boundary.

---

### C-LAT-02 — streaming universally reduces perceived latency

**Status:** REFUTED / TOO BROAD

**Evidence:**
- `paper/results/streaming.json`
- current `docs/benchmarks.md` rerun

**Narrow supported claim:** streaming can expose substantial partial text on very fast checkpoints such as `tiny.en`, but on `base.en` the rolling CPU decode often fails to stay ahead of the microphone stream and makes final commit slower.

**Do not write:** streaming is faster.

---

### C-LAT-03 — current streaming result is definitive across machines

**Status:** OPEN / NEEDS REPLICATION

**Reason:** n=15, one main machine, read speech. The effect direction is large but should be replicated on at least one second CPU and with spontaneous speech before being elevated to a broad interaction claim.

---

## D. Diarization claims

### C-DER-01 — old clustering default was unsuitable for real meetings

**Status:** SUPPORTED

**Claim:** On the full 16-recording AMI test split, the former 0.5 clustering threshold massively over-split speakers, producing 75.21% mean DER and an average +155.19 speaker-count error; raising the meeting threshold to 1.2 reduced mean DER to 26.71%.

**Evidence:**
- `paper/results/diarization-ami16_corpus-der.json`
- ADR-v2-133
- related probe results

**Preferred paper-comparable figure for current system:** 27.37% time-weighted DER, 20.51% at 250 ms collar.

**Qualification:** AMI headset mix is cleaner than a far-field table microphone; 26–27% DER is not a claim of state-of-the-art quality.

---

### C-DER-02 — a four-speaker clustering cap improves DER at the current threshold

**Status:** NOT ESTABLISHED

**Evidence:**
- `paper/results/diarization-ami16_corpus-maxspk4-vs-der-significance.json`

**Results:**
- 7 recordings better, 7 worse, 2 unchanged
- sign test p=1.0
- mean ΔDER +2.71, CI [-1.64, +7.60]

**Supported replacement claim:** `max_speakers=4` is a clustering ceiling, not an exact-count oracle. It makes the estimated count exact on 15/16 recordings instead of 2/16; the one remaining recording has three reference speakers and is over-counted by one. The sample does not resolve a DER benefit.

---

### C-DER-03 — one threshold is suitable for all diarization domains

**Status:** REFUTED

**Evidence:** synthetic, VoxConverse, and AMI sweeps.

**Observed operating points:**
- synthetic ~0.8–0.9
- VoxConverse ~0.9
- AMI ~1.2

**Allowed conclusion:** clustering calibration is domain-sensitive; feature-specific defaults are better justified than one global constant.

---

### C-DER-04 — centroid similarity can safely repair split speakers

**Status:** REFUTED FOR THE TESTED SIMPLE HEURISTIC

**Evidence:**
- `paper/results/centroid-merge-ami16_corpus-meeting.json`
- `paper/results/centroid-merge-ami16_corpus-recimport.json`
- `paper/benchmark/analyze_centroid.py`

**Conclusion:** no useful threshold repaired enough split-speaker clusters without unacceptable wrong-person merges.

**Research value:** keep this as a negative result, not an omitted failed idea.

---

## E. HCI / user-value claims

### C-HCI-01 — YazSes is faster than typing in actual use

**Status:** OPEN

**Reason:** no controlled user study has measured composition + correction + final error cost in YazSes.

The literature can motivate a hypothesis about speech bandwidth, but it cannot substitute for a YazSes experiment.

**Needed experiment:** within-subject typing vs. dictation, same tasks, final corrected output, entry rate, correction time, error cost, subjective workload, and learning effects.

---

### C-HCI-02 — Dysfluency-Friendly Mode benefits people who stutter or have dysarthria

**Status:** OPEN FOR USER BENEFIT; TECHNICAL FILTER GATE SUPPORTED

**Supported technical result:** on the repository's small test set, false collapse = 0/33 and recall = 92.9% on 28 dysfluent clips.

**Not supported:** clinical/accessibility benefit, usability, or generalization across speakers.

**Needed study:** participant evaluation and/or external representative corpus.

---

### C-HCI-03 — hold-to-talk is superior to toggle/always-on interaction

**Status:** HYPOTHESIS / DESIGN RATIONALE

The HCI literature and privacy boundary support the design decision, but YazSes has not run a controlled comparison of activation modes.

---

## F. Candidate manuscript headline claims

These are the strongest claims currently ready to anchor the abstract/results:

1. **A shared offline CPU harness produces materially different robustness conclusions on hard speech than clean speech alone.**
2. **Repeated `large-v3` failures in the measured dictation workload are driven by variable insertions/runaway continuation rather than substitutions.**
3. **Previous-text conditioning is checkpoint-dependent and can trade a small average benefit on smaller models for rare catastrophic repetition on a larger checkpoint.**
4. **Cross-platform numeric variation exists but is checkpoint-dependent, so third-decimal WER claims should not be transported blindly across hardware.**
5. **The original meeting clustering default failed catastrophically on real annotated meetings, and real-data measurement changed the shipped operating point.**
6. **A four-speaker clustering cap greatly improves count correctness, but does not establish a diarization-error benefit.**
7. **Several intuitive interventions—synthetic onset silence, generic CPU streaming, and simple centroid merge—do not survive direct measurement.**
8. **Preserving contradictory reruns and full provenance changed the scientific interpretation and should be treated as part of the evaluation method.**

## G. Claims that need a literature search before “novel/first” language

Before submission, assign a related-work owner to verify:

- reports of faster-whisper/CTranslate2 repeated decode instability;
- previous-text conditioning causing repetition loops in Whisper-family models;
- insertion-only variance under temperature fallback;
- CPU cross-engine comparisons among Whisper, Parakeet TDT, and Moonshine;
- diarization threshold domain transfer and speaker-count constraint interactions;
- negative results on CPU local-agreement streaming in interactive dictation.

Until then, use “we observe,” “we measure,” “in our experiments,” and “to our knowledge” only after explicit verification.