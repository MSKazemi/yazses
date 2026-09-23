# YazSes paper v2 — research synthesis and writing package

**Status:** working research plan, 2026-09-20  
**Baseline paper:** *YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk Voice-Dictation System*, arXiv:2607.28878 v1 (2026-07-30)  
**Evidence window synthesised here:** primarily the 2026-08-23–2026-08-26 measurement campaign, including the rented Azure CPU runs and the follow-up analyses already archived under `paper/results/`.

This directory is the starting point for a second manuscript/revision. It does not replace the benchmark archive. The JSON artifacts remain the evidence; these files say what can be concluded from them, what changed relative to the first paper, what should be written next, and what must not be claimed.

## Read this package in this order

1. **[RESULTS_DELTA.md](RESULTS_DELTA.md)** — what is genuinely new relative to arXiv v1, with the key numbers and explicit supported/qualified/refuted status.
2. **[AZURE_CAMPAIGN.md](AZURE_CAMPAIGN.md)** — reconstruction of the August measurement campaign: machines, corpora, experiment sequence, evidence hierarchy, and provenance rules.
3. **[CLAIM_LEDGER.md](CLAIM_LEDGER.md)** — candidate manuscript claims mapped to exact result artifacts and their current evidentiary strength.
4. **[MANUSCRIPT_PLAN.md](MANUSCRIPT_PLAN.md)** — paper thesis, research questions, contribution framing, section plan, tables/figures, statistical rules, future work, and submission gates.

## What changed since the first paper

The first paper established that the hold-to-talk system works offline on a commodity Linux laptop and measured three Whisper checkpoints on 200 LibriSpeech `test-clean` utterances. Its own limitations named the next work: one machine, one operating system in the evaluation, clean read English, exploratory streaming, no user study, and incomplete end-to-end validation on macOS/Windows.

The August campaign changes the empirical picture substantially:

- the evaluation now compares **eight engine/checkpoint combinations** through the shipping engine seam, rather than three Whisper checkpoints;
- the same engine matrix was run on both **`test-clean` and `test-other`**, exposing robustness differences hidden by clean speech;
- repeated decodes exposed a **run-to-run reproducibility failure in `large-v3`**, and follow-up probes isolated the error to variable insertions / runaway continuation rather than substitutions;
- the effect of `condition_on_previous_text` was measured across `base.en`, `small.en`, `medium.en`, and `large-v3`, showing that one decoder setting changes sign with checkpoint size;
- the same benchmark path now has archived results across Linux x86-64, Linux arm64, macOS arm64, and Windows x86-64;
- Meeting Mode was evaluated on the **full 16-recording AMI test split**, giving a real annotated diarization result instead of a synthetic-only story;
- several product assumptions were tested directly, including pre-speech padding, streaming, beam width, speaker-count constraints, and cluster-centroid repair. Some were supported, several were qualified, and some were refuted.

This is a better scientific story than “v1 plus more features.” The paper should be organised around **what survives measurement, what fails, and how those failures changed the system**.

## Recommended central thesis

> A privacy-first offline voice-input system cannot be evaluated by a single WER on clean speech. Robust deployment depends on model-specific failure modes, run-to-run reproducibility, audio difficulty, hardware/ISA variation, and task-specific post-processing; measuring those dimensions changes both the recommended model configuration and the product defaults.

That thesis is supported by the repository evidence. It is also narrower and safer than claiming a universal “best ASR model” or a completed usability result.

## Candidate paper identity

Three defensible title directions:

- **YazSes v2: Reproducible Offline Voice Input Across Engines, Hardware, and Meeting Conditions**
- **When Bigger ASR Models Fail to Stop: Reproducibility and Robustness in Offline Dictation**
- **From Clean Dictation to Real Meetings: A Reproducible Evaluation of Offline Voice Input**

The first is the best fit for an arXiv v2 that remains recognisably the YazSes systems paper. The second is stronger for a focused measurement paper if the decoder-reproducibility section is expanded with additional independent corpora and library versions. The third fits a broader systems/HCI evaluation if a human study is added.

## What is innovative here

Separate **measured contribution** from **novelty claim**.

### Measured contributions already supported by repository artifacts

1. A like-for-like CPU comparison of Whisper, Parakeet TDT, and Moonshine through the same shipping product seam, on clean and harder LibriSpeech splits.
2. A reproducibility analysis showing that `large-v3`'s repeated WER movement in this workload is driven by **insertions while substitutions, deletions, and hits remain fixed**.
3. A model-size-dependent study of previous-text conditioning: beneficial on `base.en`, smaller on `small.en`, byte-identical at `medium.en`, and associated with rare catastrophic repetition on `large-v3`.
4. Cross-ISA/OS decoding evidence showing model-dependent numerical sensitivity rather than a single “WER is portable” assumption.
5. Real-meeting diarization evidence on AMI showing a catastrophic domain mismatch in the former clustering default, and showing that a known speaker count reliably fixes the *count* but does not establish a DER improvement at the new threshold.
6. Negative results that matter to product design: synthetic pre-speech silence cannot restore audio that was never captured; streaming is not a general latency win on CPU; and the tested centroid-merge heuristic cannot repair split speakers without unacceptable real-speaker merges.

### Candidate novelty requiring a current literature review before submission

The repository alone cannot establish that a finding is the first in the literature. Before using words such as “novel”, “first”, or “previously unreported”, search specifically for:

- faster-whisper / CTranslate2 run-to-run non-determinism, temperature fallback, previous-text conditioning, repetition loops, and insertion variance on short utterances;
- comparative CPU robustness studies of Whisper, Parakeet TDT, and Moonshine under a shared harness;
- diarization cluster-threshold transfer across AMI / VoxConverse / synthetic meeting domains;
- work distinguishing rare catastrophic ASR failures from corpus-average WER in interactive dictation.

Until that review is complete, the manuscript should call these **observed failure modes**, **measurement findings**, or **systems contributions**, not literature-first claims.

## The decision: arXiv v2 or a separate new paper?

The current evidence is already sufficient for a materially stronger **arXiv v2 / expanded systems manuscript**. It closes or narrows several limitations named in v1 and adds a substantial reproducibility result.

A separate peer-reviewed paper becomes much stronger if it adds at least one genuinely new human-facing study:

- controlled within-subject typing vs. dictation including correction time and final text quality;
- real spontaneous microphone speech across rooms, microphones, accents, and noise;
- an accessibility study with participants from the populations the feature is intended to serve.

The existing `paper/benchmark/bench_throughput.py` is an instrument, **not a completed study**. The new manuscript must preserve that distinction.

## Evidence authority

Use this order when writing:

1. `paper/results/*.json` from stable benchmark harnesses;
2. derived `*-significance*.json` analyses that read those measurements;
3. promoted follow-up results under `paper/results/probes/` when replicated and methodologically necessary;
4. `paper/results/history/` only to explain displaced/repeated runs;
5. logs only as supporting provenance, never as the sole source of a headline number.

`docs/benchmarks.md` is the current human-readable interpretation. `paper/results/MANIFEST.md` is the artifact index. If prose and JSON disagree, the JSON plus provenance wins and the prose must be corrected.

## Non-negotiable writing rule

Every central sentence in the Results section should be reducible to:

> **claim → artifact → population/corpus → condition → uncertainty → caveat**

If one of those pieces is absent, the claim is not ready for the manuscript.


## Authorship, consent, and publication governance

The second paper uses an explicit three-gate publication protocol. Start with **[authorship/README.md](authorship/README.md)**.

The governing rule is intentionally strict: every person in the frozen contributor roster is invited, silence is not consent, and publication is blocked unless every candidate explicitly opts in and every confirmed author approves the same final manuscript fingerprint.

Supporting documents:

- **[authorship/CANDIDATE_AUTHOR_ROSTER.md](authorship/CANDIDATE_AUTHOR_ROSTER.md)** — 29-person seed roster derived from the project's public contributor records; must be reconciled again at the final authorship cutoff.
- **[authorship/COMMUNICATION_TEMPLATES.md](authorship/COMMUNICATION_TEMPLATES.md)** — public/private invitation text, metadata form, reminders, draft-review messages, final approval request, withdrawal handling, and publication notice.
- **[authorship/APPROVAL_PROTOCOL.md](authorship/APPROVAL_PROTOCOL.md)** — per-author state machine, immutable source/PDF fingerprint, approval evidence rules, invalidation and reapproval triggers, withdrawal handling, and audit summary.
- **[authorship/ARCHIVE_ORG_PUBLICATION_CHECKLIST.md](authorship/ARCHIVE_ORG_PUBLICATION_CHECKLIST.md)** — pre-upload, Internet Archive metadata/file checks, post-upload verification, and corrected-version procedure.

Private contact emails and raw consent evidence belong in an access-controlled registry outside this public repository. The repository records the process, public-safe author metadata, manuscript fingerprints, and aggregate approval state.
