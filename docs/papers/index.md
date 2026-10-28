---
title: YazSes papers — the research behind the software
description: The two research papers by the YazSes author - the system paper (arXiv 2607.28878) and the measurement study of silent failures in on-device speech recognition - with abstracts, citation details and the final PDF.
---

# Papers

Two papers describe YazSes. Both are by the project's author, and both are preprints: they
have not been peer reviewed.

## 1. The system

**YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk Voice-Dictation System**
Mohsen Seyedkazemi Ardebili · arXiv:2607.28878

- Landing page and PDF: [arxiv.org/abs/2607.28878](https://arxiv.org/abs/2607.28878)
- DOI: [10.48550/arXiv.2607.28878](https://doi.org/10.48550/arXiv.2607.28878)

## 2. The measurement study

**Silent Failures in On-Device Speech Recognition: A Measurement Study of CPU Dictation and
Long-Form Meeting Transcription**
Mohsen Seyedkazemi Ardebili · October 2026 · 29 pages

- **PDF:** [yazses-silent-failures-measurement-study-2026-10.pdf](yazses-silent-failures-measurement-study-2026-10.pdf)
- Status: preprint, not peer reviewed. The arXiv posting is pending; when it is public, cite
  the arXiv version and this page will link it.
- Every number in the paper is generated from the JSON artifacts in
  [`paper/results/`](https://github.com/MSKazemi/yazses/tree/main/paper/results) (index:
  [`MANIFEST.md`](https://github.com/MSKazemi/yazses/blob/main/paper/results/MANIFEST.md)),
  and the harness is in
  [`paper/benchmark/`](https://github.com/MSKazemi/yazses/tree/main/paper/benchmark). The
  manuscript source itself is not published.

**Abstract.** On-device speech recognition has no provider to monitor its output or offer a second opinion. We measure a shipping open-source dictation and meeting-transcription system and report failures that return successfully and are poorly summarised by one corpus word error rate (WER). On 200 LibriSpeech test-other utterances, 10 default-configuration decodes of Whisper large-v3 on one machine type span 4.84-7.69% WER, so one decode cannot rank it against smaller checkpoints. In every archived large-v3 run the aggregate substitution and deletion counts are identical and only insertions move. Disabling the temperature fallback made the output deterministic but raised WER to 15.26%, so it is not a fix. Disabling conditioning on previous text appears to lower WER by 1.7 points, but paired per utterance the gain is 1.05 points with an interval spanning zero; three clips account for 95.7% of the 47 errors removed (gross, before 8 errors added elsewhere). Beam-width conclusions did not transfer across the cells tested, and LibriSpeech cross-family comparisons are confounded by training-data overlap. On 16 AMI meetings diarization error is 26.71% (27.37% time-weighted; threshold tuned on the same corpus); fixing the speaker count gave no resolvable difference. A 41-minute meeting was reported as successfully transcribed although its transcript was dominated by one repeated phrase. A preliminary live-versus-batch word-count check flagged it (16.0x, against 1.008x on one healthy meeting); the check was fitted and assessed on the same five meetings, with counts for two. Harness and results are public; manuscript scripts are not.

**Cite as** (until an arXiv identifier exists):

```bibtex
@misc{seyedkazemiardebili2026silent,
  title  = {Silent Failures in On-Device Speech Recognition: A Measurement Study of CPU
            Dictation and Long-Form Meeting Transcription},
  author = {Seyedkazemi Ardebili, Mohsen},
  year   = {2026},
  note   = {Preprint, not peer reviewed}
}
```

&copy; 2026 Mohsen Seyedkazemi Ardebili. All rights reserved. The papers are preprints; where an
arXiv version exists, it is the authoritative one.
