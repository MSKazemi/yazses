# Results delta — what paper v2 has that arXiv v1 did not

This file answers one question: **what new empirical result exists now that was not in the 2026-07-30 v1 paper?**

The comparison is intentionally conservative. A result is called *new* only when the repository now contains an archived measurement or analysis that goes beyond the v1 evaluation. Product features added after v1 are not automatically research results.

## 1. Baseline: what v1 actually measured

arXiv v1 evaluated one commodity Linux laptop (Intel i7-1370P, Ubuntu 24.04, CPU/int8), using a deterministic 200-utterance, 40-speaker LibriSpeech `test-clean` subset. The headline Whisper results were:

| checkpoint | v1 WER |
|---|---:|
| `tiny.en` | 4.82% |
| `base.en` | 4.07% |
| `small.en` | 2.59% |

v1 also reported latency/memory, command grammar, a small VAD test, and the dysfluency filter gate. Its limitations explicitly included one evaluated machine/OS, clean read English, exploratory streaming, and no user study.

That is the comparison point below.

## 2. New engine matrix: eight configurations under one product path

**New evidence:** `paper/results/wer.json` and `paper/results/wer-test-other.json`.

On the Azure `Standard_D16s_v6` measurement host (16-vCPU Xeon Platinum 8573C, Ubuntu 24.04, CPU/int8), the shipping engine factory was used for all rows.

### `test-clean`, 200 utterances

| engine / checkpoint | WER | 95% CI | RTF |
|---|---:|---:|---:|
| Parakeet TDT 0.6B v2 | **2.06%** | 1.54–2.68 | 0.050 |
| Whisper `small.en` | 2.66% | 2.05–3.28 | 0.092 |
| Moonshine base | 3.17% | 2.49–4.02 | **0.023** |
| Whisper `large-v3` | 3.23% | 1.95–5.00 | 0.451 |
| Whisper `medium.en` | 3.28% | 2.09–5.01 | 0.246 |
| Whisper `base.en` | 4.01% | 3.21–4.87 | 0.042 |
| Moonshine tiny | 4.20% | 3.42–5.06 | **0.016** |
| Whisper `tiny.en` | 5.18% | 4.22–6.31 | 0.028 |

**What is supported:** the product can compare multiple local engines through one harness; Parakeet has the lowest point-estimate WER on this sample; Moonshine is much faster on this CPU.

**What is not supported:** “Parakeet is statistically better than `large-v3`.” Their intervals overlap substantially. Also do not transport the RTF values to another CPU.

**Correction to prior documentation:** Parakeet is about 1.8× the measured speed of `small.en` here, not the ~4× previously inherited from a vendor comparison.

## 3. Harder audio changes the story

**New evidence:** `paper/results/wer-test-other.json`.

Same harness, same Azure host, 200 LibriSpeech `test-other` utterances, 33 speakers, about 23.4 minutes.

| engine / checkpoint | clean WER | hard WER | hard/clean |
|---|---:|---:|---:|
| Parakeet TDT 0.6B v2 | 2.06% | **2.88%** | **1.4×** |
| Whisper `large-v3` | 3.23% | 4.86% / **7.69%** | 1.5× / 2.4× |
| Whisper `medium.en` | 3.28% | 5.51% | 1.7× |
| Whisper `small.en` | 2.66% | 5.59% | 2.1× |
| Moonshine base | 3.17% | 8.04% | 2.5× |
| Whisper `base.en` | 4.01% | 9.46% | 2.4× |
| Moonshine tiny | 4.20% | 10.35% | 2.5× |
| Whisper `tiny.en` | 5.18% | 11.61% | 2.2× |

**New conclusion:** clean-speech WER is not enough to characterise robustness. Parakeet degrades least in this comparison; several models roughly double their error rate.

**Important caveat:** `test-other` is still read audiobook speech. It is harder than `test-clean`, but it is not spontaneous desk dictation, accented field audio, or a noisy far-field microphone. Do not call these values “real-world dictation WER.”

## 4. Repeated decoding exposed a reproducibility failure

**New evidence:** `paper/results/probes/largev3-instability-test-other.json`, the `decode-determinism-*.json` family, and `decode-mechanism-*.json`.

The August full-matrix reruns showed movement in `large-v3` and small shifts in `tiny.en`, while `base.en`, `small.en`, `medium.en`, Parakeet, and both Moonshine rows were stable in those matrices. A later September follow-up narrows that interpretation: `paper/results/probes/decode-determinism-tiny.en-test-clean-baseline.json` decoded the same 60 `test-clean` utterances five times with `tiny.en` and obtained byte-identical hypotheses and 3.67% WER on every run. Therefore paper v2 should treat `large-v3` as the reproducible corpus-level instability finding; `tiny.en` has evidence of rare clip-level fallback instability, but not a general repeated-corpus instability under every sampled condition.

For `large-v3` on `test-other`, five observed WERs include:

- 5.46%
- 6.07%
- 6.53%
- 6.61%
- 7.69%

Across those repeated decodes:

- substitutions stayed at **87**;
- deletions stayed at **15**;
- hits stayed at **3619**;
- insertions moved from **101 to 184**.

Therefore the measured WER spread is not a change in which spoken words are recognised. It is variation in **extra emitted text**. The evidence supports the narrower statement:

> In this workload, `large-v3` is reproducible in substitutions/deletions but not in stopping; insertion count drives the run-to-run WER movement.

Do **not** claim that high host load caused the 7.69% run. That run had unusually high load and is an extreme, but the comparable-load repeats still span 5.46–6.61%, so variance remains without that explanation.

## 5. Previous-text conditioning changes sign with model size

**New evidence:** `paper/results/probes/decode-determinism-*.json` and `decode-mechanism-*.json`.

On `test-other`:

| checkpoint | conditioning ON | conditioning OFF | current reading |
|---|---:|---:|---|
| `base.en` | **9.46%** | 9.81% | conditioning helps |
| `small.en` | **5.59%** | 5.70% | small benefit |
| `medium.en` | 5.51% | 5.51% | byte-identical |
| `large-v3` | 4.84–6.21%, 5 distinct | **3.82%, 1 distinct** | OFF removes runaway repetitions in these runs |

The corpus-average `large-v3` gain from disabling conditioning is **not statistically established as a mean WER improvement**: the paired difference is about 1.05 points with a 95% interval of [-2.59, +0.16], more utterances get worse than better, and 95.7% of the aggregate gain is carried by three clips.

The defensible claim is different and more interesting: disabling previous-text conditioning removed the **rare catastrophic repetition mode** in this measured condition. It is a tail-risk result, not a “one point better WER” result.

Also, setting `temperature=0.0` is not a fix. On measured conditions it can remove the fallback rescue and cause severe failures; e.g. 15.26% for `large-v3` on the hard split in the 2×2 experiment.

## 6. Cross-platform / ISA variation is now measured

**New evidence:** `paper/results/platforms/`.

Same 60-utterance subset and CTranslate2 4.8.1:

| checkpoint | Linux x86-64 | Linux arm64 | macOS arm64 | Windows x86-64 | spread |
|---|---:|---:|---:|---:|---:|
| `tiny.en` | 3.39% | 3.60% | 3.74% | 3.88% | 0.49 |
| `base.en` | 3.32% | 3.32% | 3.25% | 3.39% | 0.14 |
| `small.en` | 2.05% | 2.05% | 2.05% | 2.05% | 0.00 |

This directly improves on v1's single-Linux-machine evaluation.

**Scope limit:** this is a decode benchmark, not a full proof of hotkey → microphone → decode → injection on every OS. The new paper must not convert cross-platform decode evidence into an end-to-end GUI/input validation claim.

The companion resolver experiment (`paper/results/platform-resolution.json`) tests 92 installation target combinations and records 84 that resolve, while exposing real and environment-version-specific packaging limits.

## 7. Beam width: greedy decoding has a measurable cost on the default model

**New evidence:** `paper/results/beam-test-*.json` and paired `*-significance*.json`.

For `base.en`:

- clean: beam 1 = 4.39%, beam 5 = 4.01%; paired difference 0.386 points, 95% CI [0.069, 0.726], p=0.0192;
- hard: beam 1 = 10.56%, beam 5 = 9.46%; paired difference 1.102 points, 95% CI [0.305, 2.196], p=0.001.

Beams 2, 3, 5, and 8 are not shown to differ meaningfully from each other on the hard split when paired against beam 2; e.g. beam 2 vs beam 5 differs by 0.027 points with p=0.964.

**Conclusion:** the major distinction is greedy vs. a modest beam on `base.en`; “more beam is always better” is not supported. On `small.en` clean speech, beam 1's point estimate is slightly better than beam 5, but its interval crosses zero (p=0.1474).

## 8. Pre-speech synthetic silence does not recover missed speech

**New evidence:** `paper/results/onset.json` and `paper/results/onset-significance.json`.

The experiment trims natural lead-in, clips 0/40/120/240 ms of actual speech, and prepends 0/100/300/600/1000 ms of synthetic silence. The outcome is first-word correctness on 200 `test-clean` utterances.

Key result:

- when onset is intact, the shipped 300 ms padding does not show a measurable benefit over no lead-in;
- once real speech is clipped, no amount of prepended silence can reconstruct it;
- none of the 16 tested lead-in comparisons survives multiplicity correction;
- two replicated uncorrected p<0.05 cells at 120 ms clipping go in the **harmful** direction for very long lead-ins.

This refutes the product rationale that synthetic leading silence can “give back” a first word already missed by capture. It also validates the privacy boundary: the mechanism that could genuinely recover pre-key audio would require retaining real microphone audio while the key is up.

## 9. Streaming is not a general CPU latency improvement

**New evidence:** `paper/results/streaming.json` plus the current benchmark re-runs documented in `docs/benchmarks.md`.

The archived n=15 real-time-fed experiment shows the same qualitative failure that motivated the current default:

- `tiny.en` can produce useful partial text before release;
- `base.en` often cannot keep its rolling decode ahead of incoming audio;
- streaming makes final text slower because commit still performs a final decode while the partial loop has consumed CPU.

The currently documented re-run reports speech-end→final text moving from **0.92 s to 1.22 s on `tiny.en`** and from **1.42 s to 2.21 s on `base.en`**, with **72% median text visible at release on `tiny.en` and 0% on `base.en`**.

This is a useful negative result: “streaming” is not automatically “lower perceived latency” on CPU. The claim is checkpoint- and compute-budget-dependent.

## 10. Real meeting diarization: the former default was catastrophically wrong

**New evidence:** `paper/results/diarization-ami16_corpus-der.json`, `diarization-ami16_corpus-maxspk4.json`, significance analysis, and ADR-v2-133.

Full AMI test split:

- 16 recordings;
- 543.7 minutes of real four-person meetings;
- 30,714 s (8.5 h) of scored reference speech;
- human RTTM reference;
- sherpa-onnx diarization backend.

| configuration | DER, per-recording mean | speaker-count error | exact count |
|---|---:|---:|---:|
| old threshold 0.5, estimated count | **75.21%** | **+155.19** | 0/16 |
| old threshold 0.5, exact count supplied | 29.42% | +0.06 | 16/16 |
| current meeting threshold 1.2, estimated count | **26.71%** | +2.06 | 2/16 |
| threshold 1.2, exact count supplied | 29.42% | +0.06 | 16/16 |

The time-weighted DER for the current unpinned run is **27.37%** (20.51% with a 250 ms collar). Use the time-weighted figure when comparing with published diarization papers; use the per-recording mean when discussing the experience of a typical meeting.

The defensible finding is that the old `0.5` clustering threshold was a severe domain mismatch for long meetings, primarily producing speaker confusion through extreme over-splitting.

## 11. “Knowing the number of speakers improves DER” is not established at the new threshold

A previous interpretation compared 26.71% vs. 29.42% and called the supplied count worse. That comparison was invalid because the two runs had also changed the threshold.

The properly paired comparison at threshold 1.2 finds:

- 7 recordings improved, 7 worsened, 2 unchanged;
- exact sign test p = **1.0**;
- mean ΔDER +2.71 with 95% CI **[-1.64, +7.60]**;
- time-weighted ΔDER +1.96 with 95% CI **[-3.39, +7.69]**.

So the sample cannot resolve a DER effect.

What the supplied count **does** reliably buy is the count itself: 16/16 exact instead of 2/16. That is a product/use-case distinction worth publishing.

## 12. One clustering threshold does not transfer across domains

The threshold sweeps show different optima:

- synthetic meetings: about 0.8–0.9;
- VoxConverse: about 0.9;
- AMI: about 1.2.

At AMI's preferred 1.2, crowd-scene VoxConverse recordings are under-counted badly. This supports feature-specific defaults and warns against presenting a single threshold as a universal diarization constant.

## 13. Centroid-based post-hoc merge: a useful negative result

**New evidence:** `paper/results/centroid-merge-ami16_corpus-{meeting,recimport}.json` and `paper/benchmark/analyze_centroid.py`.

The follow-up asked whether cluster centroid cosine similarity could repair a real speaker split into multiple clusters without merging different people. On the measured AMI data there is no safe threshold that provides useful recall without unacceptable wrong merges.

For the meeting-profile subset, a very conservative threshold can reach 100% precision only by repairing a small fraction of splits; relaxing it rapidly introduces wrong-person merges. The analysis deliberately concludes that this simple centroid rule **does not work on this data** and should not be tuned into production.

This is exactly the kind of negative result worth keeping in v2: the campaign did not merely optimise until every idea looked successful.

## 14. What remains open from v1

The August campaign is predominantly a technical measurement campaign. It does **not** close these important limitations:

- no controlled user study of dictation vs. typing including correction cost;
- no representative spontaneous microphone corpus across accents, rooms, and noise;
- no study with dysarthric/stuttering participants for Dysfluency-Friendly Mode;
- no longitudinal study of personalization/learning;
- no full end-to-end macOS/Windows interaction study covering hotkey, capture, injection, recovery, and accessibility;
- no GPU study and no systematic energy/battery study.

Those are future-work items, not missing prose. Do not write around them.
