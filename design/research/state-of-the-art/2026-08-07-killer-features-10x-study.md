# Killer Features 10x — State-of-the-Art Study & Program (2026-08-07)

**Date:** 2026-08-07 · **Tier:** `design/` — public engineering research
**Companion:** [voice-dictation market landscape](2026-08-07-competitor-landscape.md) ·
[local/offline STT engine SoA](2026-08-07-stt-engine-sota.md) ·
[gaze / EMG / BCI / multimodal input SoA](2026-08-07-hci-input-sota.md) ·
[ADR-v2-129: Killer Features 10x](../../adr/adr-v2-129-killer-features-10x.md)

Synthesis of the three companion state-of-the-art studies above plus a full codebase
reachability audit (2026-08-07, 132 subpackages). Written as the direct planning
input to what became ADR-v2-129.

**Goal at the time:** make the project's differentiating input features an order of
magnitude more real and more capable — gaze, voice, and eventually muscle-based
control — with every heavy addition staying opt-in and lazy-installed, so the base
dictation install stays small.

## 1. Where the project stood at the time

**Already differentiated (nothing surveyed matched these):** fully offline across
Linux and 3 operating systems; offline diarized meeting minutes; a local, encrypted,
self-improving learning loop; a reliability layer (microphone auto-heal, a
no-text-target guard, an end-to-end pipeline verifier); gaze-routed dictation; an EMG
hotkey (designed but not yet wired); SSH remote forwarding.

**Behind the surveyed market on:** voice-editing of already-typed text (a cloud-only
feature elsewhere), per-app tone matching, custom AI prompt modes, and sub-second
perceived latency as a default.

**What the codebase audit found:** 72 of 132 subpackages (~4.3k LOC) were
transitively unreachable from the daemon and CLI at the time; 69 of 139 feature-
registry entries toggled configuration that nothing read (`features enable` was
technically lying about what it turned on); the EMG backend was complete but never
constructed by any code path; a wake-word predicate existed with no spotter behind
it; the STT engine was hard-wired to faster-whisper at three separate levels (no
Protocol, no factory, and the streaming engine reached into a private attribute); and
the gaze pipeline hard-coded `confidence=1.0` for its default backend, silently
making a documented confidence threshold a no-op.

**What "10x" meant here:** not new packages, but (a) making the advertised exotic
input methods real and honestly reported rather than half-wired, (b) upgrading the
perception layer with the zero-dependency moves the two companion SoA studies
surfaced, and (c) breaking the single-engine STT assumption for a real step change in
accuracy and latency.

## 2. The resulting program

### Wave 1 — perceptual input (zero new required dependencies; all opt-in)

| # | Feature | SoA basis | Why it mattered |
|---|---|---|---|
| 1.1 | Real gaze confidence for the default backend (landmark-stability/presence-derived), replacing the hard-coded 1.0 | MediaPipe/MobileGaze practice | The confidence threshold starts actually gating routing instead of doing nothing |
| 1.2 | Gaze deixis — resolving "close this"/"focus that" against the gaze zone snapshotted at hold-start | GazePointAR/SemanticScanpath late fusion; +26.5% coreference payoff; an open gap in the surveyed field | Turns gaze routing into gaze *reference* |
| 1.3 | A whispered-speech command channel via a numpy fundamental-frequency gate | The DualVoice pattern (UIST 2022) | A socially quiet mode-switch channel not seen elsewhere in the survey |
| 1.4 | A pluggable activation-source seam, with the daemon constructing an EMG backend when configured | Nature 2025 sEMG validation; EMG's realistic role as a trigger, not a text channel | Makes the advertised muscle-control input real, and opens the same seam for a future wake word or other switch |
| 1.5 | Registry honesty — `features enable` refuses, with a clear message, any entry whose package nothing imports yet | Project value: never claim a capability is on when it is not | Restores trust in the feature registry |

### Wave 2 — engine (opt-in, lazy-installed)

| # | Feature | SoA basis | Why it mattered |
|---|---|---|---|
| 2.1 | An `SttEngine` protocol and factory, removing the streaming engine's dependency on a private attribute | codebase audit | Unlocks a second engine everywhere in the pipeline |
| 2.2 | A Parakeet TDT 0.6B backend via `onnx-asr` int8, auto-installed on `features enable stt-parakeet`, model auto-downloaded on first use | 6.32% WER, beating large-v3's 7.44%, at ~30x realtime CPU; no silence hallucination; CC-BY-4.0; pure Python | Better-than-large-v3 accuracy at roughly the latency of a 5-second burst, fully offline |

### Wave 3 — offline command mode

Voice-editing of selected text with a local LLM: select text anywhere, hold the
command key, say "make this shorter" or "fix the grammar" or "turn into bullets."
Reuses the existing command-key mode, clipboard machinery, output-side rewrite
guards, and grammar constraints. Every product offering this in the market survey was
cloud-only.

### Deferred at the time (recorded, not built in this wave)

- Implicit gaze calibration from mouse clicks (needs a click listener; a later
  iteration).
- A hands-free accessibility bundle (dwell-to-talk, face-gesture switches,
  Wayland-compatible injection) — recorded as a full wave of its own.
- Moonshine v2 streaming preview; decode-time phrase boosting; small-model cleanup
  presets; per-app tone profiles; custom prompt modes.
- Explicitly set aside: consumer EEG triggers (artifact-grade, dominated by EMG on
  every axis measured), lip-reading/AVSR (non-commercial weights, not CPU-real-time),
  silent-speech sEMG (~68% WER), and the Meta Neural Band (no raw EMG access, no
  Linux path).

## 3. Design invariants this program stayed inside

Offline by construction and off by default (see the project's privacy/threat model);
every heavy addition ships as a lazy-installed optional extra so the base install
stays lean; each new input integrates at a single daemon seam behind a Protocol; and
`probe_backend`-style honest error messages for anything not yet shipped, rather than
a silent no-op.

### What shipped

[ADR-v2-129](../../adr/adr-v2-129-killer-features-10x.md) records this program as
accepted and implemented in the same change. See `design/v2-cognitive-layer/` for the
resulting design notes, and `design/adr/` for the individual decisions (gaze deixis,
sotto-voce, the activation-source seam, and the pluggable STT engine each has its
own ADR).
