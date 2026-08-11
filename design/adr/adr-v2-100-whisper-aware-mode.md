# ADR-v2-100 — Whisper-Aware Mode

**Status:** Accepted (2026-07-02) · Wave L
**Context links:** acoustic_profiles (noise profile), voicehealth (vocal strain), vad_calibrated, [[adr-011]]

## Context

Wave L research (#5) — Vocal-Strain Guard protects the voice; Acoustic Profiles picks a noise
profile; neither *detects whisper phonation* and switches recognition behavior. Whispered speech is
acoustically distinct (no F0/voicing, flatter spectral tilt, elevated turbulence) and normal STT
degrades sharply on it. Detecting the whisper and auto-adapting gain, VAD threshold, and the STT
prompt keeps quiet/whispered dictation accurate in shared or private spaces. Anchor: Ito et al.,
*Analysis and recognition of whispered speech* (ICASSP 2005); wTIMIT; *Quartered Spectral Envelope
1D-CNN classification of phonated vs whispered speech* (arXiv 2408.13746, 2024) — whisper is
separable by voicing ratio + spectral tilt.

## Decision

Add an opt-in **Whisper-Aware Mode**: `[whispermode] enabled=false, voicing_max=0.3, tilt_min=-1.0,
gain_db=6.0, vad_scale=0.5`. Pure cores in `whispermode/detect.py`: `voicing_ratio(frame)` (normalized
autocorrelation peak), `spectral_tilt(frame, fs)` (log-spectrum slope), `is_whispered(feats,
voicing_max, tilt_min)` (low voicing *and* flat tilt), and `whisper_adaptation(...)` → a
gain/VAD/prompt adjustment dict. Pure numpy DSP; no model. OFF by default.

## Consequences

- Accurate quiet/whispered dictation for weak-voice users and private spaces.
- Pure DSP feature ratios + threshold rule → fully testable on synthetic frames.
- Distinct from Vocal-Strain Guard (detect+adapt whisper vs protect voice).
- Privacy (ADR-011): local audio only.
- Caveat: threshold-based detection (a learned classifier is a later tier); off by default.
