---
id: arch-yazses-v0.4
title: "YazSes v0.4 Architecture — Offline LLM Routing, LSP Context, EMG Backend"
type: architecture
status: in-review
scenario: "yazses-future-voice-hci"
created_at: 2026-05-17
updated_at: 2026-05-17
sources: [src-001, src-002, src-003, src-005, src-006, src-010]
confidence: medium
owner: "Mohsen Seyedkazemi Ardebili"
next_action: "Spike OQ-01 (SLM prompt template) and OQ-02 (model latency benchmark) before committing to component interface definitions"
version: "0.4"
prd_id: "prd-yazses-v0.4"
adr_ids: [adr-v04-001, adr-v04-002, adr-v04-003]
diagram_format: mermaid
---

# YazSes v0.4 — Architecture

---

## System Overview

YazSes v0.4 is a local, offline-first voice daemon that accepts audio input from an acoustic microphone or an EMG biosignal device, transcribes utterances using faster-whisper (CPU int8), classifies intent using a three-tier routing stack (regex → local SLM → optional cloud), optionally enriches transcription with LSP code context, and injects the result as keystrokes into the active application window.

This architecture does not introduce a new process model — all v0.4 components run in-process within the existing `yazses-daemon` process. The architecture deliberately avoids microservices, external databases, or new IPC channels; all new capabilities are integrated as optional, degradable components within the v0.3.0 pipeline stages.

**Key design principles:**

1. **Offline-first, degradation-graceful:** Every new component (SLM, LSP provider, EMG backend) is optional. If a component is unavailable (model absent, editor not running, device disconnected), the daemon degrades to the next available tier and continues operating. No new component is required for the daemon to start. [HYPOTHESIS]
2. **Protocol extension, not core replacement:** The `HotkeyBackend` protocol and the `CommandIntent` dispatch table are the stable interfaces. New input modalities (EMG) and new classification tiers (SLM) plug into these existing interfaces without changing the daemon state machine. [HYPOTHESIS]
3. **Latency budget ownership per stage:** The v0.3.0 pipeline has a well-understood latency profile (< 500 ms for acoustic STT). Each v0.4 component has an explicit latency budget: Tier 2 SLM ≤ 300 ms, LSP context read ≤ 50 ms. Total end-to-end budget remains ≤ 800 ms p99. [HYPOTHESIS]
4. **Privacy by architecture:** No audio, transcript, or intent data leaves the local machine in v0.4. The Tier 3 cloud slot is reserved in the config schema but not implemented; its absence is not a degradation but a deliberate design choice. [HYPOTHESIS]

---

## Component Diagram

```mermaid
flowchart TB
    subgraph Input["Input Layer"]
        Hotkey["HotkeyBackend\n(evdev / pynput)"]
        EMG["EMGBackend\n(USB serial)"]
    end

    subgraph Context["Context Layer (optional)"]
        LSP["LspContextProvider\n(language + identifiers)"]
    end

    subgraph STT["STT Layer"]
        Audio["AudioRecorder\n(sounddevice)"]
        Whisper["FasterWhisperSTT\n(CPU int8)"]
    end

    subgraph Intent["Intent Routing Layer"]
        T1["Tier 1: GrammarClassifier\n(regex, < 5 ms)"]
        T2["Tier 2: SLMRouter\n(Phi-3 / TinyLlama, ≤ 300 ms)"]
    end

    subgraph Dispatch["Dispatch Layer"]
        Dispatch["CommandDispatch\n(DICTATE / inject_key / inject_text)"]
        Inject["InjectorBackend\n(xdotool / ydotool / wtype / clipboard)"]
    end

    subgraph Daemon["Core Daemon (daemon.py)"]
        StateMachine["State Machine\n(IDLE ↔ RECORDING → TRANSCRIBING → INJECTING)"]
        IPC["IPC Server\n(JSON-RPC, Unix socket)"]
    end

    Hotkey -->|"HOLD_START / HOLD_END"| StateMachine
    EMG -->|"HOLD_START / COMMAND / HOLD_END"| StateMachine
    StateMachine -->|"start recording"| Audio
    StateMachine -->|"get context (50 ms timeout)"| LSP
    Audio -->|"audio buffer"| Whisper
    LSP -->|"CodeContext (initial_prompt)"| Whisper
    Whisper -->|"transcript"| T1
    T1 -->|"None (no regex match)"| T2
    T1 -->|"CommandIntent"| Dispatch
    T2 -->|"CommandIntent or DICTATE"| Dispatch
    Dispatch -->|"inject text / key sequence"| Inject
    IPC -->|"status / config queries"| StateMachine
```

---

## Component Descriptions

### HotkeyBackend (existing)

**Responsibility:** Detects the hold-to-talk keyboard shortcut and fires `on_hold_start` / `on_hold_end` callbacks to the daemon state machine.

**Interface:** Implements `HotkeyBackend` protocol from `platform/base.py`. Callbacks are `on_hold_start(leaked_audio: bytes)` and `on_hold_end()`.

**Dependencies:** `evdev` (Linux), `pynput` (macOS/Windows), `hold_detector.py`.

**Technology choice:** Unchanged from v0.3.0. [HYPOTHESIS]

---

### EMGBackend (new — cap-003)

**Responsibility:** Reads USB serial messages from a connected EMG device, interprets `HOLD_START`, `HOLD_END`, and `COMMAND:<label>` messages, and fires the same `on_hold_start` / `on_hold_end` callbacks as `HotkeyBackend`, plus `on_command(label: str)` for direct command dispatch.

**Interface:** Implements `HotkeyBackend` protocol — drop-in replacement for `HotkeyBackend` in the daemon state machine. The `on_command` callback is an extension to the protocol for command-vocabulary EMG devices. `pyserial.Serial` at configurable port and baud rate.

**Dependencies:** `pyserial >= 3.5`, `EmgConfig` from `config.py`.

**Technology choice:** USB CDC serial via `pyserial`. [HYPOTHESIS] BLE support deferred to v0.4.1.

---

### LspContextProvider (new — cap-002)

**Responsibility:** Queries the running LSP server for the active editor's current file language, enclosing scope chain, and recent identifiers, and returns a `CodeContext` object within a configurable timeout.

**Interface:** Single public method `get_context(timeout_ms: int = 50) -> CodeContext | None`. Returns `None` on timeout or LSP unavailability. Instantiated by the daemon during `LOADING` if `CommandsConfig.lsp_enabled = True`.

**Dependencies:** `pygls >= 1.3.0` (JSON-RPC transport), `EditorBridge` protocol implementations (`NeovimBridge`, `VsCodeBridge`).

**Technology choice:** `pygls` for JSON-RPC transport; per-editor bridge classes for editor-specific connection mechanisms. [HYPOTHESIS]

---

### AudioRecorder (existing)

**Responsibility:** Captures audio from the system microphone into a numpy buffer for the duration of the hold event.

**Interface:** `record(duration_s: float | None) -> np.ndarray`. Unchanged from v0.3.0.

**Dependencies:** `sounddevice`.

**Technology choice:** Unchanged. [HYPOTHESIS]

---

### FasterWhisperSTT (existing, extended)

**Responsibility:** Transcribes the audio buffer to text using faster-whisper (CPU int8). In v0.4, accepts an optional `initial_prompt: str` parameter that is populated with LSP context when available.

**Interface:** `transcribe(audio: np.ndarray, initial_prompt: str | None = None) -> str`. The `initial_prompt` change is a one-parameter addition to the existing call site in `daemon.py`. [HYPOTHESIS]

**Dependencies:** `faster-whisper`, `CodeContext` from `LspContextProvider` (optional).

**Technology choice:** Unchanged. [HYPOTHESIS]

---

### Tier 1: GrammarClassifier (existing)

**Responsibility:** Classifies a transcript into a `CommandIntent` using the 25 regex rules in `commands/grammar.py`. Returns `None` if no rule matches.

**Interface:** `grammar.classify(transcript: str, profile: GrammarProfile) -> CommandIntent | None`. Unchanged from v0.3.0.

**Dependencies:** `commands/grammar.py`, `commands/profiles.py`.

**Technology choice:** Unchanged. [HYPOTHESIS]

---

### Tier 2: SLMRouter (new — cap-001)

**Responsibility:** Classifies a transcript that failed Tier 1 using a locally-loaded quantised SLM. Returns a `CommandIntent` with a confidence score, or `None` if confidence is below threshold or if no model is loaded.

**Interface:** `slm_router.classify(transcript: str, profile: GrammarProfile, code_context: CodeContext | None = None) -> tuple[CommandIntent | None, float]`. The daemon in `daemon.py` calls this only if `grammar.classify()` returns `None`.

**Dependencies:** `llama-cpp-python >= 0.3.0`, GGUF model file at `CommandsConfig.slm_model_path`.

**Technology choice:** `llama-cpp-python` CPU backend with GGUF quantised model (Phi-3-mini-4k-Q4_K_M or TinyLlama-1.1B-Q4_K_M). [HYPOTHESIS] Model choice resolved by OQ-02 benchmark spike.

---

### CommandDispatch (existing)

**Responsibility:** Routes a classified `CommandIntent` to the appropriate action: text injection for `DICTATE`, key sequence injection for other intents.

**Interface:** `dispatch(intent: CommandIntent, args: dict, injector: InjectorBackend) -> None`. Unchanged from v0.3.0.

**Dependencies:** `inject/auto.py`, `InjectorBackend` protocol.

**Technology choice:** Unchanged. [HYPOTHESIS]

---

## Data Flow

### Primary Use Case: Natural-language voice command (acoustic, with SLM)

**Happy path:**

1. User presses and holds the hotkey. `HotkeyBackend` fires `on_hold_start(leaked_audio)`. Daemon transitions to `RECORDING`. [HYPOTHESIS]
2. `AudioRecorder` captures audio until hotkey release. Simultaneously, `LspContextProvider.get_context(timeout_ms=50)` is called if `lsp_enabled=True`; the CodeContext (or None) is held pending. [HYPOTHESIS]
3. User releases the hotkey. `HotkeyBackend` fires `on_hold_end()`. Daemon transitions to `TRANSCRIBING`. [HYPOTHESIS]
4. `FasterWhisperSTT.transcribe(audio, initial_prompt=context_string)` is called. If CodeContext is available, `context_string` is the formatted identifier list; otherwise None. Transcription completes in < 500 ms. [HYPOTHESIS]
5. `GrammarClassifier.classify(transcript)` is called. If a regex matches (Tier 1 hit), the `CommandIntent` is returned immediately. Daemon transitions to `INJECTING`. (Continues at step 7.) [HYPOTHESIS]
6. If no regex match, `SLMRouter.classify(transcript, profile, code_context)` is called. Result is returned within ≤ 300 ms. If confidence ≥ threshold, the intent is used; otherwise `DICTATE` is returned. Daemon transitions to `INJECTING`. [HYPOTHESIS]
7. `CommandDispatch.dispatch(intent, args, injector)` is called. Text or key sequence is injected into the active window. Daemon transitions to `IDLE`. [HYPOTHESIS]

**Error path:**

- If `SLMRouter` raises any exception or times out, the exception is caught, logged at WARNING, and `DICTATE` is returned — the transcript is injected as raw text. The daemon does not crash. [HYPOTHESIS]
- If `LspContextProvider` times out (> 50 ms), `None` is used as the `initial_prompt`; transcription proceeds without code context. [HYPOTHESIS]
- If `AudioRecorder` fails to open the microphone device, the daemon transitions to `ERROR` state and reports via IPC. This is existing v0.3.0 behaviour unchanged. [HYPOTHESIS]

### Secondary Use Case: EMG silent command

1. User activates a command gesture on the EMG device. Device sends `COMMAND:window_close` over USB serial. [HYPOTHESIS]
2. `EMGBackend.on_command("window_close")` is called. The `command_map` maps `"window_close"` to `CommandIntent.CLOSE_WINDOW`. [HYPOTHESIS]
3. `CommandDispatch.dispatch(CLOSE_WINDOW, {}, injector)` is called directly. No STT or SLM pipeline invoked. [HYPOTHESIS]
4. Key sequence for window close is injected. [HYPOTHESIS]

---

## Technology Choices

| Technology | Purpose | Justification | Evidence |
|------------|---------|---------------|----------|
| Python 3.11+ | Primary implementation language | Existing codebase; strong ML and audio ecosystem | [HYPOTHESIS] |
| faster-whisper (CPU int8) | Acoustic speech transcription | Existing v0.3.0 component; no change | [HYPOTHESIS] |
| llama-cpp-python >= 0.3.0 | Tier 2 SLM inference | Supports GGUF quantised models on CPU; actively maintained; Apache-2.0 | [EVIDENCE src-003] TinyLlama via llama.cpp used in the edge inference paper |
| Phi-3-mini-4k-Q4_K_M.gguf OR TinyLlama-1.1B-Q4_K_M.gguf | Tier 2 intent classification model | Both Apache-2.0; sufficient parameter count for intent classification; CPU-feasible at 4-bit | [EVIDENCE src-003] |
| pygls >= 1.3.0 | LSP JSON-RPC client transport | Standard Python LSP library; used by nvim-lsp and other Python LSP tools | [HYPOTHESIS] |
| pyserial >= 3.5 | EMG device serial communication | Minimal dependency; stable; supports all platforms; MIT license | [HYPOTHESIS] |
| sounddevice (existing) | Microphone audio capture | Unchanged from v0.3.0 | [HYPOTHESIS] |
| pytest 8.x | Test framework | Existing project convention | [HYPOTHESIS] |

---

## Deployment Notes

**Deployment unit:** All v0.4 capabilities are delivered as Python package updates to the existing `yazses` package. No new processes, containers, or services are introduced. The daemon runs as a single Python process (unchanged from v0.3.0). [HYPOTHESIS]

**Target environment:** Local developer machine (Linux x86_64, macOS arm64). Unchanged from v0.3.0.

**Configuration management:** All new v0.4 configuration is added to the existing TOML config at `~/.config/yazses/config.toml`. New sections: `[slm]` (model path, confidence threshold), `[lsp]` (enabled, editor), `[emg]` (device port, baud rate, command map). All new config fields have safe defaults; the daemon starts correctly with an empty config file. [HYPOTHESIS]

**Environment differences:**

| Environment | Deployment | Config source | Storage |
|-------------|------------|--------------|---------|
| Local dev | `uv run yazses-daemon` | `~/.config/yazses/config.toml` | Local disk (model file in `~/.cache/yazses/models/`) |
| Snap (Linux) | `yazses.yazses-daemon` | `$SNAP_USER_DATA/config.toml` | Snap user data directory |
| macOS pkg | Installed via `.dmg` | `~/Library/Application Support/yazses/config.toml` | Local disk |

**Build and run:**
```bash
uv sync
uv run yazses-daemon            # starts with SLM/LSP/EMG if configured
uv run yazses doctor            # checks all component statuses
uv run pytest tests/ -v         # full test suite
```

---

## Constraints

### Technical Constraints

- [HYPOTHESIS] **CPU-only inference for Tier 2 SLM:** The SLM must operate on CPU (no GPU required). Violation would exclude the vast majority of target users who run on laptops without discrete GPUs. This rules out full-precision models (>7B parameters) for the Tier 2 role.
- [HYPOTHESIS] **In-process SLM (no subprocess IPC):** The SLM is loaded in-process via `llama-cpp-python`, not as a separate subprocess with IPC. A subprocess model would add 10–20 ms IPC overhead per inference and complicate the lifecycle management. The in-process approach is standard for embedded inference on consumer hardware.
- [HYPOTHESIS] **No new IPC endpoints for v0.4:** The JSON-RPC IPC interface is unchanged. `yazses status` gains new fields (intent_tier, lsp_connected, emg_connected) but no new method names. This preserves backward compatibility with existing CLI and tray implementations.

### Business / Legal Constraints

- [HYPOTHESIS] **Apache-2.0 compatible dependencies only:** All new dependencies (llama-cpp-python, pygls, pyserial) must be Apache-2.0, MIT, or BSD licensed. Phi-3-mini and TinyLlama model weights are Apache-2.0. Violation would create licensing conflicts for users who build proprietary derivatives of YazSes.
- [HYPOTHESIS] **No audio transmitted off-device:** All transcription, intent classification, and EMG processing occurs locally. This is a hard constraint for privacy-sensitive users (the stated YazSes differentiator vs. cloud tools). Any future Tier 3 cloud implementation must require explicit opt-in, per-session user confirmation, and a visible indicator.
- [EVIDENCE src-005] **EMG command labels only (no raw biosignal data):** The EMG serial protocol transmits labelled command strings, not raw biosignal waveforms. Transmitting raw waveforms to the OS would raise health-data compliance concerns; labelled strings are not health data.

---

## ADR References

| ADR ID | Decision | Status |
|--------|----------|--------|
| adr-v04-001 | Use llama-cpp-python (in-process GGUF) for Tier 2 SLM inference | proposed |
| adr-v04-002 | Use pygls JSON-RPC client for LSP context extraction | proposed |
| adr-v04-003 | EMG backend uses USB CDC serial with hardware-agnostic message protocol | proposed |

---

*Study: [[yazses-future-voice-hci/input/research_scope|yazses-future-voice-hci]]*
