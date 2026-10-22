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

  Opt-in [stt] idle_unload_s > 0 (ADR-029), model released while idle:
  RECORDING → LOADING (ready=true) → TRANSCRIBING   while the reload finishes
```

**The speech model is resident for the daemon's life by default.** With `[stt] idle_unload_s`
positive, `stt/resident.py::IdleUnloadEngine` wraps the engine and the model may be released
after that many idle seconds; every holder of the engine (`StreamingEngine`, the latency
governor's `EnginePool`, meeting capture) keeps the wrapper, so nothing has to be rebuilt and a
decode reloads it transparently. An unload never races a decode: decodes count themselves in, and
the release happens only at zero, from the `stt-idle-unload` tick, while the daemon state is
IDLE or PAUSED under `_lock`.

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
| `bidi.py` | Display-only bidi isolation (FA-07, #516). `wrap_user_text` puts FSI..PDI around user, transcript or OS-supplied text quoted inside an English UI sentence, **only** when it holds a right-to-left character (bidi class R/AL/AN), per paragraph, after dropping any embedding/override/isolate control from the display copy; `quote_user_text` replaces `!r` at those sites (`repr` escapes ZWNJ). Used by the tray tooltip and mic menu, the settings microphone list, save and filter messages, bookmark messages and the window-focus toast. Invariant: display copies only -- the raw value is what is stored, typed or copied, and `tests/test_bidi.py` fails if the injector, post-processing, clipboard, config-write or transcript-file modules import it. Never reverses a string; layout is the toolkit's (Qt honours isolates, measured in `tests/test_settingsui_bidi_render.py`). The CLI and transcript files get no isolates (pure, stdlib only) |
| `settingsui/theme.py` | Secondary-text colour computed from the desktop palette to stay above WCAG AA 4.5:1; Qt-free maths |
| `system/servicehealth.py` | Why the daemon is *not running*, asked of the service manager rather than the daemon: `classify_service` (unit state → findings: missing `ExecStart`/203, `start-limit-hit`, crash loop) and `classify_log` (journal/log signatures → cause, exact commands, distro-correct packages via `install_command`), falling through to `diagnosis.diagnose` for runtime causes. Pure apart from `collect_service_state`. Used by `yazses start` (`_explain_start_failure`) and a `yazses doctor` "Service health" row. Complements `system/diagnosis.py`, which only sees failures the *running* daemon catches |
| `system/depsize.py` | What enabling a feature will download — *marginal* against what is installed, from a committed table of resolved closures, plus the model files it fetches on first run (ADR-018) |
| `system/dormant.py` | Which **enabled** capabilities cannot run because their optional libraries are missing — derived from the feature registry, never a hand-kept list — with the one command that fixes each (`yazses features enable <slug>`, `--force` when experimental; the refusal reason in a snap or frozen bundle). Desktop-only rows (`tray`, `overlay`) are not findings without a graphical session. A camera feature (its registry row checks for `cv2`) whose libraries all import is also not ready when `opencv_health` finds `cv2` half-deleted; that finding is `installable=False` (no **Install now**), carries `problem`, and its remedy is the pinned repair from `updater.cv2_repair_here`. Read by the daemon at start (log + one rate-limited toast), `yazses doctor` and the `yazses features` ◐ marker; `preserved_requirements` feeds the uv-tool upgrade. Pure apart from injected probes; installs nothing |
| `system/opencv_health.py` | Is `cv2` half-deleted? `cv2_half_deleted` is the one decision the start-up dormant check and `yazses doctor`'s **OpenCV** row share: an OpenCV distribution is installed and `cv2` is a namespace package, or a package without its native module (left behind when removing one of two OpenCV builds deletes the files they share). Never imports `cv2`; a whole install costs one `find_spec` and one directory listing, and package metadata is read only when the directory already looks broken. Owns `CV2_DISTRIBUTIONS` / `installed_cv2_versions`, which `updater.py` re-uses. Stdlib only, never raises |
| `system/ondemand.py` | The one-action install for a dormant feature: the daemon toast's **Install now** / **Not now** buttons and their handler (one install at a time), the `yazses start`/`restart` terminal prompt, `yazses features install`, and `yazses features repair` (`repair_plan` splits the dormant set into installable and blocked before anything runs; `repair_summary`/`repair_exit_code` report per feature). Installs only on a click, a typed yes or the command; no button where `dormant.py` says nothing can install |
| `settingsui/maintenance.py`, `settingsui/maintenance_panel.py` | The Settings window's **About and updates** box. `maintenance.py` (pure) turns an update check plus `installer_update.one_click_offer` into one action (one-click hand-off, verified pip-family upgrade, open the releases page, or none) and routes each dormant feature to the install that can work here (`ondemand.install_one`, an ADR-028 pack via `packs.manage.install` in a frozen build, or a disabled button with `dormant.py`'s reason); it reads the transaction's undo outcome from `deps._undo`'s own lines. `maintenance_panel.py` owns the widgets and runs every check, hand-off, upgrade and install on a `QThread`, delivering results through a UI-thread `QObject` relay (a signal connected to a plain callable would run it on the worker thread). Implements no update or install logic: it calls `tray.updates.check_updates`/`hand_off_outside_tray`, `updater.run_upgrade_checked` and the functions above |
| `system/install_txn.py` | Pure decisions for a feature install as a transaction: the install channel (`uv-tool`, `pipx`, `editable`, `venv`, `system`, `snap`, `frozen`) and `METHOD_CHANNELS` from every `updater` install method; YazSes's base requirements as `--constraint` lines; markers evaluated for pipx (which ignores them); snapshot/diff of the installed set and the undo specs. `system/deps.py` runs the subprocesses |

### `src/yazses/platform/`

| File | Role |
|---|---|
| `base.py` | Protocol interfaces: `HotkeyBackend`, `InjectorBackend`, `LifecycleBackend`, `IpcServer`, `IpcClient`, `PermissionsBackend`, `TrayBackend`. Also `Platform.pointer_factory` — the optional `PointerSinkFactory` a bundle registers, `None` on an OS with no pointer backend yet (a factory, so nothing is constructed and no permission asked until a pointer consumer is enabled) |
| `factory.py` | `get_platform()` — detects `sys.platform`, returns `Platform` dataclass |
| `*/permissions.py` | Keyboard capture, microphone and (ADR-v2-145 / #414) **camera**. `check_camera()` returns a `CameraPermission`, never a bare boolean, and returns `NOT_DETERMINED` — never `GRANTED` — when it cannot answer |
| `emg/backend.py` | `EMGBackend` — `HotkeyBackend` over USB CDC serial YESP protocol (v0.4.0); requires `pyserial` optional dep |
| `linux/` | evdev hotkey, LinuxInjector (xdotool/ydotool/wtype/clipboard), systemd lifecycle, Unix socket IPC |
| `macos/` | CGEventTap hotkey, MacosInjector (CGEvent Unicode), launchd lifecycle, rumps tray, `pointer.py` (`MacosPointerSink` over CoreGraphics) |
| `windows/` | WH_KEYBOARD_LL hotkey, WindowsInjector (SendInput UTF-16), named-pipe IPC, pystray tray, `pointer.py` (`WindowsPointerSink` over SendInput mouse events), `update_handoff.py` (`WindowsUpdateLauncher`: the `UpdateLauncher` Protocol — a detached `-EncodedCommand` PowerShell job that waits for YazSes to exit — and installs nothing if it has not within 300 s — re-checks the installer's SHA-256, runs the silent, never-elevated in-place upgrade or the choco/winget/scoop command by absolute path, records the exit code and relaunches YazSes either way; also reads the Inno uninstall key for the install scope and asks each package manager which version its feed carries; ADR-027) |

### `src/yazses/cameraperm/` (EYE-PERM-001, #414 — camera permission + packaging contract)

One answer to "may this install open the camera, and if not, why?", shared by every
camera feature so that gaze, the face-gesture switch and the head pointer cannot each
invent their own. Pure and dependency-free; the OS probe is injected from the platform
seam and the heavy camera libraries are never imported here.

| File | Role |
|---|---|
| `contract.py` | `CameraPermission` (granted / denied / not-determined / unavailable / unsupported-platform), `CameraBlocker`, `CameraFacts`, `CameraGate`, `evaluate()`, `needs_permission_probe()` |
| `matrix.py` | The checked-in packaging matrix: which install format can run a camera feature, and what it must declare (`NSCameraUsageDescription` + the `com.apple.security.device.camera` entitlement, MSIX `webcam`, snap `camera`, flatpak `--device=all`). Cross-checked against the real manifests by `tests/test_camera_packaging_matrix.py` |
| `probe.py` | `resolve()` — gathers config, installed runtime and install format, and asks the OS **only** after the first two allow it |

**Invariants.** (1) With every camera feature off — the shipped default — the OS is never
asked, so no camera permission prompt can occur. (2) A format that cannot run a camera
feature declares no camera capability (R-21), and one that can must declare it before the
feature is claimed to work. (3) A probe that cannot determine the state reports
`NOT_DETERMINED`; nothing but `GRANTED` opens a camera. (4) A format the matrix marks
`can_add_runtime = False` never runs pip: `system.deps.install_blocked_reason` reads the
same row, so every enablement surface refuses a camera feature there before writing config.

### `src/yazses/handsfree/` (hands-free composition, ADR-v2-148)

What the camera-driven inputs must *share* rather than each reinvent: one suppression
state, and one privacy-safe way to report their health. Pure and dependency-free — no
camera, no clock, no config import, no thread of its own.

| File | Role |
|---|---|
| `safety.py` | The global stop + stale-signal watchdog (#417): `HandsFreeSafety`, one ACTIVE/PAUSED/FAULTED `SafetyStatus` with per-source `SourceHealth`, and `gate_from_config()` returning `None` until the user opts into `[handsfree_safety]` |
| `observability.py` | EYE-OBS-001 (#416). `HandsFreeFacts` → `HealthRow`s, rendered once and consumed three times: `doctor_rows()` for `yazses doctor`, `render_status_lines()` for `yazses status` and the controls window's health rows. The Head-Pointer's controller states live in one table (`HEAD_STATES`) all three read, and `tests/test_handsfree_surfaces_agree.py` drives one fabricated machine through each surface's *real* gathering path and fails if they disagree. `as_payload()`/`facts_from_payload()` are the IPC wire, a whitelist rather than `asdict`. Invariant: a sample older than the stale window (the watchdog's `stale_after_ms`, else `DEFAULT_STALE_AFTER_MS`, which a test holds equal to every consumer's own freshness limit) is never reported as tracking valid. A failed shared source's remedy is chosen by its `failure_kind` (`FAILURE_REMEDIES`, held total over the producer's kinds) |
| `preset.py` | The `[handsfree]` preset (#410). A pure expander (stdlib + config schema only) that rewrites the raw config before any section is built, so the result is ordinary per-feature config; a user-written key always wins and weakening the safety floor refuses the preset naming the key. `config.py` is its only caller and an AST test asserts nothing reads `cfg.handsfree` at run time. The preset is also the `features` registry row `handsfree` (experimental, off): `enable_refusal()` is the safety-floor gate that `yazses handsfree enable`, `yazses features enable handsfree` and the settings window all apply before writing, and `floor_unmet()` lets `inactive_reason` say when a requested preset was refused. `config.handsfree_preset()` is the registry's one status read of the section, and a test limits its callers to `system/features.py` |
| `recovery.py` | The recovery hierarchy as a pure rule: a destructive action never falls back to an inferred stand-in such as the focused window; every degraded result carries feedback |
| `stopword.py` | The voice stop word, pure and stdlib-only: `matches(utterance, phrase)` is an equality test on the WHOLE normalised transcript (case, edge punctuation and hyphen/space variants only; never a substring), `problem()` validates a configured phrase (2-6 words; checked at load by `configcheck`). It decides only; `Daemon._try_voice_stop` acts, by asking the `handsfree` IPC handler to *pause* (there is no resume phrase), before any other handler sees the utterance, and types nothing |
| `panel.py`, `panel_io.py` | The accessible controls view-model (banner, Pause/Resume/Recover/Recenter, health rows, face-switch mappings — every state a word, no action takes a pointer position) and its gather/perform layer, which reuses existing probes and never opens the camera. The Qt shell is `settingsui/handsfree_panel.py` |
| `probe.py` | The impure gatherer: config → requested features, the feature registry → whether a runtime path drives each one, an optional platform seam → the pointer backend's name and capabilities, and the stored gaze calibration's validity. Opens no camera and starts no pointer session |

**Invariants.** (1) With every camera feature off — the shipped default — `health_rows()`
is empty, no `doctor` row is printed, and the `handsfree` status field is `null`. (2) Only
names, states, ages, counts and capability flags reach the output: `HandsFreeFacts` has no
field able to hold a gaze coordinate, head angle, blendshape score, landmark, frame or
window title, which is how R-09 is kept by construction rather than by review. (3) A probe
that cannot determine a state reports `unknown` — never a default that reads as OK — and
does so as a `SKIP` so it cannot become a permanent warning on a working install
(ADR-021). (4) A cause is reported once: a blocked camera produces one failure, and the
perception row points at the Camera row rather than restating it. (5) A state the running
daemon holds is never reported as `unknown` by a surface that could have asked: `doctor` and the
window read the daemon's `status`, and a shared camera source that *failed* is a failure, not
"running". (6) Every continuous consumer honours the gate's one-shot `clear_pending` latch, so
no half-made activation crosses a stop or a re-arm: the Head-Pointer drops its dwell and treats
the next frame as a settling frame; the face switch's `SwitchMapper.frame()` reads the gate on
every frame that carries a face (a faceless frame counts nothing toward a hold) and returns the latch, and `FaceGestureBackend` then calls
`GestureSwitch.discard_pending()` on every detector before that frame is counted (an open hold
stays held, so a face still gesturing across a Resume must relax and gesture again); Gesture
Chords do the same (#408): `ChordEngine.frame()` reads the gate on every tick that carries a
signal (and on every tick while an engagement is open), taints an engagement in flight so only
the stop path can complete it, and returns the latch, and `SensorTokens` then calls
`GestureSwitch.discard_pending()` on every face-token detector and
`HeadGestureDetector.discard_pending()` on the head detector before the tick's frame is counted.
A local `yazses gesture pause`/`resume` is the same boundary. (7) Shutdown closes the gate before anything is stopped:
`Daemon.shutdown` closes it before stopping the activation sources, and `Daemon._shutdown`
closes it again (idempotent) before the pointer and camera backends.

### `src/yazses/inject/` (Linux sub-backends)

| File | Role |
|---|---|
| `auto.py` | Runtime probe: xdotool → ydotool → wtype → clipboard |
| `base.py` | `BaseInjector` protocol (inject, inject_backspaces, inject_key_sequence) |
| `xdotool.py` | X11 via `xdotool type` / `xdotool key` |
| `ydotool.py` | Wayland via `ydotool` |
| `wtype.py` | Wayland via `wtype` |
| `portal.py` | Wayland via the XDG RemoteDesktop portal (`PortalInjector`), the only path a strictly confined snap can type on. Holds the one `_PortalSession` — consent copy, restore token, idle release — and, per ADR-v2-146 rule 6, the pointer backend `PortalPointerSink` that extends that same session |
| `clipboard.py` | Universal fallback via clipboard + Ctrl+V |
| `streaming.py` | `StreamingInjector` — tracks partial char count, correction-on-commit via Shift+Left |
| `payload.py` | Pure. `hide_payload()` / `describe_argv()`: a failed or timed-out tool call re-raises with every argument after `--` (the text being typed) described by its length, so the exception that `LinuxInjector` and the daemon log at WARNING, and `last_error` keeps, never quotes the transcript |

### `src/yazses/pointer/` (pointer output boundary, ADR-v2-146)

The sibling of `inject/` for the *pointer* rather than the keyboard, and for the same
reason: Head-Pointer, the voice mouse grid and future gaze-assisted control all produce
pointer intent, and none of them may contain a platform command. Pure and
dependency-free — standard library only, no camera/gaze/head-pose concept, no
subprocess. Platform backends arrive one at a time (X11, the existing XDG RemoteDesktop
portal session, macOS, Windows), each living with its own OS code and reached through the
platform layer. The sink is deliberately dumb: dwell, confirmation and global pause all
live above it.

| File | Role |
|---|---|
| `base.py` | `PointerSink` protocol (`capabilities`, `move_relative`, `move_absolute`, `click`, `scroll`, `close`), `PointerButton`, `PointerCapabilities`, `PointerError`/`PointerUnsupportedError`/`PointerBackendError`, and the `check_finite`/`require_*` guards every backend validates with |
| `consent.py` | The permission vocabulary for a backend that has a consent step (`PointerConsent`: `not_required` / `pending_consent` / `granted` / `denied` / `unavailable` / `unknown`), the pure `classify_portal_session` that maps a RemoteDesktop session's record onto it, and the optional `ConsentReporting` protocol (`pointer_consent()`) a sink implements. A separate optional protocol, not a seventh `PointerSink` method, because `PointerSink` is `runtime_checkable`. The Head-Pointer asks it before it moves, so an unanswered dialog is a state, not a fault |
| `route.py` | `plan_pointer_route` — a pure prediction of which backend would drive the pointer (`portal` / `x11` / `sendinput` / `quartz` / none) from the session type, the typing backend and whether python-xlib is importable. What `yazses doctor`'s Pointer output row shows; held equal to `platform/linux/_pointer_factory` by `tests/test_pointer_route.py`. `uinput` and `xdotool` are not pointer backends in this build and are never named |
| `subpixel.py` | `SubPixelAccumulator` — pure, carries the remainder when a native API only takes whole steps (Windows' `LONG` pixel delta, CoreGraphics' `int32` line count), so a head-driven fraction of a pixel per frame is accumulated rather than rounded away. A taken step is spent, which is ADR-v2-146 rule 4 in arithmetic: a motion whose platform call fails is lost, never folded into the next one |

Unsupported is explicit, never a silent no-op: every implementation defines every method
(including `move_absolute`, which many backends cannot offer) and raises
`PointerUnsupportedError` for what `capabilities()` already said it cannot do.

**The backends live with their platform, not in this package.** `src/yazses/pointer/` is
held to an import-purity test (`tests/test_pointer_contract.py`): standard library only,
and no `subprocess` or `ctypes`. A backend needs exactly those things, so each one sits
beside the rest of its OS's code and is reached through the platform layer:

| Backend | Where | Mechanism |
|---|---|---|
| X11 | `platform/linux/pointer_x11.py`, opened by `platform/linux/build_pointer_sink()` | XTEST via python-xlib (already a Linux/BSD base dependency, already used by `hotkey_xgrab.py`) — no subprocess per motion, which `xdotool` would cost once per camera frame |
| Wayland | `inject/portal.py`, opened by `PortalInjector.pointer_sink()` | XDG RemoteDesktop `NotifyPointer*` on the **existing** session |
| macOS | `platform/macos/pointer.py` | CoreGraphics `CGEvent*` via PyObjC |
| Windows | `platform/windows/pointer.py` | `SendInput` mouse events via ctypes |

Wayland sits in `inject/` for a stronger reason than purity: ADR-v2-146 rule 6 requires
**one** RemoteDesktop session, so the pointer extends the session dictation already types
through. `POINTER` joins the single `SelectDevices` call only while a sink is open, and a
pointer consumer therefore raises no second consent dialog. Capability is read from the
`Start` response's granted-device mask rather than from having asked; absolute motion is
refused because `NotifyPointerMotionAbsolute` addresses a position inside a ScreenCast
stream, which this session deliberately does not have.

Sharing the session means sharing its one D-Bus connection between two threads: dictation
types on the daemon's thread while the Head-Pointer moves on the perception thread. That
connection is a `jeepney.io.blocking` one, whose `send` takes no lock, so every `Notify*`
goes out through `_PortalSession._notify`, which holds `_send_lock` for one message (never
across a keystroke's delay). The grant is gated on what the negotiation *asked* for, not on
which consumers are still registered when `Start` returns. The keyboard's wire is held
byte-identical with and without a pointer consumer by `tests/test_portal_shared_session_wire.py`.

The X11 backend injects its display connection (`X11PointerConnection`), so the shared
contract suite runs in CI with no display server, and it keeps the X11 dialect where it
can be asserted on: button 1/2/3 for left/middle/right, buttons 4-7 for one wheel notch
each (`+dy` down is button 5, so the sign never flips at the boundary), integer device
coordinates rounded half away from zero at the Xlib call with no remainder carried, and a
flush after every operation — including a failed one, so a queued press cannot ride out
on the next action a user asks for.

⚠ **The backends disagree about sub-unit motion, and whoever wires Head-Pointer (#404)
must reconcile it.** macOS and Windows carry the remainder through `SubPixelAccumulator`;
X11 rounds half away from zero and carries nothing, so a head movement producing under
half a device unit per frame moves an X11 pointer not at all while it moves a Windows one.
Both choices are defensible at the backend — accumulating inside a sink adds hidden state
to something ADR-v2-146 keeps deliberately dumb — but the consumer must accumulate, or the
same head motion behaves differently per platform.

No fake ships in `src/`. `tests/pointer_fake.py` holds `FakePointerSink`, which records
`PointerAction` values instead of moving anything — a click records a press **and** a
release, and `fail_with()` models a dead backend — and `tests/pointer_contract.py` is the
shared behaviour suite: each backend subclasses `PointerSinkContract`, supplies four
hooks (`make_sink`, `recorded`, `induce_failure`, `clear_failure`), and inherits the whole
contract rather than re-describing it. The recorded-action vocabulary itself
(`PointerAction`, in `yazses.pointer.actions`) is data and does ship, so the suite imports
nothing from `tests/`: an out-of-tree backend copies that one file next to its own tests.
`tests/test_pointer_contract_mutants.py` keeps the suite honest by running it against
deliberately wrong sinks (swallowed errors, reordered or dropped releases, success after
`close()`, replayed or queued commands, silent no-ops, a flipped scroll sign, a clamped
absolute position, a capped or split long move, a capability reported as an outage) and
requiring a named test to go red for each.

**Bounds are not the sink's.** A sink passes positions and deltas through unchanged apart
from its documented unit conversion: no clamp to zero or to the primary display, because a
display left of or above the main one has negative coordinates (ADR-v2-149), and no
per-call cap or split, because speed limits belong to the feature. An unsupported operation
raises `PointerUnsupportedError` in every sink state, failing or closed, so "cannot ever"
is never reported as "cannot right now". Spec: `design/specs/eye-pointer-output.md`, *Bounds*.

One thing the contract does **not** pin: whether a click
whose release fails after its press makes a best-effort release. The portal sink does; the
X11, macOS and Windows sinks leave the button down and say so — a maintainer decision.

**Platform backends (EYE-PTR-003, #402).** Each is two layers: a sink holding the whole
contract and knowing nothing about the OS, over an injected native-API object holding
nothing but the platform calls. That seam is why the shared contract suite runs on Linux CI
against the real sink classes, and why the native layer can be driven by a fake Quartz
module or a fake `SendInput` — the ctypes struct packing is genuinely exercised, since
ctypes works everywhere.

| Backend | Capabilities reported | Notes |
|---|---|---|
| `platform/macos/pointer.py` (`quartz`) | relative + **absolute** motion, three buttons, vertical scroll | No relative mouse event exists, so motion is read-cursor-then-post-absolute. Vertical scroll is negated (Apple's axis 1 is up-positive). **Horizontal scroll is reported absent on purpose**: Apple documents no sign for axis 2 and no Mac is available to settle it, and an inverted horizontal scroll makes a head-driven pointer fight its user. The platform factory is `build_macos_pointer_sink`, not the bare class: it refuses at open time with `PointerUnsupportedError` when the Quartz bridge is missing and `PointerBackendError` when `CGPreflightPostEventAccess` says no, so the Head-Pointer reports the Accessibility pane before the first head movement |
| `platform/windows/pointer.py` (`sendinput`) | relative motion, three buttons, vertical + horizontal scroll | **Absolute motion is reported absent on purpose**: `MOUSEEVENTF_ABSOLUTE` takes 0-65535 normalised coordinates over a multi-DPI virtual desktop, which ADR-v2-146 names as the case absolute coordinates get wrong. Vertical scroll is negated, horizontal is not — both signs are documented by Microsoft |

**Neither backend has ever run on its own OS.** No Mac and no Windows machine exists in
this project's CI or on the maintainer's desk, so every native call in both is written from
vendor documentation and verified only against a fake. `SendInput` in particular returns the
count of events it *inserted*, which UIPI can discard afterwards, so a full return count is
treated as "Windows accepted this" and never as "the pointer moved". Both module docstrings
say so, and the live-smoke evidence `design/specs/eye-pointer-output.md` asks for is still
outstanding for both.

### `src/yazses/stt/`

| File | Role |
|---|---|
| `faster_whisper.py` | `FasterWhisperEngine` — wrapper around `faster_whisper.WhisperModel`; accepts `initial_prompt` for LSP context (v0.4.0) |
| `vocabulary.py` | Built-in STT vocabulary. `merge_initial_prompt(*parts)` always primes the coined app name `YazSes` (`BUILTIN_PROMPT`), placed **after** the configured/personal vocab because faster-whisper keeps only the last `PROMPT_TOKEN_BUDGET` = 223 tokens of a prompt and silently drops the front — first meant first to be discarded, so a large vocabulary cost exactly the priming this module exists for. Single chokepoint used by `daemon._effective_initial_prompt`, which also merges the user's personal dictionary (`system/vocabulary.py`, `yazses vocab`) |
| `resident.py` | `IdleUnloadEngine` — `[stt] idle_unload_s` (ADR-029 §1, off by default: `0` builds no wrapper). Wraps the built engine; decodes count in/out under one condition (never held across a decode, so decodes still run side by side); one thread reloads through the daemon's `build_engine` while others wait; `detach_if_idle()` never blocks and hands back the engine only when the residency `IdleTracker` says it is due and nothing is in flight; `prefetch()` at a press starts the reload in the background while the user speaks. Delegates unknown attributes to a resident engine without loading one |
| `streaming.py` | `StreamingEngine` — background decode thread, LocalAgreement stable-prefix policy (ADR-002). `prefix_stable_for_ms()` accessor + `prewarm()` feed Ghost Ahead endpoint anticipation |
| `filters/disfluency.py` | Disfluency filter: filler removal → 2-gram dedup → **opt-in collapse pass (Rule B.5, ADR-015): sub-word repetition + prolongation collapse for Dysfluency-Friendly Mode, off by default, `_is_protected`-guarded** → self-correction rollback |
| `endpoint.py` | Ghost Ahead pivot (spec-ghost-ahead): `EndpointAnticipator` (with debounce) — predicts end-of-utterance from partial-transcript stability + trailing silence. **Wired** into `_partial_poll_loop` via `daemon._endpoint_prewarm_tick`: on a likely endpoint, pre-warm (eager, discardable decode); `[endpoint]` off by default. Speculative finalize (Phase 2) gated |
| `decoder_settings.py` | Pure: `file_decoder_settings(stt, section)` -> frozen `DecoderSettings` (model, language, task, device, compute_type, threads, beam, conditioning, `chinese_script`, `persian_normalisation`, warnings) for every **file** decode — `yazses transcribe`, `meeting recover`, the meeting post-pass without an engine, and the MCP `transcribe` tool. An empty `[recimport]`/`[meeting] model` inherits `[stt] model` (never another engine's checkpoint); the section's `language` is authoritative. `require_section()` raises `TypeError` on a whole `Config` where a section belongs — the substitution that made the MCP tool decode `small.en` English silently |
| `faster_whisper.py` | `FasterWhisperEngine.transcribe` (fast path) + `transcribe_words()` — opt-in word-timestamp path returning `(text, list[Word])`, used by Prosody Ink (`[prosody]`) and by Diarized Recording Import (`recimport/pipeline.py`, `yazses transcribe <file>`) |

### `src/yazses/recimport/` (Wave O, ADR-v2-125 — Diarized Recording Import)

Reached from `yazses transcribe <file>`, `yazses meeting recover`, the meeting post-pass
and the MCP `transcribe` tool; no IPC/hotkey involvement. Decoder settings come from
`stt/decoder_settings.py` (one rule for every entry point). Off by
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

### `src/yazses/packs/` (ADR-028 — feature add-on packs for frozen installs)

Windows installer build only (Phase 1). A heavy feature's libraries arrive as a `.yazpack`
built by the same release job as the installer and pinned to that exact base build; the
index of every pack's SHA-256 is built into the installed app. **Invariant: no stale pack is
ever loaded** — a pack mounts only into the base whose `base_build_id` it names, never into
an elevated process, and never with `YAZSES_NO_PACKS=1`. Nothing under `packs/` reads
`sys.platform`; the OS facts come from `PackRuntime` (`platform/base.py`,
`platform/windows/packs.py`). **Invariant: a pack never brings its own copy of a library
the base already loads** — a DLL the build dropped is named in `pack.json`'s
`bind_to_base`, and the pack runs only against the base's own file of that name, loaded
by absolute path from the frozen app's folder before the pack's first module, at a version
no lower than `bind_min_versions`; otherwise it is refused with a reason. The loader is
never asked to *search* for that name.

| File | Role |
|---|---|
| `manifest.py` | Pure. Parses the index, `pack.json`, `RECORD.json`; `ManifestError` with a user sentence |
| `abi.py` | Pure. `match()` → `ok` / `stale` (another build) / `refused` (same build, wrong field), one reason per field |
| `layout.py` | Pure. Paths below `data_dir/packs`, `b-<12hex>` build folders, the `MAX_PATH` budget |
| `archive.py` | Pure. Member checks before extraction (traversal, UNC, symlink, length, counts, ratio, case duplicates); `check_tree` against `RECORD.json` |
| `state.py` | Pure. Per-feature state for every surface (*waiting for add-on* never reads `on`); `state.json` |
| `policy.py` | Pure. Size ceiling, disk space, deadline, capability (`PACK_INSTALL_METHODS`), GC and rollback |
| `catalog.py` | Pure. `_FEATURE_DEPS` ↔ extras ↔ `packaging/packs/packs.toml` consistency |
| `context.py` | Reads only: the facts above for this process |
| `fetch.py` | **Egress (ADR-019 `FETCH_VIA`)**: the two release URLs, through ADR-027's `download_verified` |
| `install.py` | The transaction: lock → disk → download → extract → match → child-process probe → `os.replace` → `COMPLETE` |
| `mount.py` | `mount_at_startup()`, called by `packaging/windows/rthook_yazses_packs.py`; appends to `sys.path`, keeps DLL-directory handles, puts a first-use binder on `sys.meta_path` for a `bind_to_base` pack, never raises |
| `bind.py` | ADR-028 M1. Pure decisions (one base copy, or the only one inside a package folder named after the DLL, else refuse; version floor, nothing else of that name loaded) plus `bind_pack()` through `PackRuntime` and `FirstUseBinder`, which loads the base's DLL on the pack's first import, never at start-up. `OutOfProcessHost` is the typed, unbuilt ADR-028 §1 fallback |
| `probe.py` | `yazses packs probe`: binds `bind_to_base` first, imports `entry_modules`, re-checks the loaded modules; exit code names the Phase 0 risk that failed, and success names the DLL file and version that bound |
| `manage.py` | What the `yazses packs` commands and `features enable` do |
| `refetch.py` | ADR-028 Q3: the update question's add-ons line (`addons_for_update`), the consent file written once the update hand-off started, and on the new version's first start the one-time re-download through `manage.install` against the new build's own index; the old build is retired only after every new tree verified, and a start with nothing to download writes `started_ok` and retires it (`mark_first_start`) |

User-initiated only: the daemon, the update watcher and the runtime hook cannot reach
`fetch.py`, `install.py` or `manage.py` (`tests/test_egress_inventory.py`). `refetch.py` downloads only on a consent the user gave in the update
question, from a tray worker thread, at most once per consent; it has no downloader of
its own (`install`/`verify` are bound by `tray/app.py`, which the daemon cannot import).

**Build side** (`scripts/build-packs.py`, `packaging/packs/packs.toml`). The frozen base
is exactly the extras `packs.toml` decides `bundled` (`desktop`, `overlay`, and since
ADR-028 Q1 `parakeet` and `chinese`); `scripts/build-windows.ps1` syncs that set and
`build-packs.py validate` holds the two together. A bundled extra is never packed, and its
closure is subtracted from every pack. **Invariant: a pack never ships a DLL whose
basename the base also ships**, unless the bytes are identical (the pack's copy is
dropped) or the basename is on that pack's reviewed `bind_to_base` allow-list (every
pack copy is dropped, and `pack.json`'s `bind_to_base` tells the runtime to load the
base's copy first). The `diarization` pack binds `onnxruntime.dll` this way; any other
differing collision withholds the pack.

**Build-side invariant (ADR-028 Q7): no pack is published whose licences the build could
not classify.** `scripts/pack_licences.py` (pure, standard library only) classes every
distribution in a pack as permissive, LGPL, GPL or UNKNOWN; `scripts/build-packs.py`
withholds the pack on UNKNOWN, a missing licence file, a copyleft distribution with no
source URL, or GPL without a matching owner approval in
`packaging/packs/licence-approvals.toml`. A copyleft pack carries `LICENSES/SOURCE.md`.
The only stand-in for a missing licence file is a `[[licence_text]]` there: a committed
copy under `packaging/packs/licence-texts/`, pinned by SHA-256 and copied into
`LICENSES/<dist>/` only for the exact version, the declared licence, and a non-empty
`reviewed_by`; it never overrides a licence file the distribution ships. **An entry with
an empty `reviewed_by` honours nothing**, so a prepared entry cannot release a pack until
a person signs it. The runtime does not re-check licences.

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
| `output_profile.py` | Language output profiles (FA-01, #509; design draft PR #483): `profile_for(stt.language)` -> `PassThroughProfile` (every language by default, builds no normaliser) or `PersianProfile` (`fa`, delegates to the opt-in `persian_text` gate). Keyed by the **STT** language, never the UI locale. Consumed at the one seam `stt/factory.py::_with_persian_normaliser`; shaped like `han_script.build_han_normaliser` so Chinese script normalisation can migrate in later (not moved yet). |
| `punch_in.py` | Punch-In (spec-punch-in): `propose_corrections` + `apply_top_candidate(buffer, respoken)` — difflib alignment -> corrected full burst. **Wired** via `daemon._apply_punch_in`/`_handle_punch_in` + `yazses punch-in` CLI (record respeak -> align -> backspace + retype; `--dry-run`/`--choose N`). `[punch_in]` off by default |

### `src/yazses/language/` (language profiles, ADR-v2-140, #497)

A profile (`en`, `zh-CN`/`zh-Hans`, `zh-TW`/`zh-Hant`) is a **preset over canonical config**, never a stored
`active_profile`. `zh-HK` and Cantonese requests are refused, not aliased. Importing the package loads no model,
OpenCC, Qt or Mandarin grammar module.

| File | Role |
|---|---|
| `profiles.py` | The P1 profile table and alias resolution (pure) |
| `plan.py` | `resolve_profile(...) -> LanguagePlan` — the minimal `[stt]` mutations (engine, model, language, chinese_script), preserve-first or `recommended`, plus the command grammar before/after and warnings (pure) |
| `capability.py` | **Language/model compatibility table** (#515). Pure data: for every checkpoint YazSes knows by name (the faster-whisper names are exactly `stt/download.WHISPER_MODELS`; Parakeet v2/v3; Moonshine tiny/base), the language codes it transcribes plus a cited source URL and quoted evidence. A row without a source is marked `verified=False` and never refuses anything. `check(engine, model, language)` resolves the checkpoint that would actually load (an unknown engine is faster-whisper; Parakeet/Moonshine ignore a Whisper name) and answers `supported` / `unsupported` / `unknown`. That one answer is used by `stt/download.language_model_problem` (and so Settings and `yazses language set`), by `configcheck.language_pairing_problems`, by `stt/factory.refuse_unsupported_language` and by doctor's **Speech language** row. Tests hold the table equal to `WHISPER_MODELS`, faster-whisper's language codes and the engines' `DEFAULT_MODEL`s |
| `status.py` | `derive_status(cfg)` — profile match, coherence problems, and the Tier-1 command grammar resolved by `commands/grammars/registry.resolve_command_language`, the resolver the daemon calls. An explicit `[commands] language` that contradicts speech is a *warning*, not incoherence (pure) |
| `service.py` | The one side-effect ordering shared by CLI and Settings: stable snapshot -> resolve -> prerequisite preflight -> optional install/download -> `system/configedit.set_config_keys_atomic`. Its `validate` hook (`committed_candidate_validator`) re-reads the temporary candidate **through `load_config_checked`** and refuses the replace unless `[stt]` is exactly the plan, no other section changed, and the result derives as the requested profile |
| `settingsui/language_view.py` | The Settings row as a Qt-free view-model: profile choices from the registry, staged-change hint and the download/install question, all rendered from the same `PreparedLanguageChange` the CLI previews |

Invariant: a high-level switch is all-or-nothing. Speech language, model compatibility, Han-script output and
(with `[commands] language = "auto"`) the command grammar move in one atomic write, or the original file stays
byte-for-byte. Injection keys are not owned by a profile: the injector receives Unicode text either way (target
architecture §12). `yazses doctor`, `yazses language status` and Settings read the same `derive_status`.

Invariant (#515): a `[stt] language` that the resolved engine/model cannot transcribe, according to a *cited*
`capability.py` row, is never decoded. The config loader reports it (`ConfigProblem.refused`), Settings refuses
to write it, and `stt/factory.py` raises `LanguageUnsupportedError` before any model loads. That error subclasses
`ModelUnavailableError`, so the daemon holds in ERROR state with a toast. It is the one exception to the factory's
fall-back-and-stay-up rule, because every fallback ends on an English-only checkpoint. An `unknown` verdict (custom
checkpoint) is only reported.

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
| `src/yazses/gaze/` | **Glance-Type** (spec-glance-type) look-to-pane. `calibrate.py` (least-squares gaze→screen), `zones.py` (`grid_zone`/`window_at_point`/`resolve_window`), `l2cs.py` (L2CS-Net backend, manual-install), `factory.py`. `yazses gaze calibrate`, `status`, `rollback`, `measure`. Glance-Type leases the shared perception source (#396) when `[perception]` is on and both camera indexes match; otherwise it keeps its own capture. `clicks.py`/`association.py`/`capture.py` collect timestamped click+gaze pairs behind a `ClickObserver` protocol (#397), from a gaze ring bounded in count and age that is dropped when the ADR-v2-149 context fingerprint changes (`ThrottledFingerprint`, read on a click, at most once a second); `refine.py` applies an implicit refinement only when the held-out error beats the explicit baseline (the verdict is the pure `decide_promotion`, the split the pure `routes_to_holdout`), writes atomically and keeps the previous file for `gaze rollback` (#398); `refine_runtime.py` owns the opt-in `[gaze_refine]` lifecycle. `Platform.click_observer_factory` is set on Linux X11 (`platform/linux/click_observer_x11.py`, #607: XInput2 `XI_RawButtonPress` on the root window, no grab, `QueryPointer` for the position, `time.monotonic` stamps, buttons 1–3 only, awaiting a real-desktop smoke report) and `None` elsewhere; where it is `None` the platform may state why in `Platform.click_observer_unavailable_reason` (Wayland: no global click stream), and the refiner is dormant with that reason logged and shown by `yazses doctor`. `yazses gaze measure` writes the eyeeval envelope with derived metrics only (#399). `topology.py` — pure, stdlib-only display model for ADR-v2-149 (#415): one named canonical space (`desktop-logical-px`: the platform's own virtual-desktop coordinates, the X11 framebuffer today, never re-origined), `Display`/`DisplayTopology` with explicit HiDPI scale, a virtual-desktop `origin` that may be negative, the only canonical↔physical↔desktop-relative conversions (a point between monitors converts to `None`), the context fingerprint, `check_context` (VALID / UNVERIFIED / STALE; any determinable difference is stale) and `SessionTopologyGuard`, which suspends routing when the layout changes mid-session until a recalibration accepts it. `display.py` is its backend half (the `DisplayTopologyProvider` Protocol and the `xrandr` reader, X11 only). `store.py` persists the map with its context and refuses damage: a non-finite or coerced map is no map, a `version` that is not a positive integer is a damaged file (a newer-schema file routes but is never re-encoded by a promotion), and a context that fails the strict rebuild or no longer hashes to its stored fingerprint is a damaged binding, never VALID. `grounded.py` — the optional semantic-grounding seam (ADR-v2-151 P2): `GazeGrounder` turns one confident, gaze-routed sample into a `TargetSnapshot`, asks an **injected** `SemanticSource` what is under it and hands the resolver's tri-state answer back; `refine()` collapses that to `RefinedTarget`, whose `window_id` is always the route decision's and whose `entity_id` is filled only for a `GROUNDED` result that is not a window-geometry fallback (`source` carries the provenance, so `is_exact` is never true for the window's own rectangle); `GazeGrounder(region_px=...)` is the opt-in way to state the sensor's uncertainty as a region instead of asserting a precise point (no default is chosen — that size is a measurement). `GazeTargeter(grounder=...)` is the whole injection point and defaults to `None`, so with no grounder — every install today — the routing path is unchanged; a source that raises costs one warning per failure streak and the window-level target. |
| `src/yazses/perception/` | **Shared camera perception** (ADR-v2-145, spec-eye-shared-perception). `signals.py` — frozen value types (`GazeSignal`, `HeadPoseSignal`, `FaceSignal`, `PerceptionSample`) plus the `FacePerceptionSource` Protocol, so gaze, head pose and face switches consume one webcam's derived numbers instead of each opening their own. Pure and dependency-free: no cv2/mediapipe, no thread, no frame-shaped field; a missing channel is `None`, never a zero. `source.py` — `SharedPerceptionSource` is the one camera owner: consumers take a `PerceptionLease`, the first lease opens the camera and the model once, the last release closes both, `status()` reports state/backend/consumers/open-count for `doctor`, and a camera failure is contained rather than raised at the feature. A contained failure carries a `failure_kind` from `FAILURE_KINDS` (`camera`, `dependency`, `model`, `processing`) because the camera and the face model are opened in two separate attempts: a model download refused by a firewall is not reported as a camera that would not open (#416). Capture and processor are injected seams (`FrameCapture`, `FrameProcessor`), so the lifecycle and its tests need no webcam; the capture loop runs on a daemon thread by default and the driver is injectable too. `factory.py` — `build_perception_source` returns `None` when `[perception]` is off, which is the shipped state. Frames live only inside one observation (ADR-011). The MediaPipe adapter derives gaze, head pose and blendshapes from one FaceLandmarker result (#395); a missing transform or blendshape disables only that channel. Leased today by Glance-Type gaze and the Head-Pointer; the face switch still opens its own capture. |
| `src/yazses/headpointer/` | **Head-Pointer** (ADR-v2-052). `pointer.py` — the pure `pose_to_cursor` math and `DwellClicker`. `controller.py` — the pure state machine over them: neutral centre and `recenter`, pause, clutch, signal-loss freeze (never replays the last delta), no click on startup or recovery, dwell armed only after real movement and independently disableable. `runtime.py` — leases the shared perception source and drives a `PointerSink`; it accumulates sub-unit motion itself because the X11 sink carries no remainder. Honours `handsfree.safety` (global pause/kill, stale-signal watchdog). Opt-in `[headpointer]`; enabling it implies the shared source. Dwell is refused unless the overlay can show its progress ring. `yazses headpointer status\|recenter\|pause\|resume\|clutch\|dwell`. The Linux pointer factory is X11-only; native Wayland has none until the portal sink is selected. Motion is **per second**: gains are units per second per radian, integrated over the real gap between accepted samples (clamped by `max_dt_s`, so a stall is one bounded step), with per-axis and overall speed caps that cannot be disabled (`max_speed_x`/`_y`/`_overall`); `pointer.limit_velocity`/`elapsed_s` are the pure helpers. Dwell is **real time** too: `[headpointer] dwell_ms` is summed from the gaps between accepted samples that stayed inside the radius (`DwellClicker.update(x, y, ts)`), and a gap longer than `max_dt_s` restarts the dwell instead of counting; the old frame-counted `dwell_hold_frames` is read as frames at a nominal 30 fps. `freshness_ms` is bounded (`(0, 60000]`, otherwise repaired to the default and reported) via `effective_freshness_s`. All magnitudes are provisional. On native Wayland the pointer is the deferred portal sink (`inject/portal.py`) on the keyboard injector's own session. |
| `src/yazses/facegesture/` | **Face-gesture switch** (ADR-v2-135, ADR-v2-147). `detector.py` — `GestureSwitch` with separate hold/release thresholds, debounce, refractory window, an optional per-user neutral baseline and a confidence floor that is a distinct input; `gesture_reading()` turns a shared-perception `FaceSignal` into a reading (NaN, stale or missing channel = no reading, a release candidate). `calibration.py` — baseline capture and JSON persistence of derived numbers only (`yazses facegesture calibrate\|reset`). `switches.py` — `SwitchIntent`, `parse_bindings`, `SwitchMapper`: `backend.py` emits intents only, hold-to-talk is one binding among several, an unmapped gesture reaches no daemon action (a test forbids `facegesture/*.py` importing the daemon, injector, commands or pointer). `actions.py` — the pure decisions behind `select` / `confirm` / `cancel` (`select_refusal`, `SelectLimiter`, `perform_select`, `resolve_confirmation`, `SwitchOutcomeLog`): `select` is one left click through the Head-Pointer's own sink (`HeadPointerController.commit_click`), only when it is running, tracking, unpaused, unclutched and the hands-free gate is open, rate-limited to one per `SELECT_MIN_INTERVAL_S` (provisional); `confirm` / `cancel` answer the daemon's existing `ConfirmGate` hold and are a no-op when nothing is pending. Every outcome (done / refused with a reason / no-op) is kept and shown by `yazses facegesture status` and the hands-free state; the daemon's handlers (`_switch_select`, `_switch_confirm`, `_switch_cancel`) are glue only. `pause_pointer` pauses the global gate when `[handsfree_safety]` is on, otherwise a running Head-Pointer only (the `handsfree pause` rule, `_switch_pause_pointer`), otherwise it stays unwired and the daemon logs which setting would wire it; the two holds enter through the hotkey's own `_on_hold_start` / `_on_command_hold_start`, so the cmdsafety confirmation still applies to a command made with a face. The landmarker reports no per-frame confidence, so a floor above 0.5 blocks every frame on the backend's own camera path. `levels.py` — the pure *active-level* capture (`calibrate --active --talk`): derives hold/release between the user's rest and active levels, keeps hold above a recorded speech peak, and returns a specific reason instead of thresholds for every degenerate case (opt-in `use_active_levels`). The backend leases the shared camera when `[perception]` is on and the camera indexes match. |
| `src/yazses/gesture/` | **Gesture Chords from sensor tokens** (WIRE-GESTURE-001, #408). Pure: `chords.py` (the resolver), `headmotion.py` (nod / shake / tilt from `HeadPoseSignal` over a window; stale or non-finite pose yields no token), `engine.py` (`ChordEngine`, which freezes the Head-Pointer through its public clutch from the first disturbed frame until 300 ms after, names the camera frame that began the freeze so the clutch can take back the controller's own step for that frame (`since_s`/`max_rewind_s`, never past `REWIND_LIMIT_S`; face tokens only), and makes the `hold` token itself from the clock the caller passes in: the held tokens, unchanged for `hold_s`), `sensors.py` (face tokens through the face switch's own `GestureSwitch`). `runtime.py` leases the shared camera. A chord may name only `pause_pointer`, `recenter` or `command:<phrase>`; an unmapped token and any action under a global pause reach nothing; non-reversible actions are refused. |
| `src/yazses/eyeeval/switch_replay.py` | **False-activation replay** (#409). Pure replay of numeric face-switch traces (`switch_trace.py` is the versioned document + validator, structurally no place for frames) reporting phantom actions per non-deliberate hour with an exact Poisson upper bound, recall, latency and chatter, plus a threshold sweep. Refuses empty input; a zero denominator is a missing marker, never 0.0. The activation policy is injected (`Detector`: a name plus a factory, default the shipped `GestureSwitch` built as the backend builds it), so a candidate detector is scored over the same traces by the same rules. |
| `src/yazses/grounding/` | **Grounded target resolution** (ADR-v2-151, spec-eye-grounded-targets). `contracts.py` — frozen vocabulary (`TargetSnapshot`, `SemanticCandidate`, `IntentHint`, tri-state `GroundingResult`, the `SemanticSource` Protocol) with no thresholds in it; `resolver.py` — the deterministic `TargetResolver` that enforces the spatial envelope, lets an intent hint *filter* what survived it, ranks lexicographically (focus > source > containment > geometry) and abstains when nothing separates the winner from a runner-up. Pure: no pyatspi/AX/UIA, no screen capture, no clock, no randomness; every number is a field on `ResolutionPolicy` and none of the defaults is measured. Turns a coarse pointing region into one exact control so webcam gaze does not have to pretend to be pixel-precise. `trace.py` — a versioned, privacy-safe trace document (target + candidates + intent hint + ground-truth entity id, and structurally nowhere to put a screenshot or a window title) with a pure validator; `replay.py` — the P4 evaluation harness that replays those cases through the same resolver under a `window_only` and a `semantic_grounding` strategy and reports grounded-correct/wrong, ambiguity, abstention, the target-source vs semantic-source split and the candidate-count distribution around an intent hint. An empty trace is refused rather than reported on, a zero denominator is a missing marker rather than `0.0`, and no product threshold may be read off a synthetic fixture. Run it with `scripts/replay_grounding_trace.py`; the committed report is `tests/fixtures/grounding_replay_report.json`. Wired from `gaze/grounded.py` (#443) as an optional, absent-by-default seam — nothing in the daemon constructs a grounder, and no platform adapter exists yet, so the spec's coverage study (P3) comes first. The package's `__init__` deliberately does not re-export the harness. |
| `src/yazses/polyglot/` | **Polyglot Switch** (spec-polyglot-switch) — **not wired**. `lid.py` — `parse_pair`/`dominant_language`/`is_code_switched` routing scaffolding (`[polyglot]`); the per-pair CS adapter is trained out-of-band and gated. Nothing imports the package at runtime: no decode path produces the per-span language IDs `PolyglotRouter.should_route` needs. |

New config sections: `[voiceprint]`, `[cocktail]`, `[personalize]`, `[gaze]`, `[perception]`, `[polyglot]` (all off by default). New extras: `voiceprint` (speechbrain); `gaze` deps are manual-install (l2cs pins an old torch). `doctor` reports each enabled extra's importability.

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
| `updater.py` | `check_update`/`run_upgrade` backing `yazses update` (snap channel / PyPI by install method). `resolve_upgrade_command` is the one upgrade command `yazses update`, the Settings window, the Linux tray and `run_upgrade_checked` all show and run: first `preserve_enabled_features` (which matches only the plain `uv tool upgrade yazses`), then `keep_cv2_whole` (adds `--reinstall-package opencv-contrib-python` when two `cv2` owners are installed). `run_upgrade_checked` verifies the version moved and, where OpenCV was in use, that `cv2` still loads; otherwise it returns the repair command. `cv2_repair_here` builds the same pinned repair for the running environment (the `uv pip` form in a pip-less venv) for `dormant.py` and doctor. The Windows/macOS tray balloon (`tray.updates.describe_update`) shows the resolved command too, or a pointer to `yazses update` when it would overrun the 255-character balloon |
| `installer_update.py` | One-click Windows update ([ADR-027](adr/adr-027-one-click-windows-update.md)). Pure: pick the installer asset for the machine's arch from the release JSON, allowlist `github.com/MSKazemi/yazses/releases/download/` URLs and redirects, parse `SHA256SUMS.txt`, gate on strictly newer. I/O: capped, deadline-bound download verified by SHA-256 before anything runs. Then builds an `UpdateHandoff` for the platform's `UpdateLauncher` and reports the result on the next start by the version actually running. ADR-019 FETCH |
| `residency.py` | Runtime residency policy ([ADR-029](adr/adr-029-runtime-residency.md), Accepted): which models stay in memory, for how long, and in which process — as pure arithmetic over **residency units** (`UNIT_OF_SLUG` folds `gaze`/`facegesture`/`headpointer`/`gesture` into one MediaPipe unit, the three voiceprint slugs into one torch unit, and so on). `IdleTracker.due_for_unload(now)` is *unload after idle* with a per-unit keep-alive (`DEFAULT_POLICY`: the dictation engine `None` = resident while enabled; the heavy units 120–600 s), firing at the boundary and never for a `None` row; `ResidencyBudget.admit(unit, now)` is the LRU cap on resident heavy models with pinned units never evicted; `placement(unit)` is the out-of-process table (`WORKER_UNITS`: gaze, llm, voiceprint, diarize) and raises for an unknown unit; `check_rss`/`unmeasured` are the nightly RSS budget's verdict, refusing an empty run. Stdlib only; the clock is injected or `now` is passed; NaN, infinite, negative or backwards time raises. `with_stt_idle_unload(s)` turns `[stt] idle_unload_s` into the `stt` row's keep-alive and `unload_tick_s` sets the daemon's tick. **Wired for the dictation engine only** (`stt/resident.py`); the heavy units' unload hooks, the LRU cap and the workers are still the ADR's *Integration hand-offs* |
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
| `headpointer` | CLI | Head-Pointer controls, chosen by an `action` param: `status`, `recenter`, `pause`, `resume`, `clutch`, `dwell` (`yazses headpointer ...`) |
| `handsfree` | settings window, CLI | Global hands-free stop, chosen by an `action` param: `pause` (every source at once; Head-Pointer only when `[handsfree_safety]` is off) or `resume` (explicit re-arm; refuses while a source is stale or faulted). Takes no pointer position (`yazses handsfree ...`) |
| `facegesture` | CLI | Face-switch action outcomes, `action` param: `status` only. Lists each bound `select` / `confirm` / `cancel` with its last outcome (done, refused with a reason, no-op) and counts. Read-only; names, words and ages, never a score (`yazses facegesture status`) |
| `gesture` | CLI | Gesture Chords controls, chosen by an `action` param: `status`, `pause`, `resume` (`yazses gesture ...`) |
| `mousegrid` | overlay | Voice Mouse Grid (`[mousegrid]`), chosen by an `action` param: `status` (active flag, grid size, the current cell rectangle, depth — no transcript), `open`, `say` (runs `text` through the spoken grid grammar), `cancel`, and `screen` (the overlay reports its screen rectangle for sessions where the daemon cannot read the display layout). Replies `ok: false` while the feature is off |
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
| `polyglot/router.py` | True Code-Switch routing decision (not wired — nothing calls `should_route`) | v2-008 |
| `agent/plan.py` | Voice-to-Tool / Spoken MCP planner + guard | v2-006 |
| `pilot/plan.py` | AT-SPI Voice Pilot | v2-007 |
| `modality/router.py` | Modality Role Router | v2-011 |
| `continuum/whisper_mode.py` | Accessibility Continuum (Whisper Mode) | v2-012 |
| `gaze/route.py` | Gaze-Routed Dictation | v2-010 |
| `gaze/target_capabilities.py`, `gaze/target_semantics.py` | Gaze-target semantics per session (#418): the pure platform matrix (screen position, other windows' geometry, focus; pointer injection kept separate and never read), the derivation "a target needs all three as plain `yes`", and the plan's `dictation_route` / `destructive_deixis`. Where no target can exist (every Wayland session), `Daemon._deixis_without_gaze_target` refuses gaze commands with feedback. Spec: `design/specs/eye-wayland-gaze-target.md` | v2-010, v2-146, v2-148 |
| `bridge/` (session, frame) | Glasses↔Desktop Bridge | v2-013 |

### Daemon integration points (`core/daemon.py`)

- `_effective_initial_prompt` — Context-Primed terms + Personal Adapter corpus-mined bias.
- decode path — Confidence Ink count (metadata only); Whisper-Mode effective VAD threshold.
- `_on_hold_end` command mode — Ambient Scratch capture, Spoken Edit (`_try_spoken_edit`).
- IPC — `recall`, `scratch` methods; `_handle_status` exposes `confidence_enabled` +
  `low_confidence_last`.
- startup — `[polyglot] enabled` only logs that code-switch routing is not wired; the daemon
  builds no router, because no decode path produces the span languages one would need.

### Waves D–O (`v2.1`–`v2.11` developer preview)

The table above lists the founding Wave A–C packages (ADRs v2-000..013). Waves D–O add ~100 more
off-by-default capabilities following the **same pattern** — a pure, 100%-covered core module under
`src/yazses/<feature>/`, an `enabled = False` dataclass in `config.py`, a `system/features.py`
registry entry, and heavy backends (if any) lazy-imported behind an optional extra. A feature
that is off also costs a default start no import of its own package: `tests/test_base_weight_budget.py`
holds `import yazses.main` and `yazses --help` to that, and `tests/test_dormant_features_stay_unimported.py`
holds a default daemon's `__init__` and `_build_pipeline` to it, each with a shrink-only list of the
remaining exceptions (`docs/contribute/startup-budget.md`). As of
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
