---
title: Architecture
description: How YazSes works under the hood — the subsystem map, the offline dictation pipeline and what each stage actually costs, the daemon and its states, the cross-platform abstraction, text injection, the remote path, the opt-in learning loop, and an honest account of what is built versus what is only designed. All on-device; nothing leaves your machine.
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

## How to read this page

Two things are marked throughout, and they are never blurred together:

<span class="yz-tag yz-tag--ship">BUILT</span> — wired into the shipping build,
with tests. You can run it today.

<span class="yz-tag yz-tag--plan">DESIGNED</span> — decided and documented, and
deliberately **not** in the running system. Some of these are waiting on
hardware, some on a model, and one is deferred on purpose so a promise stays
kept.

The figures below are generated from the code and the measurements, not drawn by
hand — see [how these figures are made](#how-these-figures-are-made) for the
provenance and how to regenerate them yourself. Every figure is followed by the
same numbers as a table, so nothing here is only reachable by looking at a
picture.

## High-level overview

YazSes is a small background program — a *daemon* — that runs on your desktop
and listens for a single hold-to-talk key. The model is deliberately simple:

- **Hold** the hotkey and start speaking.
- **Release** it when you finish.
- Your words appear in whatever window has focus, usually within about a second
  and a half on the default model.

Everything happens **offline, on-device**. Speech is transcribed locally by
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) running on your CPU
(int8, no GPU required). There is no cloud service, no API key, and no account.
**Nothing leaves your machine** unless you explicitly point YazSes at a remote
host over SSH (see [the remote path](#the-remote-path)). Because it is
push-to-talk, YazSes is not always-listening: no audio is captured while the key
is up.

A thin command-line tool (`yazses`) talks to the running daemon to start it,
stop it, query its status, and tune it. The daemon does the actual work; the CLI
is a remote control.

## Subsystem map

<figure class="yz-figbox">
--8<-- "assets/arch/system-map.svg"
<figcaption>The whole system in six bands. Everything above the last band runs today; the last band is designed and deliberately absent.</figcaption>
</figure>

**A squeeze can now carry which mode, not just when.** `platform/emg/pressure.py`
turns raw EMG into a level — relaxed / light / hard — using the Teager–Kaiser
energy operator rather than a bare amplitude threshold, because TKEO responds to
amplitude *and* frequency and therefore ignores the large, slow artefacts (baseline
wander, cable sway, a shifting electrode) that a rectified threshold reads as a
contraction. Light squeeze dictates, hard squeeze commands, mirroring the command
key so all three mode switches behave identically. Thresholds are calibrated from
the user's own relaxed baseline and maximum contraction, because muscle amplitude
varies by an order of magnitude between people and fixed microvolt numbers are
meaningless. `platform/emg/brainflow_source.py` adds buyable hardware (OpenBCI,
Muse, …) through BrainFlow, keeping the serial YESP path as the DIY reference; a
missing device or dependency is a logged no-op, never a crash. (#103)

**Gaze calibration refines itself.** `gaze/implicit.py` treats a mouse click as
ground truth for where the user was looking and folds it into the existing affine
map with recursive least squares — the same estimator `fit_calibration` uses,
updated one sample at a time, so cost per click is constant and no sample history
is kept. It is gated on eye-agreement confidence and a residual bound, carries a
forgetting factor so it tracks a moved laptop lid rather than averaging both
positions, and `refined_if_better` only replaces the wizard's map when the
candidate wins on **held-out** samples (ADR-014's rule). Capture stays opt-in and
on-device per ADR-011/012; the module itself opens no camera and listens for no
clicks, which is why it is testable without a desktop.

**Three STT engines now sit behind one seam.** `faster-whisper` (default),
`parakeet` (accuracy), and `moonshine` (#74 — built for short segments on CPU,
which is the shape of hold-to-talk, and needs only `onnxruntime` + `tokenizers`,
so it installs without torch). `stt/factory.py` selects on `[stt] engine` and
falls back to faster-whisper with a warning whenever an engine's optional
dependency is absent or its model fails to load — dictation always comes up.

Neither Parakeet nor Moonshine supports `initial_prompt`, so the personal
dictionary reaches them a different way: `postprocess/vocab_correct.py` (#73)
recovers mis-heard vocabulary *after* decoding, which is why it was built
engine-agnostic rather than as a Whisper prompt trick.

Moonshine carries a hard upstream constraint the adapter absorbs rather than
propagates: audio must be 2-D and between 0.1 s and 64 s, enforced with bare
`assert`s. Both bounds are reachable — a stray key tap is under 0.1 s, a dictated
paragraph is over 64 s — so short buffers return empty and long ones are split on
the silence gate, instead of an `AssertionError` surfacing as a crash.

**Noise suppression has a backend that can be installed.** The denoise seam
(ADR-v2-015) shipped with only a `deepfilternet` adapter, which no environment can
satisfy: its latest release pins `numpy<2.0` while this project needs
`numpy>=2.4.6`, and those ranges are disjoint on every Python version — so the
feature was designed, wired and permanently unusable. `denoise/spectral.py`
(spectral gating over `noisereduce`) is the installable backend and the new
default. It is weaker than DeepFilterNet and the docs say so: it removes steady
broadband noise — fans, air conditioning, road hum — and does little against a
second speaker, which is the Cocktail Filter's job. Selecting `deepfilternet`
still parses and degrades to a passthrough, with no remedy offered, because
advising an extra that can never install is worse than saying "unavailable".

The control plane never touches the pipeline — the CLI, the settings window and
the tray all speak to the daemon over the same JSON-RPC channel, which is why
`yazses status` reports the truth rather than a guess, and why the tray can be
killed and relaunched without disturbing dictation.

Both front ends also share one definition of *enabling* a capability. Fifteen of
the ~140 rows need an optional Python package (`gaze` needs mediapipe, `cocktail`
needs speechbrain, and so on), and `yazses features enable` has always installed
those before telling you to restart. The settings window now does the same, on a
worker thread, through the identical `system/deps.py` call — so the two cannot
drift on what "enabled" means. The decisions (what to install, what to say when
it fails) are pure and Qt-free in `settingsui/deps.py`; only the thread and the
widgets live in `settingsui/app.py`.

**When an install fails, the config key stands.** A failed install is usually
transient — a network blip, a slow mirror, a wheel building — and silently
un-toggling the switch a user just moved discards their intent and leaves no
trace of why. Instead the capability is recorded as on and reported as *dormant
until its packages arrive*, which is a state `yazses doctor` and `yazses
features` already model and a user can fix by retrying. Enabling records intent;
satisfying it is a separate, retryable step, and the gap between the two is
always visible.

The four blocks in the bottom band are the ones people most often assume are
already there. Each is a recorded decision rather than an omission:

| Designed, not built | Why it isn't in the build | Where the decision lives |
|---|---|---|
| **Android dictation keyboard** | Architecture and portability matrix are done; the app is not written. iOS follows Android because an iOS keyboard extension cannot use the microphone. | [The mobile programme](mobile/index.md) |
| **Cloud escalation** | Fully designed with guardrails, and deliberately **not implemented**, so "nothing leaves your machine" is never quietly weakened. | [Roadmap — designed, but explicitly deferred](roadmap.md#future-work) |
| **Personal speech adapters (LoRA)** | On-device fine-tuning for your voice, including atypical speech. Gated on a measured accuracy win on held-out data — prompt-level personalization from your own corpus already ships. | `[personalize] lora` in the [configuration reference](configuration.md) |
| **Code-switch models** | The language-routing layer ships (`src/yazses/polyglot/`); the code-switch-adapted acoustic model does not, and the feature stays dormant until `adapter_path` is set. | [v2 features preview](v2-features.md) |

The same subsystem map ships in three other formats under
[`docs/diagrams/`](diagrams/index.md): [Mermaid](diagrams/yazses-architecture.mmd)
(renders on GitHub), [ASCII](diagrams/yazses-architecture.txt) for terminals and
code review, and a self-contained [HTML page](diagrams/yazses-architecture.html).

## The dictation pipeline

Each time you hold the key, speak, and release, your audio flows through a fixed
sequence of stages. The figure below colours each stage by what it actually
costs, measured rather than assumed.

<figure class="yz-figbox">
--8<-- "assets/arch/pipeline-heat.svg"
<figcaption>Nine stages. One of them is the entire latency budget; the other eight together are 0.02% of a burst.</figcaption>
</figure>

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
9. **Dispatch and inject.** Plain dictation goes to text injection; commands go to
   a key sequence (`src/yazses/commands/dispatch.py`). For dictation only, two
   optional finishing steps run first: an offline **LLM cleanup** pass that lightly
   reformats the text (`src/yazses/postprocess/llm_cleanup.py`, off by default), and
   **continuation spacing** so back-to-back bursts don't glue together
   (`src/yazses/postprocess/spacing.py`).

The measured cost of each stage that is separately timed:

| Stage | Median | Share of a burst |
|---|---|---|
| VAD gate | 0.063 ms | 0.004 % |
| Text cleaner | 0.005 ms | 0.000 % |
| Disfluency filter | 0.147 ms | 0.009 % |
| Command grammar (dictation) | 0.075 ms | 0.005 % |
| **STT decode** (`base.en`) | **1 561 ms** | **99.98 %** |

The design consequence is worth stating plainly: **all latency is the speech
model.** Micro-optimising the filters, the grammar, or the injector would not be
measurable. What *is* measurable is which model you choose — so that is the knob
the docs push you toward, and the only one worth turning.

Most of these stages are configurable or can be turned off; see the
[configuration reference](configuration.md).

## What a burst costs

<figure class="yz-figbox">
--8<-- "assets/arch/latency.svg"
<figcaption>Decode time for one utterance, measured 30 times per model on a 13th Gen Intel Core i7-1370P, int8 on CPU, no GPU.</figcaption>
</figure>

| Model | WER on LibriSpeech `test-clean` | Cold start | Decode, median | Decode, p95 | On disk |
|---|---|---|---|---|---|
| `tiny.en` | 4.82 % | 0.60 s | 0.89 s | 1.61 s | 78 MB |
| `base.en` **(default)** | 4.07 % | 0.85 s | **1.56 s** | 3.53 s | 148 MB |
| `small.en` | **2.59 %** | 1.63 s | 5.05 s | 8.97 s | 486 MB |

`base.en` is the default because it is the compromise that survives contact with
real use: noticeably more accurate than `tiny.en`, and still back inside a second
and a half. `small.en` is the most accurate and the right choice for
`yazses transcribe` and Meeting Mode — but a 5-second median breaks the flow of
live dictation, which is a different job.

These are read audiobook clips in clean conditions, so **your dictation WER will
be worse**; treat them as a comparison between models, not a promise about your
desk. Full method, hardware and the commands to reproduce every number are on the
[benchmarks page](benchmarks.md).

## The daemon and its states

The orchestrator is a single long-lived process, `yazses-daemon`
(`src/yazses/core/daemon.py`). It wires the whole pipeline together, owns the
hotkey listener, and runs an IPC server for the CLI and tray.

Internally it is a state machine. The ordinary dictation loop is the spine down
the middle; everything else is a mode you enter deliberately and return from.

<figure class="yz-figbox">
--8<-- "assets/arch/states.svg"
<figcaption>The dictation loop is the spine; everything below it is a mode you enter deliberately over IPC. The two states at the bottom are in the type but are not states the daemon enters.</figcaption>
</figure>

- **LOADING** — the daemon is up but the speech model is still loading.
- **IDLE** — ready and waiting for the hotkey.
- **RECORDING** — the key is held; audio is being captured.
- **TRANSCRIBING** — the key was released; the engine is decoding.
- **INJECTING** — the result is being typed into the focused app.
- **MEETING** — hands-free whole-meeting capture, driven over IPC rather than by
  the hotkey; stopping it runs the batch diarization pass through **TRANSCRIBING**.
- **REMOTE_SETUP / REMOTE_ACTIVE** — establishing or using the SSH forwarding path.
- **ENROLLING** — the accessibility / mic calibration wizard is running.
- **READBACK** — speaking a transcript back via offline TTS.

Two more states exist in the type and are worth being precise about, because a
tidier diagram would misrepresent them. **ERROR** is not a daemon state at all —
the *tray* synthesises it when the daemon stops answering IPC, which is why the
icon can go red while the daemon itself has simply died. **PAUSED** is defined,
and Meeting Mode and enrollment both accept it as a legal starting point, but
nothing in the daemon currently sets it.

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
| `LifecycleBackend` | Start/stop the daemon, manage the PID file, register autostart | systemd user unit | launchd | Service Control Manager |
| `IpcServer` / `IpcClient` | JSON-RPC transport for CLI ↔ daemon | Unix socket | Unix socket | named pipe |
| `PermissionsBackend` | Probe keyboard/microphone permissions, explain how to grant them | input group | TCC prompts | (n/a) |
| `TrayBackend` | Tray / menu-bar UI | PySide6 `QSystemTrayIcon` | rumps | pystray |

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

## What is built, and what is designed

YazSes carries a large catalogue of capabilities, and it is deliberately honest
about which of them are real. Every capability is a row in one registry
(`src/yazses/system/features.py`), and each row knows whether it is actually
wired into the build. `yazses features` prints that distinction, and
`features enable` **refuses** a capability that isn't wired rather than writing a
config key nothing will read.

<figure class="yz-figbox">
--8<-- "assets/arch/capabilities.svg"
<figcaption>Every capability in the registry, by category. The left segment is wired and working; the right segment is designed and not yet wired.</figcaption>
</figure>

| Category | Wired | Designed, not wired | Total |
|---|---:|---:|---:|
| Formatting & structure | 20 | 11 | 31 |
| Core dictation | 13 | 7 | 20 |
| Accuracy & correction | 11 | 9 | 20 |
| Accessibility & input modalities | 2 | 18 | 20 |
| Editing & navigation | 10 | 3 | 13 |
| Commands & automation | 5 | 7 | 12 |
| Learning, memory & analytics | 5 | 4 | 9 |
| Conversation & recording capture | 4 | 4 | 8 |
| Multilingual | 3 | 4 | 7 |
| **Total** | **73** | **67** | **140** |

Two readings of that chart matter.

**The core is dense and the frontier is thin.** The categories a daily user
touches — core dictation, formatting, editing — are majority-wired. The one
category that is almost entirely designed is **accessibility and input
modalities** (2 of 20), and that is not an accident: those are the capabilities
gated on hardware nobody has yet (sEMG wristbands, switch access rigs) or on a
platform capability that isn't universal (gaze on Wayland). They are specified so
that when the hardware arrives the work is integration, not invention.

**A designed row is a contribution-shaped hole.** Several of these have a tested,
dependency-free pure core and no caller — the design is done and the wiring is
not. Five such capabilities were wired by outside contributors in a single week,
which is why this number moves. If you want to help, this chart is the map: see
[find a task that fits you](contribute/find.md).

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
your config. Each proposal is checked against held-out data it wasn't derived
from, so a change has to survive evidence it hasn't already seen. You can inspect
or delete the corpus at any time with `yazses corpus status`, and flag a bad
transcription with `yazses mark-wrong` to feed the loop a correction signal.

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

## Where this is going

The architecture is built so the next era is an extension rather than a rewrite.
Three seams carry most of the future work, and each already exists in the
shipping code:

- **The activation seam.** `_build_activation_sources` treats "what starts a
  burst" as a plug-in. A keyboard key and an EMG squeeze are already two
  implementations of the same contract; a wake word, a switch, or a
  brain-computer interface would be a third without touching the pipeline.
- **The engine seam.** `SttEngine` made a second engine (Parakeet) a config
  change rather than a fork. Anything that turns audio into words plugs in here.
- **The platform seam.** Every OS-specific concern is a Protocol, which is what
  makes the Android programme a port rather than a rewrite.

What is deliberately *not* being built is as much a part of the design as what
is. Cloud escalation is fully specified and stays unimplemented so the offline
promise cannot erode by increments; personal speech adapters wait on a measured
win against held-out data rather than shipping on the strength of the idea. See
the [roadmap](roadmap.md) for the full account, including the speculative
directions — spoken recall over your own corpus is the one the project exists
for.

## Privacy posture

YazSes is **offline by design**. Push-to-talk means it only records while you
hold the key; transcription runs locally on your CPU; and no audio, text, or
telemetry is sent anywhere by default. The only outbound path is one you turn on
yourself — the SSH remote injection above, and even then only the final text is
forwarded, not your audio. The learning corpus is opt-in, encrypted, and local.

For the full commitment and details, see the
[privacy statement](privacy-statement.md).

## How these figures are made

The four figures on this page are generated, not drawn:

```bash
uv run python scripts/gen-arch-figures.py
```

The generator reads the live capability registry (`yazses.system.features` — the
same one `yazses features` prints), the generated
[command index](command-index.md), and the measured timings parsed out of the
[benchmarks page](benchmarks.md). It fails rather than guessing: if a benchmark
table is reworded it stops, and if a label would overflow the shape holding it
the figure is refused. So a figure claiming a capability is wired is making the
same claim the CLI makes, and a figure quoting a latency is quoting a number you
can reproduce with the commands on the benchmarks page.

The figures are plain SVG with no script and no external reference — nothing is
fetched from a third party when you load this page, which is the same commitment
the [privacy statement](privacy-statement.md) makes about the software itself.
They animate from the site's stylesheet and stop animating entirely if your
system asks for reduced motion; every value they show is also in a table on this
page.
