# SoA research — AR/VR/metaverse & wearable input (2024–2026)

**Date:** 2026-07-02 · **Tier:** `design/` — public engineering research · **Author:** Mohsen Seyedkazemi Ardebili
**Companion:** domain 3 of the 5-domain v2 vision sweep. Fed
[adr-v2-010](../../adr/adr-v2-010-gaze-routed-dictation.md) (Gaze-Routed Dictation),
[adr-v2-011](../../adr/adr-v2-011-semg-modality-router.md) (sEMG + Modality Router), and
[adr-v2-013](../../adr/adr-v2-013-glasses-desktop-bridge.md) (Glasses↔Desktop Bridge).
See the [waves index](README.md).

> A snapshot of the field on the date above, kept as the research record behind the ADRs it fed.
> Where a "candidate feature" below never shipped, treat it as a research note, not a promise —
> check `yazses features` and the linked ADRs for what is actually built.

## Key SoA findings

- **Gaze + pinch is the shipped spatial default, but text entry is slow** — Vision Pro
  gaze-target + pinch; virtual-keyboard ~11.2 WPM vs ~36 on iPhone; dictation/BT keyboard
  are the fallbacks. [arXiv 2406.00255]
- **Meta shipped a consumer sEMG wristband** — Neural Band + Ray-Ban Display, $799, Sept
  30 2025; wrist EMG for subtle finger gestures. First mass-market neural-input wearable.
- **Meta sEMG generalizes across users without per-person training (Nature, Jul 2025)** —
  handwriting decode **20.9 WPM**, gesture 0.88/sec, out-of-box; neural handwriting ("write
  on any surface") shipping on Ray-Ban Display. [Meta Reality Labs; Nature]
- **Android XR (Samsung Galaxy XR, 2025) makes voice-first multimodal the OS model** —
  Gemini Live central, fuses gaze+hand+voice+visual; voice/agent primary, controllers
  optional.
- **"Point-and-speak" / gaze-deixis is maturing research** — GazePointAR (CHI'24) fuses
  gaze+pointing+history to resolve "what is *that*?". Clearest voice+gaze template.
- **CHI'26 quantifies which combos work** — Gaze+Pinch best for multi-select; **Gaze+Voice
  subselection disliked (repeated vocal commands tedious).** Key negative: voice great for
  *content/dictation*, weak for *repetitive selection*. [arXiv 2602.12406]
- **Dwell-free gaze typing improving but below speech** — EyeSwipe ~11.7 WPM; theoretical
  ceiling ~46 WPM. Assistive/fallback, not a speech replacement.
- **Silent-speech (subvocal) commercializing** — MIT AlterEgo spun out (IP transfer Apr
  2025), "near-silent" wearable demoed Sept 2025; ~92% on constrained vocab. [secondary]
- **Context-aware/gaze-adaptive selection is a live front** — CONTEXT-GAD (VRST'25) adapts
  dwell to context; multi-display gaze-routing targets *which screen/window* the user attends.
- **Consensus modality split stabilizing** — gaze = targeting/where, pinch/sEMG micro-
  gesture = confirm/discrete, voice = content/dictation + complex intent, on-device inference
  = disambiguation/layout. Designs that work assign each channel its fastest role.
- **Air-typing/handwriting-in-air is the emergent keyboard-replacement bet** (not virtual
  QWERTY); all remain slower than fluent speech (~150 WPM), so dictation stays throughput champ.
- **Recurring negative:** voice is throughput-strong but fatiguing/awkward for commands/
  selection — hybrids reserve voice for dictation, hand off discrete control to gaze/EMG.

## Gaps / opportunities (desktop-first, privacy-first)

- **No privacy-first local bridge from wearable neural/gaze input to the desktop** — Meta
  sEMG and Android XR are cloud-tethered and vendor-locked; offline STT + EMG/gaze intake
  are the hard local pieces most tools don't have.
- **"Where does the text go?" is unsolved on the desktop** — spatial OSes solved gaze-
  targeting of windows/zones; desktops route to focus. This project already had gaze zones.
- **Point-and-speak (gaze deixis) exists only in cloud AR assistants.**
- **sEMG micro-gestures as a silent command channel unexploited on desktop.**
- **Cross-device continuity is vendor-siloed** — dictate on glasses → land in a desktop
  editor over a local channel is missing, and a remote-injection agent was a plausible base.
- **Whisper/silent speech for shared offices missing from offline tools.**
- **Modality-role assignment isn't codified in any config-driven local tool.**

## Candidate features considered in this domain

1. **Gaze-Routed Dictation** — inject into whichever window/monitor you look at. Risk:
   webcam gaze ~1-2° too coarse for small adjacent windows → zone granularity + confirm;
   Wayland can't focus other windows.
2. **Point-and-Speak Deixis** — "rename *this*", "insert here" resolved from gaze (offline
   GazePointAR); deixis words as grammar slots filled by gaze zone. Risk: gaze/intent
   divergence → confirm window.
3. **sEMG Command Vocabulary** — promote EMG from trigger to silent gestures (squeeze=confirm,
   double=undo, flick=mode). Frees voice for dictation. Risk: cheap EMG may not resolve
   multi-gesture → start with 2-3.
4. **Glasses↔Desktop Dictation Bridge** — dictate via glasses/phone → inject to desktop over
   encrypted LAN. Risk: glasses hardware is closed → phone-as-mic near-term.
5. **Modality Role Router** — config policy: gaze→targeting, EMG→discrete, voice→dictation;
   presets (voice-only/voice+gaze/voice+emg/full). Risk: complexity → sane presets via features.
6. **Whisper-Mode Dictation (EMG-gated quiet capture)** — low-gain/whisper STT profile gated
   by EMG for shared spaces; stepping-stone to silent speech. Risk: whispered accuracy
   unverified → experimental, opt-in only.

**Caveats, from the original sweep:** the 46 WPM gaze ceiling is theoretical; AlterEgo's
~92% is early, constrained-vocab, secondary-sourced; Meta's 20.9 WPM is the Nature figure
(~30 WPM was a stage demo); webcam gaze accuracy is hardware-dependent and needs measuring
on the actual backend before relying on it. Citations here have not been re-verified
against [`research/verify_refs.py`](../verify_refs.py).
