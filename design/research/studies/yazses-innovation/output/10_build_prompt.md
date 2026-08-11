---
id: "build-prompt-yazses-v030"
title: "YazSes v0.3.0 — Build Prompt for Claude Code"
type: build_prompt
scenario: yazses-innovation
created_at: 2026-05-14
updated_at: 2026-05-14
confidence: high
---

# YazSes v0.3.0 — Build Prompt for Claude Code

## Repository and Architecture

You are implementing YazSes v0.3.0. The repository is at `/home/mohsen/scratch/yazses`. The project is a cross-platform, offline hold-to-talk voice dictation daemon (Linux/macOS/Windows). It uses Python 3.11+, managed with `uv`. The test command is `uv run pytest tests/ -v`.

**Existing pipeline (do not break):**

```
Hotkey hook → AudioRecorder → FasterWhisperEngine → postprocess/cleaner.py → inject/auto.py
```

The daemon orchestrator is `src/yazses/core/daemon.py`. Platform abstractions (hotkey, injector, IPC server/client, lifecycle, tray) are in `src/yazses/platform/`. All platform backends implement Protocol interfaces declared in `src/yazses/platform/base.py`. Config is a dataclass tree in `src/yazses/config.py`, loaded from TOML at `~/.config/yazses/config.toml`. IPC uses JSON-RPC 2.0 over newline-delimited JSON on a Unix socket (Linux/macOS) or named pipe (Windows), implemented in `src/yazses/ipc/`.

---

## Files to Create

Create all of the following new files. Do not modify existing files unless explicitly instructed.

### cap-001 — SSH/Remote Voice Forwarding

| File | Responsibility |
|---|---|
| `src/yazses/remote/__init__.py` | Empty package init |
| `src/yazses/remote/forwarder.py` | SSH tunnel lifecycle: spawns `ssh -R 9875:localhost:9875 user@host yazses-agent --listen 9875` via `subprocess.Popen`. Exposes `connect(host, port, key_file)`, `disconnect()`, `is_connected() -> bool`. Monitors the subprocess and sets a `_connected: bool` flag. |
| `src/yazses/remote/local_proxy.py` | Listens on local TCP loopback port 9875 for JSON-RPC `inject(text)` calls arriving from the SSH tunnel. Bridges received text to the `InjectorBackend` passed at construction. |
| `src/yazses/remote/agent.py` | Standalone script: `yazses-agent --listen PORT`. Accepts JSON-RPC `inject(text)` over TCP loopback. Calls `remote/inject.py` to type the text. Zero `faster-whisper` imports. |
| `src/yazses/remote/inject.py` | Mirrors `inject/auto.py`: probes for `xdotool`, `ydotool`, `wtype` (Linux), `SendInput` (Windows), `CGEventPost` (macOS). Returns best available `InjectorBackend` instance. |

**Implementation notes for cap-001:**
- The SSH command is: `ssh -o ExitOnForwardFailure=yes -R 9875:127.0.0.1:9875 [-i key_file] [-p port] host yazses-agent --listen 9875`
- `forwarder.py` must catch `FileNotFoundError` (ssh not installed) and raise a descriptive `YazSesError`.
- `local_proxy.py` uses `asyncio` streams to accept connections on `127.0.0.1:9875`.
- `agent.py` is the entry point for the `yazses-agent` CLI command (add to `pyproject.toml` `[project.scripts]` as `yazses-agent = "yazses.remote.agent:main"`).
- Session state: add `REMOTE_SETUP` and `REMOTE_ACTIVE` to `TrayState` enum in `platform/base.py`.
- Add IPC methods `remote_start`, `remote_stop`, `remote_status` to `ipc/server.py`.
- Add CLI subcommand `yazses remote --host` to `cli.py` that calls `remote_start` over IPC.

### cap-002 — Streaming Transcription with Real-Time Display and Correction

| File | Responsibility |
|---|---|
| `src/yazses/stt/streaming.py` | Wraps `WhisperModel.transcribe()` on a rolling `np.ndarray` audio buffer. Implements LocalAgreement 2-iteration policy: maintains `_prev_hypothesis: str`; on each decode tick computes `os.path.commonprefix([prev, new])` (adapted for strings); emits only the new stable prefix delta. Exposes `stream_partials(audio_queue: asyncio.Queue) -> AsyncGenerator[PartialHypothesis, None]`. |
| `src/yazses/inject/streaming.py` | Stateful wrapper around `InjectorBackend`. Tracks `_chars_injected: int`. `inject_partial(text)` injects new chars and increments counter. `commit(final_text)` issues `Shift+Left × _chars_injected` then injects final_text. `cancel()` issues `_chars_injected` backspaces. |

**Implementation notes for cap-002:**
- `PartialHypothesis` is a `dataclass` with fields `text: str`, `is_stable: bool`, `char_count: int`.
- The stable prefix comparison is: `common = ""` then iterate chars of both strings in parallel until mismatch. The stable delta is `common[len(last_emitted):]`.
- `StreamingEngine` runs in a `threading.Thread` started by `daemon._build_pipeline()` when `config.streaming.enabled = True`.
- The audio queue is an `asyncio.Queue[np.ndarray]`; audio chunks are pushed by `AudioRecorder._callback` when streaming is active.
- Add `inject_key_sequence(keys: list[str])` to `InjectorBackend` Protocol in `platform/base.py`. Implement in each platform injector: Linux xdotool (`xdotool key shift+Left`), macOS CGEventPost with shift modifier, Windows SendInput with VK_LEFT + SHIFT.
- Add config dataclass `StreamingConfig` to `config.py`: `enabled: bool = True`, `partial_interval_ms: int = 300`.
- Add `streaming_enable` IPC method to `ipc/server.py`.

### cap-003 — Code Command Grammar

| File | Responsibility |
|---|---|
| `src/yazses/commands/__init__.py` | Empty package init |
| `src/yazses/commands/grammar.py` | Stateless classifier. `classify(text: str, profile: str = "default") -> CommandIntent`. Evaluates an ordered list of compiled `re.Pattern` entries against `text`. Returns `CommandIntent(intent=DICTATE, ...)` if no match. |
| `src/yazses/commands/dispatch.py` | Receives `CommandIntent`. Routes `DICTATE` to normal injection. Routes structured intents to `InjectorBackend.inject_key_sequence()` or `subprocess.run`. Emits `command_dispatched` IPC notification. |
| `src/yazses/commands/profiles.py` | Loads per-app profiles from `config.toml` `[commands.profiles.*]` sections. Returns `ProfileRegistry` mapping profile name to `GrammarSpec`. |

**Implementation notes for cap-003:**
- `CommandIntent` is a `dataclass`: `intent: IntentType`, `action: str`, `args: dict[str, str]`, `raw_text: str`.
- `IntentType` is an `Enum`: `DICTATE`, `NAVIGATE`, `EDIT`, `REFACTOR`, `TERMINAL`.
- `GrammarSpec` is a list of `(re.Pattern, IntentType, str)` tuples (pattern, intent, action_name).
- Implement all 12 commands from the PRD FR-003.3 table as compiled regex entries.
- Number word normalisation: implement a `_normalise_numwords(text: str) -> str` helper that replaces "one"→"1", "two"→"2", "three"→"3" (through "ten"→"10") before pattern matching.
- `dispatch.py` action table maps action names to key sequences: `"undo" → ["ctrl+z"]`, `"save" → ["ctrl+s"]`, `"go_to_line" → ["ctrl+g", "{n}", "Return"]`, etc.
- Add config dataclass `CommandsConfig` to `config.py`: `enabled: bool = True`, `profile: str = "auto"`, `custom: list[dict] = []`.

### cap-004 — Offline Disfluency Filter

| File | Responsibility |
|---|---|
| `src/yazses/stt/filters/__init__.py` | Empty package init |
| `src/yazses/stt/filters/disfluency.py` | Pure-Python filter. `filter_transcript(text: str, config: DisfluencyConfig) -> FilterResult`. Applies three rules in sequence: (A) filler word regex removal, (B) consecutive 2-gram deduplication, (C) self-correction trigger detection and preceding text removal. |

**Implementation notes for cap-004:**
- `FilterResult` is a `dataclass`: `text: str`, `chars_removed: int`.
- Rule A: compile `re.compile(r'\b(' + '|'.join(re.escape(w) for w in config.filler_words) + r')\b[,]?', re.I)`. Substitute with `""`. Then normalise multiple spaces.
- Rule B: tokenise by whitespace. Walk with a sliding 2-gram window; if `tokens[i:i+2] == tokens[i+2:i+4]`, remove the second occurrence. Repeat until stable.
- Rule C: scan for any trigger phrase from `config.self_correction_triggers`. If found, remove from the last sentence boundary (`.`, `!`, `?`) before the trigger, through to the end of the trigger phrase.
- Proper noun and code identifier guard: apply rules only to tokens that are all-lowercase or match `\b(um|uh|er|...)\b`. Do NOT strip tokens that contain uppercase letters (proper nouns) or contain `_`, `/`, `.` (code identifiers).
- Add `DisfluencyConfig` and `FiltersConfig` to `config.py` with all fields from the architecture doc (§5.4).
- Wire `disfluency.filter_transcript()` into `core/daemon.py` in `_process_final_transcript()`, after `postprocess/cleaner.py` and before `commands/grammar.py`.

### cap-005 — Accessibility Profile

| File | Responsibility |
|---|---|
| `src/yazses/accessibility/__init__.py` | Empty package init |
| `src/yazses/accessibility/enroll.py` | Interactive CLI wizard. Records 20 utterances via `AudioRecorder`. Computes per-user RMS stats. Writes `vad_threshold`, `min_silence_ms`, `pre_speech_padding_ms` to `config.toml`. |
| `src/yazses/audio/vad_calibrated.py` | `is_silent_calibrated(audio: np.ndarray, config: AccessibilityConfig) -> bool`. Drop-in replacement for `vad.is_silent()` using `config.vad_threshold`. |
| `src/yazses/audio/padding.py` | Ring buffer holding last `config.accessibility.pre_speech_padding_ms` ms of audio. `prepend_padding(audio: np.ndarray) -> np.ndarray` returns the ring buffer + audio. |

**Implementation notes for cap-005:**
- `enroll.py`: for each of 20 utterances, record 3 s using `AudioRecorder`, compute `noise_floor = np.abs(audio[:int(0.5 * 16000)]).mean()` and `speech_rms = np.abs(audio[int(0.5 * 16000):]).mean()`. After all 20: `vad_threshold = np.percentile(noise_floors, 95) * 3.0`, `min_silence_ms = max(500, int(np.percentile(pause_durations, 95)))`. Write to config with `tomllib`/`tomli_w`.
- `platform/linux/hotkey.py`: add `evdev_device: str = ""` to config lookup. If `config.hotkey.source == "evdev"` and `config.hotkey.evdev_device != ""`, open that device path instead of the default keyboard device.
- Add CLI command `yazses enroll` to `cli.py` that calls `accessibility/enroll.py:run_wizard()`.
- Extend `yazses doctor` to accept `--accessibility` flag: print current values of `vad_threshold`, `min_silence_ms`, `pre_speech_padding_ms`, `hotkey.evdev_device`, `stt.model`.
- Add `AccessibilityConfig` and `RemoteConfig` to `config.py` (see architecture doc §5.4 for all fields and defaults).

---

## Config Schema Changes

Modify `src/yazses/config.py` to add the following dataclasses (all fields have safe defaults so existing configs remain valid):

```python
@dataclass
class StreamingConfig:
    enabled: bool = True
    partial_interval_ms: int = 300
    partial_marker: str = ""

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
    vad_source: str = "default"
    vad_threshold: float = 0.01

@dataclass
class CommandsConfig:
    enabled: bool = True
    profile: str = "auto"
    custom: list[dict] = field(default_factory=list)

@dataclass
class RemoteConfig:
    default_host: str = ""
    ssh_port: int = 22
    agent_port: int = 9875
    key_file: str = ""
```

Add these as fields to the top-level `Config` dataclass: `streaming`, `filters`, `accessibility`, `commands`, `remote`.

---

## Architecture Decisions (Already Made — Do Not Relitigate)

All design decisions are locked. Implement exactly as specified:

- **ADR-001:** Only transcribed text crosses the SSH tunnel. No audio bytes leave the local machine. `remote/forwarder.py` and `remote/local_proxy.py` have zero imports of `sounddevice` or `audio.*`.
- **ADR-002:** Use LocalAgreement 2-iteration policy for streaming partial hypotheses. Do not emit raw Whisper output. The stable prefix is the longest common prefix between two consecutive decode passes.
- **ADR-003:** Command classification is a compiled-regex grammar classifier on text output from Whisper. No second ASR model, no fine-tuning, no LLM classifier.
- **ADR-004:** Correction-on-commit uses `Shift+Left × _chars_injected` to select partial text, then injects final text to replace. No clipboard operations. No floating overlay window.
- **ADR-005:** Accessibility in v0.3.0 is config parameters + enrollment wizard only. No LoRA fine-tuning. No new ML dependencies.

---

## Tests to Write

For each new module, create a corresponding test file in `tests/`. Write tests that do not require real hardware (mock `sounddevice`, `evdev`, `xdotool`, `subprocess`):

| Test file | What to test |
|---|---|
| `tests/test_disfluency_filter.py` | Parametrised test over `tests/fixtures/disfluency/corpus.json`. Assert `filter_transcript(input)` equals `expected`. Assert runtime < 10 ms via `time.perf_counter`. Assert proper nouns and identifiers are unchanged. |
| `tests/test_grammar_classifier.py` | Parametrised test over `tests/fixtures/commands/command_phrases.json` (50 command phrases) and `tests/fixtures/commands/dictation_corpus.txt` (25 ~20-word phrases). Assert precision ≥ 90% on command set. Assert zero false positives on dictation corpus. |
| `tests/test_streaming_engine.py` | Load 3 WAV fixtures from `tests/fixtures/streaming/`. Run `StreamingEngine` with mock `WhisperModel`. Assert first `inject_partial()` call occurs within 600 ms of fixture start. |
| `tests/test_streaming_injector.py` | Unit tests for `StreamingInjector` state machine. Test `inject_partial()` increments counter. Test `commit()` issues correct Shift+Left count. Test `cancel()` issues correct backspace count. Test counter resets to 0 after each. |
| `tests/test_accessibility_enroll.py` | Load 20 WAV fixtures from `tests/fixtures/accessibility/calibration_utterances/`. Run `run_wizard()` with mock `AudioRecorder` and mock config write. Assert derived `vad_threshold` is within ±15% of expected value from `rms_stats.json`. |
| `tests/test_vad_calibrated.py` | Unit tests for `is_silent_calibrated()`. Assert silent audio (RMS < threshold) returns `True`. Assert speech audio (RMS > threshold) returns `False`. |
| `tests/test_audio_padding.py` | Unit tests for ring buffer in `padding.py`. Assert `prepend_padding()` prepends exactly `pre_speech_padding_ms` ms of prior audio. Assert ring buffer wraps correctly. |
| `tests/test_remote_agent.py` | Unit test for `agent.py` JSON-RPC handler. Mock `remote/inject.py`. Assert `inject(text)` call triggers the mock injector with the correct text. |

Create the test fixture files:
- `tests/fixtures/disfluency/corpus.json` — 100 entries as described in the eval plan.
- `tests/fixtures/commands/command_phrases.json` — 50 entries, one per command from FR-003.3.
- `tests/fixtures/commands/dictation_corpus.txt` — 500 words of prose.
- `tests/fixtures/streaming/` — at minimum 3 WAV files (synthetic, 16 kHz, float32, 3 s).
- `tests/fixtures/accessibility/calibration_utterances/` — 20 WAV files (synthetic, 16 kHz, float32, 3 s).
- `tests/fixtures/accessibility/rms_stats.json` — expected RMS statistics for the 20 fixtures.

---

## Pass/Fail Criteria

All of the following must be true before reporting complete:

| ID | Criterion |
|---|---|
| M-001-LAN | SSH tunnel injection latency ≤ 500 ms median on LAN |
| M-001-WAN | SSH tunnel injection latency ≤ 800 ms median on WAN |
| M-002-TTFP | Time-to-first-partial ≤ 600 ms median on streaming fixtures |
| M-002-COR | Correction operation latency ≤ 200 ms with 50 chars injected |
| M-002-CANCEL | Zero partial chars remain after cancel |
| M-003-PREC | Command grammar precision ≥ 90% on 50-command phrase set |
| M-003-FPR | Zero false-positive commands on 500-word dictation corpus |
| M-003-RT | `grammar.classify()` runtime ≤ 5 ms |
| M-004-RT | `disfluency.filter_transcript()` runtime ≤ 10 ms |
| M-004-PNID | Proper nouns and code identifiers unchanged by filter |
| M-005-ENR | Enrollment wizard produces `vad_threshold` within ±15% of expected |
| R-001 | `test_config.py` still passes (no schema breakage) |
| R-002 | `test_ipc_protocol.py` still passes (no IPC breakage) |
| R-003 | `test_hold_detector.py` still passes |
| R-004 | `test_auto_inject.py` still passes |

---

## Version Bump

After all tests pass, update the version in two places:

1. `pyproject.toml`: change `version = "0.2.4"` to `version = "0.3.0"`.
2. `src/yazses/__init__.py`: set `__version__ = "0.3.0"`.

Verify: `uv run yazses --version` outputs `YazSes 0.3.0`.

---

Run `uv run pytest tests/ -v` and confirm all tests pass before reporting complete.
