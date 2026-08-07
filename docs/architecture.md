---
title: Architecture
description: How YazSes works under the hood — the offline dictation pipeline, the daemon and its states, the cross-platform abstraction, text injection, the remote path, and the opt-in learning loop. All on-device; nothing leaves your machine.
---

# Architecture

This page explains how YazSes turns a held key and a few spoken words into text
in your focused application — entirely on your own machine. It is written for
users and curious contributors who want to understand the moving parts, not a
line-by-line internal reference.

For what each capability *does* and how to turn it on, see the
[features reference](features.md). For every configuration key, see the
[configuration reference](configuration.md). For the commands mentioned below,
see the [CLI reference](cli-reference.md).

## High-level overview

YazSes is a small background program — a *daemon* — that runs on your desktop
and listens for a single hold-to-talk key. The model is deliberately simple:

- **Hold** the hotkey and start speaking.
- **Release** it when you finish.
- Your words appear in whatever window has focus, usually within about a second.

Everything happens **offline, on-device**. Speech is transcribed locally by
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) running on your CPU
(int8, no GPU required). There is no cloud service, no API key, and no account.
**Nothing leaves your machine** unless you explicitly point YazSes at a remote
host over SSH (see [The remote path](#the-remote-path)). Because it is push-to-talk,
YazSes is not always-listening: no audio is captured while the key is up.

A thin command-line tool (`yazses`) talks to the running daemon to start it,
stop it, query its status, and tune it. The daemon does the actual work; the CLI
is a remote control.

## Subsystem map

The diagram below shows how the pieces fit together — the CLI/tray control plane,
the daemon's staged pipeline, text injection (local or remote), and the
cross-cutting config, feature registry, platform abstraction, and opt-in
subsystems. The same diagram ships in three formats under
[`docs/diagrams/`](diagrams/index.md): [Mermaid](diagrams/yazses-architecture.mmd)
(renders on GitHub), [ASCII](diagrams/yazses-architecture.txt), and a
self-contained [HTML page](diagrams/yazses-architecture.html).

```text
                        ┌───────────────────────────────────────┐
   USER-FACING CONTROL  │   yazses CLI            yazses-tray     │
                        │   (44 cmds, 6 panels)   (macOS/Windows) │
                        └───────────────────┬───────────────────┘
                                            │  JSON-RPC 2.0 (Unix socket /
                                            │  Windows named pipe)
                                            ▼
                                   ┌──────────────────┐
                                   │  IPC server      │  (ipc/)
                                   └────────┬─────────┘
                                            ▼
 ┌──────────────────────────────────────────────────────────────────────────────┐
 │  yazses-daemon — orchestrator (core/daemon.py)                                 │
 │   [1] HOTKEY  keyboard hook OR EMG (USB/BLE)                                    │
 │   [2] AUDIO   recorder ─► VAD gate ─► pre-speech padding                        │
 │   [3] STT     faster-whisper (int8) · streaming · disfluency  ◄─ initial_prompt │
 │   [4] POST    cleaner · voice-punctuation · spacing · optional LLM cleanup      │
 │   [5] CMDS    Tier-1 regex grammar ─► Tier-2 SLM router · LSP context           │
 │   [6] dispatch() ──────────────┬───────────────────────────┐                   │
 └────────┬────────────────────────┼──────────────────────────────────────────────┘
          ▼ dictate                ▼ command
 ┌──────────────────────┐   ┌────────────────────┐
 │ INJECTOR (inject/)   │   │ KEY SEQUENCE       │
 │ auto → ydotool /     │   │ ctrl+z, ctrl+s, …  │
 │ xdotool/wtype/clip   │   └─────────┬──────────┘
 └───────┬──────────┬───┘             ▼
         │          └────────►┌────────────────────────────┐
         │  SSH tunnel        │  Focused application (local)│
         ▼  (remote/)         └────────────────────────────┘
 ┌────────────────────────┐
 │ yazses-agent (remote)  │   text only; audio stays local
 └────────────────────────┘

 CROSS-CUTTING   config.toml/config.py ·  features.py (135 caps) ·
                 platform/base.py Protocols → linux · macos · windows · emg
 OPT-IN (off)    learning loop (encrypted corpus · `yazses tune`) ·
                 v2 cognitive (voiceprint · gaze · personalize · polyglot · cocktail) ·
                 recimport (`yazses transcribe`) · meeting (`yazses meeting`)
```

The next section walks the numbered pipeline stages [1]–[6] in detail.

## The dictation pipeline

Each time you hold the key, speak, and release, your audio flows through a fixed
sequence of stages. Most stages are pure, fast transforms; the heavy step is the
faster-whisper decode in the middle.

```text
   ┌─────────────────────────────────────────────────────────────────┐
   │  HOLD KEY                                                         │
   │  Hotkey backend  (keyboard hook  OR  EMG muscle-sensor over USB)  │
   └───────────────────────────────┬─────────────────────────────────┘
                                    │ on_hold_start
                                    ▼
                      Audio capture (microphone → buffer)
                                    │
                                    ▼
                      VAD gate (drop near-silent audio)
                                    │
                                    ▼
                      Pre-speech padding (prepend a short lead-in
                      so the first word isn't clipped)
                                    │
                                    ▼
        initial_prompt ──►  faster-whisper decode  (CPU, int8)
        (app name, your                │
         vocabulary, editor            ▼
         context)              Text cleanup (strip Whisper artefacts,
                               leading punctuation)
                                    │
                                    ▼
                      Disfluency filter (remove fillers, repeats,
                      self-corrections)
                                    │
                                    ▼
              Command classification
              ├─ Tier 1: fast regex grammar → intent
              └─ Tier 2 (optional): small language model router
                                    │
                                    ▼
                               dispatch()
                 ┌──────────────────┴───────────────────┐
                 ▼                                       ▼
         DICTATE (plain text)                    COMMAND (e.g. "undo",
                 │                                "save file", "go to line 42")
                 ▼                                       │
   optional LLM cleanup (reformatting)                   ▼
                 │                              inject key sequence
                 ▼                              (ctrl+z, ctrl+s, …)
   continuation spacing (space between
   successive bursts so they don't glue)
                 │
                 ▼
        Inject text into the focused app
        (locally, OR forward over SSH to a remote host)
```

Stage by stage:

1. **Hotkey.** A hold-to-talk key press starts a recording; releasing it ends
   the burst. The trigger is usually a keyboard key, but it can also be an
   **EMG muscle-sensor** connected over USB serial — a hands-free / silent-input
   option (`src/yazses/platform/emg/`).
2. **Audio capture.** The microphone is recorded into an in-memory buffer for the
   duration of the hold (`src/yazses/audio/recorder.py`).
3. **VAD gate.** A calibrated voice-activity check discards audio that is mostly
   silence, so an accidental tap doesn't produce a spurious transcript
   (`src/yazses/audio/vad_calibrated.py`). If you see "Silent audio -- discarding"
   in the logs, your speech fell below the threshold — run `yazses mic-level --set`.
4. **Pre-speech padding.** A short silent lead-in is prepended before decoding so
   faster-whisper doesn't clip your first word (`src/yazses/audio/padding.py`).
5. **STT decode.** The buffered audio is transcribed on the CPU by a pluggable
   engine behind the `SttEngine` protocol (`src/yazses/stt/base.py`, selected by
   `[stt] engine`): **faster-whisper** by default, or **NVIDIA Parakeet TDT**
   (`yazses features enable stt-parakeet`) — lower word-error rate than
   whisper-large-v3 at roughly 4× whisper-small's CPU speed, with no hallucinated
   text on silence. On the Whisper path an `initial_prompt` biases the model
   toward the right words — the app name, your personal vocabulary, and
   (optionally) context from your active editor.
6. **Text cleanup.** `clean_text()` strips Whisper artefacts such as
   `[BLANK_AUDIO]` and stray leading punctuation (`src/yazses/postprocess/cleaner.py`).
7. **Disfluency filter.** A three-pass filter removes fillers, de-duplicates
   repeated words, and rolls back self-corrections
   (`src/yazses/stt/filters/disfluency.py`).
8. **Command classification.** A fast **Tier 1 regex grammar** decides whether the
   utterance is plain dictation or a command like *"undo that"* or *"go to line 42"*
   (`src/yazses/commands/grammar.py`). When Tier 1 is unsure, an optional
   **Tier 2 small-language-model router** (`slm_router.py`) resolves the intent.
9. **Dispatch.** Plain dictation is routed to text injection; commands are routed
   to a key sequence (`src/yazses/commands/dispatch.py`).
10. **Dictate path extras.** For plain dictation only, two optional finishing
    steps run: an offline **LLM cleanup** pass that lightly reformats the text
    (`src/yazses/postprocess/llm_cleanup.py`, off by default), and **continuation
    spacing** that inserts a separating space so back-to-back bursts don't glue
    together (`src/yazses/postprocess/spacing.py`).
11. **Inject.** The final text (or key sequence) is typed into the focused
    application — locally, or forwarded over SSH to a remote host.

Most of these stages are configurable or can be turned off; see the
[configuration reference](configuration.md).

## The daemon and its states

The orchestrator is a single long-lived process, `yazses-daemon`
(`src/yazses/core/daemon.py`). It wires the whole pipeline together, owns the
hotkey listener, and runs an IPC server for the CLI and tray.

Internally it is a small state machine:

```text
LOADING ──► IDLE ◄──► RECORDING ──► TRANSCRIBING ──► INJECTING ──► IDLE
```

- **LOADING** — the daemon is up but the speech model is still loading.
- **IDLE** — ready and waiting for the hotkey.
- **RECORDING** — the key is held; audio is being captured.
- **TRANSCRIBING** — the key was released; faster-whisper is decoding.
- **INJECTING** — the result is being typed into the focused app.

Then it returns to **IDLE** for the next burst. A few additional states cover
special modes:

- **REMOTE_SETUP / REMOTE_ACTIVE** — establishing or using the SSH forwarding path.
- **ENROLLING** — the accessibility/mic calibration wizard is running.
- **READBACK / PAUSED** — speaking a transcript back via offline TTS, or paused.
- **ERROR** — something went wrong; the last error is surfaced to the CLI and tray.

### CLI ↔ daemon IPC

The CLI and system tray never touch the pipeline directly — they talk to the
daemon over a small **JSON-RPC 2.0** channel (newline-delimited JSON). On Linux
and macOS this is a **Unix domain socket**; on Windows it is a **named pipe**
(`src/yazses/ipc/`). This is how `yazses status`, `yazses stop`, and
`yazses mark-wrong` reach a running daemon, and how the daemon reports live state
(model, PID, ready/loading, mic level) back to callers.

## Platform abstraction

YazSes runs on Linux, macOS, and Windows from one codebase. It does this by
defining a set of **Protocol interfaces** — abstract contracts — that each OS
implements in its own way. The contracts live in `src/yazses/platform/base.py`;
the implementations live in `src/yazses/platform/linux/`, `.../macos/`, and
`.../windows/`. A factory (`platform/factory.py`) inspects the running OS and
returns a `Platform` bundle of the right concrete backends, so the daemon and CLI
are written once against the interfaces and never branch on the operating system.

| Interface | Responsibility | Linux | macOS | Windows |
|---|---|---|---|---|
| `HotkeyBackend` | Detect the hold-to-talk key, emit start/end callbacks | evdev | Quartz event tap | keyboard hook |
| `InjectorBackend` | Type text / send key sequences into the focused app | ydotool / xdotool / wtype | Quartz | SendInput |
| `LifecycleBackend` | Start/stop the daemon, manage the PID file, register autostart | systemd | launchd | Service Control Manager |
| `IpcServer` / `IpcClient` | JSON-RPC transport for CLI ↔ daemon | Unix socket | Unix socket | named pipe |
| `PermissionsBackend` | Probe keyboard/microphone permissions, explain how to grant them | input group | TCC prompts | (n/a) |
| `TrayBackend` | Optional tray / menu-bar UI | none | rumps | pystray |

The **EMG hotkey backend** (`platform/emg/backend.py`) is a
platform-independent `HotkeyBackend` implementation — it reads squeeze events
from a USB serial device (YESP protocol). Since v2.14.0 the daemon constructs
it through a pluggable **activation-source seam**
(`core/daemon.py::_build_activation_sources`) whenever `[emg] device_port` is
set: a squeeze drives the command-key callbacks by default (`mode = "command"`),
or plain hold-to-talk dictation (`mode = "full_text"`). Each activation source
runs in its own background thread beside the keyboard hook and is stopped at
shutdown; the same seam is where future non-keyboard triggers (wake word,
switch access) plug in.

### Adding a new operating system

Because every OS-specific concern is behind a Protocol, porting YazSes to a new
platform is well-scoped: implement each interface in
`src/yazses/platform/<os>/`, then register the new `sys.platform` value in
`platform/factory.py`. No changes to the daemon, pipeline, or CLI are required.

## Text injection backends

Getting characters into the focused window is surprisingly OS- and
display-server-specific, so on Linux YazSes ships several injector backends and
picks one automatically (`src/yazses/inject/`):

- **ydotool** — types via the kernel `uinput` device. This works everywhere,
  **including on Wayland and inside terminals**, which is why it is the default
  where available.
- **xdotool** — the classic X11 typing tool; fine on plain X11 sessions.
- **wtype** — a Wayland typing tool, but it is **blocked on GNOME and KDE
  Wayland**, so it can't be relied on there.
- **clipboard** — copies the text and pastes it. A pragmatic fallback, but a
  no-op inside terminals (paste means something different there) and it clobbers
  your clipboard.

At startup, `auto.py` probes the environment and selects the best available
backend; you can override the choice with the `[injection] backend` config key
(`auto` | `type` | `clipboard` | `wtype`).

**Why Wayland needs ydotool.** Wayland deliberately isolates applications from
one another for security, so an app generally can't synthesise input into a
different window. `wtype` relies on a protocol that GNOME and KDE do not expose,
so it fails silently there. `ydotool` sidesteps this by injecting at the kernel
level through `uinput` (via its helper daemon `ydotoold`), which is why it is the
one reliable path for keystroke injection on modern Wayland desktops. `yazses setup`
provisions `ydotoold` for you; see the [Linux install guide](install-linux.md).

## The remote path

YazSes can dictate into an application running on a **different machine** over
SSH (`src/yazses/remote/`, `yazses remote <host>`). The speech is still captured
and transcribed **locally** — only the final text is sent onward, so your audio
never leaves your machine.

At a high level: the local daemon opens an SSH reverse tunnel
(`remote/forwarder.py`), a lightweight injection agent runs on the remote host
(`yazses-agent`, `remote/agent.py`), and the daemon's normal injector is swapped
for a proxy (`remote/local_proxy.py`) that forwards typed text over the tunnel to
that agent. From your point of view it feels identical to local dictation; the
last mile just happens over the network.

## The optional learning loop

YazSes can improve its accuracy for *your* voice and vocabulary over time — but
only if you opt in. This is **off by default**.

When enabled (`[learning] enabled = true`), the daemon records one event per
hold-release into an **encrypted, machine-bound local corpus**
(`src/yazses/learning/`). The corpus is a local SQLite database at
`~/.local/share/yazses/`; the transcript text and any stored audio are encrypted
with a key derived from the machine, while only coarse metadata is kept in the
clear. Capture happens on a background thread so it never slows down dictation,
and nothing is ever uploaded.

Later, `yazses tune` analyses that corpus offline and **proposes** concrete
improvements — new vocabulary entries, a better VAD threshold, a different model,
disfluency tweaks — which you review and approve before anything is written to
your config. You can inspect or delete the corpus at any time with
`yazses corpus status`, and flag a bad transcription with `yazses mark-wrong` to
feed the loop a correction signal. See the [features reference](features.md) and
[configuration reference](configuration.md) for the full set of `[learning]` keys.

## The v2 cognitive layer

Beyond core dictation, YazSes includes an experimental **v2 cognitive layer**: a
set of opt-in perceptual and personalization features such as a target-speaker
"cocktail" filter, look-to-pane gaze targeting, corpus-driven vocabulary biasing,
and code-switch language routing. **Every one of them is OFF by default**, and
their heavy machine-learning dependencies (speaker embeddings, gaze models, and
so on) are isolated behind optional install *extras* — the base install never
pulls them in, and the pure logic stays dependency-free and dormant until you
explicitly enable a feature (manage them with `yazses features enable/disable`).
See the [v2 features preview](v2-features.md).

## Staying up: the reliability layer

A dictation daemon is only useful if it is running and correct at the moment you reach for
the key, and the failures that matter most are the ones with no visible symptom. Five
mechanisms exist for that, all on by default.

**Config can never stop startup.** `configcheck.py` reads the config dataclasses' own
annotations and repairs what it can (`"0.004"` → `0.004`), falls back to documented
defaults otherwise, drops unknown keys and sections, and survives unparseable TOML. Nothing
is swallowed: every decision becomes a `ConfigProblem`, listed at startup and shown by
`yazses doctor` as a **Config validity** check. Previously a single quoted number loaded
cleanly and then failed every dictation burst inside numpy, naming neither the file nor the
key.

**One authority on "is it running".** A PID file survives `kill -9` and is not recreated if
deleted under a live daemon; the single-instance lock is held by the OS for the process
lifetime and so is exact in both directions. `pid.is_running()` consults the lock first, so
`yazses status` and `yazses start` cannot give opposite answers — a state this project
reached in practice.

**It comes back.** `yazses autostart enable` installs a systemd user service pointing at
the current install (`platform/linux/autostart.py` is its single source of truth) with
`Restart=on-failure` and a StartLimit crash-loop bound. A clean exit — what `yazses stop`
produces — is deliberately not restarted.

**The gate follows your voice.** `audio/adaptive_vad.py` watches outcomes: a run of
discards with no successful transcription between them means the silence threshold sits
above the speaker, so it is lowered to pass those bursts, persisted, and announced. Only
downward, because a gate that is too high fails invisibly while one that is too low only
adds noise the user can see.

**The icon stays.** The tray was once launched at startup and never checked, so a crash
left dictation running unobserved. `tray/supervisor.py` re-checks every 20 s using the tray
lock as the liveness signal, bounded at five relaunches.

Two commands expose the result: `yazses verify` runs the real chain and names the first
broken link, and `yazses report` writes a redacted diagnostic bundle locally — never
uploaded, per the privacy posture below.

## Privacy posture

YazSes is **offline by design**. Push-to-talk means it only records while you
hold the key; transcription runs locally on your CPU; and no audio, text, or
telemetry is sent anywhere by default. The only outbound path is one you turn on
yourself — the SSH remote injection above, and even then only the final text is
forwarded, not your audio. The learning corpus is opt-in, encrypted, and local.

For the full commitment and details, see the
[privacy statement](privacy-statement.md).
