---
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

Two optional features use a **local** language model. There is **no cloud LLM and no
OpenAI/Azure/Anthropic backend** in either:

- **SLM intent router** (`[commands] slm_model_path`) — a small local model, loaded from
  a model file on your disk via `llama-cpp-python`, that resolves a spoken command when
  the fast regex grammar is unsure. In-process only; it opens no socket.
- **Offline dictation cleanup** (`[filters.disfluency] llm_enabled`) — lightly reformats
  dictation. **Off by default.** It has two backends: a local GGUF file via
  `llama-cpp-python` (`llm_model`), or — if no model file is set — an **HTTP POST to
  Ollama** at `llm_endpoint`, which defaults to `http://localhost:11434`.

If you do not configure a model path, neither feature is active and no model runs.

### The one call that carries text, and what stops it leaving

Dictation cleanup's Ollama backend is the **only** path in YazSes that sends *transcribed
text* over a socket. That is worth stating plainly rather than rounding down to "nothing
leaves your machine", because it is an HTTP request and `llm_endpoint` is a string you can
edit.

**YazSes refuses to send it anywhere but this machine.** Before any request is made, the
endpoint is checked to be a loopback address — `localhost`, anything in `127.0.0.0/8`, or
`::1`. Point it at a LAN box, a VPS, or a hosted API and **cleanup switches itself off and
logs why**, rather than quietly posting your dictation to it.

A hostname that merely *resolves* to `127.0.0.1` is not accepted either. DNS is not a
security boundary: the answer is controlled by whoever owns the zone and can change between
the check and the connection, so a guard that trusted resolution would depend on the network
it exists to avoid.

If sending dictated text off this machine is genuinely what you want, it takes a second,
separate, deliberate setting:

```toml
[filters.disfluency]
llm_endpoint = "http://ollama.my-lan-box:11434"
llm_allow_remote_endpoint = true    # off by default; warns on every daemon start
```

Two edits, not one, and never the default. Audio is never involved in any case — only the
already-transcribed text, and only when you have turned cleanup on.

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

Two features can change that, and both are off until you turn them on and neither ever
moves audio: `yazses remote <host>` forwards the **final text** to a host you name, and
dictation cleanup can POST **transcribed text** to an Ollama endpoint — which YazSes holds
to loopback unless you also set `llm_allow_remote_endpoint = true`. There is no third path,
and the table above is what the test suite and the `--network none` check below verify.

### Do not take our word for it — check

A privacy policy is a promise. This one is testable, and you should test it rather than
trust it. The strongest check takes one flag: transcribe with networking switched off
entirely and confirm it still works.

No Docker, or you would rather test the app you actually installed? The
[offline-inference challenge](launch/offline-challenge.md) walks through the same
demonstration on a normal desktop in about ten minutes, and there is a report template
if you want to publish what you saw. It is careful about one distinction that is easy to
blur and would make the result meaningless: **installing and downloading a model needs
the network; transcribing does not.**

```sh
# Once the model is cached, this container has no network at all.
docker run --rm --network none \
    -v yazses-models:/models \
    -v "$PWD/data/librispeech-sample:/data:ro" -v /tmp:/out \
    yazses jfk.wav -o /out/jfk-heard.txt
```

That transcribes correctly with no route to the internet, which is only possible if the
speech recognition is genuinely running on your own machine.
[Full instructions](try-without-installing.md).

On a normal install you can watch the same thing directly:

```sh
# Show every connection the daemon has open. After the model download, expect none.
ss -tunp 2>/dev/null | grep -i yazses || echo "no network connections"
```

Or cut it off at the source and keep dictating:

```sh
sudo ip link set <your-interface> down    # or just pull the Wi-Fi
```

The one time YazSes *does* need the network is the **first** run, to download the speech
model from Hugging Face. After that it never needs it again. `yazses update` is the only
other outbound action, and only when you run it yourself.

## Telemetry, analytics, and updates

YazSes collects **no telemetry, no usage analytics, and no crash reports**, and makes
no automatic outbound connections. Update checks are a manual, explicit action
(`yazses update`); YazSes does not phone home on its own.

## Third-party dependencies

YazSes builds on open-source libraries — faster-whisper, sounddevice, and (optionally)
llama-cpp-python, among others — all of which run on your device. You can audit them
through the project's dependency manifest (`pyproject.toml`).

**A machine-readable inventory ships with the project**, for anyone whose organisation
requires one before software may be installed:

- [`sbom.cdx.json`](https://github.com/MSKazemi/yazses/blob/main/sbom.cdx.json) — a
  **CycloneDX 1.5** SBOM listing every resolved dependency with its version, package URL
  and, where the lock file records one, the SHA-256 of its source distribution.

It is generated from `uv.lock` rather than from whatever happens to be installed on a
build machine, so it describes what *you* will actually resolve to, and a test fails if
it drifts out of step with the lock file. Regenerate it yourself with
`python scripts/gen-sbom.py`.

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
