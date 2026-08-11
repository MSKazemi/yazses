---
id: prd-yazses-v0.4
title: "YazSes v0.4 PRD — Offline LLM Routing, Code-Aware Dictation, EMG Backend"
type: prd
status: in-review
scenario: "yazses-future-voice-hci"
created_at: 2026-05-17
updated_at: 2026-05-17
sources: [src-001, src-002, src-003, src-005, src-006, src-007, src-010, src-011]
confidence: medium
owner: "Mohsen Seyedkazemi Ardebili"
next_action: "HUMAN REVIEW REQUIRED — review functional requirements and open questions before architecture design begins"
version: "0.4"
target_users: [power-user-developer, open-office-worker, accessibility-user]
mvp_capabilities: [cap-001, cap-002, cap-003]
out_of_scope:
  - "Cloud API integration (Tier 3 ceiling is defined but not implemented in v0.4)"
  - "Gaze+voice fusion via OS accessibility tree (gap-004, depends on cap-001 stabilisation)"
  - "Gaming voice protocol / emotion annotation (gap-005)"
  - "AAC mode combining acoustic + EMG + camera (gap-006)"
  - "Dysarthric speech LoRA fine-tuning (gap-007)"
  - "Ambient wake-word mode (gap-008)"
  - "JetBrains / Eclipse LSP bridge (cap-002 initially covers Neovim + VS Code only)"
  - "EMG full-text input path (cap-003 v0.4 covers command-vocabulary mode only)"
---

# YazSes v0.4 — PRD

---

## Executive Summary

YazSes v0.4 transforms the daemon from a grammar-bound voice tool into a natural-language offline voice interface for developer workflows. This version adds three capabilities that together address the three largest documented gaps in offline voice HCI research: semantic intent routing without cloud dependency, code-aware transcription via Language Server Protocol integration, and a hardware-agnostic EMG silent speech backend for open-office and accessibility use cases.

This PRD covers v0.4, targeting a public release after internal alpha testing. The MVP scope includes cap-001 (Offline LLM Intent Routing), cap-002 (Code-Aware Voice Dictation via LSP), and cap-003 (EMG Silent Speech Backend). These three capabilities are prioritised because they each open a distinct user population with no viable current alternative: cap-001 benefits all users, cap-002 targets the developer cohort, and cap-003 opens open-office and disability contexts.

The evidence base for this scope is drawn from a 12-source systematic survey (see `output/02_soa_matrix.md`). All three capabilities are supported by research demonstrating technical feasibility on consumer CPU hardware. [EVIDENCE src-003, src-005]

Success for v0.4 is defined as: power-user developers can issue natural-phrasing voice commands offline without memorising grammar rules; developers can dictate code with correct identifier spelling in at least two editors; and users with EMG devices can operate the daemon silently using the 10-command default vocabulary.

---

## Problem Statement

### The Problem

[EVIDENCE src-002] Every voice system in the survey, including YazSes, shows instruction-following failure (not transcription error) as the primary quality gap. YazSes v0.3.0 uses 25 regex rules for command classification. Users who phrase commands naturally — "close this tab", "make a new window", "go to the next function" — fall through to dictation mode if their phrasing doesn't match a regex. This silent failure mode causes users to disengage from grammar-based voice interfaces entirely.

For developers specifically, transcription of code vocabulary (identifiers, symbols, naming conventions) is a secondary but critical problem: without context about the current file and language, every identifier must be corrected manually. [EVIDENCE src-001, src-002]

For open-office workers and accessibility users, the acoustic input requirement of all voice daemons (including YazSes) is an absolute barrier — they cannot use the tool at all.

### Why Existing Solutions Fall Short

- **YazSes v0.3.0 regex grammar classifier:** 25 rules cover approximately 80% of natural phrasing for known intents, but fail silently for the remaining 20%. Users must memorise grammar-safe phrasing or accept silent misdirections. The grammar cannot be extended cheaply to cover all natural phrasing variants of 25+ intents. [HYPOTHESIS]
- **Cloud voice assistants (Google Assistant, Siri):** Semantic intent routing is excellent but requires cloud connectivity, cannot run offline, and do not integrate with desktop text injection or editor state. Privacy-sensitive users and offline workers cannot use them. [EVIDENCE src-001, src-002, src-009]
- **Generic dictation tools (Whisper Dictation, Vosk):** Transcription-only; no intent routing, no code context injection, no command dispatch. Cannot be used as a voice interface for structured tasks without significant user-side scripting. [HYPOTHESIS]
- **EMG research systems (OpenBCI, academic prototypes):** High accuracy in lab conditions but no desktop voice daemon integration. Require custom per-application integration; no standardised desktop text injection. [EVIDENCE src-005, src-006]

### "Good Enough" for v0.4

v0.4 is good enough if: (a) a developer can issue any of the 25 known intents in natural phrasing and have them correctly classified offline > 90% of the time; (b) the same developer can dictate Python code with at least two editors and see correct snake_case identifiers from the active file without manual correction; (c) a user with an OpenBCI or compatible EMG device can use the 10-command default vocabulary silently with > 90% command accuracy without writing any code.

---

## Target Users

### Power-User Developer

**Role:** Software engineer or data scientist who writes code for 4–8 hours daily, frequently uses terminal + editor switching, and has either RSI concerns or accessibility needs that motivate voice input.

**Primary job-to-be-done:** When I need to execute complex editor and terminal commands while keeping my hands on the keyboard for typing, I want to issue voice commands in natural language so that I can reduce keyboard hand load without losing execution speed.

**Current pain point:** Voice command grammar requires memorisation of exact phrases. Natural variations — "undo last change", "revert that", "go back" — all fail and produce unwanted dictated text. After three command misclassifications in a session, the user disables grammar mode and reverts to keyboard. Code identifier transcription errors require correction for every function name, requiring the user to spell identifiers phonetically or correct constantly.

**How this product helps:** cap-001 removes the need to memorise grammar phrases — natural phrasing for all 25 existing intents is classified correctly offline. cap-002 reduces per-utterance code identifier correction rate by injecting the active file's vocabulary into the transcription prompt for supported editors.

---

### Open-Office Worker

**Role:** Knowledge worker (writer, analyst, manager) in a shared open-plan workspace who wants voice dictation for long-form text composition but cannot speak aloud without disrupting colleagues.

**Primary job-to-be-done:** When I am in a shared office environment and need to compose documents or execute repetitive text tasks, I want to use voice input silently so that I can get the productivity benefits of voice dictation without disturbing others.

**Current pain point:** All voice daemons require acoustic input; there is no path from "I want to use voice dictation silently in an open office" to "it works" with any existing tool, including YazSes. The user is blocked at the hardware interface level.

**How this product helps:** cap-003 enables silent operation via an EMG device. The daemon's command vocabulary, text injection, and grammar classification are unchanged — only the audio source is replaced by EMG signals. The user gets the full YazSes functionality in complete silence.

---

### Accessibility User

**Role:** User with motor, speech, or situational disability (Parkinson's tremor affecting acoustic speech, laryngectomy, post-surgery voice rest, or severe RSI making any keyboard use painful) who needs an alternative input modality for desktop computer interaction.

**Primary job-to-be-done:** When I cannot reliably produce acoustic speech or use a keyboard due to my disability, I want to control my desktop using EMG or biosignal input so that I can compose text and execute commands without physical strain or voice production.

**Current pain point:** Existing AAC devices (Tobii Dynavox, Grid 3) are proprietary, expensive, and separate from the desktop OS — they require a separate device and do not integrate with the user's existing desktop workflow. No open-source desktop daemon accepts EMG or biosignal input. [EVIDENCE src-011, src-012]

**How this product helps:** cap-003 provides the first open-source, offline EMG input backend for a desktop voice daemon, integrated directly into the standard YazSes text injection and command dispatch pipeline. Users can use their existing computer with a USB or BLE EMG device and YazSes as their input system.

---

## MVP Scope

### Included in This Version

- **cap-001 (Offline LLM Intent Routing):** A three-tier intent routing stack (regex fast path → local SLM → optional cloud ceiling) that classifies natural-phrasing voice commands offline using a quantised Phi-3-mini or TinyLlama model loaded at daemon startup.
- **cap-002 (Code-Aware Voice Dictation via LSP):** An `LspContextProvider` that reads active file language, enclosing scope, and recent identifiers from a running LSP server, and injects this context into the faster-whisper `initial_prompt` before each transcription. Supported editors at v0.4: Neovim and VS Code.
- **cap-003 (EMG Silent Speech Backend):** A new `EMGBackend` implementing the `HotkeyBackend` protocol, accepting USB serial events from EMG devices using a documented hardware-agnostic protocol. Command-vocabulary mode (10 commands) is implemented; full-text mode is deferred to v0.4.1.

### Explicitly Excluded

- **Cloud API Tier 3 ceiling:** The three-tier architecture defines a Tier 3 slot but does not implement any cloud provider integration in v0.4. The feature flag exists in config but is disabled and undocumented. Reason: cloud integration adds compliance and privacy policy obligations that require separate review.
- **VS Code companion extension for LSP (marketplace publish):** The companion extension source code is included in the repository but marketplace publication and automated testing on the Marketplace are deferred to v0.4.1. Reason: Marketplace review timeline is unpredictable; the core daemon feature should not be blocked by it.
- **EMG full-text input mode (cap-003):** Devices that transmit decoded text strings are deferred to v0.4.1. Reason: no consumer full-text EMG device exists yet; the command-vocabulary mode (src-005 architecture) covers real hardware available today.
- **LSP bridge for JetBrains IDEs:** JetBrains requires a Java plugin and a separate IDEA plugin SDK build chain. Deferred to v0.4.1. Reason: Neovim + VS Code cover the primary developer cohort; JetBrains adds significant build complexity without proportional coverage gain.
- **Per-user SLM intent vocabulary fine-tuning:** User-specific fine-tuning of the Tier 2 prompt template is not included. The default few-shot template covers the 25 existing intents; user customisation is via config TOML, not model fine-tuning.
- **Streaming integration wire-up (cap-002 from v0.3.0 backlog):** The `StreamingEngine` and `StreamingInjector` remain as tested-but-not-wired components in v0.4. This backlog item is separately tracked.

### Scope Boundary Rationale

The three MVP capabilities were selected because they collectively score 17–19/20 on the prioritisation matrix — a distinct cluster above all remaining gaps. cap-001 is a prerequisite for several future capabilities and benefits all current users immediately. cap-002 targets the highest-value user cohort (developers) with a capability that no competing tool provides. cap-003 is independent of cap-001/002 and opens entirely new user populations; developing it in parallel makes efficient use of available engineering time. All three have sufficient research evidence (src-003, src-005, src-006) to reduce implementation risk to engineering execution rather than algorithmic uncertainty. [HYPOTHESIS]

---

## Functional Requirements

### FR Group: cap-001 — Offline LLM Intent Routing

**FR-01:** The system MUST classify any utterance that matches one of the 25 existing `CommandIntent` values in natural phrasing (not just regex-matching phrasing) without cloud connectivity.
Acceptance: Given a set of 50 natural phrasing variants for the 25 intents (5 examples not in the regex grammar per intent), ≥ 90% must be classified to the correct intent by the Tier 2 SLM, measured offline on a machine with no network access. [EVIDENCE cap-001]

**FR-02:** The system MUST load the SLM at daemon startup and keep it resident; Tier 2 classification latency MUST be < 400 ms p99 on a 4-core 8 GB RAM laptop.
Acceptance: Benchmarked with a wrk-style loop of 100 Tier 2 classify calls on a 2020-era laptop CPU. p99 latency ≤ 400 ms. [HYPOTHESIS]

**FR-03:** When the SLM model file is absent, the system MUST start and operate in Tier 1 (regex-only) mode without error. `yazses doctor` MUST report the SLM as absent and provide the download command.
Acceptance: Delete the model file; run `yazses-daemon`; confirm no crash and `yazses status` reports `intent_tier: 1`. Run `yazses doctor`; confirm output includes the download instruction. [HYPOTHESIS]

**FR-04:** The system MUST expose the current intent tier (1 = regex, 2 = SLM, 3 = cloud) in `yazses status` JSON output.
Acceptance: `yazses status` output includes `"intent_tier": 2` when SLM is loaded. [HYPOTHESIS]

**FR-05:** The system SHOULD fall back to Tier 1 on any Tier 2 inference error (model decode failure, timeout) without crashing the daemon.
Acceptance: Inject a syntactically invalid GGUF response; confirm the daemon logs the error and classifies the utterance as `DICTATE` rather than crashing. [HYPOTHESIS]

---

### FR Group: cap-002 — Code-Aware Voice Dictation via LSP

**FR-06:** When `lsp_enabled = true` in config, the system MUST read the active editor's language ID, enclosing scope, and top-10 recent identifiers from the LSP server within 50 ms before each recording session.
Acceptance: Start a Neovim session with a Python file open, `lsp_enabled = true`; trigger a recording; confirm the transcription prompt includes the language and at least 3 identifiers from the active file. [HYPOTHESIS]

**FR-07:** When LSP context is unavailable (editor not running, LSP timeout), the system MUST proceed with standard transcription without error or delay.
Acceptance: Kill the LSP server; trigger a recording; confirm no error in daemon logs and transcription proceeds normally within the standard latency budget. [HYPOTHESIS]

**FR-08:** The system MUST support Neovim (via `nvim --remote-expr` RPC) and VS Code (via companion extension) as LSP bridge targets at v0.4.
Acceptance: With a Neovim session running `nvim-lspconfig` and a Python file, verify that the context contains the correct scope chain. Repeat for VS Code. [HYPOTHESIS]

**FR-09:** The system SHOULD improve transcription accuracy for identifiers present in the LSP context by ≥ 20 percentage points compared to without LSP context, measured on a 20-item test set of code-specific utterances containing identifiers from the active file.
Acceptance: A/B evaluation with and without LSP context on a fixed test set (20 utterances containing identifiers from a test Python file). This is a SHOULD requirement because the effect size depends on the specific Whisper model version. [HYPOTHESIS]

---

### FR Group: cap-003 — EMG Silent Speech Backend

**FR-10:** The system MUST accept USB serial input from a connected EMG device following the YazSes EMG serial protocol and route HOLD_START / HOLD_END events to the recording pipeline.
Acceptance: With an OpenBCI Cyton connected, configure `[emg] device_port = /dev/ttyUSB0`; trigger a HOLD_START event from the device; confirm the daemon enters `RECORDING` state. [HYPOTHESIS]

**FR-11:** The system MUST map at least 10 EMG command labels to `CommandIntent` values or raw text strings via the `EmgProfile.command_map` configuration.
Acceptance: Define a 10-entry `command_map`; send each of the 10 command labels over serial; confirm each maps to the correct intent dispatch. [HYPOTHESIS]

**FR-12:** When the configured EMG device port is absent at startup, the system MUST fall back to the default hotkey backend without error.
Acceptance: Configure `[emg] device_port = /dev/ttyUSB99` (non-existent); start the daemon; confirm it starts with the default hotkey backend and `yazses doctor` reports the EMG device as absent. [HYPOTHESIS]

**FR-13:** The system MUST document the YazSes EMG serial protocol in `docs/emg-protocol.md` with sufficient detail for a third-party firmware developer to implement a compatible device.
Acceptance: Review the protocol document; confirm it specifies message format, baud rate, timing requirements, and includes a reference implementation example. [HYPOTHESIS]

---

## Non-Functional Requirements

### Performance

- **NFR-P01:** The combined transcription + Tier 2 intent routing pipeline MUST complete within 800 ms p99 wall-clock time from hotkey release to first character injection on a 4-core 8 GB RAM laptop under default configuration. [HYPOTHESIS]
  _Rationale:_ Transcription alone is < 500 ms on a 4-core CPU for < 5 s audio with faster-whisper int8. Tier 2 budget is 300 ms. Total 800 ms remains below the 1 s threshold where users perceive a significant lag.
- **NFR-P02:** Tier 1 (regex) path MUST complete classification in < 5 ms p99. [HYPOTHESIS]
  _Rationale:_ The regex path must not add perceptible latency for grammar-matching commands; 5 ms is well within human perception threshold.

### Scale

- **NFR-S01:** The daemon MUST operate on a single-user machine with as little as 6 GB total RAM when Phi-3-mini-4k is loaded. [HYPOTHESIS]
- **NFR-S02:** The SLM model file MUST be loadable from a local filesystem path only; no runtime network access for model loading. [HYPOTHESIS]

### Reliability

- **NFR-R01:** The daemon MUST run continuously for ≥ 8 hours without crash or memory growth > 100 MB above startup RSS. [HYPOTHESIS]
- **NFR-R02:** Any single-component failure (SLM inference error, LSP timeout, EMG disconnect) MUST NOT crash the daemon; it MUST log the error and degrade gracefully to the next available tier. [HYPOTHESIS]

### Security

- **NFR-SEC01:** All transcription and intent routing MUST occur on-device. No audio, transcription output, or command text MUST leave the local machine unless the user explicitly enables the optional cloud Tier 3 ceiling (which is excluded from v0.4 implementation). [HYPOTHESIS]
- **NFR-SEC02:** The EMG serial protocol MUST NOT transmit raw biosignal data to the daemon; only labelled command strings are accepted. Daemon MUST validate that received command labels are in the configured `command_map` before dispatch. [HYPOTHESIS]

### Observability

- **NFR-O01:** `yazses status` JSON output MUST include: `intent_tier` (1/2/3), `lsp_connected` (bool), `emg_connected` (bool), and `slm_model_path` (str or null). [HYPOTHESIS]
- **NFR-O02:** All Tier 2 SLM inference calls MUST be logged at DEBUG level with: transcript input, top intent output, confidence score, and inference duration in ms. [HYPOTHESIS]
- **NFR-O03:** `yazses doctor` MUST report the status of all three new components (SLM model file present/absent, LSP editor detected/not-detected, EMG device present/absent) with clear actionable messages. [HYPOTHESIS]

---

## Success Metrics

| Metric | How Measured | Target | Timeframe | Evidence |
|--------|-------------|--------|-----------|----------|
| Natural-phrasing intent accuracy (Tier 2) | Offline evaluation: 50 natural phrasing variants for 25 intents, classified by SLM | ≥ 90% correct | At v0.4 alpha release | [HYPOTHESIS] |
| Tier 2 latency p99 | Benchmarked: 100 Tier 2 calls on reference 4-core 8 GB laptop | ≤ 400 ms | At v0.4 alpha release | [HYPOTHESIS] |
| Code identifier transcription accuracy improvement | A/B test: 20 utterances with in-scope identifiers, with vs. without LSP context | ≥ 20 percentage point improvement | At v0.4 alpha release | [HYPOTHESIS] |
| EMG command accuracy (10-command default vocabulary) | Manual test with OpenBCI Cyton: 50 command triggers per label | ≥ 90% correct routing | At v0.4 alpha release | [EVIDENCE src-005] |
| Daemon stability (8-hour run) | Automated soak test: daemon running with simulated hotkey events for 8 hours | Zero crashes, < 100 MB memory growth | At v0.4 alpha release | [HYPOTHESIS] |
| Graceful degradation (component failure) | Integration test: kill LSP server, disconnect EMG device, delete SLM model during session | Zero daemon crashes, correct fallback state reported in `yazses status` | At v0.4 alpha release | [HYPOTHESIS] |

---

## Open Questions

**OQ-01:** What is the optimal few-shot prompt template structure for the Tier 2 SLM intent classification task on the YazSes intent vocabulary?
_Blocking:_ FR-01 accuracy target; this is the most significant unknown for cap-001.
_Owner:_ Mohsen Seyedkazemi Ardebili — requires a prompting spike (1–2 days).

**OQ-02:** Does Phi-3-mini-4k-Q4_K_M or TinyLlama-1.1B-Q4_K_M meet the ≤ 400 ms p99 latency target on the reference hardware? If neither does, what is the minimum acceptable accuracy/latency trade-off?
_Blocking:_ NFR-P01, FR-02; determines which model ships as default.
_Owner:_ Mohsen Seyedkazemi Ardebili — requires a benchmarking spike on reference hardware.

**OQ-03:** Should the VS Code LSP bridge be a companion extension in the VS Code Marketplace, or should it use the VS Code CLI socket interface (available without a marketplace extension)?
_Blocking:_ FR-08 implementation approach for VS Code; determines whether a separate extension pipeline is required.
_Owner:_ Mohsen Seyedkazemi Ardebili.

**OQ-04:** For the EMG backend, should the first release use USB CDC serial (requires physical USB connection) or BLE (wireless but requires platform-specific BLE stack)? Most consumer EMG devices are BLE-primary.
_Blocking:_ cap-003 hardware compatibility scope; USB-first is simpler but limits device compatibility.
_Owner:_ Mohsen Seyedkazemi Ardebili.

**OQ-05:** How should the SLM model download be handled — automatic on first use (requires network access at first run), manual via `yazses doctor --download-slm`, or packaged as a separate optional install script?
_Blocking:_ FR-03 (doctor reporting) and first-user onboarding UX.
_Owner:_ Mohsen Seyedkazemi Ardebili.

---

*Study: [[yazses-future-voice-hci/input/research_scope|yazses-future-voice-hci]]*
