---
layout: default
title: Privacy Statement
description: What YazSes does and does not do with your voice, text, and data. Offline by design — nothing leaves your machine unless you explicitly turn on the SSH remote path.
---

# YazSes Privacy Statement

**Last updated: 2026-07-10**

YazSes is designed from the ground up to keep your voice and text on your device.
**By default, no audio, transcripts, editor context, or usage data ever leave your
machine.** There is no cloud dependency, no telemetry, and no account. Everything
below describes local behaviour; the only outbound path is the SSH remote feature
you turn on yourself, and even then only the final typed text is sent.

## Audio

Audio is captured from your microphone **only while you hold the hold-to-talk key**
(or squeeze a connected EMG device). It is held in a short in-memory buffer, fed
directly to the on-device transcription model, and then discarded. Because YazSes is
push-to-talk, nothing is recorded while the key is up. Audio is never written to disk,
never logged, and never transmitted anywhere — unless you explicitly opt in to the
learning corpus (below) with audio capture enabled.

## Transcription (speech-to-text)

Transcription runs entirely on your device using
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) (CPU, int8; no GPU
required). The model weights are downloaded once to `~/.local/share/yazses/`
(Linux), `~/Library/Application Support/yazses/` (macOS), or `%APPDATA%\yazses\`
(Windows) and run offline thereafter. The resulting transcript is held in memory
only long enough to inject the text (and, if commands are enabled, to check whether
you spoke a command). It is not written to any log file and is not transmitted
anywhere.

The diagnostic log (`yazses logs`) records **metadata only** — timing and state,
never your dictated text.

## The learning corpus (opt-in, off by default)

YazSes can improve its accuracy for your voice over time, but only if you opt in.
The `[learning]` feature is **disabled by default**; when it is off, nothing is
captured.

When you enable it (`yazses features enable learning`), the daemon records one event
per hold-release into a **machine-bound, encrypted local corpus** at
`~/.local/share/yazses/corpus.db` (with audio clips under `clips/`). The transcript
text and any stored audio are encrypted with **AES-256-GCM** using a key derived from
your machine — there is no passphrase to remember and no cloud backup. Only coarse
metadata is kept in the clear. Capture happens on a background thread and nothing is
ever uploaded.

You stay in control of the corpus:

| Action | How |
|---|---|
| Never capture anything | Leave `[learning]` disabled (the default) |
| Turn capture off again | `yazses features disable learning` |
| Store text but not audio | Set `capture_audio = false` under `[learning]` |
| Auto-expire old events | `retention_days` / `max_corpus_mb` under `[learning]` |
| Inspect what is stored | `yazses corpus status` |
| Erase everything | `yazses corpus destroy` (or delete `corpus.db`) |

The `recall` and `scratch` note features read from this same local corpus and never
leave the machine.

## Configuration file

YazSes reads a TOML configuration file at startup:

| Platform | Path |
|---|---|
| Linux | `~/.config/yazses/config.toml` |
| macOS | `~/Library/Application Support/yazses/config.toml` |
| Windows | `%APPDATA%\yazses\config.toml` |

It holds your preferences (hotkey, microphone device, model selection, optional EMG
port, feature toggles, and so on). It is read locally and never transmitted anywhere.

## IPC (inter-process communication)

The daemon communicates with the CLI and tray through a **local, host-only** channel:
a Unix domain socket on Linux/macOS, a named pipe on Windows. YazSes does not open a
network port or listen on any external interface for this.

## Editor context (optional)

When the LSP editor-context feature is enabled (`lsp_enabled = true` under
`[commands]`; **off by default**), YazSes reads the active file path, language, and
cursor line from your editor and uses them only as a prefix to the transcription
prompt, so code identifiers from your current file are recognised. This context is
never transmitted outside your device and is discarded after each transcription.

## On-device language models (optional)

Two optional features use a **local** language model, loaded from a model file on
your disk via `llama-cpp-python`. Both run entirely on-device — there is **no cloud
LLM, no OpenAI/Azure backend, and no HTTP API call**:

- **SLM intent router** (`[commands] slm_model_path`) — a small local model that
  resolves a spoken command when the fast regex grammar is unsure.
- **Offline dictation cleanup** (`[filters.disfluency] llm_enabled`) — a local model
  that lightly reformats dictation. Off by default.

If you do not configure a model path, neither feature is active and no model runs.

## Remote mode (`yazses remote <host>`)

Remote mode lets you dictate into an application on another machine you control.
**Your speech is still captured and transcribed locally** — only the **final typed
text** is forwarded over an SSH tunnel to the remote host, where `yazses-agent`
injects it. Your audio never leaves your machine. The target host is always specified
by you on the command line; YazSes never connects anywhere automatically. Ensure you
trust and control the remote host before using this feature.

## What leaves your device

| Data | Default (local-only) | Remote mode (`yazses remote`) |
|---|---|---|
| Audio | Stays on device | Stays on device (never forwarded) |
| Transcript / typed text | Stays on device | Final text forwarded over SSH to your host |
| Editor context | Stays on device | Not forwarded |
| Learning corpus | Stays on device | Not forwarded |
| Telemetry / usage stats | Never collected | Never collected |

In the default configuration, **nothing leaves your device**.

## Telemetry, analytics, and updates

YazSes collects **no telemetry, no usage analytics, and no crash reports**, and makes
no automatic outbound connections. Update checks are a manual, explicit action
(`yazses update`); YazSes does not phone home on its own.

## Third-party dependencies

YazSes builds on open-source libraries — faster-whisper, sounddevice, and (optionally)
llama-cpp-python, among others — all of which run on your device. You can audit them
through the project's dependency manifest (`pyproject.toml`).

## Your rights and controls

| Action | How |
|---|---|
| Disable the learning corpus | Leave `[learning]` off (default), or `yazses features disable learning` |
| Erase all captured data | `yazses corpus destroy` (or delete `corpus.db`) |
| Disable editor context | Set `lsp_enabled = false` under `[commands]` (the default) |
| Disable the offline cleanup LLM | Set `llm_enabled = false` under `[filters.disfluency]` (the default) |
| Inspect stored data | `yazses corpus status` |

Because all data is stored locally and no account is required, there is no
server-side data to request deletion of. You have full control over every file
YazSes writes.

## Contact

YazSes is an open-source project. If you find a privacy concern or a discrepancy
between this statement and the software's actual behaviour, please open an issue on
the project's GitHub repository so it can be investigated and corrected.
