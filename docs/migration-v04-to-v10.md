# Migrating from YazSes v0.4.x to v1.0

> ⚠️ **Historical / archived.** This guide describes migrating to the **Rust-core
> v1.0** that was explored on the `archive/rust-hci-v1` branch and **never
> shipped.** The product that actually ships is **Python** (now v1.2.x) on
> `main` — upgrading within the Python line (`pipx upgrade yazses` /
> `sudo snap refresh yazses`) needs none of the steps below. Keep this only as a
> reference for the paused Rust exploration; see the README's "Two versions of
> YazSes" section.

This guide covers every breaking and non-breaking change between the Python
v0.4.x release and the Rust-core v1.0 release. Read it top to bottom before
upgrading; the config and data sections in particular have details that affect
all users.

---

## What changed at a high level

| Aspect | v0.4.x | v1.0 |
|---|---|---|
| Runtime | CPython 3.11+ via `uv` | Native Rust binary |
| Install | `pip install yazses` / `uv tool install yazses` | `cargo install yazses` or pre-built binary |
| Daemon binary | `yazses-daemon` (Python) | `yazses-daemon` (Rust, same name) |
| CLI binary | `yazses` (Python) | `yazses` (Rust, same name, same subcommands) |
| STT engine | `faster-whisper` (CPU int8, Python) | Dual-stack: Moonshine v2 (streaming, ~9 ms P50) + Whisper.cpp (long-form) |
| LLM | Optional `llama-cpp-python` Tier 2 SLM | Full LLM-first pipeline: llama.cpp / Ollama / OpenAI-compatible |
| Memory | None — no transcript persistence | `PersonalMemory`: encrypted SQLite + vector KNN |
| Config format | TOML (`~/.config/yazses/config.toml`) | Same TOML file, same path, superset of v0.4 keys |
| IPC | JSON-RPC 2.0 over Unix socket | Same protocol, backwards-compatible, new methods added |
| Python pipeline | Production default | Preserved and importable — `uv run yazses` still works |

The Python v0.4.x pipeline is not removed. You can continue running it with
`uv run yazses` while evaluating v1.0 (see the Rollback section).

---

## Installing v1.0

### Pre-built binaries (recommended)

Binary archives for Linux (x86\_64, aarch64), macOS (arm64, x86\_64), and
Windows (x86\_64) are attached to the GitHub Release for each `v1.*` tag.
Download the archive for your platform, extract it, and put `yazses` and
`yazses-daemon` somewhere on your `PATH`.

On macOS, the Homebrew tap is the simplest path:

```sh
brew tap MSKazemi/tap
brew install yazses
```

On Linux, the `.deb` and `.rpm` packages are in the same GitHub Release and
install both binaries to `/usr/bin/`:

```sh
# Debian / Ubuntu
sudo dpkg -i yazses_1.0.0_amd64.deb

# Fedora / RHEL
sudo rpm -i yazses-1.0.0-1.x86_64.rpm
```

### Building from source

You need Rust 1.85+ and `cargo`. A default build compiles in MockSTT (no
Moonshine, no Whisper) and MockLLM (pass-through dictation, no LLM):

```sh
git clone https://github.com/mohsen-seyedkazemi/yazses
cd yazses
cargo build --release
# Binaries: target/release/yazses  target/release/yazses-daemon
```

For a production build with Whisper STT and Ollama LLM (the recommended
feature combination for most users):

```sh
cargo build --release --features whisper,ollama
```

See the Feature flags section for the full list.

### Keeping the Python v0.4 installation alongside v1.0

The two installations do not conflict. The Rust binaries are standalone
executables; the Python installation lives entirely inside the `uv` tool
environment. To keep both:

```sh
# Install v1.0 Rust binaries
cargo install yazses

# Keep the Python v0.4 pipeline available via uv
uv tool install "yazses==0.4.2"
uv run yazses status   # uses the Python daemon
yazses status          # uses the Rust daemon
```

---

## Config migration

The TOML config file stays at the same path:

| Platform | Path |
|---|---|
| Linux / macOS | `~/.config/yazses/config.toml` |
| Windows | `%APPDATA%\yazses\config.toml` |

**Your existing v0.4 config file loads in v1.0 without any changes.** All
v0.4 keys are read and honoured by the Rust daemon. New v1.0 keys are
optional; their defaults match v0.4 behaviour.

### Keys present in v0.4 and still present in v1.0

All of the following sections and keys are unchanged in meaning and default
value:

- `[stt]` — `model`, `device`, `compute_type`
  (Note: `model` in v1.0 selects the Whisper GGUF variant; see STT section
  below for how Moonshine is selected.)
- `[hotkey]` — `key`, `hold_threshold_ms`, `source`, `evdev_device`
- `[audio]` — `sample_rate`, `channels`, `max_record_seconds`
- `[general]` — `log_level`
- `[streaming]` — `enabled`, `partial_interval_ms`, `partial_marker`
- `[filters.disfluency]` — `enabled`, `filler_words`, `self_correction_triggers`,
  `llm_enabled`, `llm_endpoint`
- `[accessibility]` — `vad_threshold`, `min_silence_ms`, `pre_speech_padding_ms`,
  `vad_source`
- `[commands]` — `enabled`, `profile`, `slm_model_path`, `slm_confidence_threshold`,
  `lsp_enabled`, `lsp_editor`
- `[remote]` — `default_host`, `ssh_port`, `agent_port`, `key_file`
- `[emg]` — `device_port`, `baud_rate`, `ble_address`, `mode`, `command_map`

### Renamed keys

None. No v0.4 keys were renamed.

### Removed keys

| v0.4 key | Status in v1.0 |
|---|---|
| `[injection] backend` | Ignored — v1.0 probes the backend at runtime (same auto-probe logic, no config needed). |
| `[injection] fallback_to_clipboard` | Ignored — clipboard fallback is always enabled in v1.0. |

If your config.toml contains `[injection]`, the section is silently ignored.
No error is raised.

### New keys in v1.0

The following sections are new. They are all optional; omitting them gives
sensible defaults.

#### `[llm]` — LLM backend selection

```toml
[llm]
# "ollama" | "llama-cpp" | "mock"
# Default: "mock" (pass-through dictation, v0.4 behaviour)
backend = "ollama"

# For ollama backend: model tag served by the local Ollama daemon
# Default: "mistral-nemo:latest"
model = "mistral-nemo:latest"

# For ollama backend: base URL of the Ollama HTTP API
# Default: "http://localhost:11434"
endpoint = "http://localhost:11434"

# For llama-cpp backend: path to a GGUF file
# Default: "" (must be set explicitly)
model_path = "~/.cache/yazses/models/mistral-nemo.gguf"
```

When `backend = "mock"`, the daemon behaves exactly like v0.4: transcribed
text is injected directly without passing through an LLM, and voice commands
are dispatched via the Tier 1 regex classifier. This is the default, so
**existing users who do not want LLM processing do not need to add `[llm]`
at all.**

#### `[memory]` — Personal memory store

```toml
[memory]
# Enable the personal memory store. Default: false
enabled = false

# If set, the database is AES-256 encrypted (requires --features sqlcipher build).
# On first start with a passphrase, you will be prompted to confirm it.
# Leave empty for unencrypted storage (data still local; never leaves the device).
# Default: ""
passphrase = ""

# Time-to-live in seconds for automatically captured utterances.
# 0 = never expire. Default: 0
default_ttl_seconds = 0
```

Memory is disabled by default. Enabling it adds `commit_to_memory` and
`recall` tools to the LLM dispatch layer. No data is captured without
explicit user action or a tool call from the LLM.

### Before / after example

The following is a complete v0.4.1 config file followed by its minimal v1.0
equivalent (adding Ollama LLM and enabling memory):

**v0.4.x config (still works unchanged in v1.0):**

```toml
[stt]
model = "base.en"
device = "cpu"
compute_type = "int8"

[hotkey]
key = "right_alt"
hold_threshold_ms = 400

[commands]
enabled = true
profile = "auto"
lsp_enabled = true
lsp_editor = "neovim"

[filters.disfluency]
enabled = true

[accessibility]
vad_threshold = 0.008
min_silence_ms = 400
```

**v1.0 config adding LLM and memory (all v0.4 keys preserved):**

```toml
[stt]
model = "base.en"
device = "cpu"
compute_type = "int8"

[hotkey]
key = "right_alt"
hold_threshold_ms = 400

[commands]
enabled = true
profile = "auto"
lsp_enabled = true
lsp_editor = "neovim"

[filters.disfluency]
enabled = true

[accessibility]
vad_threshold = 0.008
min_silence_ms = 400

# ── new in v1.0 ──────────────────────────────────────────
[llm]
backend = "ollama"
model   = "mistral-nemo:latest"

[memory]
enabled = true
```

---

## STT changes

In v0.4, `faster-whisper` handled all transcription. In v1.0 a dual-stack
`STTRouter` dispatches based on utterance length:

| Utterance length | Backend (default build) | Latency |
|---|---|---|
| <= 4 s | Moonshine v2 (streaming) | ~9 ms P50 |
| > 4 s | Whisper.cpp (long-form) | 200–500 ms |

The `[stt] model` key in the v1.0 config controls which Whisper GGUF file is
loaded for long-form transcription. The Moonshine model is bundled and
selected automatically; it is not configurable via TOML.

To specify the Whisper model file path at runtime, use the environment
variable:

```sh
YAZSES_STT_MODEL=~/.cache/huggingface/hub/whisper.cpp/ggml-large-v3-turbo.bin yazses start
```

If `YAZSES_STT_MODEL` is unset, the daemon defaults to
`~/.cache/huggingface/hub/whisper.cpp/ggml-base.bin`. Download Whisper GGUF
files using the new model subcommand (see New commands below).

---

## New commands in v1.0

### `yazses memory` subcommands

The personal memory store is managed from the CLI:

```sh
# Save a note to the memory store
yazses memory commit "prefer Rust for performance-critical code"

# Save with tags and a 7-day expiry
yazses memory commit "standup is at 09:30" --tags "schedule,work" --ttl 604800

# Search the memory store (nearest-neighbour over embeddings)
yazses memory recall "what time is standup"

# Show memory store status
yazses memory status

# Delete the most recently saved entry
yazses memory forget

# Permanently delete the entire memory database (irreversible)
yazses memory destroy --i-mean-it
```

The memory store requires the daemon to be running for all subcommands except
`destroy`. Memory data is stored at:

| Platform | Path |
|---|---|
| Linux | `~/.local/share/yazses/memory.db` |
| macOS | `~/Library/Application Support/yazses/memory.db` |
| Windows | `%LOCALAPPDATA%\yazses\memory.db` |

### `yazses model` subcommands

Download and manage Whisper GGUF files:

```sh
# List available models and which are downloaded
yazses model list

# Download a model (writes to ~/.cache/huggingface/hub/whisper.cpp/)
yazses model pull whisper-base              # 145 MB, fast
yazses model pull whisper-small             # 488 MB, balanced
yazses model pull whisper-large-v3-turbo    # 874 MB, highest accuracy

# Remove a downloaded model
yazses model rm whisper-base
```

### `yazses bugreport`

Packages the daemon log, config directory, and version/platform info into a
tarball for sharing when reporting issues:

```sh
yazses bugreport
# Writes ~/yazses-bugreport-<unix-timestamp>.tar.gz
# Review it before sharing — it contains your config and recent logs.
```

No credentials are included; the config file holds no secrets. The memory
database is not included.

### `yazses latency-stats` (via `yazses status`)

There is no separate `latency-stats` subcommand. Latency percentiles are
reported as part of `yazses status`:

```
YazSes is running (PID 12345).
  state     Idle
  hotkey    right_alt
  model     moonshine-v2-small-streaming
  backend   xdotool
  uptime    143.2
  turns     27
  latency   p50=748ms  p95=1203ms
```

The underlying IPC method is `latency_stats` and returns `latency_p50_ms` and
`latency_p95_ms` fields.

---

## Changed commands in v1.0

### `yazses status`

The output is backwards-compatible. v1.0 adds three new fields:
- `turns` — total completed dictation turns since daemon start
- `latency p50` / `latency p95` — end-to-end pipeline latency over the last 100 turns

### `yazses doctor`

Fully reimplemented in Rust. Checks are expanded:
- Added: session type (Wayland vs X11), injection tool availability, model cache
  presence, screen reader coexistence (auto-creates `~/.talon/user/yazses_coexist.talon`
  if Talon is detected)
- Changed: exits with status code 1 if any check fails (v0.4 always exited 0)

### `yazses remote`

Behaviour is unchanged. The `--stop` flag works the same way.

### `yazses enroll`

Reimplemented in Rust using cpal for audio capture. The wizard flow (20
Harvard Sentences, percentile derivation, TOML write) is identical to v0.4.
The `[accessibility]` section of `config.toml` is written in the same format.

### `yazses inject`

Behaviour is unchanged: the daemon must be running; the text is injected into
the focused window via the active injection backend.

### `yazses start` / `yazses stop`

Behaviour is unchanged. In v0.4, `yazses start` delegated to `systemd` /
`launchd` / the Windows SCM. In v1.0 the daemon is spawned directly as a
background process tracked by a PID file. If you relied on `systemd` for
auto-restart on boot, install the systemd unit from
`packaging/systemd/yazses.service` (included in the `.deb` package).

### `yazses test`

The self-test is not yet ported to Rust (planned for v1.1). Running `yazses
test` prints a message directing you to the v0.4 implementation. To run the
v0.4 self-test:

```sh
uv run yazses test
```

---

## Feature flags

The Rust workspace uses Cargo feature flags to control which optional
backends are compiled in. Pre-built binaries from the GitHub Release include
`whisper` and `ollama` but not `moonshine`, `llama-cpp`, `silero`, or
`sqlcipher`.

| Feature | Crate | What it adds | Build-time deps |
|---|---|---|---|
| `whisper` | `yazses-stt` | Whisper.cpp long-form STT (whisper-rs 0.16) | cmake, C++ compiler |
| `moonshine` | `yazses-stt` | Moonshine v2 streaming STT (PyO3 0.28, Python 3.11+) | Python 3.11+, pip |
| `llama-cpp` | `yazses-llm` | llama.cpp GGUF LLM backend (llama-cpp-2) | cmake, C++ compiler |
| `ollama` | `yazses-llm` | Ollama HTTP LLM backend (reqwest) | Running Ollama daemon at runtime |
| `openai-compatible` | `yazses-llm` | OpenAI-compatible HTTP backend (opt-in only; reqwest) | Network at runtime |
| `silero` | `yazses-audio` | Silero VAD v4 ONNX (replaces RMS gate) | ONNX Runtime shared library |
| `sqlcipher` | `yazses-memory` | AES-256 encrypted memory database | Slow first build (compiles SQLCipher + vendored OpenSSL) |
| `onnx` | `yazses-memory` | BGE-small-en ONNX embeddings for memory recall | ONNX Runtime shared library |
| `neovim` | `yazses-editors` | Neovim bridge (nvim-rs 0.9) | Running Neovim with `$NVIM` set |
| `vscode` | `yazses-editors` | VS Code bridge (TCP port 57843) | YazSes VS Code extension |
| `emg` | `yazses-inputs` | EMG YESP serial backend | USB serial device |

Build examples:

```sh
# Minimal: MockSTT + MockLLM (pass-through dictation, zero external deps)
cargo build --release

# Recommended: Whisper + Ollama
cargo build --release --features whisper,ollama

# Full local stack: Whisper + llama.cpp (no network required at runtime)
cargo build --release --features whisper,llama-cpp

# Full featured (slow build): everything except openai-compatible
cargo build --release \
  --features whisper,moonshine,llama-cpp,ollama,silero,sqlcipher,onnx,neovim,vscode,emg

# Encrypted memory only (add to any combination above)
cargo build --release --features whisper,ollama,sqlcipher
```

The `openai-compatible` feature is intentionally excluded from all of the
above. It is an opt-in escape hatch that sends audio transcripts to a remote
server, which violates the zero-egress privacy guarantee. Enable it only if
you understand and accept that trade-off.

---

## Data migration

There is no data to migrate from v0.4 to v1.0. The Python pipeline never
persisted transcripts or any user data to disk (aside from `config.toml` and
the PID file, both of which carry forward unchanged).

The v1.0 `PersonalMemory` database is new. It starts empty. Populate it by:
- Enabling memory in config and using voice dictation normally — the LLM tool
  calls `commit_to_memory` when it decides something is worth remembering.
- Running `yazses memory commit "<text>"` from the CLI to seed it manually.

If you want to pre-populate memory from an external notes file:

```sh
while IFS= read -r line; do
    yazses memory commit "$line" --source "import"
done < ~/my-notes.txt
```

---

## Plugin and extension authors

In v0.4, extensions could import `yazses` Python modules directly or drop
scripts into the config directory. Neither mechanism is available in v1.0.

The supported extension surface in v1.0 is the **JSON-RPC IPC socket**. Any
process that can connect to a Unix socket (Linux/macOS) or named pipe
(Windows) can call the IPC methods documented in `docs/architecture.md`.
New IPC methods in v1.0:

| Method | Description |
|---|---|
| `memory_commit` | Store text + source into PersonalMemory |
| `memory_recall` | KNN search over PersonalMemory |
| `memory_forget` | Delete records from the last N minutes |
| `latency_stats` | Return P50/P95 latency over last 100 turns |

All v0.4 IPC methods (`status`, `shutdown`, `inject`, `remote_start`,
`remote_stop`, `remote_status`, `enroll_start`, `streaming_enable`,
`streaming_disable`) remain available unchanged.

A Python Rust FFI bridge (`pyo3` plugin loading) is planned for v1.1. Until
then, the recommended migration path for Python plugins is to rewrite the
extension as a standalone process that communicates via IPC.

Example: listening for inject events and logging them from Python:

```python
import socket, json

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect("/run/user/1000/yazses/daemon.sock")  # adjust UID

# Call the status method
req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "status", "params": {}})
sock.sendall((req + "\n").encode())
response = json.loads(sock.recv(4096))
print(response)
```

---

## Rollback

If you need to return to v0.4, the Python installation is preserved and
untouched by the Rust install. Stop the v1.0 daemon and start the Python one:

```sh
# Stop the Rust v1.0 daemon
yazses stop        # (Rust binary, if on PATH)

# Run the v0.4 Python daemon
uv run yazses-daemon

# Or pin to the last v0.4 release and use the Python CLI
pip install "yazses==0.4.2"
yazses-daemon &
yazses status
```

With `uv`:

```sh
uv tool install "yazses==0.4.2"
uv run yazses start
```

The v0.4 daemon and the v1.0 daemon both use the same Unix socket path
(`$XDG_RUNTIME_DIR/yazses/daemon.sock`). Only one can be active at a time.
Make sure the v1.0 daemon is stopped before starting the v0.4 one, and vice
versa.

---

## Quick-reference: what the default (no-feature) v1.0 build does

With no feature flags, the v1.0 daemon starts, listens for hold events, and
routes audio through a mock STT that returns the empty string. Text injection
does not happen. This is the CI default — it verifies that the daemon starts,
the state machine runs, and IPC works, without requiring any model files.

For real dictation, build with at least `--features whisper`:

```sh
cargo build --release --features whisper
yazses model pull whisper-base
yazses start
```

Or point `YAZSES_STT_MODEL` at an existing Whisper GGUF file and build with
`--features whisper`:

```sh
YAZSES_STT_MODEL=/path/to/ggml-base.bin yazses start
```
