# Paper v2 status — results, gaps, and execution map

**Updated:** 2026-09-23  
**Programme issue:** [#510](https://github.com/MSKazemi/yazses/issues/510)  
**Authorship/publication operations:** [#484](https://github.com/MSKazemi/yazses/issues/484)

This page is the short operational view of the second YazSes paper. It does not replace the detailed
[result delta](RESULTS_DELTA.md), [claim ledger](CLAIM_LEDGER.md),
[Azure campaign record](AZURE_CAMPAIGN.md), or [manuscript plan](MANUSCRIPT_PLAN.md).

## Current paper direction

The next paper should be an **expanded empirical systems paper**, not a feature changelog.

Working thesis:

> A privacy-first offline voice-input system cannot be evaluated by one WER on clean speech.
> Harder audio, repeated decoding, decoder settings, hardware/ISA variation, and task-specific
> failure modes materially change the engineering conclusions.

Current evidence is already strong enough for a materially expanded arXiv revision after a final
evidence freeze. A stronger conference/journal submission should add human-facing and external-
validity studies.

## Strongest new results since paper v1

| Finding | Current evidence |
|---|---|
| Shared local-ASR comparison | Eight engine/checkpoint configurations measured through the shipping product seam. On the Azure clean-speech matrix, Parakeet TDT 0.6B v2 has the lowest point-estimate WER at **2.06%**; Moonshine/tiny has the lowest measured RTF at **0.016**. Intervals and host-specific timing caveats still apply. |
| Harder speech changes the picture | Parakeet moves **2.06% → 2.88%** from `test-clean` to `test-other`; `base.en` moves **4.01% → 9.46%**; Moonshine/base **3.17% → 8.04%**. Clean speech alone does not characterise robustness. |
| `large-v3` repeated-decode failure | In repeated hard-split runs, substitutions stay at **87**, deletions at **15**, hits at **3619**, while insertions move **101 → 184**. The measured WER movement is a continuation/insertion tail failure, not changing recognition substitutions. |
| Previous-text conditioning is checkpoint-dependent | On the measured ladder it helps `base.en`, helps `small.en` slightly, is byte-identical at `medium.en`, and disabling it removes the observed `large-v3` runaway mode. This is not evidence that disabling context universally improves WER. |
| Greedy decoding has a measurable cost on the default model | `base.en`: beam 1 vs beam 5 is **4.39% vs 4.01%** on clean speech and **10.56% vs 9.46%** on hard speech; the hard-split paired comparison is significant in the archived analysis. |
| Cross-platform decode variation is measured | On the 60-utterance common subset, `tiny.en` spans **3.39–3.88%**, `base.en` **3.25–3.39%**, while `small.en` is **2.05% on all four measured runners**. Decode portability is still different from full end-to-end OS validation. |
| Synthetic onset silence does not recover missed speech | No tested lead-in value establishes a corrected paired benefit over no lead-in. Audio not captured before activation cannot be reconstructed by prepending silence afterward. |
| Streaming is conditional, not automatically faster | Current documented rerun: `tiny.en` final latency **0.92 → 1.22 s** with streaming while exposing substantial partial text; `base.en` **1.42 → 2.21 s** with **0% median visible at release**. |
| Real-meeting diarization changed the shipped default | Full AMI test split: old threshold 0.5 gives **75.21% mean DER** and extreme over-splitting; current meeting threshold 1.2 gives **26.71% mean DER**, **27.37% time-weighted DER**. |
| Knowing speaker count is not the same as better DER | At the current threshold, 7 meetings improve, 7 worsen and 2 are unchanged when the exact count is supplied; sign test **p=1.0**. The count itself becomes reliable, but a DER benefit is not established. |
| One diarization threshold does not transfer across domains | Approximate preferred regions differ: synthetic **0.8–0.9**, VoxConverse **~0.9**, AMI **~1.2**. |
| Simple centroid repair failed | No useful cosine threshold repairs enough split-speaker clusters without unacceptable wrong-person merges. This negative result should remain visible. |
| Provenance/history changed the science | Retaining displaced contradictory runs, exact commands and corpus identity turned an apparent benchmark disagreement into the `large-v3` reproducibility investigation instead of silently overwriting it. |

## September follow-up that narrows an August interpretation

A later `tiny.en` follow-up decoded the same 60 `test-clean` utterances five times and produced
**byte-identical hypotheses at 3.67% WER in all five runs**.

Therefore:

- `large-v3` is the strong corpus-level repeated-decode instability result;
- `tiny.en` should **not** be described as generally corpus-level unstable;
- rare clip-level fallback instability can still exist, but the paper must keep that claim narrow.

The detailed wording is already corrected in [RESULTS_DELTA.md](RESULTS_DELTA.md).

## What is ready now

- [x] August Azure campaign reconstructed with provenance and corpus roles.
- [x] v1 → v2 result delta documented.
- [x] Claim ledger separates supported, qualified, open and withdrawn claims.
- [x] Full manuscript architecture and threats-to-validity plan exists.
- [x] Authorship/consent/final-approval protocol exists.
- [x] Scientific follow-up work is split into issue-sized work packages.
- [x] September `tiny.en` follow-up incorporated into the interpretation.

## Required work for the arXiv-v2 evidence freeze

- [ ] [#495](https://github.com/MSKazemi/yazses/issues/495) — freeze and rerun the core ASR engine matrix.
- [ ] [#496](https://github.com/MSKazemi/yazses/issues/496) — replicate the `large-v3` insertion/runaway result on a second corpus and CPU.
- [ ] [#507](https://github.com/MSKazemi/yazses/issues/507) — verify novelty and update related work.
- [ ] [#508](https://github.com/MSKazemi/yazses/issues/508) — generate manuscript tables/figures directly from committed result artifacts.
- [ ] Freeze exact manuscript evidence commit, commands, lockfile and result manifest.
- [ ] Re-run consistency/claim guards before final numbers are copied into the private manuscript.

## Strongly recommended additions for a conference/journal submission

- [ ] [#498](https://github.com/MSKazemi/yazses/issues/498) — controlled typing-vs-dictation human study.
- [ ] [#500](https://github.com/MSKazemi/yazses/issues/500) — consented spontaneous-microphone robustness evaluation.
- [ ] [#502](https://github.com/MSKazemi/yazses/issues/502) — far-field meeting diarization evaluation.
- [ ] [#504](https://github.com/MSKazemi/yazses/issues/504) — full end-to-end Windows/macOS validation.
- [ ] [#506](https://github.com/MSKazemi/yazses/issues/506) — CPU core-seconds and energy/battery measurements.

These are scientific evidence tasks. They are separate from authorship/publication approval.

## Publication/governance track

Follow [#484](https://github.com/MSKazemi/yazses/issues/484) and
[authorship/](authorship/):

1. freeze the contributor/candidate roster;
2. collect explicit authorship opt-in and metadata;
3. circulate one review draft to all confirmed authors;
4. resolve requested changes;
5. freeze source commit + final PDF hash;
6. receive unanimous approval of the same final fingerprint;
7. publish only the approved artifact.

Private emails, private consent messages, participant data and raw approval evidence stay outside
public Git.

## Evidence rules

For every central result, require:

> **claim → artifact → corpus/population → condition → uncertainty → caveat**

Do not:

- turn a point-estimate ranking into statistical superiority without evidence;
- call LibriSpeech `test-other` “real-world dictation”;
- attribute `large-v3` instability to host load without a causal experiment;
- claim disabling previous-text conditioning generally lowers WER;
- call streaming universally faster;
- infer full cross-platform interaction from decode-only artifacts;
- claim known speaker count improves DER at the current threshold;
- call the current AMI DER state of the art;
- use “first” or “novel” until [#507](https://github.com/MSKazemi/yazses/issues/507) verifies the literature.

## Definition of paper-v2 readiness

The manuscript is evidence-ready when:

- the central result matrix is frozen and reproducible;
- the `large-v3` tail claim is independently replicated or explicitly kept workload-specific;
- every headline figure/table regenerates from public JSON;
- the claim ledger reflects the final evidence;
- novelty wording has a current literature check;
- threats to validity are explicit;
- no withdrawn claim survives in the abstract/conclusion.

Publication readiness is a separate gate governed by the authorship protocol and #484.
