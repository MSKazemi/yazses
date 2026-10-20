# Wave F — feature research (SoA sweep, 2026)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-035](../../adr/adr-v2-035-speaking-coach.md) through
[adr-v2-044](../../adr/adr-v2-044-two-way-interpreter.md). See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Feature status should be checked against `yazses features` and the linked ADRs, not this note.

10 features distinct from the ~34 already built before this wave (v2 + Wave D + Wave E, ADRs
000–034). All respect on-device / off-by-default / no-persistence invariants. Ranked
strongest-first. Anchors verified live at the time (no invented IDs).

## Build tiers
- **Ship-now pure:** #2 Speaking Coach, #3 Audio-Anchored Scrubbing, #4 Smart-Paste, #1 Reflow (core).
- **Medium (pure core + deferred backend):** #5 Acoustic Profiles, #6 Personal Read-Back Voice, #7 Mood Ledger, #8 Pronunciation.
- **Hardware/research-gated:** #9 Gesture Chords, #10 Two-Way Interpreter.

## Features

1. **Dictation Reflow (Voice Outliner)** — "structure this" rewrites the last burst into
   headings/bullets/action-items in place. Anchor: Gemma 3n E2B/E4B, Qwen3 local (arXiv
   2604.07035). Pure core: discourse-marker segmentation → outline builder + length/token
   guard (reuses the `llm_cleanup` guard). Deferred: llama.cpp SLM. `[reflow]`. ≠ Meeting Scribe
   / Recall. → [adr-v2-038](../../adr/adr-v2-038-dictation-reflow.md).

2. **Speaking Coach** — private on-device analytics of your own dictation: filler rate, WPM, pause
   ratio, type-token diversity, trend. Anchor: Yoodli/Poised (cloud) — an on-device niche neither
   covers. Fully pure (text+timestamp stats); optional parselmouth prosody. `[coach]`. ≠ Vocal-Strain
   (physical) / Confidence Ink (STT conf). Data from the opt-in encrypted corpus only. → [adr-v2-035](../../adr/adr-v2-035-speaking-coach.md).

3. **Audio-Anchored Scrubbing** — word-level timestamps kept; "replay what I said" / pick a
   word → hear that slice / re-dictate just that word. Anchor: faster-whisper `word_timestamps`
   (already in the stack). Pure: word→audio index + slice selection; playback via sounddevice.
   `[scrub]`. ≠ Spoken Edit (text) / Punch-In (blind re-record). → [adr-v2-037](../../adr/adr-v2-037-audio-anchored-scrubbing.md).

4. **Smart-Paste Format Adaptation** — detect the target surface (markdown/code/email/terminal/
   rich) and adapt injected syntax (bullets, casing, URL wrap). Anchor: existing window-class +
   AT-SPI introspection. Fully pure: target-detector → format-policy table. `[smartpaste]`.
   ≠ Tone Formatting (adapts syntax-to-app, not voice punctuation). → [adr-v2-036](../../adr/adr-v2-036-smart-paste.md).

5. **Acoustic Context Profiles** — detect scene (quiet/café/car/meeting) → auto-switch VAD/
   injector/denoise. Anchor: YAMNet, DCASE-2024 low-complexity ASC (arXiv 2405.10018,
   2410.20775, 2512.13905), CLAP. Pure: scene-label → profile switch with hysteresis. Deferred:
   YAMNet/CLAP tagger. `[acoustic_profiles]`. → [adr-v2-039](../../adr/adr-v2-039-acoustic-profiles.md).

6. **Personal Read-Back Voice** — read-back proofreading in a clone of your own voice from a
   short enrollment. Anchor: F5-TTS (CC-BY-NC), OpenVoice V2 (permissive → default), XTTS-v2.
   Pure: enrollment-sample management + reference-embedding wiring. Deferred: clone backend.
   Reuses `voiceprint/` + `tts/`. `[readback] clone_voice`. Voice embedding is biometric →
   encrypted corpus only. → [adr-v2-042](../../adr/adr-v2-042-personal-readback-voice.md).

7. **Mood Ledger** — tag each burst with an emotion label → private local mood-over-time view.
   Anchor: emotion2vec+ (ACL 2024, ~19M), SenseVoice SER (GGUF q8 ~254MB). Pure: label →
   time-series aggregation + trend. Deferred: SER backend. `[sentiment]`. ≠ Vocal-Strain
   (physical). Affective labels in the encrypted corpus only, off by default. → [adr-v2-040](../../adr/adr-v2-040-mood-ledger.md).

8. **Pronunciation Feedback (L2 mode)** — dictate a target phrase → per-phoneme goodness-of-
   pronunciation scoring. Anchor: wav2vec2 GOP/MDD (arXiv 2506.02080, 2507.16838). Pure:
   phoneme-alignment scoring + feedback formatting. Deferred: wav2vec2 GOP. `[pronunciation]`.
   ≠ Atypical LoRA (adapts the model to you; this scores you against a target). → [adr-v2-041](../../adr/adr-v2-041-pronunciation-feedback.md).

9. **Gesture Chords** — custom hand gestures (fist/palm/point) as PTT/command modifiers.
   Anchor: MediaPipe Gesture Recognizer custom fine-tune (arXiv 2309.10858), 30fps on-device.
   Pure: gesture→action map + debounce (mirrors `hold_detector`). Deferred: MediaPipe classifier.
   `[gesture]`. Webcam-gated; frames stay in-RAM only (see [adr-011](../../adr/adr-011.md)).
   ≠ Gaze / sEMG. → [adr-v2-043](../../adr/adr-v2-043-gesture-chords.md).

10. **Two-Way Live Interpreter** — bidirectional spoken interpreter: hears the other party →
    transcribe+translate+TTS back, and translates your reply the other way. Anchor: Seamless/
    SeamlessStreaming (arXiv 2312.05187), spatial speech translation (arXiv 2504.18715). Pure:
    turn-taking state machine + language-pair routing (reuses `polyglot/lid`). Deferred:
    Seamless + TTS out. `[interpreter]`. ≠ one-way Translation. Captures the other party →
    off by default + consent prompt. → [adr-v2-044](../../adr/adr-v2-044-two-way-interpreter.md).

## Reuse map
#6/#10 reuse `voiceprint/` + `tts/`; #10 reuses `polyglot/`; #1 reuses the `llm_cleanup` guard;
#3 reuses the faster-whisper word timestamps already in the stack.

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
