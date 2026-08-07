---
title: Roadmap
description: Where YazSes is going — the vision of keyboard-optional, fully private computing, the eras that get us there, and the working milestones you can join today.
---

# Roadmap

YazSes is a fully-offline, hold-to-talk voice dictation daemon for Linux,
macOS, and Windows — no cloud, no account, nothing leaves your machine.
**The current stable release is v2.15.0**, published on PyPI, GitHub
Releases, Snap, and the APT repository.

This page is two things at once: an honest status report, and a statement of
where we are going. If you only read one thing, read the pictures.

## The destination

The keyboard is a 150-year-old constraint, not a law of nature. YazSes exists
to make it **optional** — to become the private layer between you and your
computer that *hears* you, *understands* you, and *acts* for you, entirely on
your own hardware. Not a cloud assistant that rents you access to your own
words: an instrument you own, that gets better the more it learns about you,
and that never tells anyone what it learned.

The finished shape has three faculties, wrapped in two promises:

```mermaid
mindmap
  root((YazSes))
    Perceive
      Voice through Whisper and Parakeet
      Gaze knows where you look
      Muscle signals for silent input
      Meetings and recordings
    Understand
      Your personal vocabulary
      Dictation or command intent
      Who said what
      Your languages mixed freely
    Act
      Type into any app
      Command the desktop
      Write the meeting minutes
      Recall your own words
    Trust
      Offline always
      Encrypted on device
      Off by default
    Everywhere
      Linux macOS Windows
      Android next
      Every package manager
```

## The eras

Each era is a promise kept before the next one starts. Foundation is shipped.
Perception is shipping now. Understanding is the active frontier. Recall is
the reason the project exists.

```mermaid
timeline
    title From dictation tool to keyboard-optional computing
    section Foundation — shipped
        v0.x to v1.4 : Hold-to-talk dictation that just works : Linux, macOS and Windows : Encrypted on-device learning loop
    section Perception — shipping now
        v2.x : Meeting Mode with speaker diarization : Second STT engine (Parakeet TDT) : Gaze deixis and EMG activation : Sotto-voce command channel
    section Understanding — next
        v2.15+ : Settings GUI (no terminal needed) : Offline command mode over selected text : Vocabulary biasing in every engine : Android dictation keyboard
    section Recall — the horizon
        v3 : Spoken recall over everything you ever dictated : Ambient scribe you control : A computer you talk with, that stays yours
```

```mermaid
flowchart LR
    F["🏗️ Foundation<br><em>a tool that works</em>"] --> P["👁️ Perception<br><em>it hears and sees well</em>"]
    P --> U["🧠 Understanding<br><em>it knows what you mean</em>"]
    U --> R["💬 Recall<br><em>it remembers for you</em>"]
    style F stroke-width:1px
    style P stroke-width:3px
    style U stroke-dasharray: 5 5
    style R stroke-dasharray: 2 4
```

*(solid = shipped · bold = in progress · dashed = ahead)*

## Working milestones — where you can join

Every open issue belongs to exactly one milestone, and every milestone is an
outcome, not a bucket. Pick the one that sounds like you:

| Milestone | The promise | Flavour |
|---|---|---|
| [Settings GUI — click, not config](https://github.com/MSKazemi/yazses/milestone/5) | Configure everything from a window and a tray icon | Desktop / Python / Qt |
| [Install anywhere](https://github.com/MSKazemi/yazses/milestone/6) | One command on every distro and OS — you own a channel | Packaging |
| [Hear better — speech intelligence](https://github.com/MSKazemi/yazses/milestone/7) | Accuracy measured, not asserted: benchmarks, denoising, new engines | Speech / ML |
| [Voice control — beyond dictation](https://github.com/MSKazemi/yazses/milestone/8) | Git, files, windows, and symbols — commanded, not typed | Systems / HCI |
| [Welcome mat](https://github.com/MSKazemi/yazses/milestone/9) | The first hour is easy, the first contribution is likely | Docs / testing / no-code |
| [M0–M3 — Android](https://github.com/MSKazemi/yazses/milestones) | An offline dictation keyboard in your pocket, designed in the open | Mobile / Kotlin |

Start at the [pinned contributor guide](https://github.com/MSKazemi/yazses/issues/22),
or — for research-shaped work — at
[Students, researchers & industry](research/get-involved.md).

## Three principles that never move

- **Offline first.** Transcription runs on your CPU. No telemetry, no network
  dependency for dictation, ever. The one designed cloud-escalation path stays
  deliberately unbuilt so this promise is never quietly weakened.
- **Off by default.** The stable dictation path is small and predictable. The
  large catalogue of capabilities is opt-in: `yazses features enable <name>`,
  then `yazses restart`. An upgrade never changes behaviour you didn't ask for.
- **Honest about what exists.** `yazses features` distinguishes what is wired
  and working from what is designed-but-planned, and refuses to pretend
  otherwise. This roadmap follows the same rule.

## Shipped

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
| **v1.4.x** | 2026-07-01 | Opt-in voice punctuation, a selectable injection backend, and cross-platform CI green again. |
| **v2.12.0** | 2026-07-31 | **First stable v2**: Meeting Mode (hands-free capture → speaker-labelled transcript + minutes), offline recording import with diarization (`yazses transcribe`), Glance-Type on X11, mic-change guard, system tray, "no text target" guard. |
| **v2.13.0** | 2026-08-07 | The reliability release: config self-repair, `yazses autostart enable` for pipx/uv installs, self-retuning VAD gate, supervised tray, `yazses verify` end-to-end proof. |
| **v2.14.0** | 2026-08-07 | The perception release: **Parakeet TDT** second STT engine, gaze deixis with real confidence, sotto-voce command channel, EMG activation seam, honest feature registry. |
| **v2.15.0** | 2026-08-07 | The honesty release: dictation stops deleting real words (contract 1.1.0 → 4.0.0), `doctor` stops giving snap users advice that cannot work, `install.sh` pins and checksums its bootstrap, property-based fuzz tests over the text pipeline. First release to ship all three desktop installers (`.deb`, `.dmg`, `.exe`). **Current stable release.** |

## Future work

The items below are planned directions. We distinguish clearly between what is
**designed but deliberately not built yet** and what is **speculative**.

**Designed, but explicitly deferred:**

- **Cloud escalation for transcription.** Fully designed with strict
  guardrails — and **not implemented**, so the "nothing leaves your machine"
  default is never quietly weakened. Offline remains the only path.
- **Personal speech adapters (LoRA).** On-device fine-tuning that adapts the
  model to your voice — including atypical speech (dysarthria, ALS,
  Parkinson's) — gated on a measured accuracy win on held-out data.
  Prompt-level personalization from your own corpus already ships.
- **Per-language model auto-switching** and **code-switch dictation.** The
  routing layers exist; the language-specific and code-switch models are the
  deferred part.

**Hardware- or model-gated (designed, waiting on the missing piece):**

- **Silent-speech input (sEMG).** The activation seam ships today; it comes
  alive when the wristband hardware is present.
- **Vision-based screen commanding.** Gaze targeting ships on X11; deeper
  pure-vision commanding depends on platform support that is not universal yet.

**Speculative / research directions:**

- Spoken recall — semantic retrieval (RAG) over your personal dictation
  corpus, fully offline. This is the Recall era's core bet.
- Deeper multi-step task chaining over long sessions.

When research directions ship, they follow the same rule as everything else:
off by default, opt-in, on-device.

## Known limitations

- **CPU transcription latency.** Whisper runs on your CPU (int8). First model
  load takes roughly 10–30 seconds, and larger models trade latency for
  accuracy. Choose a model to suit your machine.
- **English-tuned by default.** The default configuration targets English
  (`small.en` / `base.en`). Other languages work; per-language auto-switching
  and code-switch support are still in progress.
- **Desktop-only, today.** An **Android app is in design** — see
  [the mobile programme](mobile/index.md) for the architecture and how to help.
  iOS follows Android for a platform reason explained there.
- **Some capabilities need optional extras or hardware.** Diarization, gaze,
  EMG, neural denoise and others stay dormant until you install their extras
  and enable them.
- **Linux packaging caveat.** Install via the APT script or `pipx` for
  hold-to-talk dictation. The strictly-confined snap cannot read the keyboard
  device, so the snap only serves the offline file-transcription use case.

## Requesting features and reporting bugs

Feedback drives what gets built next. To report a bug or request a feature,
open a GitHub issue — or run:

```bash
yazses about
```

It prints the author, version, project links, and where to report issues.
`yazses doctor` also ends with a contact footer, so if you hit a problem you
always know where to go.
