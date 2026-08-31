---
id: "prod-readiness-yazses-v030"
title: "YazSes v0.3.0 — Production Readiness Checklist"
type: production_readiness
scenario: yazses-innovation
created_at: 2026-05-14
updated_at: 2026-05-14
confidence: high
---

# YazSes v0.3.0 — Production Readiness Checklist

## 1. Observability

### 1.1 Daemon Logging

- [ ] All new state transitions (`REMOTE_SETUP`, `REMOTE_ACTIVE`, `ENROLLING`) are logged at `INFO` level with ISO-8601 timestamp, current state name, and transition trigger.
- [ ] `stt/streaming.py` logs each decode tick at `DEBUG` level: tick index, rolling buffer duration (ms), stable prefix length (chars), and chars emitted in this tick.
- [ ] `inject/streaming.py` logs `_chars_injected` counter value at `DEBUG` level on each `inject_partial()`, `commit()`, and `cancel()` call.
- [ ] `commands/grammar.py` logs classifier result at `DEBUG` level: matched pattern name, intent type, action, extracted args, and elapsed time (ms).
- [ ] `stt/filters/disfluency.py` logs filter result at `DEBUG` level: input length, output length, chars_removed, rules fired (bitmask of A/B/C).
- [ ] `remote/forwarder.py` logs tunnel health at `INFO` level: connection established (host, port), connection lost (reason), reconnect attempt (attempt N).
- [ ] `accessibility/enroll.py` logs calibration progress at `INFO` level: utterance N/20, measured noise floor, measured speech RMS.
- [ ] Log level is configurable via `YAZSES_LOG_LEVEL` environment variable (default: `WARNING` in production, `INFO` in daemon `--verbose` mode).

### 1.2 IPC Debug Events

- [ ] New IPC notification `debug_event` is emitted by the daemon when `config.general.debug_events = true`. Carries: timestamp, event_type (string), payload (dict). Consumed by `yazses status --watch`.
- [ ] `command_dispatched` notification (FR-003.5) is always emitted on the IPC socket when a non-DICTATE intent fires. Tray and external tooling can subscribe.
- [ ] `remote_status` IPC method returns tunnel health as a structured dict: `{"connected": bool, "host": str, "latency_ms": float | null, "bytes_forwarded": int}`.

### 1.3 Daemon Status Reporting

- [ ] `yazses status` output is extended for v0.3.0 to include:
  - Streaming mode: `enabled|disabled`, last TTFP (ms).
  - Remote session: `active|inactive`, host, tunnel latency (ms).
  - Disfluency filter: `enabled|disabled`, chars removed in last session.
  - Command grammar: `enabled|disabled`, last intent classified.
  - Accessibility profile: `default|calibrated`, enrolled VAD threshold.
- [ ] All status fields have stable JSON output when `yazses status --json` is used. Breaking changes to the JSON schema are versioned.

---

## 2. Reliability

### 2.1 SSH Tunnel Disconnect Handling

- [ ] `remote/forwarder.py` detects SSH subprocess exit (non-zero exit code or `SIGCHLD`) and sets daemon state to `REMOTE_DISCONNECTED`.
- [ ] On disconnect, any in-progress recording is finalised locally (transcribed and discarded — text is not forwarded when no tunnel is active).
- [ ] The daemon emits a `remote_disconnected` IPC notification with reason string.
- [ ] `yazses remote --reconnect` flag enables automatic reconnect with exponential backoff (1 s, 2 s, 4 s, 8 s, cap 60 s). Maximum retry count configurable via `remote.max_reconnects` (default: 10).
- [ ] If SSH subprocess is killed by signal (e.g., SIGHUP on terminal close), the daemon cleans up the `RemoteForwarder` and returns to `IDLE` state cleanly.

### 2.2 Streaming Timeout

- [ ] `stt/streaming.py` enforces a decode timeout: if a single `WhisperModel.transcribe()` call exceeds `config.streaming.partial_interval_ms × 3` ms (default 900 ms), it is abandoned and the streaming session continues with the previous stable prefix. An `INFO` log entry is emitted.
- [ ] If the rolling audio buffer exceeds `config.audio.max_record_seconds` (default 90 s), streaming is automatically committed as if the hotkey were released. The user is notified via a `session_auto_committed` IPC notification.
- [ ] On `cancel()`, `StreamingInjector` emits backspace events synchronously in the same thread as the hotkey event handler. If the injector backend raises an exception (e.g., `xdotool` not found), the exception is caught, logged at `ERROR`, and the `_chars_injected` counter is reset to 0 (partial text may persist in the window, but the daemon continues functioning).

### 2.3 Command Misrecognition Recovery

- [ ] `commands/dispatch.py` wraps all shell action executions (`subprocess.run`) in a `try/except`. If a shell command fails (non-zero exit code), the failure is logged at `WARNING` and a `command_failed` IPC notification is emitted. The daemon does not crash.
- [ ] The `IntentType.DICTATE` fallthrough path has zero side effects: if no pattern matches in `grammar.classify()`, the original text is returned unmodified and no IPC notification is emitted.
- [ ] User can disable the command grammar at runtime via `yazses config set commands.enabled false` without daemon restart (IPC method `streaming_enable` is extended to cover command grammar toggling).

### 2.4 Accessibility Device Disconnect

- [ ] On Linux, if the `evdev_device` path becomes unavailable (device unplugged), the `platform/linux/hotkey.py` backend catches the `FileNotFoundError` from `evdev.InputDevice`, logs at `ERROR`, emits a `hotkey_device_lost` IPC notification, and falls back to keyboard hotkey detection automatically.
- [ ] `yazses doctor --accessibility` checks that the configured `evdev_device` path exists and is readable before the daemon starts, and prints a specific error message if not.
- [ ] The enrollment wizard (`yazses enroll`) validates that the microphone device is accessible before starting the 20-utterance calibration sequence. If the device becomes unavailable mid-enrollment, the wizard saves partial results and prints instructions to resume.

---

## 3. Security

### 3.1 SSH Key Management

- [ ] `remote/forwarder.py` never generates or stores SSH keys. It delegates authentication entirely to the user's existing SSH agent (`SSH_AUTH_SOCK`) or key file specified via `remote.key_file` in config.
- [ ] The `remote.key_file` config value is never logged (masked to `"[redacted]"` in all log output).
- [ ] SSH subprocess is spawned with the minimum required arguments: no `StrictHostKeyChecking=no` by default (user controls their `~/.ssh/known_hosts`). A `remote.no_host_check = true` option exists for CI/testing environments but emits a `WARNING` log when used.
- [ ] `yazses remote install user@host` (the bootstrap command to install `yazses-agent` on the remote) uses the standard `ssh` client and `pip install` over the tunnel. It does not handle credentials itself.

### 3.2 No Audio in Transit

- [ ] ADR-001 is enforced architecturally: `remote/forwarder.py` and `remote/local_proxy.py` have no imports of `sounddevice`, `numpy`, or `audio.*`. Code review and CI lint check enforce this.
- [ ] The only data that crosses the SSH tunnel is the JSON-RPC payload: UTF-8 text strings and control signals (`inject`, `remote_start`, `remote_stop`). No binary audio buffers are serialised or transmitted at any point. [EVIDENCE src-001]
- [ ] The SSH tunnel itself is encrypted by OpenSSH (AES-128-CTR or better, depending on the server's cipher list). YazSes does not add a second encryption layer.

### 3.3 No Cloud Endpoints

- [ ] The daemon has no outbound HTTP/HTTPS calls in any code path. A CI lint step (`grep -r "requests\|httpx\|urllib.request" src/yazses/`) verifies this.
- [ ] The optional LLM disfluency enhancement (`filters.disfluency.llm_enabled = true`) connects only to a user-configured local endpoint (`llm_endpoint`, default: `http://localhost:11434`). The endpoint is never a cloud URL by default.
- [ ] `yazses doctor` checks for unexpected network socket activity (Linux: `ss -tp | grep yazses-daemon`) and warns if any non-IPC sockets are open.

### 3.4 Config File Permissions

- [ ] On Linux and macOS, `config.py` checks that `config.toml` is not world-readable (`chmod 600`) and logs a `WARNING` if it is. The warning includes a remediation command.
- [ ] On first run, `config.toml` is created with `mode=0o600`.

---

## 4. Scalability

### 4.1 Daemon Architecture (Still Single-Process)

- [ ] The daemon remains a single Python process with no worker processes added by v0.3.0. The streaming decode runs in a `threading.Thread` (not a subprocess), sharing the existing `FasterWhisperEngine._model` instance without creating a second model. [EVIDENCE src-001]
- [ ] Verified: memory footprint of the daemon with all v0.3.0 features enabled (`tiny.en`, streaming, grammar, disfluency filter, remote) does not exceed baseline by more than 50 MB RSS. Measured using `tracemalloc` in the integration test suite.

### 4.2 Streaming Memory Bounds

- [ ] `stt/streaming.py` maintains a single rolling audio buffer capped at `config.audio.max_record_seconds × sample_rate × 4 bytes/sample`. At the default 90 s cap with 16 kHz: `90 × 16000 × 4 = 5.76 MB`. This is the upper bound on streaming memory growth per session. [EVIDENCE src-002]
- [ ] `inject/streaming.py`'s `_chars_injected` counter is a plain `int`. It does not grow with session length; it is reset on each `commit()` or `cancel()`.
- [ ] `commands/grammar.py`'s compiled `re.Pattern` list is instantiated once at daemon startup and held as a module-level singleton. No per-request allocation beyond the match operation.

### 4.3 Concurrent Remote Sessions

- [ ] v0.3.0 supports exactly one remote session at a time (single `RemoteForwarder` instance). Attempting to start a second remote session while one is active returns a JSON-RPC error `{"code": -32003, "message": "Remote session already active"}`.
- [ ] The single-session constraint is documented in the CLI help text: `yazses remote --host` (note: only one active remote session supported per daemon instance).

---

## 5. Operational Runbook

### 5.1 Startup / Stop / Restart

```bash
# Start daemon (systemd, Linux)
systemctl --user start yazses

# Start daemon (launchd, macOS)
launchctl start com.yazses.daemon

# Start daemon (direct, any platform)
uv run yazses-daemon --config ~/.config/yazses/config.toml

# Stop daemon
yazses stop

# Restart daemon (Linux)
systemctl --user restart yazses

# Check daemon status
yazses status
yazses status --json
```

### 5.2 Troubleshooting SSH Remote Sessions

**Tunnel fails to establish:**
1. Run `yazses doctor` — check that `remote.key_file` is accessible and that SSH to the target host works independently (`ssh user@host echo ok`).
2. Check that `AllowTcpForwarding yes` is set in the remote `/etc/ssh/sshd_config`.
3. Verify `yazses-agent` is installed on the remote machine: `ssh user@host yazses-agent --version`.
4. Check firewall: the remote agent listens on loopback (`127.0.0.1:9875` by default) — no external port is required.

**Text appears in wrong window on remote:**
- The remote agent uses the same injector probing as the local daemon. If `xdotool` is not installed on the remote, the agent falls back to clipboard injection (Ctrl+V).
- Install `xdotool` on the remote machine for keyboard-native injection: `apt install xdotool`.

**High latency on WAN:**
- Enable `stt.model = "tiny.en"` (fastest model) if using `base.en`.
- Disable streaming in remote mode (it is already non-default for remote): `yazses config set streaming.enabled false`.
- Check tunnel RTT: `yazses remote --status --json` reports `latency_ms`.

### 5.3 Resetting the Enrollment Profile

```bash
# Re-run enrollment (overwrites vad_threshold, min_silence_ms, pre_speech_padding_ms)
yazses enroll

# Reset to factory defaults (removes all accessibility-tuned values)
yazses config reset accessibility

# Manually edit config
yazses config edit   # opens config.toml in $EDITOR

# View current accessibility config
yazses doctor --accessibility
```

If the enrollment wizard produces a `vad_threshold` that causes too many false recordings (threshold too low), increase it manually:

```toml
# ~/.config/yazses/config.toml
[audio]
vad_threshold = 0.05   # default post-enrollment is ~0.02–0.04; increase if false triggers occur
```

### 5.4 Debugging the Disfluency Filter

```bash
# Pipe a test transcript through the filter
yazses filter --text "um let me uh go to line go to line 42"
# Output: "let me go to line 42"

# Disable filter temporarily
yazses config set filters.disfluency.enabled false

# View filter log (requires --verbose)
yazses-daemon --verbose 2>&1 | grep disfluency
```

---

## 6. Release Checklist

### 6.1 Version Bump

- [ ] `pyproject.toml`: `version = "0.3.0"`
- [ ] `src/yazses/__init__.py`: `__version__ = "0.3.0"`
- [ ] `yazses --version` outputs `YazSes 0.3.0` (verified by running the command after bump).

### 6.2 Changelog

- [ ] `CHANGELOG.md` updated with v0.3.0 section at the top.
- [ ] Changelog entries for: cap-001 (SSH remote), cap-002 (streaming), cap-003 (code commands), cap-004 (disfluency filter), cap-005 (accessibility + enrollment).
- [ ] Breaking changes section: none for v0.3.0 (all config additions have safe defaults).
- [ ] Upgrade guide section: instructions for users upgrading from v0.2.x (run `yazses enroll` to opt into accessibility tuning; no other action required).

### 6.3 Test Suite

- [ ] `uv run pytest tests/ -v` passes on Linux (Python 3.11 and 3.12).
- [ ] `uv run pytest tests/ -v` passes on macOS (Python 3.11 and 3.12).
- [ ] `uv run pytest tests/ -v` passes on Windows (Python 3.11 and 3.12).
- [ ] All pass/fail thresholds from §4 (Eval Plan) are met.
- [ ] All regression tests from R-001 through R-004 pass.
- [ ] Integration test (`pytest --integration tests/integration/test_ssh_tunnel.py`) passes on Linux CI.
- [ ] Test coverage ≥ 80% on all new modules (measured by `pytest --cov=src/yazses`).

### 6.4 Snap Package

- [ ] `snapcraft.yaml` version updated to `0.3.0`.
- [ ] New Python modules added to `snapcraft.yaml` `override-build` section (if snapcraft does not auto-detect them from `pyproject.toml`).
- [ ] Snap built locally and installed: `sudo snap install yazses_0.3.0_amd64.snap --dangerous`.
- [ ] `yazses --version` from Snap installation outputs `YazSes 0.3.0`.
- [ ] Snap published to `edge` channel first; promoted to `stable` after 48-hour soak.

### 6.5 apt Repository

- [ ] `scripts/build-deb.sh` produces `yazses_0.3.0_amd64.deb`.
- [ ] `.deb` installs cleanly on Ubuntu 22.04 and 24.04: `sudo dpkg -i yazses_0.3.0_amd64.deb`.
- [ ] `apt-repo.yml` GitHub Actions workflow triggered by `v0.3.0` tag publishes to the apt repository.
- [ ] `apt update && apt install yazses` installs `0.3.0` on a clean Ubuntu 24.04 container.

### 6.6 Homebrew Tap (macOS)

- [ ] Homebrew cask updated in the `MSKazemi/yazses` tap with `version = "0.3.0"` and updated SHA256.
- [ ] `brew install --cask MSKazemi/yazses/yazses` installs `0.3.0` on macOS 13 (Ventura) and macOS 14 (Sonoma).
- [ ] `yazses --version` from Homebrew installation outputs `YazSes 0.3.0`.

### 6.7 GitHub Release

- [ ] `v0.3.0` tag pushed to `main`.
- [ ] GitHub Release created with title `v0.3.0` and changelog body.
- [ ] Release assets attached: `.deb`, `.snap`, macOS `.dmg` (from `build-macos.yml`), Windows `.exe` installer (from `build-windows.yml`).
- [ ] Release marked as `Latest` after Snap and apt packages are confirmed live.
