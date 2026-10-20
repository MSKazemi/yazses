# Voice Dictation / Voice Control: A Market Survey, Mid-2026

**Date:** 2026-08-07 · **Tier:** `design/` — public engineering research
**Companion:** [local/offline STT engine SoA](2026-08-07-stt-engine-sota.md) ·
[gaze / EMG / BCI / multimodal input SoA](2026-08-07-hci-input-sota.md) ·
[the roadmap](../../../ROADMAP.md)

A survey of the voice-dictation and voice-control tools on the market as of
2026-08-07, gathered to understand where an offline-first project sits in the wider
landscape. This is a snapshot, not an endorsement or a criticism of any of the
products named — pricing and feature claims below are as published by each vendor at
the time of writing and may have changed since.

## 1. Per-product summaries

### Commercial, cloud-based, AI-native dictation

- **Wispr Flow** — Mac/Windows/iOS/Android. $15/mo, with a free 2,000-words/week
  tier. Cloud-only (AWS plus third-party LLMs). Notable features: auto-edits as you
  speak, a Command Mode (highlight text, say "make this more concise", get an
  in-place rewrite), and per-app tone matching (Slack vs. Gmail vs. an editor). The
  vendor reports 184 WPM effective throughput. Publicly discussed concerns: it
  captures screenshots of the active window for cloud processing, with Privacy Mode
  off by default; a 2.7/5 Trustpilot rating as of 2026-04; and it is a comparatively
  heavy Electron application.
- **Superwhisper** — macOS/iOS. Free tier; $8.49/mo; $249.99 lifetime. Local-capable
  (Whisper/Parakeet on Apple Silicon) with an optional cloud LLM. Notable features:
  custom "modes" (per-task prompt presets) and context capture from
  selection/clipboard/app. No Windows support as of this survey.
- **Aqua Voice** — Mac/Windows. $8/mo. Cloud-only, using a proprietary STT model
  (Avalon, 2025-08) trained on prompt-style speech, code, and email. Notable
  features: reported <50 ms start latency and ~1 s insertion, per-surface style
  matching, voice-driven editing, and an 800-term custom dictionary.
- **Willow Voice** — four platforms, ~$15/mo, cloud-first, with style-matching as its
  central pitch and an optional offline mode on Mac/iOS.
- **Monologue** — $10/mo, with a downloadable model for on-device transcription.
- **Spokenly** — Mac/iOS, free, local models with bring-your-own API keys for cloud
  options.

### Open-source dictation

- **VoiceInk** — macOS, GPL-3, $25 one-time. Local whisper.cpp with a "Power Mode"
  (automatic per-app settings) and AI enhancement via a local Ollama instance.
- **Handy** — Mac/Windows/Linux, MIT, free, fully offline, built on Tauri
  (Rust+React). The largest open-source project in this space by star count as of
  this survey. Does not ship AI cleanup, and users report a 2–5 s post-speech wait.
- **Speed of Sound** — Linux, on-device (Whisper/Parakeet/Canary backends), X11 and
  Wayland, packaged for Flathub/Snap/AppImage/deb/rpm, with primary/secondary
  language switching.
- Others surveyed: Vocalinux (Vulkan-accelerated), VOXD (Wayland-first), OpenWhispr,
  nerd-dictation, Whispering. Ito (GPL-3) shut down in 2026-01 after a Show HN
  launch — a data point on how quickly an open-source dictation project can lose
  momentum.

### Voice control

- **Talon + Cursorless** — free tier, with a $25/mo beta tier. A local Conformer/
  Whisper hybrid "mixed mode" handles commands and dictation in one utterance;
  Cursorless adds structural, AST-aware code editing. Reported downsides: a
  weeks-long learning curve and vocal fatigue from its dense command grammar.
- **Numen** — Linux, libre, Wayland-native, syllable-based full voice control.

### Incumbents / built-in dictation

- **Dragon Professional v16** — Windows, $699, no major release since 2023; Dragon
  Home has been discontinued and Dragon Anywhere mobile was retired on 2026-07-01.
- **Windows Voice Access + Fluid Dictation** (2026-06 update) — on-device grammar and
  filler correction as you speak, gated to Copilot+ NPU hardware.
- **macOS Tahoe Dictation** — on-device on Apple Silicon; Apple states it is 55%
  faster than Whisper on its hardware. Reported to be weaker on technical vocabulary
  and proper nouns.
- **Otter.ai** — cloud meeting transcription, $8.33–$19.99/user/month, English/
  French/Spanish only.

## 2. Feature landscape, condensed

Fully-offline operation, Linux support, and a single cross-platform daemon
architecture are comparatively rare in this survey — most local-capable competitors
are Mac-only or Mac-first. Offline diarized meeting transcription, a local encrypted
personalization loop, and gaze/EMG/SSH-remote activation sources were not observed
in any competing product surveyed.

Areas where the cloud-based tools above are ahead of what a fully-offline tool
typically offers: voice-editing of already-typed or selected text, per-app tone/
format matching, custom AI prompt modes, and sub-second perceived latency as a
default (rather than an opt-in).

## 3. White space — capabilities not observed in any product surveyed

1. Offline, cross-platform voice-editing of selected text using a local LLM — every
   product with this feature in this survey is cloud-only, and none run on Linux.
2. Offline per-app tone-matching on an ordinary CPU — Microsoft's version is
   NPU-gated; no product surveyed does this without either the cloud or specialised
   hardware.
3. A single tool combining everyday dictation with offline, diarized meeting
   minutes.
4. A local, self-improving personalization loop that gets better over time without
   any data leaving the device — only Dragon personalizes locally among the products
   surveyed, and it has had no major release since 2023.
5. Pipeline reliability (automatic recovery from a dropped microphone, a device
   change, or a silent failure) marketed as a feature in its own right.
6. Gaze-routed dictation, an EMG hotkey, and SSH-forwarded remote dictation — no
   product surveyed offers any of these.

## 4. What users report valuing most, across reviews surveyed

1. Instant, everywhere text insertion — sub-second latency is a headline claim
   across nearly every commercial product.
2. AI cleanup that makes spoken text read like careful writing — cited repeatedly as
   the main reason people pay for a subscription tool.
3. Per-app tone and context matching.
4. Voice-editing of existing text — a standout feature in Wispr Flow reviews
   specifically.
5. Privacy and ownership — local processing, a one-time or free price, or an
   open-source license.

## 5. Why users report abandoning these tools

Recurring themes in reviews and forum discussion: a sense of privacy shock (Wispr
Flow's screenshot capture, in particular); subscription fatigue; post-speech latency
(Handy's 2–5 s wait is called out repeatedly); the manual cleanup burden on long
dictations without an AI pass; instability in heavier Electron-based apps; and
outright platform abandonment (Dragon's stalled release cadence, Ito shutting down).

---

Key sources: efficient.app/apps/wispr-flow · docs.wisprflow.ai (Command Mode) ·
getvoibe.com (Wispr privacy discussion, Handy, Willow, Dragon pricing) ·
spokenly.app (Superwhisper pricing, Aqua review, Handy) · metawhisp.com (VoiceInk
review) · omgubuntu.co.uk 2026-04 (Speed of Sound) · talon.wiki · numenvoice.org ·
support.microsoft.com (Fluid Dictation) · tldv.io (Otter pricing) ·
afadingthought.substack.com (a differentiators essay) · onresonant.com (a Reddit
discussion) · vibetyper.com (2026 Linux dictation roundup) · alternativeto.net (Ito
status).
