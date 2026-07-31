---
title: Roadmap
description: Where YazSes is today — what has shipped, what is being wired up now, and what is planned or explicitly deferred.
---

# Roadmap

YazSes is under active development. It is a fully-offline, hold-to-talk voice
dictation daemon for Linux, macOS, and Windows — no cloud, no account, nothing
leaves your machine. This page is the honest, user-facing picture of where the
project stands: what has already shipped, what is being connected to the live
dictation pipeline right now, and what is planned versus merely designed.

Three principles hold across everything below:

- **Offline first.** Transcription runs on your CPU with `faster-whisper`. There
  is no telemetry and no network dependency for dictation.
- **Off by default.** The stable dictation path is small and predictable. The
  large catalogue of extra capabilities is opt-in — you enable exactly what you
  want with `yazses features enable <name>` and apply with `yazses restart`.
- **Nothing you didn't ask for.** New capabilities land dormant and are activated
  incrementally, so an upgrade never changes how your dictation behaves unless you
  turn something on.

For the full catalogue of individual capabilities — what each does and how to
enable it — see the [Feature Reference](features.md).

---

## Shipped

The **stable release is v1.4.1.** The table below groups milestones by minor
version and gives the headline capability each one added; see `CHANGELOG.md` for
per-release detail.

| Version | Date | Headline |
|---|---|---|
| **v0.1.x** | — | Linux-only foundation: hold-to-talk hotkey, text injection, systemd lifecycle, offline `faster-whisper` transcription. |
| **v0.2.0** | 2026-05-08 | Cross-platform: macOS and Windows support, tray icon, and installers for all three platforms (`.dmg`, `.exe`, `.deb`). |
| **v0.3.0** | 2026-05-15 | SSH/remote voice forwarding, streaming transcription, voice command grammar, offline disfluency filter, accessibility enrollment wizard. |
| **v0.4.x** | 2026-05-17 | Offline small-language-model intent routing, editor (LSP) context injection, EMG/BLE silent-speech input, and a GGUF model manager. |
| **v0.5.x** | 2026-05-29 | Opt-in, local, **encrypted** self-improvement loop (`yazses tune` / `mark-wrong` / `corpus`) plus the voice-activity overlay. All off by default. |
| **v0.6.0** | 2026-06-19 | Prosody Ink (pauses → paragraphs, emphasis → bold), endpoint pre-warm, and re-record ("Punch-In") wiring. |
| **v0.7.0** | 2026-06-19 | Held-out validation for the learning loop — every tuning proposal is checked against data it wasn't derived from. |
| **v0.8.0** | 2026-06-19 | Dysfluency-Friendly Mode — an opt-in pass that cleans stuttered/dysarthric speech out of the final text. |
| **v0.9.0** | 2026-06-19 | CLI quality of life: `yazses update`, a friendlier help system, Tab completion. |
| **v1.0.0** | 2026-06-19 | First stable release of the Python app: fully-offline dictation for Linux/macOS/Windows with a deep, off-by-default feature set. |
| **v1.1.0** | 2026-06-19 | Enriched `yazses doctor` (version, daemon status, model, config summary, `--mic` check) and reliable spoken-name recognition. |
| **v1.2.0** | 2026-06-20 | CLI usability without hand-editing TOML: `yazses features` / `vocab` / `hotkey`, a dedicated command key, and no more duplicate daemons. |
| **v1.3.0** | 2026-06-23 | Voice-activity overlay on by default (PySide6 promoted to a base dependency). |
| **v1.3.x** | 2026-07-01 | Wayland injection reliability: type-everywhere via ydotool, a flood guard for Ubuntu 26+ compositors, and longer maximum recordings. |
| **v1.4.0** | 2026-07-01 | Opt-in voice punctuation ("comma"/"period"/"new line" → symbols) and a selectable injection backend. |
| **v1.4.1** | 2026-07-01 | Cross-platform CI green again and more reliable releases. **Current stable release.** |

---

## In progress / near-term

The current focus is **wiring the large catalogue of built capability cores into
the live dictation pipeline, one batch at a time.**

Over a long series of research rounds, roughly **135 capabilities** have been
designed, implemented as self-contained cores, tested, and registered in
`yazses features`. Many of these cores were built and verified but were **not yet
connected to any runtime path** — so registering them was not the same as being
able to use them. Closing that gap is the near-term work: each batch connects a
few more cores to the real dictation flow, with a test proving each one fires only
when you enable it. Everything stays **off by default**, so existing behaviour is
unchanged.

Concretely, the batches wired in so far include:

- **Live DICTATE-path text transforms** — grammar repair, diacritic restoration,
  semantic line breaks, confusable-glyph warnings, inline compute, auto-pairing of
  brackets, phonetic correction of mis-heard names, transliteration, and
  structured-markup dictation now run in-pipeline when enabled.
- **Offline text-tool commands** — `yazses reflow` (monologue → outline),
  `yazses table` (spoken rows → CSV), `yazses shellpipe` (spoken pipeline →
  shell command text, never executed), and `yazses braille` (text → Unicode
  Braille).
- **Offline recording import** — `yazses transcribe <file>` decodes any common
  audio format, transcribes offline on CPU, and optionally tags who said what
  (`--diarize`), writing a `.txt`/`.md`/`.srt`/`.vtt`/`.json` sidecar. Speaker
  naming is opt-in and consent-gated; it never auto-enrolls other people.

Alongside this, recent near-term work has focused on making installation and
first-run **honest and unmissable**: `yazses setup` now prints an ordered
"finish installing" checklist, `yazses start`/`restart` verify the daemon
actually came up (instead of reporting success while it crashed), and
`yazses doctor` ends with a plain-language verdict and the exact next command to
run.

The remaining cores will keep activating incrementally in the same way. A subset
of the catalogue is live in the DICTATE pipeline today; the rest come online batch
by batch.

---

## Future work

The items below are planned directions. We distinguish clearly between what is
**designed but deliberately not built yet** and what is **speculative**.

**Designed, but explicitly deferred:**

- **Cloud escalation for transcription.** An opt-in path to send audio to a hosted
  provider for a hard recording was fully designed, with strict guardrails — but it
  is **not implemented**, and offline remains the only path. It stays deferred so
  the "nothing leaves your machine" default is never quietly weakened.
- **Personal speech adapters (LoRA).** On-device fine-tuning that adapts the model
  to your voice and vocabulary — including atypical speech (dysarthria, ALS,
  Parkinson's) — is designed and gated on a measured accuracy win on held-out data,
  so it only ever applies when it genuinely helps. Prompt-level personalization
  from your own corpus already ships; the training-based adapter is the deferred
  part.
- **Per-language model auto-switching.** Detecting the spoken language and hot-
  swapping to the right model is designed as a routing layer; the language-specific
  model files are deferred.
- **Code-switch dictation.** Routing for mixed-language speech is in place, but
  stays dormant until a suitable code-switch model is supplied out of band.

**Hardware- or model-gated (designed, waiting on the missing piece):**

- **Silent-speech input (sEMG).** Fully silent dictation via a surface-EMG
  wristband is designed; it activates when the hardware is present.
- **Gaze- and vision-based targeting.** Look-to-pane dictation routing and pure-
  vision screen commanding are designed, but depend on a webcam plus platform
  support that is not universally available today.

**Speculative / research directions:**

- Deeper multi-step reasoning and agentic task chaining over long sessions.
- Semantic retrieval (RAG) over your personal note corpus, fully offline.

These research directions are explored as fresh state-of-the-art rounds and may or
may not become shipped features. When they do, they follow the same rule as
everything else: off by default, opt-in, on-device.

---

## Known limitations

A short, honest list of current constraints. For hands-on help with specific
problems, see `docs/troubleshooting.md`.

- **CPU transcription latency.** Whisper runs on your CPU (int8). It is fully
  offline and private, but on a first run the model can take roughly 10–30 seconds
  to load, and larger/more-accurate models trade latency for quality. Choose a
  model to suit your machine.
- **English-tuned by default.** The default configuration targets English
  (`small.en` / `base.en`). Other languages work, but per-language models and
  code-switch support are still in progress (see Future work).
- **Desktop-only.** YazSes targets Linux, macOS, and Windows desktops. There is no
  mobile or web version.
- **Some capabilities need optional extras or hardware.** Heavier features (speaker
  diarization, gaze, EMG, neural denoise, and others) depend on optional Python
  extras or external hardware that are not bundled with the base install. They stay
  dormant until you install what they need and enable them.
- **Linux packaging caveat.** Install via the APT script or `pipx` for hold-to-talk
  dictation. The strictly-confined snap cannot read the keyboard device, so the
  hotkey does not fire there — the snap only serves the offline file-transcription
  use case.

---

## Requesting features and reporting bugs

Feedback drives what gets built next. To report a bug or request a feature, open a
GitHub issue on the project's Issues tracker.

The quickest way to find the exact link (and the current version you're running)
is to run:

```bash
yazses about
```

It prints the author, version, project links, and where to report issues or
request features. `yazses doctor` also ends with a contact footer, so if you hit a
problem you always know where to go.
