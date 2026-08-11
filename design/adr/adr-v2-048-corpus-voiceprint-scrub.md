# ADR-v2-048 — Corpus Voiceprint Scrub

**Status:** Accepted (2026-07-02) · Wave G
**Context links:** [[adr-012-self-improvement-loop]] (encrypts the corpus — this adds a biometric layer), [[adr-v2-028-multi-user-profiles]] (identify vs de-identify), [[adr-011]]

## Context

Wave G research (#5) — the opt-in learning corpus stores audio clips encrypted at rest, but raw
voice is biometric: an at-rest leak could be used for voice-cloning or speaker re-identification.
Speaker-anonymize each clip before storage so the corpus preserves *what* was said (for `yazses
tune` re-transcription) but not an identifiable *voice*. Anchors: VoicePrivacy 2024 Challenge
(arXiv 2404.02677), private kNN-VC (2505.17584), Third VoicePrivacy Challenge (2601.11846).

Distinct from Multi-User Voiceprint Profiles (which *identifies* speakers); this *de-identifies*
stored audio. It layers on top of ADR-012's encryption.

## Decision

Add an opt-in `[learning] anonymize_audio=false, anonymize_strength=1.08`. The pure DSP core
`anonymize_clip(audio, sr, strength)` shifts pitch/formants (resample-and-restore) to remove
gross speaker cues while preserving duration and linguistic content — dependency-free (numpy,
already required). Wired in `CorpusWriter` so clips are scrubbed on the background thread before
the encrypted write. The neural kNN-VC/WavLM anonymizer (strong, invertibility-resistant
guarantees) is deferred behind a `voiceprivacy` extra.

## Consequences

- Strengthens the existing no-data-leaves-machine posture with a second, biometric layer.
- Pure DSP → deterministic and unit-testable (length/dtype preserved, silence stays silence,
  output differs from input).
- Privacy (ADR-011/012): everything on-device; `corpus destroy` remains the hard forget button.
- Caveat: DSP anonymization is weaker than neural VC → documented as a first tier, with kNN-VC
  deferred; off by default so `yazses tune` audio fidelity is unchanged unless the user opts in.
