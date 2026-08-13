**Read this in other languages:** English · [हिंदी](README.hi.md) · [简体中文](README.zh-CN.md) · [Русский](README.ru.md)

# YazSes

## Hold a key, speak, and your words are typed into any app. Nothing ever leaves your computer.

**It is a voice human–computer interaction layer, not just a dictation box** — speak commands,
navigate your editor, target windows by looking at them, turn a meeting into speaker-labelled
minutes. All offline, on your own CPU.

## ⬇️ Install

| Your computer | Install it | Full guide |
|---|---|---|
| 🐧 **Linux** | `bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)` | **[Linux install →](https://mskazemi.com/yazses/install-linux.html)** |
| 🍎 **macOS** | `pipx install yazses` | **[macOS install →](https://mskazemi.com/yazses/macos-install.html)** |
| 🪟 **Windows** | `pipx install yazses` | **[Windows install →](https://mskazemi.com/yazses/windows-install.html)** |

Then run these two:

```bash
yazses quickstart   # 3 steps tailored to your machine — read-only, changes nothing
yazses start        # now hold your hotkey, speak, release
```

*On Apple Silicon, a Raspberry Pi, or anything not x86_64?* The
**[platform support matrix](https://mskazemi.com/yazses/platform-support.html)** lists every
OS and CPU with the channel that works there today — `pipx install yazses` works everywhere
that is supported at all, because the published wheel is architecture-independent.

**How it works:** you hold a key → YazSes records → [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
transcribes it on your CPU → the text is typed into whatever window has focus. There is no
network call at any step, no account, and no API key.

**How to change it:** `yazses hotkey set <key>` picks the hold-to-talk key, `yazses features`
lists every capability and turns it on or off, and `yazses doctor` tells you what is missing.
Settings live in `~/.config/yazses/config.toml` — see the
[configuration reference](https://mskazemi.com/yazses/configuration.html).

Not sure yet? **[Try it without installing](https://mskazemi.com/yazses/try-without-installing.html)**
(runs in Docker or your browser), or read
[what installing actually costs](https://mskazemi.com/yazses/install-cost.html) first.

---

[![Tests](https://github.com/MSKazemi/yazses/actions/workflows/test.yml/badge.svg)](https://github.com/MSKazemi/yazses/actions/workflows/test.yml)
[![Snap Status](https://snapcraft.io/yazses/badge.svg)](https://snapcraft.io/yazses)
[![PyPI](https://img.shields.io/pypi/v/yazses)](https://pypi.org/project/yazses/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/yazses?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/yazses)
[![PyPI Downloads](https://img.shields.io/pypi/dm/yazses)](https://pypi.org/project/yazses/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21856271.svg)](https://doi.org/10.5281/zenodo.21856271)
[![Documentation](https://img.shields.io/badge/docs-mskazemi.com%2Fyazses-5e35b1)](https://mskazemi.com/yazses/)
[![Open Source Helpers](https://www.codetriage.com/mskazemi/yazses/badges/users.svg)](https://www.codetriage.com/mskazemi/yazses)
[![All Contributors](https://img.shields.io/badge/all_contributors-12-orange.svg?style=flat-square)](#contributors)

[![Get it from the Snap Store](https://snapcraft.io/en/light/install.svg)](https://snapcraft.io/yazses)

**Your voice never leaves your machine.** Offline voice dictation that types into any app, transcribes a recording, or captures a whole meeting with speaker names and minutes — all on your own CPU. No cloud. No API key. No subscription.

YazSes is a free, open-source, offline voice dictation and speech-to-text daemon for **Linux (X11 & Wayland), macOS, and Windows**, built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper). Use it when audio must not be sent to Google, Apple, Microsoft, or Otter — because the meeting is confidential, the machine is air-gapped, or you simply don't want a subscription. Unlike cloud dictation such as Wispr Flow, YazSes runs entirely on-device; unlike Talon Voice, it aims at plug-and-play use rather than advanced scripting. YazSes is **not** recommended if you need a conversational AI agent, non-English models out of the box, or a mobile/web app.

📖 **Full documentation: [mskazemi.com/yazses](https://mskazemi.com/yazses/)** — install guides, CLI reference, configuration, features, and troubleshooting.

![YazSes — hold a key, speak, release; the text is typed into the focused app](docs/screenshots/yazses-reel.gif)

*40-second tour: the core loop, the command line, and the system tray. Terminal output is real; the command-line typing is re-enacted for legibility.*
▶️ **[Watch it on YouTube](https://www.youtube.com/watch?v=nn8WUKsCvZ4)** — same reel with chapters.

![yazses doctor — all green, fully offline](docs/screenshots/yazses-doctor.png)

Prefer text over video? [`docs/demo/yazses-cli.cast`](docs/demo/yazses-cli.cast) is an
asciinema recording of the CLI happy path (`-h` → `about` → `quickstart` → `features` →
`status`) — every byte is real command output, nothing hand-typed. Play it with
[asciinema](https://asciinema.org): `asciinema play docs/demo/yazses-cli.cast`.

> ⭐ **If that looks useful, a star is how other people find it.** There's no company and no
> ad budget behind this — word of mouth is the entire distribution strategy.

> 🙌 **Want to help?** **[Start here](https://mskazemi.com/yazses/contribute/start.html)** — one page, pick the row matching what you have, finish in 15–45 minutes. No permission needed and nothing is assigned; coding agents are welcome and there's a copy-paste prompt. Several tasks need **no Python at all** — [translate the README](https://github.com/MSKazemi/yazses/issues/18) into your language, [add your microphone](https://github.com/MSKazemi/yazses/issues/21) to the known-good list, or just run it and tell us what happened. [#22](https://github.com/MSKazemi/yazses/issues/22) lists everything open. The test suite is fully offline and takes about 30 seconds, so you need no microphone, model or GPU to contribute.

---

## Three things it does

| | What you run | What you get |
|---|---|---|
| 🎙️ **Dictate** | Hold a key, speak, release | The text is typed into whatever window has focus — editor, browser, terminal, chat. Plus voice commands (*"undo that"*, *"go to line 42"*) and macros. |
| 📄 **Transcribe a file** | `yazses transcribe interview.m4a` | A transcript of any audio/video file, optionally tagged **who said what**. Output as txt, md, srt, vtt, or json. |
| 👥 **Capture a meeting** | `yazses meeting start` … `yazses meeting stop` | Hands-free whole-meeting recording → a **speaker-labelled transcript** and, optionally, **minutes** (summary, decisions, action items) written by a local LLM. |

All three run on your CPU with no network access. The meeting recording is deleted after
transcription unless you ask to keep it, and speaker names come from voiceprints you
enroll yourself — never from a cloud account.

> **What's optional:** dictation works out of the box. Speaker labels need the
> diarization extra (`pipx install 'yazses[diarization]'`, ~15 MB of models, downloaded
> once); meeting minutes additionally need the `notes` extra plus a local GGUF model you
> point at. Both are off by default — see [offline meeting notes](docs/meeting-notes-offline.md).

---

## Quick Start

> **Want to hear how accurate it is before installing anything?**
> Run it in Docker or in your browser — no install, nothing left behind:
> **[Try it without installing](https://mskazemi.com/yazses/try-without-installing.html)**.
> A clip ships with the repo, and `--network none` proves the transcription is really
> happening on your own machine.

**Step 1 — Install** — the commands are at the [top of this page](#-install);
[all install options](#all-install-options) covers every platform and package manager.

The **recommended** Linux one-liner installs `uv` if needed, installs the latest YazSes,
provisions every system prerequisite (audio, keystroke injection, clipboard, `input` group,
Wayland `ydotoold`), and finishes by running **`yazses doctor`** so any missing tool surfaces
*during* install. The APT script
(`bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)`)
and `pipx` paths install the last tagged release. YazSes is also on the
[Snap Store](https://snapcraft.io/yazses) (`sudo snap install yazses`).

> **Piping a script from the internet into your shell?** Fair. Add `--dry-run` and it
> inspects your machine, prints every change it would make, and exits without making any
> of them:
> `bash <(curl -fsSL .../install.sh) --dry-run`
>
> Before you commit: **[what installing actually costs](https://mskazemi.com/yazses/install-cost.html)**
> (1.1 GB plus a 141 MB model, and what it changes on your system) and
> **[how to uninstall](https://mskazemi.com/yazses/uninstall.html)** — both published up
> front on purpose.


**Shell completion:** `yazses --install-completion` (or `yazses --show-completion` to print the script). See the [CLI reference](docs/cli-reference.md).

**Step 2 — Provision the system** *(Linux — one command; the APT install does it automatically)*

```sh
yazses setup        # installs audio + injection deps, joins the input group, sets up ydotoold
# then log out and back in (the input-group change needs a fresh login)
```

`yazses setup` ends by printing a numbered **finish-installing checklist** of the
steps only you can do — the `input`-group re-login, calibrate your voice
(`yazses mic-level --set`), and `yazses start` — and offers to run the mic
calibration for you right away.

> **The log-out/in is mandatory and one-time.** Joining the `input` group only
> takes effect in a *new login session* — opening another terminal tab is **not**
> enough, because it inherits the old session's groups and the hotkey stays dead.
> `yazses start` will warn you if this re-login is still pending. To dictate
> immediately without logging out, bridge the group for one session:
> `sg input -c "yazses restart"`. After a real re-login, plain `yazses start` just works.

`yazses setup` fixes everything dictation needs and is safe to re-run — it only does what's missing:
- **`libportaudio2`** — audio capture (without it the daemon crashes on start with `OSError: PortAudio library not found`).
- **injection backends** — `xdotool`/`xclip` (X11) and `wtype`/`ydotool`/`wl-clipboard` (Wayland).
- **`input` group** — required to read the hold-to-talk hotkey from the kernel.
- **`ydotoold`** — the virtual-input daemon. On **GNOME/KDE Wayland** this is the *only* way to inject keystrokes (`wtype` is blocked there), so `setup` installs and enables it.

> Prefer to do it by hand? `sudo apt install libportaudio2 xdotool ydotool wtype xclip wl-clipboard pipx && sudo usermod -aG input "$USER"`, then enable `ydotoold` (see [install-linux](docs/install-linux.md)). Verify anytime with `yazses doctor` — you want `[OK] Keyboard capture`, `[OK] Microphone`, and `[OK] Injection`. macOS/Windows skip this step (grant Accessibility/permissions when prompted — see below).

**Step 3 — Set up**

```sh
yazses quickstart           # not sure what's next? a 3-step guide tailored to your machine
yazses doctor               # check mic, injection backend, permissions (want all [OK])
yazses enroll               # calibrate your microphone (~30 seconds)
yazses autostart enable     # run it at login, so it's there after a reboot
yazses start                # start the dictation daemon
yazses verify               # speak once and prove the whole pipeline works
```

> New to YazSes? Run **`yazses quickstart`** anytime — it looks at what's already set up and tells you exactly what to do next. It changes nothing.

**Step 4 — Use it** — hold the hotkey, speak, release. The text is typed into the focused app.

| OS | Hold this key | Say… |
|---|---|---|
| Linux | `Space` | *"the quick brown fox"* (types it) · *"go to line 42"* · *"run the tests"* |
| macOS | `Right Option` | *"delete the last word"* · *"save file"* · *"new function parse config"* |
| Windows | `Right Ctrl` | *"undo that"* · *"select all"* · *"comment this line"* |

Release the key — YazSes transcribes and acts. On a modern laptop CPU that is a median of **1.6 s** with the default `base.en` model, or **0.9 s** with `tiny.en` ([measured](docs/benchmarks.md)).

> **First time on macOS?** The `.app` is still unsigned: right-click the app → Open (Gatekeeper), then grant Accessibility + Microphone when prompted.
>
> **First time on Windows?** If SmartScreen warns you, click **More info → Run anyway**.

---

## What you can say

Hold the key and just **talk** — by default everything you say is typed at the cursor. YazSes also recognises a set of **voice commands** (a fast regex grammar; an optional ~0.5B SLM router catches phrasings the grammar misses) that map to editor/terminal **key sequences** instead of being typed:

| Say something like… | What happens |
|---|---|
| *"the quick brown fox"* | Types the text at the cursor (dictation) |
| *"delete the last three words"* | Deletes the last 3 words |
| *"undo that"* / *"undo five times"* | Sends undo |
| *"save file"* · *"copy"* · *"paste"* | Save / copy / paste |
| *"select all"* · *"select to end"* | Selection commands |
| *"comment this line"* | Toggles a comment |
| *"go to line 42"* | Jumps to line 42 |
| *"go to function parse_config"* | Jumps to the symbol (via LSP, opt-in) |
| *"run the tests"* / *"run the build"* | Runs the editor/terminal action |
| *"rename this to user_id"* | Renames the symbol |

You can also define multi-step **macros** and a personal **vocabulary** of mis-heard words — see the [CLI reference](docs/cli-reference.md).

---

## How it works

```
Hold hotkey → record audio → VAD gate → faster-whisper (CPU) → clean + disfluency filter
            → command grammar (Tier 1 regex, optional Tier 2 SLM router)
            → dictate? type the text   ·   command? send the key sequence
```

Everything runs on your CPU — no GPU, no network. Transcription uses **faster-whisper** (int8). A fast regex grammar classifies each utterance as dictation or a command; when its confidence is low, an optional ~0.5B SLM router takes a second look.

Measured on a 13th-gen Core i7 laptop, int8 on CPU: **4.07 % WER** on LibriSpeech test-clean with the default `base.en`, a **1.56 s median** decode, and **0.29 ms** of total non-decode pipeline overhead — i.e. essentially all the latency is the speech model. Everything, including the method and the commands to reproduce it, is on the [benchmarks page](docs/benchmarks.md).

**Models:**
- **Speech-to-text:** faster-whisper — `tiny.en` (fast) / `base.en` / `small.en` (more accurate), int8 on CPU
- **Command routing (optional):** Qwen2.5-0.5B SLM for Tier 2 intent classification — *not* required for dictation, fetched with `yazses model download`
- **Dictation cleanup (optional, off by default):** a small offline LLM can tidy grammar/punctuation; length- and token-preservation guards stop it rewriting meaning

---

## Requirements

| | |
|---|---|
| **OS** | Linux (primary) · macOS 11+ · Windows 10 (21H2)+ |
| **RAM** | 4 GB minimum · 8 GB comfortable |
| **Disk** | ~250 MB–1 GB for the faster-whisper model (downloaded on first run) |
| **CPU** | 2+ cores · no GPU required |
| **Mic** | Any USB or built-in microphone |

---

## Key features

- **Fully offline** — no audio, no text, nothing leaves the machine by default; no cloud, API key, or subscription
- **Hold-to-talk dictation** — type into any focused app on Linux, macOS, or Windows
- **Meeting Mode** — hands-free whole-meeting capture → speaker-labelled transcript, plus optional local-LLM minutes (summary, decisions, action items); audio is deleted after transcription unless you keep it
- **Offline file transcription** — `yazses transcribe <file>` turns any audio/video into txt/md/srt/vtt/json, with optional *who-said-what* speaker tags
- **Voice commands** — editor/terminal actions (undo, save, go-to-line, run tests, rename…) via regex grammar + an optional SLM router
- **Macros & personal vocabulary** — define multi-step commands and teach YazSes your mis-heard words
- **Dysfluency-Friendly Mode** — opt-in collapse of stutters/repeats (`b-b-because` → `because`) for stuttered or dysarthric speech
- **Self-improving** — opt-in, encrypted on-device learning corpus; `yazses tune` proposes accuracy fixes from your own corrections (nothing leaves the machine)
- **Editor context** — optional Neovim / VS Code LSP context improves accuracy on code identifiers
- **Accessibility** — VAD calibration wizard, mic-level tuning, and EMG (muscle-sensor) trigger support for motor-disability use
- **Voice-activity overlay** — optional sonar rings near the cursor while you speak

---

## Use cases

- **Writers & journalists** — draft long-form text hands-free without your words leaving the machine.
- **Developers working on remote machines** — because text is injected at the OS level rather than inside an app, dictation works in **VS Code / Cursor Remote-SSH panes, integrated terminals running a remote shell, `tmux`, and container shells** — where the voice input built into editors and AI coding tools usually stops. No setup; see [dictation over SSH](https://mskazemi.com/yazses/how-to/remote-dictation.html).
- **Developers** — dictate code comments and commit messages, and drive the editor/terminal by voice (undo, save, go-to-line, run tests, rename a symbol).
- **Privacy-conscious professionals** — dictate in fields like law, medicine, or research where audio must never touch a cloud service.
- **Teams with confidential meetings** — record and summarise internal, clinical, legal, or pre-publication research meetings without uploading them to a note-taking SaaS or inviting a bot into the call.
- **Researchers & journalists with recordings** — batch-transcribe interviews, lectures, and field recordings offline, with speaker tags, under your own retention rules.
- **Accessibility & motor-disability users** — hold-to-talk or EMG (muscle-sensor) triggering for hands-free input, with Dysfluency-Friendly Mode for stuttered or dysarthric speech.
- **Offline / air-gapped environments** — dictation on machines with no reliable internet or where external network calls are disallowed.

**In depth, with setup steps for each:**
[voice typing on Linux (X11 & Wayland)](https://mskazemi.com/yazses/use-cases/voice-dictation-linux.html) ·
[voice dictation on Wayland](https://mskazemi.com/yazses/use-cases/voice-dictation-wayland.html) ·
[dictation over SSH & Remote-SSH](https://mskazemi.com/yazses/how-to/remote-dictation.html) ·
[private & confidential work](https://mskazemi.com/yazses/use-cases/private-offline-dictation.html) ·
[coding by voice](https://mskazemi.com/yazses/use-cases/voice-coding.html) ·
[accessibility & RSI](https://mskazemi.com/yazses/use-cases/accessibility-rsi-hands-free.html) ·
[transcribing recordings](https://mskazemi.com/yazses/use-cases/transcribe-audio-offline.html) ·
[multilingual dictation](https://mskazemi.com/yazses/use-cases/multilingual-dictation.html)

---

## Limitations / when *not* to use YazSes

- **Not an LLM agent.** YazSes dictates text, transcribes recordings, and runs editor/terminal commands. It does **not** browse, reason over your files, set timers, or hold a conversation — that was the paused [Rust exploration](#rust-hci-exploration-archived).
- **Speaker labels and minutes are extras, not defaults.** `--diarize` and meeting minutes each need an opt-in extra (and, for minutes, a local GGUF model you supply). Plain dictation and plain transcription need neither.
- **CPU faster-whisper, not a cloud service.** For the absolute lowest word-error rate on a noisy mic, a cloud STT may still beat it; the trade-off is that nothing leaves your machine.
- **English-tuned by default.** It ships with `*.en` Whisper models; other languages need a different model.
- **Desktop only, today.** There is no mobile or web build you can install. An **Android app is in design** — the architecture and its ten decision records are public at [docs/mobile](docs/mobile/index.md), and it is being built in the open by contributors. iOS/iPadOS follows Android; macOS is already supported by this desktop app.

---

## Comparison & alternatives

An honest comparison with other voice-dictation tools. All claims are about publicly documented behaviour; each tool has strengths YazSes does not.

| | **YazSes** | **Dragon** | **Talon Voice** | **Windows Voice Access** | **Wispr Flow** |
|---|---|---|---|---|---|
| Runs offline / on-device | ✅ | ✅ | ✅ | ✅ | ❌ (cloud) |
| Voice commands | ✅ regex grammar + optional SLM | ✅ | ✅ advanced scripting | ✅ | limited |
| Linux | ✅ | ❌ | ✅ | ❌ | ❌ |
| macOS | ✅ | ❌ (discontinued) | ✅ | ❌ | ✅ |
| Windows | ✅ | ✅ | ✅ | ✅ (built in) | ✅ |
| Price | Free, Apache-2.0 | Paid | Free (paid beta features) | Free (built into Windows 11) | Paid subscription |
| Open source | ✅ | ❌ | ❌ | ❌ | ❌ |

**When another tool may fit better:**
- **Talon Voice** — if you want deep, scriptable voice control and are willing to learn its scripting model. YazSes and Talon can coexist.
- **Windows Voice Access** — if you are on Windows 11 only and want a zero-install, OS-native option.
- **Dragon** — if you need a mature, professionally supported dictation product on Windows and can pay for it.
- **Wispr Flow** — if you prefer a polished cloud service and are comfortable sending audio off-device.

Choose **YazSes** when you specifically want dictation *and* voice commands that are open source, cross-platform (including Linux), and fully offline with nothing leaving your machine.

---

## FAQ

**What is YazSes?** YazSes is an open-source, offline hold-to-talk voice-dictation daemon for Linux, macOS, and Windows. You hold a key, speak, and release; your speech is transcribed on-device with faster-whisper and typed into the focused application, with support for editor and terminal voice commands and macros.

**Is there a good offline voice-dictation tool for Linux?** Yes — YazSes runs natively on Linux (X11 and Wayland), transcribes locally on the CPU, and needs no cloud service or API key. It installs via an APT script or `pipx`.

**YazSes vs Talon?** Both are cross-platform and work offline. YazSes focuses on plug-and-play dictation plus a practical command grammar (with an optional small SLM router). Talon offers far more advanced, scriptable voice control. They can be used side by side.

**Does it work without internet?** Yes. Transcription runs locally with faster-whisper, and no audio or text is sent anywhere by default. YazSes works fully offline and on air-gapped machines.

**Is it free and open source?** Yes — YazSes is released under the Apache 2.0 license, with no subscription or API key.

**What hardware do I need?** No GPU. It runs on CPU with 4 GB RAM minimum (8 GB comfortable) and any USB or built-in microphone.

**Is it an AI agent?** No. YazSes dictates text and runs editor/terminal voice commands; it does not browse, reason over your files, or hold a conversation. (An agentic version was prototyped in the archived Rust branch but is not shipped.)

More in the **[full FAQ](https://mskazemi.com/yazses/faq.html)** and a side-by-side in **[Comparison & alternatives](https://mskazemi.com/yazses/comparison.html)** (YazSes vs Talon, Dragon, Wispr Flow, nerd-dictation…).

---

## CLI commands

| Command | Description |
|---|---|
| `yazses quickstart` | New here? A 3-step, machine-tailored getting-started guide (read-only) |
| `yazses start` | Start the YazSes daemon in the background (restarts cleanly if one is already running; verifies it actually came up) |
| `yazses restart` | Stop all daemons (including detached) and start exactly one |
| `yazses stop` | Stop the running daemon |
| `yazses status` | Show daemon status — queries the daemon over IPC when reachable |
| `yazses doctor` | Check prerequisites (version, daemon, model, mic, injection backend, permissions) — ends with a ✓/▲/✗ verdict |
| `yazses enroll` | Calibrate your microphone — tunes `vad_threshold` for your voice and room |
| `yazses mic-level` | Measure mic speech level and recommend (or `--set`) the VAD threshold |
| `yazses features` | List capabilities and toggle them (`enable`/`disable <name>`) |
| `yazses settings` | The same switchboard as a window — every capability as a checkbox (needs a display) |
| `yazses vocab` | Personal dictionary of mis-heard words (`add`/`list`/`remove`) |
| `yazses hotkey` | Show or change the hold-to-talk key (`set`) and the dedicated command key (`command`) |
| `yazses overlay` | Launch the sonar voice-activity overlay (requires the `overlay` extra) |
| `yazses inject TEXT` | Type arbitrary text into the focused window — test injection without speaking |
| `yazses say TEXT` | Speak text aloud (offline TTS) |
| `yazses test` | End-to-end self-test: focuses a window and types `YazSes OK` |
| `yazses logs` | Show the daemon diagnostic log (metadata only — no dictated text is stored) |
| `yazses mark-wrong` | Flag the last dictation as a misrecognition (feeds the learning corpus) |
| `yazses tune` | Analyse the learning corpus and propose accuracy improvements; `--apply` to write changes |
| `yazses corpus` | Manage the local learning corpus (`status`, `forget`, `destroy`) |
| `yazses model` | List or download the optional SLM intent-routing model |
| `yazses remote HOST` | Forward voice typing to a remote host over SSH |

---

## Configuration

Config file location:

| OS | Path |
|---|---|
| Linux | `~/.config/yazses/config.toml` |
| macOS | `~/Library/Application Support/yazses/config.toml` |
| Windows | `%APPDATA%\yazses\config.toml` |

Prefer `yazses features` / `yazses hotkey` / `yazses vocab` to edit config safely (they preserve comments). Essential settings:

```toml
[stt]
model = "small.en"          # tiny.en (fast) | base.en | small.en (accurate); CPU int8
initial_prompt = ""         # vocabulary/context primed into Whisper

[hotkey]
key = "space"               # hold-to-talk key (yazses hotkey set <key>)
command_key = ""            # optional dedicated key that forces command mode
hold_threshold_ms = 500     # how long to hold before recording starts

[audio]
sample_rate = 16000
max_record_seconds = 90

[injection]
backend = "auto"            # auto | xdotool | ydotool | wtype | clipboard

[accessibility]
vad_threshold = 0.0008      # lower for quiet speech, raise if room noise triggers (yazses mic-level --set)
```

See the [CLI reference](docs/cli-reference.md) and [`examples/config.example.toml`](examples/config.example.toml) for all options.

### Microphone not working?

If YazSes does nothing and the log shows `Silent audio -- discarding`, your speech is below the VAD threshold:

```sh
yazses mic-level --set   # measure your voice and set the right threshold
yazses restart
```

---

## All install options

### Install or upgrade to the latest version

`pipx install yazses` always pulls the **latest published release** from PyPI. If you
already have YazSes installed, upgrade in place:

```bash
pipx upgrade yazses          # upgrade an existing install to the latest release
pipx install --force yazses  # reinstall the latest (if upgrade reports "already at latest")
```

Pin an exact version if you need one: `pipx install yazses==2.15.0`. Check what you have
with `yazses --version` (or `yazses doctor`, which also reports the running daemon).

### Linux

```bash
# APT script — Debian / Ubuntu (recommended)
bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install-apt.sh)

# pipx — any distro with Python ≥ 3.11
# Debian/Ubuntu runtime deps. libportaudio2 = audio capture (required);
# xdotool/xclip = X11 injection+clipboard; wtype/ydotool/wl-clipboard = Wayland.
# Installing all of them makes YazSes work on either session type.
sudo apt install libportaudio2 xdotool ydotool wtype xclip wl-clipboard pipx
sudo usermod -aG input "$USER"   # hotkey access — then log out and back in
pipx install yazses

# From source (contributors) — one command does the whole loop:
# editable install + `yazses setup` provisioning + start (bridges the input
# group so you can test before logging out).
bash scripts/dev-install.sh

# Snap Store — https://snapcraft.io/yazses
# All four lines are required. A snap cannot connect its own interfaces, and the
# daemon starts and looks healthy without them — it just never hears you, or never
# sees the key.
sudo snap install yazses
sudo snap connect yazses:audio-record   # microphone; without it, no audio
sudo snap connect yazses:raw-input      # hold-to-talk key; without it, nothing fires
yazses setup                            # provisions the rest
yazses doctor                           # says if anything is still missing
```

### macOS

```sh
# Homebrew — Apple Silicon only (see below)
brew tap MSKazemi/yazses
brew install --cask yazses

# pipx (Python ≥ 3.11) — works on Apple Silicon and Intel
pipx install yazses

# App bundle (.dmg) — unsigned developer preview, Apple Silicon only
# https://github.com/MSKazemi/yazses/releases/latest
```

> **On an Intel Mac, use pipx.** The `.dmg` is built host-arch on GitHub's arm64
> `macos-latest` runner and carries no `x86_64` slice, so it cannot launch on Intel;
> the cask declares `arch: :arm64` and refuses rather than installing a broken app.
> Details in [docs/macos-install.md](docs/macos-install.md).

### Windows

```powershell
# pipx (Python ≥ 3.11)
pipx install yazses

# Installer (.exe) — unsigned developer preview
# https://github.com/MSKazemi/yazses/releases/latest
```

---

## Documentation

**→ Full documentation site: [mskazemi.com/yazses](https://mskazemi.com/yazses/)** — searchable, with install guides, the complete CLI & configuration reference, feature catalog, architecture, and troubleshooting.

Quick links:

| | |
|---|---|
| [Install on Linux](docs/install-linux.md) | Detailed Linux guide — permissions, injection backends, service setup |
| [Install on macOS](docs/macos-install.md) | Gatekeeper, Accessibility, Microphone permissions |
| [Install on Windows](docs/windows-install.md) | SmartScreen, antivirus exceptions, privacy settings |
| [CLI reference](docs/cli-reference.md) | All commands and flags (incl. macros & vocabulary for custom voice commands) |
| [Privacy statement](docs/privacy-statement.md) | What stays on-device, what is never collected |
| [Research: the science of post-keyboard input](docs/research/index.md) | Cited surveys of eye, voice and muscle/brain input — every design decision traced to a measurement |
| [Students, researchers & industry](docs/research/get-involved.md) | Thesis-sized projects with open issues, the research platform, how to cite |
| [Record your own demo GIF](docs/demo-guide.md) | How to capture a short hold-to-talk demo GIF |

A man page ships in the Debian package, so `man yazses` works after an
`apt`/`.deb` install. From a source checkout, read it with `man -l man/yazses.1`
(regenerate with `make man`). `pipx`/`pip` and Snap installs do not place man
pages on the system man path — use `yazses --help` there.

---

## Development

YazSes (Part 1) is a Python project managed with `uv`:

```bash
git clone https://github.com/MSKazemi/yazses
cd yazses
uv sync
uv run python -m pytest tests/ -v
bash scripts/install-local.sh        # install locally + run as a user service
```

**Install the latest dev build from source** (ahead of the published PyPI release —
this is how a working copy is installed system-wide as an unconfined `uv` tool, which
Linux hold-to-talk needs because the strict-confinement snap cannot read `/dev/input`):

```bash
uv tool install --from . yazses --force   # (re)install the working tree as the `yazses` command
yazses restart                            # restart the daemon onto the new build
yazses --version                          # confirm the installed build
```

### Rust HCI exploration (archived)

This repo holds **one product** with **two implementations** — two generations of the same
idea, not two apps. The one you install and run is the **Python** implementation on `main`.
The early-stage Rust rewrite lives on the **`archive/rust-hci-v1`** branch and is not built,
installed, or depended on by anything here.

| | **Python** · `main` | **Rust HCI exploration** · `archive/rust-hci-v1` |
|---|---|---|
| What it is | The shipping app — dictation, file transcription, Meeting Mode, voice commands, macros | An early-stage rewrite exploring deeper **human–computer interaction**: an on-device *agent* (LLM tool-use, personal memory, editor awareness) |
| Status | ✅ **Active — current product** (v2.17.0, installed & maintained) | ⏸️ **Paused / archived** — not shipped, not installable |
| Offline STT | ✅ faster-whisper (CPU int8) | ✅ Whisper + Moonshine v2 (~9 ms) |
| Voice commands | ✅ regex grammar (+ optional SLM router) → key sequences | ✅ via LLM tool-calls |
| Voice macros · Mid-Thought Undo · Punch-In · Prosody Ink · Ghost Ahead | ✅ | ❌ |
| Dysfluency-Friendly Mode · learning corpus + `yazses tune` | ✅ | ❌ |
| On-device **LLM agent** (OS tools: git commit, media, notes, screenshots…) | ❌ (optional offline text *cleanup* only) | ✅ |
| **Personal memory** (encrypted on-device vector store) | ❌ | ✅ |
| Editor context (Neovim / VS Code) | ✅ LSP context, opt-in | ✅ 5-tier window detection + bridges |
| Screen-reader integration (AT-SPI / NVDA) | ❌ | ✅ |
| Packaged & distributed (PyPI, snap, APT) | ✅ | ❌ |

Revisiting the Rust effort is a deliberate future decision, not part of day-to-day work
here. To look at it:

```bash
git checkout archive/rust-hci-v1
cargo build && cargo test --workspace   # optional backends: whisper, moonshine, llama-cpp, ollama, silero
```

---

## Contributing

Contributions are very welcome — bug reports, docs, packaging, and code.

**There is nothing to sign.** No CLA, no DCO, no sign-off line, no bot to authorise, no
account beyond GitHub. Opening the pull request is the whole contract — Apache-2.0 section 5
already covers the licence grant.

- 🌱 **New here?** Start with a [good first issue](https://github.com/MSKazemi/yazses/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — each is small and self-contained, and we're happy to help you through your first PR.
- 🚀 **First time? [Start here](https://mskazemi.com/yazses/contribute/start.html)** — one page, pick the row matching what you have in front of you, finish in 15–45 minutes. No permission needed, nothing is assigned, and coding agents are welcome (there's a copy-paste prompt).
- 🎯 **Want the full list?** [**Filter 130 open tasks**](https://mskazemi.com/yazses/contribute/find.html) by what you have, your time, and whether you want to write code
  — each one names the exact files you may touch, the command that says you're done, and an
  honest time estimate. Filter by what you actually have: a browser, a terminal, a specific
  app, or unusual hardware nobody else can test.
- ⏱️ **Got 15 minutes and no Python?** [**27 tasks are `browser-only`**](https://github.com/MSKazemi/yazses/issues?q=is%3Aopen+label%3Abrowser-only)
  — doable entirely in the GitHub web editor, no clone and no install. These need only a text
  editor, take one PR each, and
  several hold many contributors at once — no permission needed, just comment and go:
  [translate the README](https://github.com/MSKazemi/yazses/issues/18) (the lede and Quick
  Start alone is a complete PR),
  [add your microphone](https://github.com/MSKazemi/yazses/issues/21),
  [share a config for your app or editor](https://github.com/MSKazemi/yazses/issues/43), or
  [add your setup to SHOWCASE.md](https://github.com/MSKazemi/yazses/issues/42).
- 🐞 **Found a bug or have an idea?** Open an [issue](https://github.com/MSKazemi/yazses/issues/new/choose) (the `yazses doctor` output resolves most reports on its own) or ask in [Discussions](https://github.com/MSKazemi/yazses/discussions).
- 🔧 **Sending a PR?** See [CONTRIBUTING.md](CONTRIBUTING.md). The gates are quick:

```bash
uv run python -m pytest tests/   # tests — must be green
uv run ruff check src tests scripts   # lint — must be green
uv run mypy src                  # types — advisory (currently clean; don't add errors)
```

Or just `make check`. Tests run fully offline in about 30 seconds — no microphone, model
download, or optional extras needed.

**No local setup?** The repo ships a [Dev Container](.devcontainer/devcontainer.json), so
[opening it in GitHub Codespaces](https://codespaces.new/MSKazemi/yazses) gives you a ready
environment in the browser. Docs, config, tests, and pure-logic changes work fully there;
anything needing a real microphone, hotkey device, or window focus needs a local machine.

Everything is offline-first — please don't add network calls or telemetry.

---

## Contributors

Thanks to these people for helping build YazSes ✨ — every bug report, doc fix, and patch counts. Contribution types follow the [all-contributors emoji key](https://allcontributors.org/reference/emoji-key/) (💻 code · 📖 docs · 🌍 translation · ⚠️ tests · 🛡️ security · 🚧 maintenance):

<!-- ALL-CONTRIBUTORS-LIST:START - Do not remove or modify this section -->
<!-- prettier-ignore-start -->
<!-- markdownlint-disable -->
<table>
  <tbody>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/MSKazemi"><img src="https://avatars.githubusercontent.com/u/13011878?v=4?s=100" width="100px;" alt="Mohsen Seyedkazemi Ardebili"/><br /><sub><b>Mohsen Seyedkazemi Ardebili</b></sub></a><br /><a href="#maintenance-MSKazemi" title="Maintenance">🚧</a> <a href="https://github.com/MSKazemi/yazses/commits?author=MSKazemi" title="Code">💻</a> <a href="https://github.com/MSKazemi/yazses/commits?author=MSKazemi" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/lntutor"><img src="https://avatars.githubusercontent.com/u/1948922?v=4?s=100" width="100px;" alt="lntutor"/><br /><sub><b>lntutor</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=lntutor" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/HeaTTap"><img src="https://avatars.githubusercontent.com/u/83951176?v=4?s=100" width="100px;" alt="HeaTTap"/><br /><sub><b>HeaTTap</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=HeaTTap" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/jackie-cqz"><img src="https://avatars.githubusercontent.com/u/88996311?v=4?s=100" width="100px;" alt="jackie-cqz"/><br /><sub><b>jackie-cqz</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=jackie-cqz" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Parinitha-26"><img src="https://avatars.githubusercontent.com/u/199358281?v=4?s=100" width="100px;" alt="Parinitha-26"/><br /><sub><b>Parinitha-26</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=Parinitha-26" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/AshSgDe29071999"><img src="https://avatars.githubusercontent.com/u/192003854?v=4?s=100" width="100px;" alt="AshSgDe29071999"/><br /><sub><b>AshSgDe29071999</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=AshSgDe29071999" title="Code">💻</a> <a href="https://github.com/MSKazemi/yazses/commits?author=AshSgDe29071999" title="Documentation">📖</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Maqbool61"><img src="https://avatars.githubusercontent.com/u/68494045?v=4?s=100" width="100px;" alt="Maqbool Ahmed"/><br /><sub><b>Maqbool Ahmed</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=Maqbool61" title="Code">💻</a></td>
    </tr>
    <tr>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn"><img src="https://avatars.githubusercontent.com/u/145488564?v=4?s=100" width="100px;" alt="Renji"/><br /><sub><b>Renji</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn" title="Code">💻</a> <a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn" title="Tests">⚠️</a> <a href="https://github.com/MSKazemi/yazses/commits?author=waterlemonnn" title="Documentation">📖</a> <a href="#security-waterlemonnn" title="Security">🛡️</a> <a href="#infra-waterlemonnn" title="Infrastructure (Hosting, Build-Tools, etc)">🚇</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/slegarraga"><img src="https://avatars.githubusercontent.com/u/64795732?v=4?s=100" width="100px;" alt="Sebastian Legarraga"/><br /><sub><b>Sebastian Legarraga</b></sub></a><br /><a href="https://github.com/MSKazemi/yazses/commits?author=slegarraga" title="Code">💻</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/YossiMH"><img src="https://avatars.githubusercontent.com/u/21257793?v=4?s=100" width="100px;" alt="YossiMH"/><br /><sub><b>YossiMH</b></sub></a><br /><a href="#ideas-YossiMH" title="Ideas, Planning, & Feedback">🤔</a> <a href="https://github.com/MSKazemi/yazses/issues?q=author%3AYossiMH" title="Bug reports">🐛</a> <a href="#research-YossiMH" title="Research">🔬</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/Prithvi4904"><img src="https://avatars.githubusercontent.com/u/216231806?v=4?s=100" width="100px;" alt="Prithvi4904"/><br /><sub><b>Prithvi4904</b></sub></a><br /><a href="#translation-Prithvi4904" title="Translation">🌍</a></td>
      <td align="center" valign="top" width="14.28%"><a href="https://github.com/4nmus"><img src="https://avatars.githubusercontent.com/u/145120721?v=4?s=100" width="100px;" alt="4nmus"/><br /><sub><b>4nmus</b></sub></a><br /><a href="#translation-4nmus" title="Translation">🌍</a></td>
    </tr>
  </tbody>
</table>

<!-- markdownlint-restore -->
<!-- prettier-ignore-end -->

<!-- ALL-CONTRIBUTORS-LIST:END -->

Want on this wall? Grab a [good first issue](https://github.com/MSKazemi/yazses/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) — first PR merged earns your spot.

---

## Citation

YazSes is described in a preprint. If it is useful in your research or projects, please cite:

> Seyedkazemi Ardebili, M. (2026). *YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk Voice-Dictation System.* arXiv:2607.28878. <https://arxiv.org/abs/2607.28878>

```bibtex
@article{seyedkazemi2026yazses,
  title   = {YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk Voice-Dictation System},
  author  = {Seyedkazemi Ardebili, Mohsen},
  journal = {arXiv preprint arXiv:2607.28878},
  year    = {2026},
  url     = {https://arxiv.org/abs/2607.28878}
}
```

See [CITATION.cff](CITATION.cff) for machine-readable metadata (CFF 1.2.0).

## License

Apache 2.0 — see [LICENSE](LICENSE).

If YazSes is useful to you, a ⭐ on GitHub and a mention in your project, blog, or talk is the best way to support continued development.
