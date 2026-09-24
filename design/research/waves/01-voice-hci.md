# SoA research — voice/speech HCI & dictation (2024–2026)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** domain 1 of the 5-domain v2 vision sweep. Fed [adr-v2-001](../../adr/adr-v2-001-confidence-ink.md)
(Confidence Ink), [adr-v2-002](../../adr/adr-v2-002-prosody-autoformat.md) (Prosody→autoformat),
[adr-v2-003](../../adr/adr-v2-003-spoken-edit-mode.md) (Spoken Edit Mode),
[adr-v2-004](../../adr/adr-v2-004-context-primed-dictation.md) (Context-Primed Dictation),
[adr-v2-005](../../adr/adr-v2-005-spoken-recall.md) (Spoken Recall),
[adr-v2-008](../../adr/adr-v2-008-code-switch.md) (Code-Switch), and
[adr-v2-009](../../adr/adr-v2-009-personal-adapter.md) (Personal Adapter).
See the [waves index](README.md) for how this fits the rest of the research trail.

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Where a "candidate feature" below never shipped, treat it as a research note, not a promise —
> check `yazses features` and the linked ADRs for what is actually built.

## Key SoA findings

- **On-device streaming ASR beats "batch Whisper" on latency without cloud** — Kyutai
  **Moshi** full-duplex (~160-200 ms). [arXiv 2410.00037]
- **Moonshine v2** — ergodic streaming encoder, purpose-built low-latency on-device English
  ASR; faster-whisper alternative for edge. [arXiv 2602.12241]
- **NVIDIA Parakeet-TDT 0.6B** tops HF Open ASR Leaderboard, punctuation/caps/timestamps,
  CC-BY-4.0; v3 adds 25 languages + auto LID + ~3 h long-form. Stronger than Whisper-base.
- **Whisper large-v3-turbo** (809M, ~8× RT), **distil-whisper** (6× faster, ~1% WER),
  **faster-whisper** (CTranslate2) — current offline sweet spot.
- **Mistral Voxtral Realtime (4B, Apache-2.0)** — live transcription + **speaker
  diarization** on edge, ~200 ms; Whisper has no diarization.
- **"Draft-then-polish" dictation is a shipped default via on-device SLMs** — MS Voice
  Access **Fluid Dictation** (Copilot+, on-device SLM) auto-fixes grammar/fillers; Google
  **Rambler/Gboard** (Gemini Nano) handles self-corrections, fillers, **mid-sentence
  code-switch**, all on-device. Both hardware/OS-locked.
- **Interactive dictation (dictate + open-ended spoken edits) is live research** — MS
  **TERTiUS/"Toward Interactive Dictation"** segments dictate-vs-command + LLM edits;
  **Rambler** (CHI'24) "gist manipulation" (respeak/split/merge/transform). [arXiv 2307.04008]
- **Voice+mouse "fix-over" correction** still beats voice-only editing (MS Word 2024).
- **Dysarthric ASR jumped** — SAP corpus → ~6.99% WER mid-severity; **AdaLoRA + x-vectors +
  synth aug ~23% lower WER than full fine-tune**; "Universal Personalizer" few-shot MetaICL.
- **Endpointing moved to semantic end-of-turn** — Phoenix-VAD (LLM semantic endpoint),
  Next-Turn (time-to-next-onset). [arXiv 2509.20410, 2606.18094]
- **Silent-speech via surface EMG maturing** — dry EMG neckband 92.7%; EMG precedes motion
  ~60 ms; command-set-limited, not open dictation.
- **Code-switching is first-class now** — monolingual WER spikes 30-50% at switch points;
  E2E multilingual cuts boundary WER ~55%; SwitchLingua 420K CS samples. Rambler/Voxtral
  ship it.
- **Prosody is the discarded signal** — STT flattens pitch/pause/energy; 2025-26 work
  re-injects prosody (emotion/emphasis) recoverable on-device. [arXiv 2603.09324]
- **Apple Personal Voice** on-device, faster enrollment 2025; atypical-speech "voice quality
  dimensions" research.

## Gaps / opportunities

- **Editing by voice is the weak link** — open-ended spoken editing is research-only &
  **not offline**; best offline tools use rigid grammars or a mouse.
- **"Polish" is cloud-adjacent/vendor-locked** (Fluid Dictation = Copilot+ only; Rambler =
  Pixel/Samsung). Cross-platform fully-local equivalent is open.
- **Atypical-speech personalization is offline-hostile** — needs corpora/fine-tune;
  few-shot/LoRA from a *local encrypted corpus* shipped by no one.
- **Prosody thrown away** — users must say "bold"/"new paragraph"; the signal is free.
- **Homophone/near-miss correction clumsy** — Whisper computes n-best/logprobs but no tool
  surfaces confidence or lets you re-pick by voice.
- **Bilingual users must manually toggle language** — no offline hold-to-talk code-switch.
- **Endpointing forces a physical hold** — motor-impaired users need a local "I'm done".

## Candidate features considered in this domain

1. **Spoken Edit Mode** — open-ended voice edits ("change 'their' to 'there'", "delete last
   sentence"); on-device dictate-vs-command classifier + text ops. Beyond regex grammar &
   Dragon/Apple. Risk: segmentation ambiguity → command-key disambiguator + destructive confirm.
2. **Local few-shot/LoRA personalization** for atypical/accented speech from the encrypted
   corpus; held-out gated (AdaLoRA ~23% WER cut). Risk: CPU fine-tune cost → WER gate.
3. **N-best / confidence re-pick ("say the other one")** — flag low-logprob spans, re-pick
   from beam alts instead of re-dictating; free from faster-whisper. Risk: limited beam
   diversity → spell-out fallback.
4. **Semantic endpointing ("smart release")** — accessibility mode: auto-close burst when
   speech semantically complete. Off by default. Risk: false endpoints → conservative.
5. **Real intra-utterance code-switch** — per-span LID → per-span decode (make `[polyglot]`
   real). Risk: mid-utterance LID errors → restrict to declared pair.
6. **Prosody-driven auto-formatting** — pauses→punctuation/paragraphs, stress→emphasis
   (finish Prosody Ink). Risk: over-formatting → conservative, opt-in.

**Net:** ideas 1–3 were highest-leverage on the stack as it stood on this date; idea 2 was
judged the strongest accessibility differentiation, since the project already had the
encrypted corpus most competitors lack.

**Caveats, from the original sweep:** streaming-latency and vendor accuracy figures came
from secondary sources and are indicative, not measured. Primary sources were arXiv papers,
MS Research, the HF leaderboard, and vendor docs. Citations here have not been re-verified
against [`research/verify_refs.py`](../verify_refs.py) — treat arXiv IDs as pointers to
chase, not as confirmed.
