# ADR-033 — A reproducibility gate for offline ASR comparisons (proposed)

**Status:** Proposed — 2026-11-03; **no runtime, model default, publication or implementation authorization**  
**Decision owner:** YazSes maintainer (pending review)  
**Research:** [#793](https://github.com/MSKazemi/yazses/issues/793), [2026-11-03 protocol](../research/2026-11-03-pinned-offline-asr-evaluation-protocol.md)  
**Context:** [ADR-030](adr-030-agent-era-direction.md), [ADR-021](adr-021-invest-in-error-cost.md), [ADR-011](adr-011.md), [ADR-019](adr-019-egress-inventory-and-escalation.md), [engine/default decision #645](https://github.com/MSKazemi/yazses/issues/645), [ASR epic #787](https://github.com/MSKazemi/yazses/issues/787)

## Context

YazSes currently has three offline STT backends (faster-whisper, Parakeet, Moonshine), a public community WAV/TXT benchmark script, and published historical multi-engine results. Its published benchmark page explicitly distinguishes the single-utterance community smoke test from the historical 200-utterance evaluation and says the primary historical harness and row-level artifacts are held outside the public repository. The community harness does not yet produce complete pinned, scored, per-sample results suitable for a third-party rerun.

The factory can transparently fall back to faster-whisper if an optional backend fails to load; this is appropriate for dictation availability but makes a benchmark invalid unless the *resolved* engine is asserted. The script can also skip an unreadable input and scores under a different text normalizer if whisper-normalizer is missing. Decode RTF and p50/p95 by themselves do not measure user release-to-final latency. These facts motivate a **research evaluation policy**, not an engine change.

## Proposed decision (review required)

Establish **protocol v1** in the linked research document as the common gate before YazSes publishes **new cross-engine or default-engine comparative conclusions**:

1. Each model evaluation must pin exact YazSes commit, candidate and resolved engine/model identity, model weight digest, dependency/runtime versions, CPU and OS, decoder settings, corpus and split manifest, and normalization profile.
2. A public candidate score must be reproducible from public benchmark source and licensed-public/synthetic per-sample result evidence. A private archive may be referenced as historical evidence but cannot replace this gate for new comparative claims.
3. Per-sample failures and fallback are first-class data; they cannot disappear from the denominator or become scored output from a different engine.
4. Report matched-corpus WER/CER and S/D/I, language/script preservation, repeatability, per-condition coverage, and speaker/group-block **paired** uncertainty. Report WER on the designated completed cohort and failures/coverage separately. Distinguish clean/read, spontaneous, multilingual, synthetic and user-study evidence.
5. Report warmed decode separately from cold model load, key-release-to-final, safe-sink delivery time, p50/p95 and sampled peak RSS; label unmeasured or unsupported metrics explicitly. Only claim energy when instrumented; otherwise label CPU time a compute proxy.
6. All benchmarking requires explicit authorized local dataset/model preparation, verified offline execution and no automated upload of user audio, transcripts or sensitive metadata. Engineering QA, synthetic work and participant research must keep their different evidentiary/consent classes.
7. The method is read-only with respect to product architecture: **no new default, model download, engine integration, telemetry, or release commitment**. A change under #645 / #798 needs an independent accepted decision consistent with ADR-030.

Provisional engineering margins in the research report are open discussion inputs, not approved pass/fail thresholds and not claims about user preferences.

## Alternatives

### A. Continue with one WER leaderboard and informal laptop measurements
**Reject.** Incorrect normalizer/fallback identity, incomplete samples, corpus overlap and unreported latency tails can reverse the ranking. These measurements are useful exploratory signals, not a reproducible platform-agnostic decision.

### B. Make the existing private historical harness the exclusive source of truth
**Reject as a policy for future public comparisons.** Existing historical data remains valuable and may be accurately quoted, but external researchers cannot independently inspect its executable version and per-sample result archive from a public YazSes checkout. No obligation to publish private archives, user data or restricted audio is created.

### C. Replace the installed speech engine immediately based on present historical WER
**Defer.** #645 is the canonical default-engine delivery decision and ADR-030 requires measuring user-visible costs and failure honesty first. Historical Parakeet/Whisper comparisons do not settle every hardware, language or latency condition.

### D. Add production telemetry to collect live error rates
**Reject.** Not necessary for public/synthetic reproducible research and contrary to the zero-telemetry offline boundary.

### E. Adopt a pinned, offline, public-result benchmark gate (this proposal)
**Recommend adopting as a documentation/research standard after review.** Reuses shipping engine seams and existing tests; requires a small independent evaluation/analyzer implementation, not a feature expansion.

## Consequences if accepted

**Benefits:** attributable comparisons, independent replication, safer model recommendations, honest unsupported cases, publication-ready provenance, a common measure across #792/#793/#796/#797/#798.

**Costs:** preparing manifests, verifying licences and weight hashes, multiple hardware runs, private-source exclusions, and statistical uncertainty that may yield “inconclusive.” Some past headline numbers remain historical rather than meeting this future standard.

**Non-goals:** no benchmark result produced by this ADR; no retroactive claim that existing published results were fabricated; no public participant corpus; no cloud inference; no new ASR API; no CI downloading gigabytes of models.

## Acceptance questions for the decision owner

- Do we agree to require immutable corpus/model provenance, exact resolved backend, public per-sample *error counts* and a public deterministic analyzer for **future** comparative claims?
- Which English corpus and primary cost metric best represent the initial user decision: normalized WER, release-to-final p95, or an error-cost-weighted pre-registered pair?
- Are provisional +0.5 percentage-point WER non-inferiority and 20% p95 improvement useful starting discussion margins, or should they remain entirely unspecified until user-workflow data exist?
- Which actual CPU hardware will rerun the same pinned manifest, and what unsupported cells must be kept as N/A?

## Follow-up if accepted

- #793: freeze v1 schema, preregistration, synthetic pure analyzer and its tests, exact corpus sample ID manifests; run local English pilots and report negative results.
- #792/#794/#795: candidate provenance/quantization/hardware details before adding arms.
- #796: streaming and hesitation replay using distinct UX metrics.
- #797: per-language/locale evaluation protocol, script preservation and leakage register.
- #798/#645: deliberate adoption/defer/reject decision on new runtime/default **only after** measured matched evidence; record an ADR-030 amendment if the breadth freeze requires it.

## Status and provenance

Research and architectural reasoning from current repository docs and code as of main commit 1598e65b708b86c2f8d5fa51749407e4a18740be, 2026-11-03. **No benchmarks have been executed for this ADR**; no user/participant audio acquired; no code or default changed. Status remains **Proposed**, not Accepted. 
