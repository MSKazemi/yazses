# Wave L — non-speech & prosodic voice interaction (SoA research)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** fed [adr-v2-095](../../adr/adr-v2-095-vocal-joystick.md) through
[adr-v2-104](../../adr/adr-v2-104-prosodic-auto-punctuation.md). See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Feature status should be checked against `yazses features` and the linked ADRs, not this note.

**Method:** background SoA scout (2024-2026 CHI/UIST/ASSETS/TOCHI, Interspeech/ICASSP, arXiv
cs.HC/cs.CL/eess.AS; Apple/MS/Google accessibility) against the full feature-exclusion list at
the time. Every candidate is on-device/offline, off by default, with a pure dependency-light
testable core (heavy DSP/models are optional lazy extras). All ten evidence anchors were
checked against real research/products at the time.

This wave opened an area the prior net-new features hadn't touched: **non-speech vocal signals
(formant/pitch/loudness/breath) and acoustic prosody as first-class interaction channels** — for
users who can phonate but not articulate discrete words, and for word-free eyes-free control.

## The ten features (ranked most→least compelling)

1. **Vocal Joystick** — sustain vowels/pitch/loudness for *continuous analog* cursor/scroll
   control (no words). Core: `vowel_to_direction`, `vocal_control_vector`, `VocalJoystick` state
   machine. Anchor: Bilmes et al., *The Vocal Joystick* (ASSETS 2006; D&RAT 2008, PMID 18416516).
   → [adr-v2-095](../../adr/adr-v2-095-vocal-joystick.md).
2. **Mouth-Sound Switch Access** — non-verbal mouth sounds (pop/click/cluck) drive a timed
   scan-and-select. Core: `classify_mouth_sound`, `ScanSelector`. Anchor: Apple Sound Actions for
   Switch Control (iOS 15, 2021). → [adr-v2-097](../../adr/adr-v2-097-mouth-sound-switch-access.md).
3. **Beam-Steered Spatial VAD** — 2-mic direction-of-arrival gate (enrollment-free,
   geometric, complements Cocktail Filter). Core: `gcc_phat`, `tdoa_to_angle`, `spatial_gate`.
   Anchor: Knapp & Carter GCC-PHAT; real-time DoA (PMC8136617). → [adr-v2-098](../../adr/adr-v2-098-spatial-vad.md).
4. **Breath-Paced Dictation** — inhalation-onset segmentation into breath groups. Core:
   `breath_envelope`, `detect_breath_onsets`, `segment_by_breath`. Anchor: BreathPrint (MobiSys
   2017); in-ear breathing-phase (Sensors 2024, 24(20):6679). → [adr-v2-099](../../adr/adr-v2-099-breath-paced-dictation.md).
5. **Whisper-Aware Mode** — detect whispered phonation, adapt gain/VAD/prompt. Core:
   `voicing_ratio`, `spectral_tilt`, `is_whispered`, `whisper_adaptation`. Anchor: Ito et al.
   (ICASSP 2005); wTIMIT; arXiv 2408.13746 (2024). → [adr-v2-100](../../adr/adr-v2-100-whisper-aware-mode.md).
6. **Earcon Feedback Language** — structured non-speech tones for daemon state (eyes-free,
   faster than read-back). Core: `earcon_for`, `render_earcon`. Anchor: Brewster earcons (TOCHI
   1993); Gaver auditory icons (1986); Walker spearcons (Human Factors 2013).
   → [adr-v2-096](../../adr/adr-v2-096-earcon-feedback.md).
7. **Hesitation-Hold Endpointing** — hold the turn open on *filled* pauses ("uhh…") instead
   of cutting off. Core: `is_filled_pause`, `endpoint_decision`. Anchor: Chatziagapi et al.
   filled-pause detection (ACII 2022). → [adr-v2-101](../../adr/adr-v2-101-hesitation-hold-endpointing.md).
8. **Involuntary-Vocalization Auto-Excision** — delete cough/throat-clear/sneeze from the
   stream. Core: `is_involuntary_vocalization`, `excise_nonspeech_spans`. Anchor: Hyfe cough
   tracker (F1000Research 11:730; PMC11809693, 91%/98%). → [adr-v2-102](../../adr/adr-v2-102-involuntary-vocalization-excision.md).
9. **Pitch-Contour Vocal Gestures** — hum a melody shape (rise=confirm, fall=cancel) as a
   word-free command grammar. Core: `normalize_contour`, `classify_contour`,
   `gesture_to_command`. Anchor: Vocal Joystick line + Meyer, *Whistled Languages* (Springer
   2015). → [adr-v2-103](../../adr/adr-v2-103-pitch-contour-gestures.md).
10. **Prosodic Auto-Punctuation** — insert `. , ?` from prosody alone (no spoken
    punctuation words). Core: `punctuate_from_prosody`. Anchor: Cho et al., *Leveraging Prosody
    for Punctuation Prediction* (Interspeech 2022, UW). → [adr-v2-104](../../adr/adr-v2-104-prosodic-auto-punctuation.md).

## Diversity
2 non-speech motor/AAC (#1, #2), 3 robustness/DSP (#3, #4, #5), 1 eyes-free feedback (#6), 2
timing/turn-taking (#7, #9 — distinct: analog control vs discrete symbolic), 2 health/editing (#8,
#10). Every "heart" is a deterministic function/state-machine over already-extracted features;
formant/F0/DoA extraction is always the optional lazy extra.

Citations here have not been re-verified against [`research/verify_refs.py`](../verify_refs.py).
