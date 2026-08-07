# YazSes Roadmap

> **The visionary, graphical roadmap lives in the docs:**
> [Roadmap — eras, milestones, and the destination](https://mskazemi.com/yazses/roadmap.html)
> (`docs/roadmap.md`). Every open issue is filed under one
> [GitHub milestone](https://github.com/MSKazemi/yazses/milestones) —
> Settings GUI · Install anywhere · Hear better · Voice control · Welcome mat ·
> Android M0–M3. This file is the contributor-facing changelog-style detail.

---

## Current frontier — Waves F–O (all OFF by default)

**Stable release: v2.15.0**, published on PyPI, GitHub Releases, Snap, and the APT repo, with
Windows `.exe`, macOS `.dmg`, and Debian `.deb` installers attached to the GitHub release (all
release workflows fire on `v*` tags). The v2 line is delivered as a long series of research
waves, each a fresh state-of-the-art sweep → ADRs → pure, 100%-covered, off-by-default cores.

As of `v2.14.0`: **141 capabilities (68 wired / 72 honestly marked "planned")**, **2066 tests
green**, ADRs `adr-v2-001..129`, research reports in `design/vision/v2-research/` and
`design/vision/library/`.

- **Shipped in `v2.14.0` — the perception release** (ADR-v2-129, all opt-in, lazy deps):
  **Parakeet TDT** second STT engine (`yazses features enable stt-parakeet` — beats
  whisper-large-v3 WER at ~4x whisper-small CPU speed, behind a new pluggable `SttEngine`
  seam); **gaze deixis** ("close this" / "focus that" act on the looked-at window, with
  real per-frame eye-agreement confidence replacing a hard-coded 1.0); the **sotto-voce
  command channel** (whisper a phrase → command, speak → dictation; pure DSP); the
  **activation-source seam** that finally constructs the EMG squeeze-to-talk backend; and
  **registry honesty** (`features enable` refuses the 72 designed-but-unwired entries
  instead of silently doing nothing). Next candidates from the 2026-08-07 study: offline
  Command Mode on selected text (the market's #1 white space), decode-time hotword
  boosting, Moonshine v2 streaming preview, the hands-free accessibility bundle.

- **Shipped in `v2.12.0-dev.2`** (off by default): **Meeting Mode** (`yazses meeting`,
  ADR-v2-127/128) — hands-free whole-meeting capture with a live rolling transcript and an
  accurate batch speaker-diarization post-pass at stop (reuses the ADR-v2-125 recimport cores,
  no new dependency), plus optional local-LLM minutes; and **Glance-Type** (`[gaze]`) now fully
  wired and tested on X11 via a light MediaPipe FaceLandmarker backend (in-RAM frames only).

- **Unreleased (core reliability/UX, on by default)** — **Mic-change guard**: dictation no longer
  dies in silence when the OS default input switches (e.g. a USB-C monitor stealing the mic) — a
  silent-discard streak + an idle-only default-device watcher auto-heal capture back to the last-good
  mic and pop an actionable desktop toast; pin a mic by name with `yazses audio use`. And a **Linux
  system-tray icon** (`yazses tray`, PySide6 `QSystemTrayIcon`, zero new dep): a top-bar "Y" badge
  (blue while working, reddish when idle/problem) whose click-menu picks/pins the mic, re-calibrates,
  and starts/stops the daemon — mic actions apply live over IPC. Plus a **"no text target" guard**:
  dictating with no editable field focused turns the tray **yellow** and copies the transcript to the
  clipboard (instead of typing into the wrong place) — AT-SPI when available, else best-effort X11.

- **Wave F–J** (`v2.2–v2.6`) — dictation/editing/agentic/accessibility features (spoken code, math,
  RAG, meeting scribe, interpreter, gesture chords, screen-grounded dictation, and more).
- **Wave K** (`v2.7`, complete) — chorded shortcuts, focus-class auto-profile, voice undo/redo
  timeline, case transform, auto-pairing, inline compute, spoken table entry, session bookmarks,
  word-goal tracker, local voice timer.
- **Wave L** (`v2.8`, complete) — non-speech & prosodic interaction: vocal joystick, earcon feedback,
  beam-steered spatial VAD, prosodic auto-punctuation, hesitation-hold endpointing, pitch-contour
  gestures, breath-paced dictation, whisper-aware mode, mouth-sound switch access,
  involuntary-vocalization excision.
- **Wave M** (`v2.9`, complete) — minimal-bandwidth AAC & text-intelligence: vocal Morse,
  checksum-validated data entry, semantic line breaks, acronym/glossary manager, style-consistency
  enforcer, suggestion-mode dictation, screenplay auto-format, spoken spaced-repetition capture,
  diagrams-as-code, interruptible read-back proofreading.
- **Wave N** (`v2.10`, complete) — structural editing, i18n & accessibility-output: HatSelect
  (Cursorless-style structural token editing), transliteration (romanized → native script), BrailleOut
  (Grade-2 UEB), spoken outline (→ Markdown/OPML), diacritic restoration, homoglyph safety (UTS-39),
  reverse-dictionary (WordFind), cognitive-load guardrails (LoadGuard), own-audio replay (Echo), and
  screen-reader-paced injection (SRPace).
- **Wave O** (`v2.11`, open) — offline media ingestion & speaker attribution: **Diarized Recording
  Import** (`yazses transcribe <file>` — decode any audio format, transcribe offline, tag speakers via
  sherpa-onnx, name them from `--names`/enrolled voiceprint, write a `.txt`/`.md`/`.srt`/`.vtt`/`.json`
  sidecar; ADR-v2-125). Cloud escalation designed but deferred (ADR-v2-126).

See `CHANGELOG.md` and `docs/releases/` for per-tag detail, and `docs/v2-features.md` for the full
capability catalog.

---

## Mobile — Android wave 1 (design complete 2026-08-07, **no code yet**)

A second, parallel programme, run in the open and built by contributors: **YazSes for
Android** — a keyboard whose mic key you hold to dictate into any app, fully on-device, with
the app's network access revocable. Design first, on purpose, so that many people can build
it at once without re-deciding the same questions in PR review.

- **Ten binding ADRs** (`docs/mobile/adr/`, public): Android first and in this repo · native
  Kotlin with pure-JVM cores · IME-first delivery and **no `AccessibilityService`** ·
  hold-the-mic-key and **no wake word** · a pluggable STT seam with whisper.cpp as default ·
  models downloaded and SHA-256-verified, never bundled · a permission budget with
  `INTERNET` in exactly one module and a CI privacy gate · **a language-neutral contract of
  golden vectors that both the Python desktop and the Kotlin app must pass** · F-Droid-shaped
  distribution · and the Apple wave, which must be a *different product shape* because iOS
  forbids microphone access to keyboard extensions.
- **Why Android before iPhone:** platform capability, not preference — Android's
  `InputMethodService` can hold the mic and type into any app; no iOS app extension can.
  **macOS is already supported** by the desktop app.
- **Milestones:** M0 foundations (contract + Gradle skeleton — *Python-only work, open now*)
  → M1 "it types what I say" (first signed APK) → M2 good enough to replace your phone's
  dictation (F-Droid; the iOS wave may start here) → M3 file transcription, diarization,
  Meeting Mode → M4 Play and reach.
- **Where to start:** `docs/mobile/index.md`, then `docs/mobile/contributing.md`. Issues are
  labelled `android`, coordinated by the Android epic (#81); the Python-only M0 tasks
  (#82, #83) are open now.

---

## v2.1.0 (in progress) — Wave D: new frontier features

A fresh 2026 SoA round on top of the v2 layer (`design/vision/v2-research/06-wave-d.md`,
`design/adr/adr-v2-014..024`). Still 100% on-device, every feature **off by default**.
Dev tags `v2.1.0-dev.1/2/3` cut (do **not** auto-publish; v1.4.1 stays stable).

- **Ship-now (dev.1):** Speech Translation (X→English) · Tone-Aware Formatting · Predictive
  Completion · Noise Suppression (DeepFilterNet).
- **Medium (dev.2):** Voice Guard (biometric + anti-spoof, experimental) · Meeting Scribe
  (streaming diarization) · Ask My Notes (voice-grounded, cited RAG).
- **Hardening + seams (dev.3):** atypical-speech LoRA held-out gate (ADR-v2-021) · codec
  streaming engine-selection seam (ADR-v2-022); every pure v2 core to 100% coverage.
- **Designed, hardware-gated:** silent-speech sEMG (ADR-v2-023) · pure-vision VLM screen
  commanding (ADR-v2-024) — ADRs written, implementation deferred until hardware.

### Wave E (dev.4/5) — more frontier features (ADRs 025-034, all off by default)
- **Ship-now (dev.4):** Hallucination Guard · Voice Snippets · Phonetic Corrector · Multi-User
  Voiceprint Profiles.
- **Zero-touch + modes (dev.5):** Hands-Free Auto-Stop · Voice Mouse Grid · Spoken Code Mode ·
  Spoken Math→LaTeX · Wake-Word Activation (exp) · Vocal-Strain Guard. Wake-Word + Auto-Stop +
  Mouse Grid compose into a hands-free operating mode. 45 features, 1032 tests, pure cores 100%.

---

## v2.0.0 (planned) — the Voice-First Interaction Layer

YazSes grows from offline dictation into a broader **voice-first HCI layer** — still 100%
on-device, privacy-first, every feature **off by default**. Grounded in a 2026-07 SoA
research sweep (`design/vision/v2-research/`) and specified in `design/adr/adr-v2-*` +
`design/vision/v2-2026/00-synthesis-10-features.md`. Delivered in three waves; the
`v2.0.0-dev` tag is cut only when Wave A code + tests land.

- **Wave A (ship-now on current stack):**
  - **Confidence Ink & Voice Re-pick** — surface Whisper token-confidence; re-pick homophones
    from n-best by voice instead of re-dictating. (ADR-v2-001)
  - **Prosody Auto-Formatting** — pauses → punctuation/paragraphs, stress → emphasis. (ADR-v2-002)
  - **Spoken Edit Mode** — open-ended voice editing ("change X to Y", "delete last sentence").
    (ADR-v2-003)
  - **Context-Primed Dictation & Commanding** — active window/selection/clipboard/LSP →
    initial_prompt + deictic command resolution, transient & never stored. (ADR-v2-004)
- **Wave B:** Spoken Recall & Ambient Scratch · Voice-to-Tool (offline Spoken MCP) · AT-SPI
  Voice Pilot (accessibility-tree control, no screenshots) · True Code-Switch dictation ·
  Personal Speech Adapter (on-device LoRA/few-shot from the corpus).
- **Wave C (experimental):** Gaze-Routed Dictation & Point-and-Speak · sEMG Command Layer +
  Modality Role Router · Accessibility Continuum (whisper mode, semantic endpointing,
  effort-adaptive, progressive voice) · Glasses↔Desktop dictation bridge.

---

## v1.4.1 — 2026-07-01 — cross-platform CI + release reliability

- Cross-platform test matrix green again (Linux × macOS × Windows, py3.11/3.12): guarded
  Unix-only imports (`evdev`/`grp`/`pwd`/`os.getuid`).
- Snap release fails loudly on the canonical repo when store creds are missing (was silently
  skipped → stuck at 1.2.0 for 9 releases); PyPI publish idempotent (`skip-existing`).
- Canonical public home moved to `MSKazemi/yazses`; PyPI + Snap now publish from there.

---

## v1.4.0 — 2026-07-01 — voice punctuation & injector backend

- Opt-in **voice punctuation & formatting** ("comma"/"period"/"new line" → symbols).
- Selectable **injection backend** (`auto`/`type`/`clipboard`/`wtype`) with a Wayland
  flood guard for Ubuntu 26+ compositors.

---

## v1.3.0 — 2026-06-23 — overlay on by default

- **Voice-activity overlay enabled by default** (`[overlay] enabled = true`) and
  **PySide6 promoted to a base dependency**, so the overlay works on a fresh install
  with no extra step. Older glibc (<2.28) logs a hint and skips the overlay instead
  of failing; dictation is unaffected. Opt out with `[overlay] enabled = false`.
- Repo polish: a 1280×640 GitHub/social-preview card for link unfurls.

---

## v1.2.0 — 2026-06-20 — CLI usability

Friendlier control surface, no TOML hand-editing:
- `yazses features [enable/disable <name>]` — a switchboard for every capability,
  with on/off + advice tiers (core/recommended/optional/experimental); experimental
  features refused without `--force`.
- `yazses vocab [add/list/remove]` — personal dictionary merged into the STT prompt.
- `yazses hotkey [show/set]` — change the hold-to-talk key from the CLI.
- `yazses hotkey command <key>` — bind a dedicated **command key**: while held, speech
  is parsed as a command and never typed as literal text (unmatched phrases ignored).
  The dictation key keeps its text + command-auto-detect behaviour.
- `yazses restart` + `yazses start` no longer spawn duplicate daemons (kills stray
  detached ones), directly fixing duplicate-daemon double-typing.
- Cocktail Filter moved to default-OFF + unenrolled-safe after live testing showed
  the 0.5 s personal-VAD window false-rejects the user's own voice.

---

## Next — v2 Perceptual & Personalization layer (post-1.0)

The four remaining v2 features (Voiceprint Mind, Cocktail Filter, Glance-Type,
Polyglot Switch) have **complete technical plans** in
`design/v2-cognitive-layer/` (master `ROADMAP.md` + four implementation plans,
grounded in the SoA dossier + a 2026 web refresh). Build order: shared `voiceprint/`
enrollment → Glance-Type P1 (look-to-pane) + Cocktail Filter P1 (personal-VAD gate) →
Voiceprint Mind P1 (biasing) → the training-gated parts (LoRA personalization, the CS
adapter). Each P1 lands as a minor release; the training-dependent parts ship behind
held-out WER/MER gates. See that directory before implementing.

**Update (v2.12.0-dev.2):** **Glance-Type P1 (look-to-pane) shipped** — fully wired
and tested on X11 with a lightweight MediaPipe FaceLandmarker gaze backend (glance at
a pane, the next dictation lands there). Voiceprint Mind P1 (biasing) and Cocktail
Filter P1 (personal-VAD gate) were wired earlier. Glance-Type stays dormant on
GNOME/Wayland (no external window-focus). Remaining: Polyglot Switch CS adapter and
the training-gated LoRA parts.

---

## Shipped

### v0.3.0 — 2026-05-15
Five new capabilities from the SoA2Prod innovation pipeline:

| Capability | Status |
|---|---|
| **SSH/Remote voice forwarding** (`yazses remote <host>`) | ✅ Shipped |
| **Streaming transcription** (LocalAgreement + correction-on-commit) | ✅ Shipped |
| **Code command grammar** (28 voice intents → key sequences, ≥90% precision) | ✅ Shipped |
| **Offline disfluency filter** (filler removal, 2-gram dedup, self-correction) | ✅ Shipped |
| **Accessibility enrollment wizard** (`yazses enroll`, calibrated VAD, pre-speech buffer) | ✅ Shipped |

### v0.2.0 — 2026-05-08
- Cross-platform: macOS (CGEvent) + Windows (SendInput) support
- Tray icon (rumps on macOS, pystray on Windows)
- All three platform installers (.dmg, .exe, .deb)
- Homebrew cask, APT repo, Snap Store, PPA pipeline

### v0.1.x — Linux only
- evdev hotkey, xdotool/ydotool/wtype injection, systemd lifecycle, faster-whisper

---

## In progress

### Distribution channels (v0.2.x)
- **winget** — PR under review at microsoft/winget-pkgs
- **Snap Store** — snapcraft.yaml bumped to v0.5.0 (2026-05-31); needs `SNAPCRAFT_STORE_CREDENTIALS` secret set to publish
- **AUR** — needs AUR account + PKGBUILD push
- **macOS signing** — Apple Developer account enrolment

---

## Shipped

### v1.1.0 — 2026-06-19 — **v2 layer cores + doctor/UX polish**
Ships the v2 perceptual/personalization P1/P0 cores (voiceprint, Glance-Type,
Cocktail Filter, Voiceprint Mind, Polyglot Switch — all off by default) plus:
- **Spoken-name recognition:** the coined app name "YazSes" is always primed into
  Whisper's `initial_prompt` (`stt/vocabulary.py`) so dictating it no longer
  mis-transcribes.
- **`yazses doctor` enriched:** installed version, daemon status (PID/state/model),
  STT-model availability, config + hotkey summary, opt-in `--mic` ambient-vs-VAD check.
- **Fixes:** overlay package was silently dropped from the wheel by an unanchored
  `.gitignore` glob (`overlay/` → `/overlay/`); CLI `start`/`test` now show the
  configured hotkey, not the platform default; `__version__` synced to the release.
- 650 tests.

### v1.0.0 — 2026-06-19 — **first stable release of the Python app (Part 1)**
The Python line graduates to 1.0: fully-offline hold-to-talk dictation for
Linux/macOS/Windows with a deep, off-by-default feature set (dictation core +
disfluency filter, command grammar + Say-Macro + Mid-Thought Undo + Punch-In +
Prosody Ink + Ghost Ahead, Dysfluency-Friendly Mode, Read-Back Loop, the encrypted
learning loop + `yazses tune`, remote dictation, overlay, EMG/BLE, LLM cleanup, a
friendly CLI + `yazses update`). 586 tests.
- **New since 0.9.0:** **Read-Back Loop (P1)** — an offline neural TTS voice
  (Kokoro-82M) speaks the transcript back (eyes-free), with a push-to-talk
  echo-loop interlock + barge-in (`[tts]` + `[accessibility] read_back`, `yazses
  say`). **Reliability:** single-instance lock kills the duplicate-daemon
  double-typing bug. **Infra:** PyPI publish CI fixed (`contents: read`), snap
  publish hardened, and the Rust HCI rewrite archived on `archive/rust-hci-v1`.
- Tagged `v1.0.0`. The 1.x line is now Part 1 (the Rust release workflow is archived).

### v0.9.0 — 2026-06-19
CLI quality-of-life: new `yazses update` self-update command (snap channel / PyPI,
never downgrades), a friendlier help system (global `-h`, copy-pasteable Examples,
grouped command panels, `<Tab>` completion, `-V`), and an `install-local.sh`
cache-bust fix so same-version source edits reinstall.

### v0.8.0 — 2026-06-19
Dysfluency-Friendly Mode (ADR-015): an opt-in collapse pass cleans stuttered/dysarthric
speech (`b-b-because`→`because`, `sooo`→`so`, `the the the`→`the`) out of the final text,
guarded against intentional speech, off by default, fully offline. The accessibility-OS
axis made concrete — grounded in Lea et al., CHI 2023. Pre-registered eval gate (0%
false-collapse, 92.9% recall). Endpointing out of scope (hold-to-talk). 536 tests.

### v0.7.0 — 2026-06-19
Held-out validation for the learning loop (ADR-014): `yazses tune` now corroborates
every proposal against a recent, held-out slice of the corpus it was not derived
from and labels each *validated / unverified / unvalidated*, closing the
train/test-overlap self-evaluation gap surfaced by the accountable-autonomy
research review. Behaviour unchanged below 20 captured events; fully offline. 522 tests.

### v0.6.0 — 2026-06-19
Python daemon runtime wiring for three v2 decision cores (all **off by default**;
specs in `design/specs/`). 507 tests.

| Capability | Spec | Status |
|---|---|---|
| **Prosody Ink** (`[prosody]`) — pause→paragraph (no dep) + emphasis→**bold** (parselmouth `prosody` extra); batch dictation only; opt-in `transcribe_words()` word-timestamp path | spec-prosody-ink | ✅ Shipped (Phase 1) |
| **Ghost Ahead** (`[endpoint]`) — endpoint anticipation pre-warm; authoritative transcript stays on hold-release | spec-ghost-ahead | ✅ Shipped (Phase 1 pre-warm) |
| **Punch-In** (`[punch_in]`) — `yazses punch-in` re-record + difflib align + retype; ledger text retention | spec-punch-in | ✅ Shipped |

Deferred (need real hardware/models): Prosody Phase 2 latency gate, Ghost Ahead
Phase 0 harness + speculative finalize, and the four model-blocked v2 features
(Cocktail Filter, Voiceprint Mind, Polyglot Switch, Glance-Type). Read-Back Loop —
the 6th feature — shipped P1 (see *Unreleased* above).

### v0.5.1 — 2026-05-31
Install reliability + dictation-quality fixes: DISPLAY inheritance for all
install methods, inter-burst continuation spacing, offline LLM dictation cleanup
(ADR-013), and opt-in editor edit-capture. Snap strict confinement (X11 grab
hotkey). See CHANGELOG.

### v0.5.0 — 2026-05-29
Opt-in, local, encrypted self-improvement loop (ADR-012): `yazses tune` /
`mark-wrong` / `corpus` over an encrypted SQLite corpus, plus the `yazses-overlay`
voice-activity sonar. Off by default (honours ADR-011: nothing leaves the machine).

### v0.4.0 — 2026-05-17
Three capabilities from the second SoA2Prod pipeline (`research/yazses-future-voice-hci/`):

| Capability | ADR | Status |
|---|---|---|
| **Offline SLM intent routing** (llama-cpp-python, Tier 2 grammar) | ADR-v04-001 | ✅ Shipped |
| **LSP code context injection** (pynvim, Neovim bridge, initial_prompt) | ADR-v04-002 | ✅ Shipped |
| **EMG silent speech backend** (YESP/USB serial, HotkeyBackend) | ADR-v04-003 | ✅ Shipped |

### v0.4.1 — 2026-05-17

| Capability | Status |
|---|---|
| **BLE EMG transport** (bleak, Nordic UART Service, same YESP protocol) | ✅ Shipped |
| **`yazses model list / download`** (GGUF model manager, Qwen2.5-0.5B + Phi-3-mini) | ✅ Shipped |
| **VSCodeBridge** (reads vscode-context.json, auto-detected in `lsp_editor = "auto"`) | ✅ Shipped |
| **Dep refresh** (all packages to latest stable; pytest-cov added) | ✅ Shipped |
| **snap fix** (python3-pip-whl in stage-packages) | ✅ Shipped |

---

## v1.0 Rewrite (Rust core + Python plugins) — archived on `archive/rust-hci-v1`

> **Status: paused / archived.** The Rust HCI rewrite was moved off `main` to the
> `archive/rust-hci-v1` branch; `main` is the Python app (Part 1). The section
> below describes the Rust exploration as it stood when it was parked.

YazSes v1.0 is a ground-up Rust rewrite adopting the **Cognitive Exocortex**
architecture — voice-first on-device agentic OS layer. The Python v0.4.x
pipeline is preserved in parallel.

### Implementation status — all phases complete ✅

| Phase | Scope | Commit | Status |
|---|---|---|---|
| Phase 0 | IPC + daemon scaffold | a452ad7 | ✅ |
| Phase 1 | Input + Audio | 3735c4d | ✅ |
| Phase 2 | STT (STTRouter, Moonshine v2, Whisper) | cac7321 | ✅ |
| Phase 3 | LLM + Constraint (llama.cpp, GBNF, 20 tools) | 1987ab2 | ✅ |
| Phase 4 | Editor Bridges (5-tier WindowDetector, Neovim, VS Code) | 4006852 | ✅ |
| Phase 5 | Memory + Dispatcher + pipeline wiring | 4d5ee68 | ✅ |
| Phase 6 | Doctor + Accessibility (AT-SPI, NVDA, Talon) | 84c6d2d | ✅ |
| Phase 7 | Distribution (cargo-dist, deb, rpm, Homebrew, winget) | 85809fd | ✅ |
| Post-phase | Pipeline fixes, OS actions, protocol, observability | 098a67f | ✅ |

**v1.0.0-dev.5** tagged — all phases complete, merged to `main`. Current state: **pre-beta, documentation in progress**.

### Before v1.0.0-rc1

- [x] Documentation: README v1.0, architecture.md, 11 ADRs in docs/adr/, install guides, privacy statement, threat model, plugin SDK reference, migration guide v0.4→v1.0
- [x] Homebrew formula v1.0.0 (formula, not cask — CLI binary) + winget manifests v1.0.0 prepared (SHA256 placeholders — fill with `scripts/patch-release-shas.sh 1.0.0` after CI release build)
- [x] `apt-repo.yml` updated to trigger on "Rust Release" workflow — v1.0 `.deb` auto-publishes on tag push; v0.4 packages retired automatically (existing `update-apt-repo.sh` replaces all `yazses_*.deb`)
- [ ] Run `bash scripts/patch-release-shas.sh 1.0.0` after CI produces the v1.0.0 release artifacts
- [ ] Beta testing / dogfooding ≥ 4 weeks (production readiness Re-06, started 2026-05-18)

### Before v1.0.0 GA

- [ ] All production readiness checklist items green (docs/adr/production-readiness.md)
- [ ] Cross-platform CI green on Linux + macOS + Windows
- [ ] Beta-tester feedback incorporated

---

## Shipped on `main` after v1.0.0-dev.5 (2026-05-29, not yet tagged)

A research-driven feature/quality push (Apple/Microsoft/Azure + papers scan;
see `.claude/plans/2026-05-29-competitive-features-plan.md` and memory
`project_competitive_features` / `project_voice_activity_overlay`).

| Item | Where | Status |
|---|---|---|
| **Voice-activity overlay** (sonar rings near cursor, voice-reactive) | Python `yazses-overlay` + `audio_level` in both daemons' `status` | ✅ Shipped |
| **Offline LLM dictation cleanup** (modes, guards, fallback) — ADR-013 | Rust `yazses-llm/cleanup.rs` | ✅ Shipped |
| **Custom vocabulary / dictionary** (STT biasing + token correction) | Rust `yazses-llm/vocabulary.rs` | ✅ Shipped |
| **Spoken formatting commands** (new line / paren / …) | Rust `yazses-llm/dictation_commands.rs` | ✅ Shipped |
| **Per-app cleanup modes** (`YAZSES_CLEANUP_APP_MODES` + table) | Rust `yazses-llm/cleanup.rs` | ✅ Shipped |
| **VAD hysteresis + hangover** endpointing | Rust `yazses-audio/vad.rs` | ✅ Shipped |
| **Deterministic mechanics polish** (caps/punct, no-LLM path) | Rust `yazses-llm/mechanics.rs` | ✅ Shipped |
| **Stronger cleanup token guard** + **STT prompt biasing** | Rust `cleanup.rs` + `daemon.rs` | ✅ Shipped |

All new dictation behavior is `YAZSES_*` env-gated and **off by default**
(default pipeline byte-identical). `cargo test --workspace` green; clippy clean.

### Deferred backlog — next-session pickup
- [ ] **Cut a release tag** for the above (versioning is mixed: Python `0.4.1`, learning `v0.5.0`, Rust `1.0.0-dev`) — decide a number.
- [ ] **Live-hardware verification** of the overlay + new dictation flags (only end-to-end gap; unit-tested already).
- [ ] **2 moderate Dependabot advisories** on the default branch — investigate + bump.
- [ ] **Wire a real `WindowDetector`** so per-app cleanup modes actually activate (daemon default is `NullWindowDetector`).
- [ ] **STT model evaluation** — Parakeet-TDT / Distil-Whisper swap vs Moonshine/Whisper (accuracy + CPU latency).
- [ ] **Semantic VAD / neural endpointing** layer on top of Silero + the new hysteresis gate.
- [ ] **Inference perf** — KV-cache quantization + prompt caching in the llama.cpp path.
- [ ] **TOML config loader** for the Rust core (currently all `YAZSES_*` env vars).

## Planned

### v2.0 — Deep-tier routing and advanced intelligence
- Tier::Deep LLM routing: multi-step reasoning, cross-turn context, agentic task chaining over long sessions.
- RAG memory: semantic retrieval over personal note corpus (sqlite-vec ANN, BGE-small-en embeddings) replacing linear O(n) scan.
- LoRA adapters for atypical speech: personal model fine-tuning for users with dysarthria, ALS, or Parkinson's (gap-005b).
- sEMG wristband input: silent-speech channel via surface electromyography wristband (BLE YESP), enabling fully silent dictation in open-plan offices.

---

## Research output

Full SoA2Prod pipeline (11 stages, 8 gaps, 5 ADRs, PRD, eval plan):
`research/yazses-innovation/`

Build prompts for future capabilities:
`research/yazses-innovation/output/10_build_prompt.md`
