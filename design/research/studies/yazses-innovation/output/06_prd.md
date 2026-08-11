---
id: "prd-yazses-v030"
title: "YazSes v0.3.0 — Product Requirements Document"
type: prd
scenario: yazses-innovation
capabilities:
  - cap-001
  - cap-002
  - cap-003
  - cap-004
  - cap-005
created_at: 2026-05-14
updated_at: 2026-05-14
confidence: high
status: approved
---

# YazSes v0.3.0 — Product Requirements Document

## 1. Product Vision

YazSes is the world's best offline, cross-platform voice dictation daemon for developers, accessibility users, and power users who require privacy-first, zero-cloud, zero-GPU voice input. [HYPOTHESIS: this positioning is achievable within the v0.3.0 milestone]

v0.3.0 closes the five most critical gaps identified in the SoA2Prod gap analysis: remote session support, streaming real-time display, code-aware commands, disfluency filtering, and accessibility accommodations. After v0.3.0, YazSes will be the only open-source voice tool that works over SSH, displays partial transcription live, understands code commands, and runs entirely offline on CPU.

## 2. Target Users

| Persona | Description | Primary Cap |
|---|---|---|
| P1: Developer (RSI/keyboard fatigue) | Software engineers on Linux who need voice-first coding; currently use Talon or Serenade but lack Linux-native offline alternative | cap-002, cap-003 |
| P2: Remote/DevOps engineer | Engineers connecting to remote servers via SSH or VS Code Remote SSH daily; cannot use any existing dictation tool in remote session | cap-001 |
| P3: Accessibility user (atypical speech/motor) | People with ALS, Parkinson's, dysarthria, or severe RSI; need personalised models and keyboard alternatives | cap-005 |
| P4: All dictation users | Every YazSes user benefits from cleaner dictation output | cap-004 |

## 3. Capability Requirements

### 3.1 cap-001 — YazSes Remote (SSH/Remote Voice Forwarding)

**Goal:** Enable voice dictation in SSH sessions, VS Code Remote, and tmux on remote servers, with audio capture and ASR running locally.

**Functional requirements:**
- FR-001.1: A new CLI subcommand `yazses remote --host <user@host> [--port N]` establishes a voice-forwarding session to a remote machine.
- FR-001.2: Audio capture and Whisper transcription run on the **local** machine only. Audio data MUST NOT be transmitted to the remote machine.
- FR-001.3: Transcribed text is forwarded to the remote machine over an SSH-tunnelled UNIX socket or TCP loopback. The transport MAY use SSH port forwarding (`-R`) or a dedicated YazSes SSH channel.
- FR-001.4: A new lightweight remote agent (`yazses-remote-agent`) runs on the remote machine, receives text over the tunnel, and performs text injection using the remote machine's available injector (xdotool/ydotool/wtype on Linux; SendInput on Windows; CGEventPost on macOS).
- FR-001.5: `yazses-remote-agent` has zero ASR dependencies. It installs as a single Python script or binary with no faster-whisper requirement.
- FR-001.6: Session state is displayed in the local CLI: `[REMOTE ACTIVE] user@server — connected — IDLE`.
- FR-001.7: Hold-to-talk hotkey is detected on the **local** machine and forwarded as a control signal to the remote agent.

**Non-functional requirements:**
- NFR-001.1: Text injection latency (from end of speech to character appearing on remote terminal) MUST be <500 ms on LAN, <800 ms on WAN (100 ms RTT link).
- NFR-001.2: Must work with OpenSSH, mosh-server (mosh path advisory only), and VS Code Remote SSH extension.
- NFR-001.3: Connection setup MUST NOT require root on either end.

**Out of scope (cap-001):** Audio forwarding over SSH (RTP/WebRTC) — ASR always runs locally. Display server forwarding (X11 forwarding). Remote GUI tray.

---

### 3.2 cap-002 — Streaming Transcription with Real-Time Display and Correction

**Goal:** Display partial transcription text in the active window as the user speaks, and silently correct it when the final transcript is committed.

**Functional requirements:**
- FR-002.1: During a hold-to-talk recording, the daemon MUST emit partial transcription hypotheses to the active window at intervals of ≤400 ms.
- FR-002.2: Partial text is injected as live characters (same injection path as final text). The daemon MUST record the cursor offset of the first partial character injected.
- FR-002.3: The LocalAgreement policy [EVIDENCE src-002] is used to determine stable prefixes: text confirmed by 2+ decode iterations is considered stable and not re-emitted.
- FR-002.4: On final transcript commit (hotkey release + end-of-speech silence), the daemon MUST: (a) select all partial text injected since the start of the utterance, (b) replace it with the disfluency-filtered final transcript (cap-004 applied), and (c) position cursor at end of injected text.
- FR-002.5: If the active application cannot support selection-replace (e.g., terminal emulators in some modes), the daemon MUST fall back to: backspace-delete the partial text character by character, then inject final text.
- FR-002.6: Streaming mode MUST be configurable: `yazses config set streaming.enabled true/false`. Default: `true`.
- FR-002.7: Partial text visual indicator: prefix partial text with a configurable marker (default: none; option: dim/italic escape codes where supported).

**Non-functional requirements:**
- NFR-002.1: First partial hypothesis MUST appear within 600 ms of speech onset.
- NFR-002.2: Final-correction replace operation MUST complete within 200 ms.
- NFR-002.3: No partial text must persist in the window after a cancelled recording (hotkey pressed then released within 0.3 s before speech starts).

**Out of scope (cap-002):** Per-word streaming (sub-word granularity). Streaming over remote sessions (that's cap-001 v2 enhancement).

---

### 3.3 cap-003 — Code Command Grammar

**Goal:** Recognise a set of code-editing and terminal voice commands from transcribed text and dispatch them as structured intents, without replacing the underlying ASR model.

**Functional requirements:**
- FR-003.1: A new module `yazses.commands.code` classifies transcribed text into one of five intents: `DICTATE`, `NAVIGATE`, `EDIT`, `REFACTOR`, `TERMINAL`.
- FR-003.2: The classifier MUST operate as a pure text post-processor (no audio reprocessing, no GPU). Runtime budget: <5 ms per transcript.
- FR-003.3: Minimum required command set (MVP):

  | Command phrase | Intent | Action |
  |---|---|---|
  | "delete [last N words/lines]" | EDIT | backspace N words/lines |
  | "undo [that/N times]" | EDIT | inject Ctrl+Z ×N |
  | "go to line [N]" | NAVIGATE | inject Ctrl+G, type N, Enter |
  | "go to [function/class/method] [name]" | NAVIGATE | inject IDE goto shortcut |
  | "run [that/tests/build]" | TERMINAL | inject appropriate command |
  | "save [file]" | EDIT | inject Ctrl+S |
  | "copy [that/line/selection]" | EDIT | inject Ctrl+C |
  | "paste [here]" | EDIT | inject Ctrl+V |
  | "rename [this/symbol] to [new name]" | REFACTOR | IDE rename shortcut |
  | "new [function/class/file] [name]" | EDIT | insert skeleton template |
  | "comment [this/line/selection]" | EDIT | inject IDE comment shortcut |
  | "select [N lines/to end/all]" | NAVIGATE | inject shift-key combination |

- FR-003.4: Unrecognised text falls through to `DICTATE` (raw text injection) with zero user interruption.
- FR-003.5: Commands are emitted as JSON-RPC events on the IPC socket in addition to (or instead of, for pure commands) text injection.
- FR-003.6: User-configurable custom commands via config.toml: `[[commands]] phrase = "run my test" action = "shell:pytest tests/ -v"`.
- FR-003.7: A profile system activates command sets per application: `[commands.profiles.vscode]`, `[commands.profiles.neovim]`, `[commands.profiles.terminal]`.

**Non-functional requirements:**
- NFR-003.1: Command recognition precision ≥ 90% on the MVP command set in a clean English evaluation set.
- NFR-003.2: Zero false-positive command triggering on a 500-word dictation-only corpus (no commands in the text).

---

### 3.4 cap-004 — Offline Disfluency Filter

**Goal:** Remove filler words, repeated phrases, and self-corrections from transcribed text before injection, without requiring a network connection or GPU.

**Functional requirements:**
- FR-004.1: A new pipeline step `yazses.stt.filters.disfluency` is applied to all final transcripts before injection.
- FR-004.2: Filler word removal: configurable list of filler patterns. Default list: "um", "uh", "er", "ah", "hmm", "like", "you know", "I mean", "basically", "right", "okay so". Patterns matched case-insensitively at word boundaries.
- FR-004.3: Repetition detection: if two consecutive phrases of ≥2 words are identical (after stemming), the second occurrence is removed.
- FR-004.4: Self-correction trigger phrases: "no wait", "I mean", "delete that", "scratch that", "never mind", "forget that", "strike that" — any of these triggers removal of the preceding injected text up to the last sentence boundary.
- FR-004.5: All patterns are user-configurable in `config.toml` under `[filters.disfluency]`. Users can add/remove patterns and disable the filter entirely.
- FR-004.6: Optional LLM enhancement: if `filters.disfluency.llm_enabled = true` and a local Ollama endpoint is configured, the transcript is also sent async to the LLM for cleanup. If the LLM result arrives within 500 ms of injection, it replaces the injected text in-place. Otherwise the rule-based result stands.

**Non-functional requirements:**
- NFR-004.1: Rule-based path runtime: <10 ms per transcript on reference hardware (2019 Intel i7).
- NFR-004.2: Filter MUST NOT alter proper nouns, code identifiers, or quoted text.
- NFR-004.3: Zero injection delay introduced by the rule-based path.

---

### 3.5 cap-005 — Accessibility Profile (Atypical-Speech Accommodations)

**Goal:** Make YazSes usable by people with atypical speech, motor disabilities, and non-standard voice onset patterns through configurable accommodations and a personalised enrollment option.

**Functional requirements (MVP — accommodations only; LoRA fine-tune is v0.4.0):**
- FR-005.1: `yazses doctor --accessibility` prints a checklist of accommodation settings and their current values.
- FR-005.2: Configurable `recording.min_silence_ms` (default 500 ms; range 200–5000 ms). Allows users with slow speech to complete sentences without premature cutoff.
- FR-005.3: Configurable `recording.pre_speech_padding_ms` (default 200 ms; range 0–2000 ms). Captures voice onset for users with delayed phonation (ALS-related hypophonia).
- FR-005.4: Alternative hold-key input sources: `[hotkey] source = "evdev"` and `evdev_device = "/dev/input/event0"` — allows footpedal, joystick button, or adapted switch to trigger recording on Linux.
- FR-005.5: Configurable ASR model selection: `asr.model = "tiny.en"` (default), `"base.en"`, `"small.en"`. Larger models have higher latency but better accuracy for non-standard speech. [EVIDENCE src-009]
- FR-005.6: `yazses enroll` wizard (interactive CLI): guides user through recording 20 calibration utterances for VAD threshold auto-tuning. Does NOT train a new model in MVP; adjusts `vad_threshold` and `silence_ms` based on user's voice characteristics.
- FR-005.7: Disfluency filter (cap-004) is auto-enabled in accessibility profile and pre-configured with extended filler list including non-standard vocalisations.

**Non-functional requirements:**
- NFR-005.1: Enrollment wizard completes in ≤10 minutes of user time.
- NFR-005.2: All accessibility settings accessible via CLI without GUI requirement.
- NFR-005.3: All documentation in accessibility profile sections MUST follow WCAG 2.2 authoring guidance.

---

## 4. Out of Scope (v0.3.0)

The following were considered and explicitly deferred:

- **LoRA Whisper fine-tuning** (cap-005 phase 2): Requires packaging a training pipeline; deferred to v0.4.0.
- **XR WebSocket API** (cap-006): Depends on streaming performance improvements from cap-002 shipping first; deferred to v0.4.0.
- **Gaming / 3D voice commands** (cap-007): Depends on cap-006; deferred to v0.4.0.
- **LLM intent routing** (cap-008): Depends on cap-003 grammar module; deferred to v0.4.0.
- **Audio forwarding over SSH**: Audio stays local by design; only text is forwarded.
- **Cloud ASR fallback**: YazSes remains offline-first; no cloud ASR integration.
- **Speaker diarization**: Multi-speaker transcription is a different product vertical.

## 5. Confidence Assessment

| Area | Confidence | Basis |
|---|---|---|
| cap-001 architecture | HIGH | SSH port forwarding is a proven pattern; text forwarding is trivial [EVIDENCE src-001] |
| cap-002 streaming | MEDIUM | LocalAgreement proven [EVIDENCE src-002]; correction-on-commit is novel engineering |
| cap-003 grammar | HIGH | Grammar-rule approach proven by Talon [EVIDENCE src-007]; vocabulary defined |
| cap-004 disfluency | HIGH | Rules well-documented; WER impact measured [EVIDENCE src-012] |
| cap-005 accommodations | HIGH | Config-only changes; enrollment wizard is additive [EVIDENCE src-008] |
| cap-005 LoRA | LOW | LoRA fine-tune packaging complexity unknown; deferred correctly |

## 6. Definition of Done (v0.3.0)

- All FR-001.x through FR-005.x implemented and passing tests
- `yazses remote --host` works with a real SSH server (integration test)
- Streaming partial display visible in a screencast demo
- Code commands dispatch correctly on a 50-item test phrase set (NFR-003.1 met)
- Disfluency filter runs in <10 ms on 10 reference transcripts
- `yazses enroll` wizard completes without error on Linux, macOS, Windows
- `uv run pytest tests/ -v` passes on all three platforms
- `yazses --version` shows `0.3.0`
- `CHANGELOG.md` updated
- Snap and apt packages updated
