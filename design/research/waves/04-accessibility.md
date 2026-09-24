# SoA research — accessibility & assistive input (2024–2026)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** domain 4 of the 5-domain v2 vision sweep. Fed
[adr-v2-009](../../adr/adr-v2-009-personal-adapter.md) (Personal Adapter),
[adr-v2-012](../../adr/adr-v2-012-accessibility-continuum.md) (Accessibility Continuum), and
[adr-015](../../adr/adr-015-dysfluency-friendly-mode.md) (Dysfluency-Friendly Mode).
See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Where a "candidate feature" below never shipped, treat it as a research note, not a promise —
> check `yazses features` and the linked ADRs for what is actually built.

## Key SoA findings

- **Atypical-speech ASR shipping on-device but shallowly** — Apple "Listen for Atypical
  Speech" (iOS 18) learns a user's patterns for Voice Control/Siri (CP, ALS, stroke);
  iPhone-centric, largely absent on Mac. [TechCrunch; WWDC25]
- **Public datasets moved the numbers** — UIUC Speech Accessibility Project (>500
  impaired speakers, 400+ hrs) drove the Interspeech 2025 SAP Challenge; funded by the
  AI Accessibility Coalition (Amazon/Apple/Google/Meta/MS). [arXiv 2507.22047]
- **Few-shot on-device personalization beats speaker-independent baselines** — "Universal
  Personalizer" 13.9% WER on Euphonia vs 17.5% baseline; 5.3% on SAP Test-1. [arXiv
  2509.15516 — preprint, WER directional]. Directly relevant to any project betting on an
  on-device personal corpus.
- **Google Euphonia / Relate** — personalized dysarthria ASR, expanding to non-English
  disordered speech. [Frontiers 2025]
- **LLM-accelerated AAC is the biggest practical win** — Google SpeakFaster/eye-gaze:
  57% motor savings, 29–60% real-world rate gains for ALS users; baseline gaze typing
  <10 WPM. [Nat Commun 2024 — peer-reviewed]
- **Microsoft Voice Access "Fluid Dictation"** (Copilot+ PCs) does real-time punctuation/
  filler cleanup; MS reports ~60% recognition gain for non-standard speech from SAP.
  [MS Ability Summit 2025]
- **Personal Voice / voice banking got cheap** — Apple WWDC25: a voice from ~10 phrases
  in <1 min, on-device (was ~150 phrases). [MacRumors]
- **BCI as first-class input** — Apple WWDC25 BCI protocol via Switch Control. Speech
  BCIs hit real home use: ALS user 3,800+ hrs; transformer brain-to-text 99.2% on 125k
  words; Stanford ~62 WPM. [Nature Medicine 2026; bioRxiv 2025 — early clinical]
- **Silent-speech (EMG/subvocal) advancing but pre-consumer** — dry-EMG neckbands,
  sentence-level recognition with LM post-processing; all research prototypes. [MDPI
  Sensors; arXiv 2509.21964]
- **Talon Voice** is the mature reference for hands-free command/coding via voice +
  mouth noises + eye tracking (RSI community). [talonvoice.com]
- **Privacy-preserving on-device adaptation demonstrated** — LoRA continual ASR where raw
  audio never leaves device; federated adapters 8.9–27.4% relative WER reduction. [arXiv
  2512.16401; IEEE 10389738] — literature support for the architectural bet of adapting
  locally rather than in the cloud.

## Gaps / opportunities

- Atypical-speech personalization is locked to Apple/Google walled gardens, mobile-first,
  closed — an open, cross-platform, fully-local equivalent was a clear gap.
- **Progressive conditions (ALS/Parkinson/MS) have no continuity story** — tools assume a
  static speaker; nobody handles a voice degrading over months, locally.
- **Low-effort / whispered dictation unserved** — fatigue, dysphonia, privacy push toward
  quiet speech; mainstream ASR is trained on modal voice.
- **Correction burden disproportionate for disabled users** — SpeakFaster-style acceleration
  is cloud/mobile-AAC only, not in an offline desktop daemon.
- CPU-int8 personalization for accessibility on a laptop is genuinely underexplored.

## Candidate features considered in this domain

1. **Local Voiceprint Adapt** — on-device dysarthria personalization from the encrypted
   corpus (in-context prime → nightly CPU LoRA gated on held-out WER). Risk: overfit →
   held-out gate.
2. **Low-Effort / Whisper Mode** — recognize very quiet/whispered speech (lower VAD floor
   + whisper-specific adaptation) for vocal fatigue/privacy. Risk: whispered ASR is hard →
   needs calibration; experimental.
3. **Progressive Voice Continuity** — bank the voice + degrade gracefully dictation →
   assisted → TTS/switch, all local, for degenerative conditions. Risk: emotionally
   sensitive, model drift.
4. **Offline Turbo-Text** — abbreviation/keyword → full sentence expansion via a local SLM.
   Risk: hallucination → mandatory confirm.
5. **Effort-Adaptive Sessions** — fatigue-aware auto-tuning of VAD/hold from mic-level
   telemetry; advisory only. Risk: false triggers/medical claims → keep advisory.
6. **Confidence Ink + One-Breath Repair** — surface low-confidence words (Whisper token
   probs) + re-say just that span. Risk: confidence ≠ error → validate correlation.

**Caveats, from the original sweep:** WER figures came from arXiv preprints and were
treated as directional; SpeakFaster (Nat Commun) and the BCI result (Nature Medicine) are
peer-reviewed; Apple's version naming was inconsistent across sources and features were
confirmed for the 2025 cycle specifically; vocal-fatigue material is clinical background,
not a description of a shipped product. Citations here have not been re-verified against
[`research/verify_refs.py`](../verify_refs.py).
