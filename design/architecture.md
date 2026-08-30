# YazSes Architecture

Last updated: 2026-05-18 (v1.0.0-dev.5)

---

## v1.0 Rust-core Architecture (archived — `archive/rust-hci-v1` branch)

> This Rust architecture is **not on `main`** anymore. It was moved to the
> `archive/rust-hci-v1` branch and paused in early stages. `main` is the Python
> app (Part 1; see `docs/cli-reference.md` and the README). Kept here for reference.

### Workspace crates

| Crate | Role |
|---|---|
| `yazses-ipc` | JSON-RPC 2.0 over Unix socket / named pipe; `handler!` macro; `SyncIpcClient` |
| `yazses-core` | Daemon orchestrator, state machine (9 states), config paths, doctor, enroll |
| `yazses-cli` | `yazses` binary — all v0.4 subcommands via `clap` |
| `yazses-inputs` | `InputBackend` Protocol; `HoldDetector`; evdev `KeyboardHoldBackend`; `EmgYespBackend` |
| `yazses-audio` | `AudioCapture` (cpal); `VadGate` (RMS; or `SileroVad` with `--features silero`); `PaddingBuffer` ring buffer |
| `yazses-stt` | `STTBackend` Protocol; `STTRouter` (4 s threshold); `MoonshineV2Backend` (PyO3 0.28, ~9 ms P50); `WhisperBackend` (whisper-rs 0.16; state reused) |
| `yazses-llm` | `LLMBackend` Protocol; `LlamaCppBackend`; `OllamaBackend`; `OpenAICompatibleBackend` (feature-gated); `Tier` enum (`Fast`/`Deep`); 20-tool registry; GBNF compiler; `CleanupEngine` (offline dictation reformatting, mode-based, reuses the loaded backend — ADR-013) |
| `yazses-editors` | `EditorBridge` Protocol; 5-tier `WindowDetector`; `NeovimBridge` (nvim-rs); `VSCodeBridge` (TCP port 57843); `EditorContext.to_llm_block()` |
| `yazses-memory` | `PersonalMemory` (SQLite BLOB KNN); PBKDF2 key + passphrase lockout (5 attempts → 15 min); SQLCipher; `OnnxEmbedder` (BGE-small-en 384-dim, ONNX mean-pool + L2-norm) |
| `yazses-atspi` | Linux AT-SPI / speech-dispatcher screen-reader announcer |
| `yazses-nvda` | Windows NVDA controller DLL + SAPI fallback |

### v1.0 Pipeline

```
Hold-key / EMG squeeze (yazses-inputs / InputBackend)
  → HoldStart event → DaemonState: Idle → Recording
  → AudioCapture (cpal) + VadGate (RMS; or SileroVad with --features silero)
  → PaddingBuffer prepends pre-speech ring buffer
  → HoldEnd event → DaemonState: Recording → Transcribing
  → EditorBridge.get_context() [async, parallel with audio]
      └─ 5-tier WindowDetector (Hyprland → Sway → WLR-toplevel → X11 EWMH → Null)
      └─ NeovimBridge (nvim-rs, $NVIM socket) / VSCodeBridge (TCP push, port 57843)
      └─ EditorContext.to_initial_prompt(224 BPE tokens) → ASR initial_prompt
      └─ EditorContext.to_llm_block() → LLM <editor_context> block
  → STTRouter (duration ≤ 4 s → streaming / > 4 s → long-form)
      ├─ MoonshineV2Backend  (PyO3 0.28, moonshine-voice, ~9 ms P50)
      └─ WhisperBackend      (whisper-rs 0.16, whisper.cpp; state reused across calls)
  → TranscriptReady event (stays in Transcribing)
  → LLMBackend.complete(LLMRequest { system_prompt, messages, grammar, editor_context, tier: Tier::Fast })
      ├─ LlamaCppBackend             (llama-cpp-2, GGUF, prompt caching on LSP prefix; --features llama-cpp)
      ├─ OllamaBackend               (reqwest, localhost:11434; --features ollama)
      └─ OpenAICompatibleBackend     (opt-in only; --features openai-compatible; never default)
  → LLMOutput: ToolCall | Text
  → CleanupEngine.clean(text, mode)   (dictation/type_text branch only; off by default;
                                       YAZSES_CLEANUP_* env; guards + fallback — ADR-013)
  → ToolCallReady event → DaemonState: Transcribing → Injecting
  → Dispatcher.dispatch(call) — 20 tools, all implemented:
      ├─ type_text / key_sequence        (xdotool/wtype/ydotool; trailing space appended)
      ├─ commit_to_memory / recall / forget_last  (PersonalMemory)
      ├─ open_file                       (xdg-open)
      ├─ git_commit                      (git subprocess, SHA extracted)
      ├─ goto_symbol                     (nvim --server $NVIM --remote-send)
      ├─ app_launch                      (direct spawn → xdg-open fallback)
      ├─ window_focus                    (wmctrl → xdotool fallback)
      ├─ volume_set                      (wpctl → pactl fallback)
      ├─ media_play_pause                (playerctl → xdotool XF86AudioPlay)
      ├─ screenshot_named                (grim → scrot → gnome-screenshot)
      ├─ note_quick                      (async append ~/notes.md with ISO timestamp)
      ├─ time_set_timer                  (tokio::spawn + sleep + notify-send)
      ├─ dismiss_notification            (dunstctl → notify-send fallback)
      ├─ mode_switch                     (logged; daemon mode wiring next release)
      ├─ send_message                    (stub — platform messaging future)
      └─ clarify / cancel_request        (immediate returns)
  → DispatchComplete event → DaemonState: Injecting → Idle
  → LatencyTracker.record(elapsed_ms)   [P50/P95 over last 100 turns; visible in `yazses status`]
```

### State machine

```
Loading ──ModelsLoaded──→ Idle ──HoldStart──→ Recording ──HoldEnd──→ Transcribing
                           ↑                                              │
                     DispatchComplete                            TranscriptReady (loop)
                           │                                    ToolCallReady ──→ Injecting
                        Injecting ◀─────────────────────────────────────┘
                           │
                     DispatchComplete → Idle

Idle → EnrollStart → Enrolling → EnrollComplete → Idle
Idle → RemoteStart → RemoteSetup → RemoteConnected → RemoteActive → RemoteStop → Idle
Any state + ErrorOccurred → Error → ErrorResolved → Idle
```

### IPC methods (v1.0 additions)

| Method | Description |
|---|---|
| `memory_commit` | Store text + source into PersonalMemory |
| `memory_recall` | KNN search over PersonalMemory |
| `memory_forget` | Delete records from the last N minutes |
| `latency_stats` | Return P50/P95 latency over last 100 turns (from `LatencyTracker`) |

### Latency budget (v1.0.0-dev.5)

```
Hold-key down ─ 0 ms
├─ Input event dispatch          5 ms
├─ Editor bridge query (async)   ≤ 100 ms (warm cache)
├─ Audio capture + VAD           continuous, 30 ms/frame
├─ STT: Moonshine v2             9 ms P50   (streaming path, ≤ 4 s utterance)
├─ STT: Whisper-large-v3-turbo   200–500 ms (long-form path, > 4 s)
├─ LLM prompt-eval               50 ms (cached prefix) / 200 ms (cold)
├─ LLM decode ≤ 50 tokens        200 ms at ~25 tok/s
├─ Tool dispatch                 10–100 ms (OS subprocess)
Tool action visible ────────── ~750 ms P50 (streaming path)
```

`LatencyTracker` maintains a 100-sample VecDeque; P50 and P95 are reported by `yazses status`.

### New features in v1.0.0-dev.5

| Feature | Crate | Notes |
|---|---|---|
| `Tier` enum on `LLMRequest` | `yazses-llm` | `Tier::Fast` (default) selects inline GGUF/Ollama; `Tier::Deep` reserved for v2 multi-turn flows |
| `LatencyTracker` | `yazses-core` | 100-sample VecDeque; P50/P95 surfaced via `yazses status` |
| `SileroVad` feature gate | `yazses-audio` | Build with `--features silero` to replace RMS gate with Silero ONNX VAD |
| Passphrase lockout | `yazses-memory` | 5 failed unlock attempts trigger a 15-minute cooldown (`key.rs`) |
| `OnnxEmbedder` | `yazses-memory` | BGE-small-en-v1.5 (384-dim); tokenizers + ONNX runtime; mean-pool + L2-norm |
| `OpenAICompatibleBackend` | `yazses-llm` | Feature-gated (`--features openai-compatible`); never compiled by default; opt-in only; zero-egress guarantee maintained |
| `yazses bugreport` | `yazses-cli` | Collects daemon logs, config (secrets stripped), sysinfo into a tarball |
| `yazses memory destroy --i-mean-it` | `yazses-cli` | Irreversibly wipes the encrypted PersonalMemory database |

### Test coverage

94 Rust unit tests across all workspace crates (up from 85 in dev.4).

---

## v0.4 Python Pipeline (legacy, preserved)

### System overview

```
┌────────────────────────┐   ┌──────────────────┐
│ Hotkey hook            │──▶│ Audio recorder   │
│ (per-OS API)           │   │ PortAudio/16kHz  │
│ OR EMGBackend (v0.4.0) │   │ PreSpeechRingBuf │
└────────────────────────┘   └────────┬─────────┘
                                      │
                    ┌─────────────────▼──────────────────────────┐
                    │ STT pipeline                                 │
                    │  1. vad_calibrated (silence gate)           │
                    │  2. faster-whisper (CPU / int8)             │
                    │     ↑ initial_prompt from LspContextProvider│ ← v0.4.0
                    │  3. clean_text                              │
                    │  4. disfluency filter                       │
                    │  5. grammar.classify()                      │
                    │     Tier 1: regex rules (< 5 ms)            │
                    │     Tier 2: SLMRouter (llama-cpp, optional) │ ← v0.4.0
                    └───────────────────┬────────────────────────┘
                                        │
                       ┌──────────────────────────────────────────┐
                       │ Dispatcher                                 │
                       │  DICTATE  → llm_cleanup (optional)         │ ← ADR-013
                       │           → continuation spacing           │
                       │           → injector.inject(text)          │
                       │  COMMAND  → inject_key_sequence()           │
                       └────────────────┬───────────────────────────┘
                                        │
             ┌──────────────────────────▼─────────────────────────┐
             │ Injector (local or remote)                           │
             │  Local:  xdotool / ydotool / wtype / SendInput      │
             │  Remote: RemoteInjectorProxy → SSH → agent          │
             └─────────────────────────────────────────────────────┘

Daemon owns the state machine and IPC server:

  LOADING → IDLE ↔ RECORDING → TRANSCRIBING → INJECTING → IDLE
                 ↕               (ERROR)
  REMOTE_SETUP → REMOTE_ACTIVE
  ENROLLING
  PAUSED
```

**DICTATE-path post-process chain (`core/daemon.py::_on_hold_end`).** After `clean_dictation`,
the cleaned transcript flows through a chain of **opt-in, OFF-by-default** text transforms, each
guarded by its own config flag (`if self._config.<x>.enabled: text = transform(text)`). Order:
self-repair (ADR-058) → inline compute (086) → phonetic corrector (027) → voice punctuation →
entity ITN (045) → redaction (046) → symbols (055) → unit convert (056) → temporal (057) →
grammar repair (050) → diacritize (122) → transliteration (116) → semantic line breaks (111) →
structured markup (067) → SafeGlyph warn (123) → auto-pairing (088) → prosody (002). Adding a new
pure-text feature = one guarded stanza here plus a `test_v2_daemon_wiring.py` case that enables the
flag and asserts the effect. (Many other v2 cores are built + tested but not yet wired into a
runtime path — see an internal planning note.)

---

## Module map

### `src/yazses/core/`

| File | Role |
|---|---|
| `daemon.py` | Orchestrator — owns state machine, IPC, pipeline wiring, signal handling |

### Guards between the transcript and the injector

Three run in `daemon.py::_on_hold_end`, **in this order**, and the order is load-bearing.

| Module | Role |
|---|---|
| `cmdsafety/classify.py` | Risk-classify a dictated shell command; `ConfirmGate` holds a dangerous one pending a spoken confirm (ADR-v2-065) |
| `cmdsafety/spoken.py` | Match the confirm/cancel word — anchored at **both** ends, because "cancel the meeting" is dictated text |
| `checkdigit/guard.py` | Is this utterance a checkable number that failed? Bare numbers only, ≥12 digits, failing every applicable scheme (ADR-021) |
| `checkdigit/validate.py` | Luhn / ISBN-10 / ISBN-13 / Verhoeff + single-edit fix suggestion (pure) |
| `staged/buffer.py` | Review buffer — runs **after** the two above, which would otherwise have their confirm word swallowed as ordinary text |

Each is judged on **how rarely it fires**. A guard that interrupts a house number teaches
the user to dismiss it, and a dismissed guard costs attention while catching nothing —
so each holds only on a specific, checkable signal, never a heuristic.

`cmdsafety` judges the *command text* and deliberately **not** the focused window: focus
detection needs AT-SPI or X11, so on Wayland without AT-SPI the window class is empty, and
a guard that silently stops protecting on a whole display server is worse than none.

### Feedback surfaces

| Module | Role |
|---|---|
| `tray/menu.py::level_ring` | Live input-level ring with the silence gate **anchored at a fixed point**, so "past the notch" means the same thing on every microphone (pure) |
| `earcon/tones.py` | Non-speech motif grammar + numpy synth (pure) |
| `earcon/play.py` | Playback seam — never blocks the hot path, never raises, drops a concurrent cue rather than queueing a late one |
| `settingsui/theme.py` | Secondary-text colour computed from the desktop palette to stay above WCAG AA 4.5:1; Qt-free maths |
| `system/depsize.py` | What enabling a feature will download — *marginal* against what is installed, from a committed table of resolved closures, plus the model files it fetches on first run (ADR-018) |

### `src/yazses/platform/`

| File | Role |
|---|---|
| `base.py` | Protocol interfaces: `HotkeyBackend`, `InjectorBackend`, `LifecycleBackend`, `IpcServer`, `IpcClient`, `PermissionsBackend`, `TrayBackend` |
| `factory.py` | `get_platform()` — detects `sys.platform`, returns `Platform` dataclass |
| `emg/backend.py` | `EMGBackend` — `HotkeyBackend` over USB CDC serial YESP protocol (v0.4.0); requires `pyserial` optional dep |
| `linux/` | evdev hotkey, LinuxInjector (xdotool/ydotool/wtype/clipboard), systemd lifecycle, Unix socket IPC |
| `macos/` | CGEventTap hotkey, MacosInjector (CGEvent Unicode), launchd lifecycle, rumps tray |
| `windows/` | WH_KEYBOARD_LL hotkey, WindowsInjector (SendInput UTF-16), named-pipe IPC, pystray tray |

### `src/yazses/inject/` (Linux sub-backends)

| File | Role |
|---|---|
| `auto.py` | Runtime probe: xdotool → ydotool → wtype → clipboard |
| `base.py` | `BaseInjector` protocol (inject, inject_backspaces, inject_key_sequence) |
| `xdotool.py` | X11 via `xdotool type` / `xdotool key` |
| `ydotool.py` | Wayland via `ydotool` |
| `wtype.py` | Wayland via `wtype` |
| `clipboard.py` | Universal fallback via clipboard + Ctrl+V |
| `streaming.py` | `StreamingInjector` — tracks partial char count, correction-on-commit via Shift+Left |

### `src/yazses/stt/`

| File | Role |
|---|---|
| `faster_whisper.py` | `FasterWhisperEngine` — wrapper around `faster_whisper.WhisperModel`; accepts `initial_prompt` for LSP context (v0.4.0) |
| `vocabulary.py` | Built-in STT vocabulary. `merge_initial_prompt(*parts)` always primes the coined app name `YazSes` (`BUILTIN_PROMPT`), placed **after** the configured/personal vocab because faster-whisper keeps only the last `PROMPT_TOKEN_BUDGET` = 223 tokens of a prompt and silently drops the front — first meant first to be discarded, so a large vocabulary cost exactly the priming this module exists for. Single chokepoint used by `daemon._effective_initial_prompt`, which also merges the user's personal dictionary (`system/vocabulary.py`, `yazses vocab`) |
| `streaming.py` | `StreamingEngine` — background decode thread, LocalAgreement stable-prefix policy (ADR-002). `prefix_stable_for_ms()` accessor + `prewarm()` feed Ghost Ahead endpoint anticipation |
| `filters/disfluency.py` | Disfluency filter: filler removal → 2-gram dedup → **opt-in collapse pass (Rule B.5, ADR-015): sub-word repetition + prolongation collapse for Dysfluency-Friendly Mode, off by default, `_is_protected`-guarded** → self-correction rollback |
| `endpoint.py` | Ghost Ahead pivot (spec-ghost-ahead): `EndpointAnticipator` (with debounce) — predicts end-of-utterance from partial-transcript stability + trailing silence. **Wired** into `_partial_poll_loop` via `daemon._endpoint_prewarm_tick`: on a likely endpoint, pre-warm (eager, discardable decode); `[endpoint]` off by default. Speculative finalize (Phase 2) gated |
| `faster_whisper.py` | `FasterWhisperEngine.transcribe` (fast path) + `transcribe_words()` — opt-in word-timestamp path returning `(text, list[Word])`, used by Prosody Ink (`[prosody]`) and by Diarized Recording Import (`recimport/pipeline.py`, `yazses transcribe <file>`) |

### `src/yazses/recimport/` (Wave O, ADR-v2-125 — Diarized Recording Import)

CLI-only (`yazses transcribe <file>`); no daemon/IPC/hotkey involvement. Off by
default; diarization is lazy behind the `diarization` extra. `pipeline.py::transcribe_file`
is pure orchestration with injected backends, so every stage is unit-testable without models.

| File | Role |
|---|---|
| `pipeline.py` | `transcribe_file()` — orchestrates decode → STT words → optional diarize → align → name → render |
| `audio_io.py` | `load_audio()` — PyAV via `faster_whisper.decode_audio` (any format → 16 kHz mono), ffmpeg-CLI fallback; **no new dep** |
| `diarizer.py` | `SherpaDiarizer` (sherpa-onnx int8 ONNX); `factory.build_diarizer()` returns `None` when dormant |
| `align.py` | Pure-numpy max-overlap word↔turn assignment + `merge_utterances()` |
| `naming.py` | Speaker naming: `--names`/`--rename` > enrolled voiceprint (`voiceprint/` centroid + `nearest_profile`, gated ≥`min_speaker_seconds`/≥`name_threshold`) > "Speaker N" |
| `render.py` | txt / md / srt / vtt / json writers (reuses `subtitles.py`, `diarize/labels.py`) |
| `download.py` | Fetches the ~15 MB sherpa segmentation + embedding models |

Privacy (ADR-011/012): fully offline; diarization labels are transient; voiceprint naming is
opt-in, consent-gated, on-device, and never auto-enrolls third parties. Cloud escalation is
designed but deferred (ADR-v2-126).

### `src/yazses/commands/`

| File | Role |
|---|---|
| `grammar.py` | `classify(text, profile, slm_router=None, macro_table=None)` — Tier 0: user macros (whole-utterance exact match); Tier 1: 28+ regex rules → `CommandIntent`; optional Tier 2: SLMRouter fallback |
| `macros.py` | Say-Macro (spec-say-macro): `MacroTable`/`load_macros`/`expand`/`build_macro_table` — user-defined trigger→`text`/`snippet` expansions from `macros.toml`; `None` (dormant) unless `[macros] enabled` |
| `revise.py` | Mid-Thought Undo (spec-mid-thought-undo): `parse_revise` (whole-utterance "scratch that" family) + `DictationLedger` (LIFO of injected-burst char counts **and text** via `last_text()`/`replace_last()` — the latter feeds Punch-In); daemon backspaces the last burst |
| `slm_router.py` | `SLMRouter` — Tier 2 llama-cpp-python classifier (v0.4.0); disabled when `slm_model_path` unset |
| `lsp_context.py` | `LspContextProvider` — reads editor context via `EditorBridge` (NeovimBridge, NullBridge); 50 ms timeout |
| `dispatch.py` | Routes `DICTATE` to `inject()`, `MACRO` to expand-and-inject (+caret `Left`), all others to `inject_key_sequence()` via `ACTION_KEYS` map |
| `profiles.py` | `ProfileRegistry` — loads `[commands.profiles.*]` TOML sections |

### `src/yazses/remote/`

| File | Role |
|---|---|
| `forwarder.py` | `RemoteForwarder` — spawns SSH reverse tunnel, monitors subprocess, reconnects |
| `local_proxy.py` | `RemoteInjectorProxy` — `InjectorBackend` that sends JSON-RPC `inject(text)` over TCP to localhost:9875 |
| `agent.py` | `yazses-agent` entry point — asyncio TCP server, handles `inject`/`ping` JSON-RPC |
| `inject.py` | `get_remote_injector()` — same probe as `inject/auto.py` but zero faster-whisper imports |

### `src/yazses/audio/`

| File | Role |
|---|---|
| `recorder.py` | `AudioRecorder` — sounddevice → numpy buffer, max_seconds cap |
| `vad.py` | `is_silent(audio)` — RMS-based silence gate (hardcoded threshold) |
| `vad_calibrated.py` | `is_silent_calibrated(audio, config)` — uses `config.vad_threshold` |
| `padding.py` | `PreSpeechRingBuffer` — fixed-capacity ring buffer, `prepend_padding(audio)` for voice-onset recovery |

### `src/yazses/accessibility/`

| File | Role |
|---|---|
| `enroll.py` | `run_wizard()` — records 20 utterances, derives `vad_threshold` + `min_silence_ms`, writes config.toml |

### `src/yazses/learning/` (v0.5.0, ADR-012 — opt-in self-improvement loop)

Off by default. When `[learning] enabled = true`, the daemon writes one event per
hold-release (every text stage + optional audio, including discards) to a local
encrypted corpus, off the dictation hot path. `yazses tune` turns it into
reviewable config diffs.

| File | Role |
|---|---|
| `crypto.py` | Machine-bound AES-256-GCM key (`corpus.key`, `0600`) + `Cipher` |
| `store.py` | Encrypted SQLite `events` + `clips/<id>.wav.enc`; CRUD, stats, `prune`, `forget`, `destroy` |
| `capture.py` | `CorpusWriter` background-thread writer (never blocks the pipeline); `build_writer()` returns `None` when disabled |
| `analysis.py` | `analyze()` → `Proposal`s (vocabulary / VAD / model / disfluency / few-shots); `retranscribe()`; TOML writers |
| `tuner.py` | `run_tune()` — propose → per-proposal approve → `apply` |

### `src/yazses/hotkeys/`

| File | Role |
|---|---|
| `hold_detector.py` | State machine: key-held-for-≥N-ms fires `on_hold_start(leaked_count)` / `on_hold_end()` |

**Optional dedicated command key.** When `[hotkey] command_key` is set (≠ the dictation
key), the daemon builds a *second* hotkey backend (`_make_command_hotkey`) and runs it in
a background thread; the dictation key keeps the main thread. Holding the command key sets
a per-burst `_command_mode` flag (`_on_command_hold_start`), which `_on_hold_end` consumes:
the utterance is always parsed as a command and **never typed as literal text** — an
unmatched phrase is discarded (`discard_reason="command_unmatched"`). Live streaming is
suppressed in command mode so command words are never partially injected.

### `src/yazses/ipc/`

| File | Role |
|---|---|
| `protocol.py` | Minimal JSON-RPC 2.0 over newline-delimited JSON |
| `server.py` | `register(method, fn)` + `serve_in_thread()` |
| `client.py` | `call(method, **params)` + `is_reachable()` |

### `src/yazses/postprocess/`

| File | Role |
|---|---|
| `cleaner.py` | `clean_text(text)` — strips Whisper artefacts (hallucinated prompts, leading/trailing noise) |
| `spacing.py` | `continuation_prefix(text, had_recent_injection)` — returns the separating space prepended before a dictation that continues a recent hold-to-talk burst, suppressed before closing punctuation. Prevents successive bursts gluing together (`...togetherI mean`). Window-gated by `[injection] continuation_window_ms` in `core/daemon.py`. |
| `llm_cleanup.py` | `LlmCleaner` / `build_cleaner()` — optional offline LLM reformatting of dictation (ADR-013); dormant unless `[filters.disfluency] llm_enabled`. Length-ratio + token-preservation guards reject unsafe rewrites. |
| `prosody.py` | Prosody Ink (spec-prosody-ink): `format_prosody` formatter + `annotate(text, audio, sr, words, config)` — **wired** into `_on_hold_end` (batch dictation only): pause->paragraph (no dep) + emphasis->bold via `_prominence_scores` (needs `parselmouth`; degrades to pause-only when absent). `[prosody]` off by default. Pitch->question excluded as unreliable. |
| `punch_in.py` | Punch-In (spec-punch-in): `propose_corrections` + `apply_top_candidate(buffer, respoken)` — difflib alignment -> corrected full burst. **Wired** via `daemon._apply_punch_in`/`_handle_punch_in` + `yazses punch-in` CLI (record respeak -> align -> backspace + retype; `--dry-run`/`--choose N`). `[punch_in]` off by default |

### `src/yazses/tts/`

Read-Back Loop (spec-read-back-loop): offline TTS that speaks the transcript back. Permissive engines only (Kokoro Apache-2.0 default). All deps in the optional `tts` extra, imported only when `[tts] enabled`.

| File | Role |
|---|---|
| `base.py` | `TtsBackend` Protocol (`name`/`synthesize`/`speak`/`cancel`) — no third-party import, always importable |
| `chunking.py` | `sentence_chunks(text)` — regex sentence split so audio streams sentence-by-sentence (optimise time-to-first-audio, not full RTF) |
| `kokoro.py` | `KokoroTtsBackend` — Kokoro-82M int8 ONNX via `kokoro-onnx`, plays each chunk through `sounddevice`; barge-in `cancel()` |
| `null.py` | `NullTtsBackend` — silent no-op used when the engine import/model is unavailable |
| `factory.py` | `build_tts(cfg.tts)` — `None` when dormant, `NullTtsBackend` when enabled-but-unavailable (degrade, never crash) |

Wired in `core/daemon.py`: built at startup; after a **dictation** injection, `_maybe_read_back` truncates to `max_readback_chars` and `_speak_readback` enters the `READBACK` state and speaks on a background thread. Commands are never read back. `yazses say` / `readback_speak` IPC speak on demand. `status` exposes `read_back` + `tts_backend`.

### v2 perceptual & personalization layer (off by default; `design/v2-cognitive-layer/`)

Four advanced features. Each follows the optional-extra + dormant-factory pattern; the dependency-free cores are fully tested, the model/sensor/training parts are behind extras and gated.

| Module | Role |
|---|---|
| `src/yazses/voiceprint/` | **Shared** speaker enrollment. `embedding.py` (cosine + `is_target_frame`), `base.py` (`SpeakerEmbedder` Protocol), `ecapa.py` (speechbrain ECAPA, `voiceprint` extra), `factory.py` (`build_embedder` dormant→None), `enroll.py` (`yazses enroll-voice`), `store.py` (encrypted save/load, ADR-012). |
| `src/yazses/personalize/` | **Voiceprint Mind** (spec-voiceprint-mind). `prompt_builder.py` — `mine_terms` + `build_prompt` compose a biased `initial_prompt`. P1 wired via `daemon._effective_initial_prompt` (`[personalize]`, `YAZSES_VOCABULARY`). P2 LoRA pipeline gated. |
| `src/yazses/audio/personal_vad.py` | **Cocktail Filter** (spec-cocktail-filter). `gate()` drops non-target-speaker frames; wired via `daemon._maybe_cocktail_gate` before STT (`[cocktail]`, needs an enrolled voiceprint). |
| `src/yazses/gaze/` | **Glance-Type** (spec-glance-type) look-to-pane. `calibrate.py` (least-squares gaze→screen), `zones.py` (`grid_zone`/`window_at_point`/`resolve_window`), `l2cs.py` (L2CS-Net backend, manual-install), `factory.py`. `yazses gaze calibrate`. Hold-start routing pending. |
| `src/yazses/polyglot/` | **Polyglot Switch** (spec-polyglot-switch). `lid.py` — `parse_pair`/`dominant_language`/`is_code_switched` routing scaffolding (`[polyglot]`); the per-pair CS adapter is trained out-of-band and gated. |

New config sections: `[voiceprint]`, `[cocktail]`, `[personalize]`, `[gaze]`, `[polyglot]` (all off by default). New extras: `voiceprint` (speechbrain); `gaze` deps are manual-install (l2cs pins an old torch). `doctor` reports each enabled extra's importability.

### `src/yazses/overlay/` (voice-activity overlay, `yazses-overlay`)

Standalone process (separate from the daemon, which is blocked by the hotkey
loop). A thin IPC client that polls `status` and renders "sonar" rings near the
cursor that pulse with `audio_level`. Pure-logic modules are unit-tested; the Qt
layer (PySide6, optional `overlay` extra) is thin and smoke-tested offscreen.

| File | Role |
|---|---|
| `envelope.py` | `EnvelopeFollower` — attack/release smoothing of mic level → 0..1 intensity (no Qt) |
| `animation.py` | `SonarModel` — emits/ages expanding rings given `(now, intensity)` (no Qt) |
| `position.py` | `place_near_cursor` / `place_fixed` — clamped on-screen placement (no Qt) |
| `poller.py` | `StatusPoller` — adaptive-cadence background poll of `status` (fast while recording) |
| `app.py` | `compute_frame` (pure per-tick decision) + `run` (the Qt shell / `yazses-overlay` entry) |
| `widget.py` | `SonarWidget` — frameless, translucent, click-through `QWidget`; `QPainter` ring render |

### `src/yazses/system/`

Host-side helpers and the CLI-facing config/diagnostics surface (no daemon needed).

| File | Role |
|---|---|
| `doctor.py` | `yazses doctor` diagnostics: version, daemon status (over IPC), permissions, session/injection tools, STT-model availability, config + hotkey summary, optional `--mic` ambient-vs-VAD sample, enabled extras |
| `miclevel.py` | `yazses mic-level` — record + `analyze()` mean/peak vs `vad_threshold`, recommend a threshold, `update_threshold_in_config` |
| `configedit.py` | `set_config_key(path, section, key, value)` — comment-preserving TOML writer used by `hotkey set` / `features enable/disable` |
| `features.py` | Capability registry (single source of truth for `yazses features`). `Feature`/`_Def`, recommendation tiers (core/on/rec/opt/exp), `feature_status(cfg)`, `find_feature`, `toggleable_slugs`; drives the advice column + the experimental-guard on enable |
| `vocabulary.py` | Personal dictionary at `~/.config/yazses/vocabulary.txt`. `load_vocab`/`add_vocab`/`remove_vocab`/`vocab_path` back `yazses vocab`; the daemon merges these words into Whisper's `initial_prompt` every dictation |
| `single_instance.py` | `SingleInstanceLock` — one-daemon guard (`daemon.lock`) preventing duplicate daemons (double-typing) |
| `updater.py` | `check_update`/`run_upgrade` backing `yazses update` (snap channel / PyPI by install method) |
| `pid.py` | PID-file management at `~/.local/share/yazses/daemon.pid` |
| `backends.py` | `probe_backend`/`BackendStatus` — honest availability reporting for lazily-imported, pluggable backends. Distinguishes "the optional dependency is missing" (installing the named extra fixes it) from "the adapter was never shipped in this build" (nothing can fix it), so a factory never sends users after an extra that cannot supply the backend. Used by `denoise/frontend.py`, `voiceprint/factory.py`, `recimport/factory.py` |

CLI commands added in the v1.1.x line (all write comment-preserving config, then prompt `yazses restart`): `yazses restart` (stop **all** daemons incl. detached, start one — `start` now restarts instead of duplicating), `yazses features [enable/disable]`, `yazses vocab [add/list/remove]`, `yazses hotkey [show/set/command]` (the `command` subcommand binds the dedicated command key; see `src/yazses/hotkeys/` above).

---

## IPC methods

Registered in `core/daemon.py::_start_ipc_server`. "Reached from" is the set of callers
in `src/` that actually send the method, not the set that could -- this table listed nine
of the twenty-one, and three of those nine were described as `CLI -> daemon` when no CLI
path had ever sent them. `tests/test_ipc_methods_are_documented.py` derives both columns
from the tree, so a method added to the daemon, or a caller added or removed, fails here.

| Method | Reached from | Description |
|---|---|---|
| `status` | CLI, tray, overlay, settings window, `doctor` | Current state, model, hotkey, backend, uptime; plus `audio_level` (live `mean(\|samples\|)` while recording, else 0) and `vad_threshold` for the overlay |
| `shutdown` | tray, Windows service controller | Graceful shutdown. `yazses stop` does **not** come through here; it goes to the lifecycle backend (systemd / launchd / SCM) |
| `inject` | CLI | Inject text directly (debug / remote agent) |
| `staged` | CLI | `yazses staged status\|commit\|discard\|undo` -- the verb is a parameter, so this is one method rather than four |
| `scratch` | CLI | Drop the most recent staged burst ("scratch that") |
| `recall` | CLI | Query the recall index |
| `punch_in` | CLI | Re-record over a selected span |
| `readback_speak` | CLI | Speak a phrase through the read-back TTS |
| `mark_last_wrong` | CLI | Flag the last dictation as a misrecognition (learning signal) |
| `enroll_start` | CLI | Start the accessibility enrollment wizard |
| `remote_start` | CLI | Start an SSH remote session |
| `remote_stop` | CLI | Disconnect the remote session |
| `meeting_start` | CLI, tray | Begin a meeting capture |
| `meeting_stop` | CLI, tray | Stop it and run the post-pass |
| `meeting_status` | CLI | Is a meeting recording, or still finalizing? |
| `pin_mic` | tray | Pin the input device by name |
| `recalibrate_mic` | tray | Re-run mic-level calibration |
| `ask_human` | MCP server | Ask the person out loud and return what they say (`[mcp] ask_human`) |
| `remote_status` | nothing | Is the tunnel connected? Redundant: `status` already carries `remote_connected`, and `yazses status` prints it |
| `streaming_enable` | nothing | Turn streaming transcription on at runtime, building the `StreamingEngine` if it is absent |
| `streaming_disable` | nothing | Turn it off again |

The last three are registered, implemented, and unreachable: no CLI command, tray entry or
MCP tool sends them, so they answer a hand-written JSON-RPC client and nothing else. They
are recorded as unreachable rather than deleted, because two of them are the only runtime
streaming toggle that exists. Before wiring one up, note that neither writes `config.toml`,
so the change lasts until the next restart and no surface reports it.

---

## Configuration reference

All fields have defaults. `config.toml` only needs the sections you want to override.

```toml
[stt]
model = "tiny.en"          # tiny.en | base.en | medium.en | large-v3
device = "cpu"
compute_type = "int8"

[hotkey]
key = "auto"               # auto | space | right_ctrl | right_option | …
hold_threshold_ms = 500
source = "default"         # default | evdev (Linux footpedal)
evdev_device = ""          # e.g. /dev/input/event5

[audio]
sample_rate = 16000
channels = 1
max_record_seconds = 90

[general]
log_level = "INFO"

[streaming]
enabled = true
partial_interval_ms = 300
partial_marker = ""

[filters.disfluency]
enabled = true
filler_words = ["um", "uh", "er", "like", …]
self_correction_triggers = ["scratch that", "delete that", …]
collapse_repetitions = false   # ADR-015 opt-in: b-b-because → because, the the the → the
collapse_prolongations = false # ADR-015 opt-in: sooo → so
llm_enabled = false
llm_endpoint = "http://localhost:11434"
llm_allow_remote_endpoint = false  # cleanup refuses a non-loopback endpoint without this

[accessibility]
vad_threshold = 0.01       # calibrate with `yazses enroll`
min_silence_ms = 500
pre_speech_padding_ms = 200
vad_source = "default"
dysfluency_friendly = false # ADR-015 preset: enables both collapse_* + widens onset padding

[commands]
enabled = true
profile = "auto"           # auto | default | vscode | vim

[injection]
backend = "auto"               # auto | xdotool | ydotool | wtype | clipboard
fallback_to_clipboard = true
continuation_window_ms = 30000 # 0 disables; bursts within this window get a
                               # separating leading space so words don't glue
                               # together at the boundary (postprocess/spacing.py)

[remote]
default_host = ""
ssh_port = 22
agent_port = 9875
key_file = ""
```

---

## Adding a new platform

1. Create `src/yazses/platform/<os>/` with implementations of all Protocol interfaces.
2. Register the new `sys.platform` string in `platform/factory.py`.
3. No changes needed in the daemon, CLI, or any other module.

---

## Key architectural decisions (ADRs)

### v0.3.0 ADRs

| ADR | Decision |
|---|---|
| ADR-001 | Text-only SSH forwarding — audio captured locally, transcript sent over tunnel |
| ADR-002 | LocalAgreement streaming policy — emit only stable prefix (longest common prefix of consecutive decodes) |
| ADR-003 | Regex grammar classifier — ~28 rules, no dedicated ASR model, ≤5 ms |
| ADR-004 | Correction-on-commit — `Shift+Left × N` to select partials, then inject final text |
| ADR-005 | Accessibility as config params first — enrollment wizard + calibrated VAD; LoRA fine-tune deferred |

Full v0.3.0 ADR files: `research/yazses-innovation/output/adrs/`

### v0.4.0 ADRs

| ADR | Decision |
|---|---|
| ADR-v04-001 | llama-cpp-python (in-process GGUF) for Tier 2 SLM inference — no external service, zero IPC overhead |
| ADR-v04-002 | pygls (JSON-RPC) + pynvim (msgpack-RPC) behind `EditorBridge` protocol for LSP context extraction |
| ADR-v04-003 | USB CDC serial (YESP protocol) for EMG devices — hardware-agnostic, 5 ASCII message types |

Full v0.4.0 ADR files: `docs/adr/`

### 2026-08 — packaging, egress and direction

Each of these is a numbered ADR in [`design/adr/`](adr/index.md), and each records what
would reverse it.

| ADR | Decision |
|---|---|
| ADR-017 | Intel macOS support is built on `macos-15-intel`, advisory — and its **end date is GitHub's**: the last x86_64 image, until Aug 2027. `macos-13` was retired 2025-12-04 |
| ADR-018 | Show a capability's **marginal** download cost before installing it; **no third-party plug-ins** — supersedes ADR-009's trust position, whose safety rested on a Rust build-time gate that was never built |
| ADR-019 | The **egress inventory**: every outbound path enumerated and enforced by a test. Five *fetch*, exactly two *send*. Escalation rules generalised from ADR-v2-126 to any feature; three categories may never escalate |
| ADR-020 | **MCP server yes** (stdio, two tools) · **FastAPI no** — it would trade an `AF_UNIX` structural guarantee for a configuration one on a process holding a live microphone · **A2A no** — YazSes has no goals |
| ADR-021 | Invest in **carrying error cost through the pipeline** (scored 24/25 against three alternatives). First step shipped: `checkdigit` |

### v0.4.0 Configuration reference additions

```toml
[commands]
# Tier 2 SLM routing (optional; needs yazses[slm] + GGUF model file)
slm_model_path = ""                  # e.g. ~/.cache/yazses/models/tinyllama.gguf
slm_confidence_threshold = 0.75

# LSP code context injection (optional; needs yazses[lsp])
lsp_enabled = false
lsp_editor = "auto"                  # auto | neovim | vscode

[emg]
# EMG silent speech backend (optional; needs yazses[emg] + device)
device_port = ""                     # e.g. /dev/ttyUSB0, COM3
baud_rate = 115200
mode = "command"                     # command | full_text
# command_map: device label → grammar phrase
# [emg.command_map]
# save = "save file"
# undo = "undo"
```

## v2.0.0 — Voice-First Interaction Layer (`v2.0.0-dev`)

v2 extends the daemon from dictation into a broader on-device interaction layer.
**Every feature is off by default and guarded**, so the v1 pipeline is unchanged when
all are off. Full rationale in `design/adr/adr-v2-000..013` and the integration map in
an internal design note.

### New packages (`src/yazses/`)

| Package | Feature | ADR |
|---|---|---|
| `postprocess/confidence.py` | Confidence Ink — low-confidence words from token probs | v2-001 |
| `commands/edit_ops.py` | Spoken Edit Mode — voice edits of the last dictation | v2-003 |
| `commands/context.py`, `system/context_read.py` | Context-Primed Dictation | v2-004 |
| `personalize/prompt_builder.py` (mine_ngrams/mine_personal) | Personal Adapter P1 | v2-009 |
| `recall/` (query, scratch) | Spoken Recall & Ambient Scratch | v2-005 |
| `polyglot/router.py` | True Code-Switch routing | v2-008 |
| `agent/plan.py` | Voice-to-Tool / Spoken MCP planner + guard | v2-006 |
| `pilot/plan.py` | AT-SPI Voice Pilot | v2-007 |
| `modality/router.py` | Modality Role Router | v2-011 |
| `continuum/whisper_mode.py` | Accessibility Continuum (Whisper Mode) | v2-012 |
| `gaze/route.py` | Gaze-Routed Dictation | v2-010 |
| `bridge/` (session, frame) | Glasses↔Desktop Bridge | v2-013 |

### Daemon integration points (`core/daemon.py`)

- `_effective_initial_prompt` — Context-Primed terms + Personal Adapter corpus-mined bias.
- decode path — Confidence Ink count (metadata only); Whisper-Mode effective VAD threshold.
- `_on_hold_end` command mode — Ambient Scratch capture, Spoken Edit (`_try_spoken_edit`).
- IPC — `recall`, `scratch` methods; `_handle_status` exposes `confidence_enabled` +
  `low_confidence_last`.
- startup — `PolyglotRouter` seam (dormant unless a CS adapter is set).

### Waves D–O (`v2.1`–`v2.11` developer preview)

The table above lists the founding Wave A–C packages (ADRs v2-000..013). Waves D–O add ~100 more
off-by-default capabilities following the **same pattern** — a pure, 100%-covered core module under
`src/yazses/<feature>/`, an `enabled = False` dataclass in `config.py`, a `system/features.py`
registry entry, and heavy backends (if any) lazy-imported behind an optional extra. As of
`v2.11.0-dev.1`: **135 capabilities, 1489 tests green**, ADRs `adr-v2-001..126`.

**Wave O (`v2.11`)** opens the first **file-ingestion entry point**: `yazses transcribe <file>`
(`src/yazses/recimport/`) — decode any audio format offline (PyAV via `faster_whisper.decode_audio`,
no new dep) → `transcribe_words()` → optional speaker diarization (`SherpaDiarizer`, sherpa-onnx int8
ONNX behind the `diarization` extra) → pure max-overlap word↔turn alignment (`align.py`) → speaker
naming (`naming.py`, reuses `voiceprint/`) → `render.py` sidecar (txt/md/srt/vtt/json). Unlike the rest
of v2 this is a **CLI-only path** (no daemon/IPC/hotkey change). ADR-v2-125; cloud escalation designed
but deferred (ADR-v2-126).

Rather than duplicate the full catalog here, the authoritative, always-current sources are:
`docs/v2-features.md` (user-facing catalog), `design/adr/adr-v2-*` (per-feature rationale), and
the per-wave SoA research notes (internal). Each is updated in
lockstep with the code every dev tag.

### Design invariants

On-device only, no telemetry, no transcript persistence beyond the opt-in encrypted
corpus (ADR-011/012). Heavy backends (SLM+MCP for `agent`, `pyatspi` for `pilot`, gaze
webcam, EMG serial) are lazy-imported behind opt-in extras/config; the pure planner/
router/parse layers carry no heavy deps and are fully unit-tested.
