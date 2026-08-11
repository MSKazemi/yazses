---
id: "arch-yazses-v030"
title: "YazSes v0.3.0 — Architecture Document"
type: architecture
scenario: yazses-innovation
created_at: 2026-05-14
updated_at: 2026-05-14
adrs: [adr-001, adr-002, adr-003, adr-004, adr-005]
confidence: high
---

# YazSes v0.3.0 — Architecture Document

## 1. Architecture Overview

The v0.3.0 system extends the existing four-stage pipeline with five new component clusters. All new components are integrated via the existing Platform bundle and daemon state machine; no new daemon entry points are required for caps 002–005. Cap-001 adds a second daemon mode (`RemoteDaemon`) that re-uses the full pipeline locally and forwards its output over an SSH tunnel.

```
LOCAL MACHINE
═══════════════════════════════════════════════════════════════════════════

  ┌──────────────────────────────────────────────────────────────────────┐
  │  Hotkey hook                                                         │
  │  platform/linux/hotkey.py  ─┐                                       │
  │  platform/macos/hotkey.py   ├─ HotkeyBackend.on_hold_start/end      │
  │  platform/windows/hotkey.py─┘      │                                │
  │  NEW: accessibility/evdev_switch.py (footpedal, adapted switch)      │
  └───────────────────────────────┬────────────────────────────────────-─┘
                                  │ on_hold_start(leaked)
                                  ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Audio recorder                                                      │
  │  audio/recorder.py  (sounddevice, numpy float32, 16 kHz)            │
  │  audio/vad.py       (RMS silence gate)                               │
  │  NEW: audio/vad_calibrated.py  (enrollment-tuned threshold)          │
  │  NEW: audio/padding.py         (pre-speech padding, configurable)    │
  └───────────────────────────────┬─────────────────────────────────────┘
                                  │ np.ndarray  (float32, 16 kHz)
                                  ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  STT engine  (always local — ADR-001)                                │
  │  stt/faster_whisper.py  (CPU int8, tiny.en/base.en/small.en)        │
  │  NEW: stt/streaming.py  (WhisperModel.transcribe generator,          │
  │                           LocalAgreement 2-iter policy — ADR-002)   │
  └───────────┬──────────────────────────┬───────────────────────────────┘
              │ final str                │ partial str (streaming)
              ▼                          ▼
  ┌───────────────────────┐   ┌──────────────────────────────────────────┐
  │  Post-processing      │   │  Streaming injector                      │
  │  postprocess/         │   │  inject/streaming.py                     │
  │    cleaner.py (v0.2)  │   │  - emits partials to active window       │
  │  NEW: stt/filters/    │   │  - tracks cursor_offset_at_first_partial │
  │    disfluency.py      │   │  - on commit: select-replace final text  │
  │    (cap-004)          │   │    (ADR-004)                             │
  └───────────┬───────────┘   └──────────────────────────────────────────┘
              │ cleaned str
              ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Command classifier  (cap-003)                                       │
  │  commands/grammar.py    (regex/keyword intent classifier)            │
  │  commands/dispatch.py   (action executor + IPC event emitter)        │
  │  commands/profiles.py   (per-app profile loader from config.toml)   │
  └───────────┬──────────────────────────────────────────────────────────┘
              │ DICTATE → str  /  command intent → structured action
              ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Text injector                                                       │
  │  inject/auto.py     (xdotool / ydotool / wtype / clipboard)         │
  │  inject/base.py                                                      │
  └───────────┬──────────────────────────────────────────────────────────┘
              │  OR (cap-001 remote mode)
              ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  Remote forwarder  (cap-001)                                         │
  │  remote/forwarder.py    (SSH tunnel manager, -R port-forward)        │
  │  remote/local_proxy.py  (local Unix socket bridge to SSH tunnel)     │
  └───────────────────────────────┬─────────────────────────────────────┘
                                  │ SSH tunnel (text only — ADR-001)
═════════════════════════════════ │ ══════════════════════════════════════
REMOTE MACHINE                    │
                                  ▼
  ┌──────────────────────────────────────────────────────────────────────┐
  │  yazses-remote-agent  (cap-001)                                   │
  │  remote/agent.py   (lightweight; no faster-whisper dependency)       │
  │  remote/inject.py  (mirrors inject/auto.py; same injector probing)  │
  └──────────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════
LOCAL MACHINE — SUPPORTING INFRASTRUCTURE
═══════════════════════════════════════════════════════════════════════════

  ┌─────────────────────────┐     ┌────────────────────────────────────┐
  │  core/daemon.py         │     │  accessibility/enroll.py           │
  │  (orchestrator,         │◄───►│  (enrollment wizard, cap-005)      │
  │   extended state        │     │  accessibility/vad_tune.py         │
  │   machine — see §5)     │     │  (calibration data → vad config)   │
  └────────────┬────────────┘     └────────────────────────────────────┘
               │ JSON-RPC 2.0 / newline-delimited JSON
               │ Unix socket (Linux/macOS) / named pipe (Windows)
               ▼
  ┌─────────────────────────────────────────────────────────────────────┐
  │  IPC server  (ipc/server.py)                                        │
  │  Existing methods: status, shutdown, inject                         │
  │  NEW v0.3.0 methods: remote_start, remote_stop, remote_status,      │
  │                       enroll_start, enroll_status,                  │
  │                       streaming_enable, streaming_disable           │
  └─────────────────────────────────────────────────────────────────────┘
               │
               ▼
  ┌──────────────────────────────┐   ┌───────────────────────────────┐
  │  CLI  (cli.py / Typer)       │   │  Tray  (tray/app.py)          │
  │  NEW: yazses remote       │   │  Updated: shows REMOTE_ACTIVE  │
  │  NEW: yazses enroll       │   │  state in tray icon            │
  │  NEW: yazses config set   │   └───────────────────────────────┘
  └──────────────────────────────┘
```

## 2. Component Descriptions

### 2.1 cap-001: SSH/Remote Voice Forwarding

#### `src/yazses/remote/forwarder.py`

**Responsibility:** Manages the lifecycle of an SSH port-forward tunnel connecting the local machine to a remote YazSes agent. Opens a reverse tunnel (`ssh -R`) from the remote machine's loopback to the local IPC proxy socket. Monitors tunnel health and emits reconnect events to the daemon.

**Interfaces consumed:** `subprocess.Popen` (OpenSSH client), `remote.local_proxy.LocalProxy`.

**Interfaces produced:** `ForwarderProtocol` — `connect(host, port, key_file)`, `disconnect()`, `is_connected() -> bool`.

#### `src/yazses/remote/local_proxy.py`

**Responsibility:** Listens on a local Unix socket, accepts connections from the SSH tunnel endpoint, and bridges incoming text payloads to the local `InjectorBackend` (in local mode) or forwards them to a `RemoteTextSink`. Translates the remote agent's JSON-RPC `inject` calls back onto the daemon's injection path.

#### `src/yazses/remote/agent.py`

**Responsibility:** Standalone lightweight process that runs on the remote machine. Listens on the SSH-forwarded loopback port for JSON-RPC `inject` requests and invokes `remote/inject.py` to type the text. Has zero `faster-whisper` or `sounddevice` imports. Installable as a single `pip install yazses-agent` package (separate PyPI distribution).

#### `src/yazses/remote/inject.py`

**Responsibility:** Mirrors `inject/auto.py` — probes for `xdotool`, `ydotool`, `wtype` (Linux), `SendInput` (Windows), or `CGEventPost` (macOS) and selects the best available backend for text injection on the remote machine.

### 2.2 cap-002: Streaming Transcription with Real-Time Display and Correction

#### `src/yazses/stt/streaming.py`

**Responsibility:** Wraps `faster_whisper.WhisperModel.transcribe()` called on a rolling audio buffer during recording. Implements the LocalAgreement 2-iteration confirmation policy [EVIDENCE src-002, src-003]: a text prefix is considered stable and emitted only after it has appeared identically in 2 consecutive decode passes. Exposes an async generator `stream_partials(audio_queue) -> AsyncGenerator[PartialHypothesis, None]` where `PartialHypothesis` carries `text: str`, `is_stable: bool`, and `char_count: int`.

**Interfaces consumed:** `faster_whisper.WhisperModel` (shared instance from `FasterWhisperEngine`), `asyncio.Queue[np.ndarray]`.

**Interfaces produced:** `AsyncGenerator[PartialHypothesis, None]`.

#### `src/yazses/inject/streaming.py`

**Responsibility:** Stateful injector wrapper that tracks cursor state during a streaming session. On receiving a stable partial, injects characters and increments `_chars_injected`. On `commit(final_text)`: issues a selection of `_chars_injected` characters backward (Shift+Home or platform select-back), then injects `final_text` to replace. On `cancel()`: issues `_chars_injected` backspaces and resets state [EVIDENCE src-004].

**Interfaces consumed:** `InjectorBackend` (from platform bundle).

**Interfaces produced:** `StreamingInjector` — `inject_partial(text: str)`, `commit(final_text: str)`, `cancel()`.

### 2.3 cap-003: Code Command Grammar

#### `src/yazses/commands/grammar.py`

**Responsibility:** Stateless text classifier. Given a transcribed string, applies an ordered list of compiled regex patterns (loaded from a `GrammarSpec` at startup) and returns a `CommandIntent` dataclass with fields `intent: IntentType`, `action: str`, `args: dict[str, str]`, and `raw_text: str`. Falls through to `IntentType.DICTATE` if no pattern matches. Runtime budget: <5 ms per transcript [EVIDENCE src-007].

**Interfaces produced:** `classify(text: str, profile: str) -> CommandIntent`.

#### `src/yazses/commands/dispatch.py`

**Responsibility:** Receives a `CommandIntent` from `grammar.py` and executes the corresponding action. For `DICTATE` intents, delegates to the normal injection path. For structured intents (`NAVIGATE`, `EDIT`, `REFACTOR`, `TERMINAL`), dispatches to `InjectorBackend` key-sequence methods and/or `subprocess` for shell actions. Also emits a JSON-RPC notification `command_dispatched` on the IPC socket for tray and external tooling.

**Interfaces consumed:** `InjectorBackend`, `IpcServer.notify()` (new method — see §5).

#### `src/yazses/commands/profiles.py`

**Responsibility:** Loads per-application grammar profiles from `config.toml` `[commands.profiles.*]` sections and custom user commands from `[[commands]]` stanzas. Returns a `ProfileRegistry` mapping profile name to `GrammarSpec`. Profile selection is driven by the active application name supplied by the platform's focus-detection helper (new optional protocol method `get_focused_app() -> str | None`).

### 2.4 cap-004: Offline Disfluency Filter

#### `src/yazses/stt/filters/disfluency.py`

**Responsibility:** Pure-Python, dependency-free post-processing step applied to all final transcripts before injection. Implements three rules in sequence: (1) filler-word removal via word-boundary regex on a configurable pattern list; (2) consecutive phrase deduplication via 2-gram rolling comparison after whitespace normalisation; (3) self-correction trigger phrase detection — upon detecting a trigger phrase ("scratch that", "delete that", etc.), removes the trigger phrase and preceding text back to the last sentence boundary. Rule-based path must complete in <10 ms on reference hardware [EVIDENCE src-012].

**Interfaces produced:** `filter_transcript(text: str, config: DisfluencyConfig) -> FilterResult` where `FilterResult` carries `text: str` and `chars_removed: int` (used by streaming injector for backspace-delete fallback).

#### `src/yazses/config.py` (extended)

**Responsibility:** Gains a new `DisfluencyConfig` dataclass and a `FiltersConfig` wrapper. New TOML section: `[filters.disfluency]` with fields `enabled`, `filler_words: list[str]`, `self_correction_triggers: list[str]`, `llm_enabled`, `llm_endpoint`.

### 2.5 cap-005: Accessibility Profile

#### `src/yazses/accessibility/enroll.py`

**Responsibility:** Interactive CLI wizard (`yazses enroll`). Guides the user through recording 20 calibration utterances, computing per-user RMS statistics (mean, 95th-percentile noise floor), and writing derived `vad_threshold`, `min_silence_ms`, and `pre_speech_padding_ms` values to `config.toml`. Does not train a model [EVIDENCE src-008, src-010].

**Interfaces consumed:** `AudioRecorder`, `audio/vad_calibrated.py`.

#### `src/yazses/audio/vad_calibrated.py`

**Responsibility:** Extends `audio/vad.py` with a calibrated threshold loaded from config. Exposes `is_silent_calibrated(audio, config) -> bool` as a drop-in replacement for `is_silent()`.

#### `src/yazses/audio/padding.py`

**Responsibility:** Implements pre-speech padding by buffering the last N ms of audio at all times (ring buffer) and prepending that buffer to the recorded audio on `recorder.start()`. Configurable via `recording.pre_speech_padding_ms`.

#### `src/yazses/platform/linux/hotkey.py` (extended)

**Responsibility:** Gains an `evdev_device` config parameter to support alternative input devices (footpedals, adapted switches, joystick buttons) as hold-to-talk triggers. Reads `hotkey.source` and `hotkey.evdev_device` from config [EVIDENCE src-011].

## 3. Data Flows

### Flow 1 — Remote Session (cap-001)

```
1. User: yazses remote --host user@remotehost
2. CLI → IPC: remote_start(host="user@remotehost")
3. Daemon: transitions state to REMOTE_SETUP
4. remote/forwarder.py: spawns ssh -R 9875:localhost:9875 user@remotehost
           yazses-remote-agent --listen 9875
5. Daemon: transitions state to REMOTE_ACTIVE (IDLE substate)
6. User holds hotkey locally
7. Hotkey backend → daemon._on_hold_start(leaked)
8. AudioRecorder.start()
9. FasterWhisperEngine.transcribe(audio) [LOCAL — no audio leaves machine]
10. DisfluencyFilter.filter_transcript(text)  [cap-004 applied]
11. CommandGrammar.classify(text)  [cap-003: is this a command?]
    a. If DICTATE: remote/local_proxy.py sends
           JSON-RPC inject(text) → SSH tunnel → remote/agent.py
    b. If command intent: dispatch.py executes locally OR
           sends command-specific key sequence via tunnel
12. remote/agent.py receives inject(text)
13. remote/inject.py probes xdotool/ydotool/wtype on remote machine
14. Text appears in remote terminal / editor
```

### Flow 2 — Streaming Transcription with Correction (cap-002)

```
1. User holds hotkey
2. daemon._on_hold_start() → state = RECORDING
3. AudioRecorder.start(); audio chunks pushed to asyncio.Queue
4. stt/streaming.py: consumes queue in background thread
   - Every ~300 ms: re-transcribes rolling buffer with WhisperModel
   - LocalAgreement: tracks previous decode result
   - If prefix matches previous decode (2 iterations): emit PartialHypothesis(stable=True)
5. inject/streaming.py.inject_partial(stable_text):
   - Injects stable characters not yet injected
   - Increments _chars_injected counter
6. User releases hotkey
7. AudioRecorder.stop() → full audio np.ndarray
8. FasterWhisperEngine.transcribe(full_audio) → final_text  [EVIDENCE src-001]
9. DisfluencyFilter.filter_transcript(final_text)  [cap-004]
10. CommandGrammar.classify(filtered_text)  [cap-003]
    - If DICTATE: inject/streaming.py.commit(final_text)
        a. Shift+Left × _chars_injected  (select partial text)
        b. inject(final_text)  (replace with final)
        c. _chars_injected = 0
    - If command: inject/streaming.py.cancel() (backspace partials)
                  dispatch.py executes command
```

### Flow 3 — Code Command Dispatch (cap-003)

```
1. Final transcript arrives at commands/grammar.py.classify(text, profile)
2. GrammarSpec for active profile is loaded from ProfileRegistry
3. Ordered regex patterns evaluated top-to-bottom
4. Match found → CommandIntent(intent=EDIT, action="undo", args={n: "3"})
5. dispatch.py receives CommandIntent
6. Action table lookup: "undo" → inject_key_sequence(["ctrl+z", "ctrl+z", "ctrl+z"])
7. InjectorBackend.inject_key_sequence(["ctrl+z"] × n)
8. IpcServer emits notification: command_dispatched(intent="EDIT", action="undo")
9. No match → CommandIntent(intent=DICTATE) → normal injection path
```

### Flow 4 — Disfluency Filter (cap-004)

```
1. Final transcript text: "um let me uh go to line go to line 42"
2. DisfluencyFilter.filter_transcript(text, config):
   Step A — filler removal:  "let me go to line go to line 42"
   Step B — repetition check: "go to line" appears twice consecutively
             → "let me go to line 42"
   Step C — self-correction check: no trigger phrase found
3. FilterResult(text="let me go to line 42", chars_removed=12)
4. Result forwarded to CommandGrammar.classify()
   → NAVIGATE intent, action="go_to_line", args={n: "42"}
```

### Flow 5 — Accessibility Enrollment (cap-005)

```
1. User: yazses enroll
2. accessibility/enroll.py: prints welcome, checks microphone permission
3. 20 calibration rounds:
   a. Print prompt ("Say: 'hello world'")
   b. AudioRecorder.start(); record 3 s; AudioRecorder.stop()
   c. Compute RMS: noise_floor = np.abs(audio[:0.5s]).mean()
                  speech_rms = np.abs(audio[0.5s:]).mean()
   d. Collect (noise_floor, speech_rms) pairs
4. audio/vad_calibrated.py.compute_threshold(samples):
   - vad_threshold = noise_floor_p95 × 3.0
   - min_silence_ms = max(500, user_p95_pause_ms)
5. Write derived config to config.toml:
   [audio]
   vad_threshold = <computed>
   min_silence_ms = <computed>
   pre_speech_padding_ms = 400  (extended default for accessibility profile)
6. Print summary: "Enrollment complete. VAD threshold set to 0.032.
                   Silence window set to 800 ms."
```

## 4. Technology Choices

| Component | Choice | Rationale | Alternatives Considered |
|---|---|---|---|
| Remote transport | OpenSSH `-R` port-forward + JSON-RPC over TCP loopback | Zero new dependencies; works with any SSH server; no root required on either end | (a) libssh2/asyncssh custom channel — more control but requires asyncssh dep; (b) WireGuard tunnel — overkill, requires kernel module; (c) WebSocket relay — requires cloud server, violates offline-first constraint |
| Streaming ASR | `faster_whisper.WhisperModel.transcribe()` on rolling buffer with LocalAgreement policy | Reuses existing model instance; no new model download; LocalAgreement proven at 0.3 s LLSS [EVIDENCE src-003] | (a) whisper.cpp streaming fork — C extension, harder to package; (b) moonshine-onnx — different model, requires separate download; (c) fixed-window chunking — ignores speech rate variability |
| Command classifier | Compiled-regex grammar with ordered pattern list | <5 ms runtime; zero new dependencies; fully offline; high precision on closed command set [EVIDENCE src-007] | (a) Serenade's deep-learning speech-to-code model — closed source [EVIDENCE src-006]; (b) Whisper fine-tune on coding vocabulary — defeats lightweight constraint; (c) local LLM classifier — 200+ ms latency unacceptable for command dispatch |
| Disfluency filtering | Rule-based: regex filler removal + rolling 2-gram dedup + trigger phrase | <10 ms; zero dependencies; deterministic; user-configurable [EVIDENCE src-012] | (a) BERT-based disfluency tagger — 50+ ms, requires model download; (b) n-gram language model scoring — requires trained LM; (c) Ollama LLM cleanup — async optional enhancement, not on critical path |
| Streaming correction | Selection-replace (Shift+cursor × N, then inject) | Atomic replacement; cursor stays correct; works in all GUI apps; avoids clipboard corruption [EVIDENCE src-004] | (a) Floating overlay window — no Linux standard; requires per-platform rendering; (b) Never inject partials — defeats UX goal; (c) Clipboard diff — corrupts user clipboard |
| Accessibility VAD tuning | Per-user RMS calibration from 20 utterances; writes to config.toml | Simple, fast (<10 min), works offline, no model training required [EVIDENCE src-008] | (a) LoRA fine-tune of Whisper — 3+ weeks packaging effort, deferred to v0.4.0; (b) Voiceitt-style mobile enrollment — out of scope; (c) Static per-disability presets — not personalised enough |
| Remote agent packaging | Separate `yazses-agent` PyPI package; zero ASR deps | Allows `pip install yazses-agent` on headless servers without 2 GB model download | (a) Single repo, optional install extras — complicates dependency graph; (b) Docker container — heavy for a remote terminal tool |

## 5. Integration Points

### 5.1 Daemon State Machine Extension

The existing `TrayState` enum in `src/yazses/platform/base.py` is extended with two new states:

```
LOADING → IDLE → RECORDING → TRANSCRIBING → INJECTING → IDLE
                                                 │
                              REMOTE_SETUP ←─────┘ (yazses remote)
                              REMOTE_ACTIVE (IDLE/RECORDING/TRANSCRIBING substates)
                              ENROLLING  (yazses enroll wizard active)
```

The daemon's `_build_pipeline()` method in `core/daemon.py` gains three conditional branches:

1. **Streaming mode** (`config.streaming.enabled`): instantiates `stt/streaming.py:StreamingEngine` alongside `FasterWhisperEngine` and wires a `asyncio.Queue` between `AudioRecorder._callback` and the streaming engine. The `inject/streaming.py:StreamingInjector` wraps the platform's `InjectorBackend`.

2. **Remote mode** (`daemon._remote_session` flag set via IPC `remote_start`): instantiates `remote/forwarder.py:RemoteForwarder` and replaces `self._injector` with a `RemoteTextSink` for the duration of the session.

3. **Accessibility mode** (`config.audio.vad_source = "calibrated"`): replaces `audio.vad.is_silent` calls with `audio.vad_calibrated.is_silent_calibrated` using the enrolled threshold.

### 5.2 Platform Bundle Extension

`src/yazses/platform/base.py` receives one new optional Protocol method:

```python
@runtime_checkable
class HotkeyBackend(Protocol):
    # existing: run(), stop()
    # NEW (optional):
    def set_input_device(self, device_path: str) -> None: ...
    """Set alternative evdev device path for accessibility input (Linux only)."""
```

`Platform.extras` dict (already present in v0.2) is used by `cap-001` to store `remote_session: RemoteForwarder | None` without changing the frozen `Platform` dataclass signature.

### 5.3 IPC Protocol Extension

`ipc/server.py` receives four new registered method handlers in `Daemon._start_ipc_server()`:

| Method | Direction | Purpose |
|---|---|---|
| `remote_start` | CLI → daemon | Start a remote forwarding session |
| `remote_stop` | CLI → daemon | Tear down the tunnel |
| `remote_status` | CLI → daemon | Query tunnel health |
| `enroll_start` | CLI → daemon | Launch enrollment wizard subprocess |
| `streaming_enable` | CLI → daemon | Enable/disable streaming mode at runtime |
| `command_dispatched` | daemon → IPC | Notification pushed to connected clients |

The existing JSON-RPC 2.0 framing (`ipc/protocol.py`) is unchanged. The new `notify()` method on `IpcServer` wraps a JSON-RPC 2.0 notification (no `id` field).

### 5.4 Config Schema Extension

`src/yazses/config.py` gains the following new dataclasses, all with safe defaults so existing configs remain valid:

```python
@dataclass
class StreamingConfig:
    enabled: bool = True
    partial_interval_ms: int = 300
    partial_marker: str = ""          # optional dim/italic prefix

@dataclass
class DisfluencyConfig:
    enabled: bool = True
    filler_words: list[str] = field(default_factory=lambda: [
        "um", "uh", "er", "ah", "hmm", "like", "you know",
        "i mean", "basically", "right", "okay so"
    ])
    self_correction_triggers: list[str] = field(default_factory=lambda: [
        "no wait", "delete that", "scratch that", "never mind",
        "forget that", "strike that"
    ])
    llm_enabled: bool = False
    llm_endpoint: str = "http://localhost:11434"

@dataclass
class AccessibilityConfig:
    min_silence_ms: int = 500
    pre_speech_padding_ms: int = 200
    vad_source: str = "default"       # "default" | "calibrated"
    vad_threshold: float = 0.01       # overridden by enroll wizard

@dataclass
class CommandsConfig:
    enabled: bool = True
    profile: str = "auto"             # "auto" | "vscode" | "neovim" | "terminal"
    custom: list[dict[str, str]] = field(default_factory=list)

@dataclass
class RemoteConfig:
    default_host: str = ""
    ssh_port: int = 22
    agent_port: int = 9875
    key_file: str = ""

@dataclass
class Config:
    # existing fields unchanged
    stt: SttConfig = field(default_factory=SttConfig)
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    injection: InjectionConfig = field(default_factory=InjectionConfig)
    general: GeneralConfig = field(default_factory=GeneralConfig)
    # new v0.3.0 fields
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
    filters: DisfluencyConfig = field(default_factory=DisfluencyConfig)
    accessibility: AccessibilityConfig = field(default_factory=AccessibilityConfig)
    commands: CommandsConfig = field(default_factory=CommandsConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)
```

### 5.5 New Module Map

| New module path | Cap | Size estimate |
|---|---|---|
| `src/yazses/remote/forwarder.py` | cap-001 | ~120 LOC |
| `src/yazses/remote/local_proxy.py` | cap-001 | ~80 LOC |
| `src/yazses/remote/agent.py` | cap-001 | ~150 LOC |
| `src/yazses/remote/inject.py` | cap-001 | ~60 LOC (mirrors inject/auto.py) |
| `src/yazses/stt/streaming.py` | cap-002 | ~130 LOC |
| `src/yazses/inject/streaming.py` | cap-002 | ~100 LOC |
| `src/yazses/commands/grammar.py` | cap-003 | ~200 LOC |
| `src/yazses/commands/dispatch.py` | cap-003 | ~160 LOC |
| `src/yazses/commands/profiles.py` | cap-003 | ~80 LOC |
| `src/yazses/stt/filters/disfluency.py` | cap-004 | ~120 LOC |
| `src/yazses/accessibility/enroll.py` | cap-005 | ~180 LOC |
| `src/yazses/audio/vad_calibrated.py` | cap-005 | ~50 LOC |
| `src/yazses/audio/padding.py` | cap-005 | ~60 LOC |
