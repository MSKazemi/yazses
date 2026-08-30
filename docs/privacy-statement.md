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
required). The model weights are downloaded once into the shared Hugging Face cache —
`~/.cache/huggingface/hub/` on Linux and macOS, `%LOCALAPPDATA%\huggingface\hub\` on
Windows — and run offline thereafter. That cache is shared with any other Hugging Face
tool you have, which is why it survives uninstalling YazSes and has
[its own step](uninstall.md#4-remove-the-speech-models) on the uninstall page. The resulting transcript is held in memory
only long enough to inject the text (and, if commands are enabled, to check whether
you spoke a command). At the default log level it is not written to any file, and it
is never transmitted anywhere.

The diagnostic log (`yazses logs`) records **metadata only** — timing and state,
never your dictated text — at the default `[general] log_level = "INFO"`.

!!! warning "`log_level = "DEBUG"` is the one exception"
    Setting `[general] log_level = "DEBUG"` in `config.toml` also writes each transcript
    into `daemon.log`, which is what makes a hard-to-reproduce dictation bug diagnosable.
    Nothing is uploaded either way — but that file then holds what you dictated, so treat
    it as you would the text itself. `yazses report` knows this and **omits every DEBUG
    line** from the bundle it builds for a bug report, stating how many it dropped. The
    same bundle also reports the daemon's **staged buffer** — text you have dictated but
    not yet committed — by length rather than content, for the same reason. To
    clear it: set the level back to `"INFO"` and delete the file at
    `yazses logs --path`.

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
| Scrub patterns from stored text | `redact_patterns` under `[learning]` |
| Inspect what is stored | `yazses corpus status` |
| Erase everything | `yazses corpus destroy` (or delete `corpus.db`) |

`redact_patterns` are regular expressions removed from every transcript column before it is
encrypted — but a redaction cannot reach into a waveform. With `capture_audio` on (the
default), the clip still holds you *saying* the thing the pattern removes. If that matters,
set `capture_audio = false`; `yazses doctor` warns when patterns are set and the audio is
being kept anyway. An invalid pattern stops capture entirely rather than being skipped, so
a redaction you asked for is never silently dropped.

`retention_days` and `max_corpus_mb` are applied in sweeps — when the daemon starts, and
then every 200 captures — rather than on every write. So an event older than
`retention_days` can still be on disk until the next sweep, and `yazses corpus status` can
report a size above `max_corpus_mb`. Both are limits the corpus is pulled back to, not
ceilings it is prevented from crossing. If you need something gone *now*, use
`yazses corpus forget -m N` or `yazses corpus destroy`, which act immediately.

A sweep will not empty the corpus to satisfy the size limit: it trims the oldest events
as far as reclaiming disk actually helps and then stops, leaving the rest in place.

Deleting an event — by `forget`, by retention, or by the size sweep — zeroes its stored
bytes rather than only unlinking the row, so the transcript is not left readable in a
freed page of `corpus.db`. That matters because the key is deliberately *not* kept
elsewhere: `corpus.key` is machine-bound and sits beside the database, so anything left
in the file is readable by anyone who has the machine. `forget` additionally compacts
the database, which clears residue left by earlier versions.

What that does not cover is the filesystem underneath: the blocks of an unlinked audio
clip, or of a deleted journal, may survive on the disk until they are overwritten. If
that matters for your threat model, full-disk encryption is the control for it.

Spoken Recall (*"what did I say about X"*) queries this same encrypted corpus. Ambient
Scratch does **not**: a spoken note-to-self is appended to `scratch.jsonl` as plain
JSON, because a note you dictated in order to read it back later is a note, not a
capture. Neither leaves the machine, and both are off by default.

## Meeting Mode (opt-in, off by default)

`yazses meeting` records a whole meeting rather than a hold-to-talk burst, so it captures
**other people's voices as well as your own**. It is disabled by default and does nothing
until you set `[meeting] enabled = true` and start a meeting explicitly.

Everything it produces stays in `meetings/<id>/` under your data directory, in plain text:
the transcript, the live rolling transcript kept for crash recovery, and — if you turned
notes on — the generated minutes. The recording itself is deleted after the post-pass
unless you set `[meeting] retain_audio = true`; it is kept until then so that a crash
during transcription cannot lose the meeting. Nothing is uploaded, and transcription and
minutes both run on-device.

Naming speakers is separate and explicit. Diarization alone labels people *Speaker 1*,
*Speaker 2*; a name appears only if you pass one, or if you have deliberately enrolled that
person with `yazses meeting enroll`. An enrolled participant is stored as an encrypted
voiceprint under `participants/` and never auto-created from a recording. Recording other
people may need their consent where you are — YazSes does not and cannot judge that for you.

## What is written to your data directory

Most of what YazSes persists lives in one directory — `~/.local/share/yazses/` on Linux,
`~/Library/Application Support/yazses/` on macOS, `%LOCALAPPDATA%\yazses\` on Windows — and
nothing in it is uploaded anywhere.

**Most, not all**, and the difference matters if you are deleting things: YazSes follows
the platform's directory conventions, so on Linux and macOS it writes under **four** roots,
not one. The other three are listed [below](#the-other-directories); the
[uninstall page](uninstall.md#3-remove-your-data) removes all of them.

| Path | Holds | Encrypted |
|---|---|---|
| `corpus.db` | the learning corpus: metadata in the clear, every transcript column encrypted | transcripts yes |
| `clips/` | source audio for corpus events, when `capture_audio` is on | yes |
| `corpus.key` | the machine-bound key for both of the above, mode `0600` | n/a — it *is* the key |
| `scratch.jsonl` | spoken notes-to-self (Ambient Scratch, off by default) | **no — plain JSON** |
| `few_shots.toml` | utterances you approved in `yazses tune` as command-router examples | **no — plain text** |
| `meetings/` | meeting transcripts, live transcripts, minutes, and retained recordings | **no — plain text** |
| `participants/` | voiceprints of people you enrolled by name for meetings | yes |
| `voiceprint.enc` | your own enrolled voiceprint | yes |
| `diarization/`, `tts/` | downloaded model files — no content of yours | n/a |
| `daemon.lock`, `tray.lock`, `tray-stderr.log` | single-instance locks and the tray's stderr | n/a |
| `yazses-report.json` | the last `yazses report` bundle you generated, already redacted | n/a |

The three marked **no** are the ones worth knowing about, and each is deliberate: a note you
dictated in order to read it back, examples you explicitly approved, and a meeting
transcript whose whole purpose is to be opened and edited. They are ordinary files with
your user's permissions. If you want them at rest under a key, that is what full-disk
encryption is for.

## The other directories

| What | Linux | macOS | Holds |
|---|---|---|---|
| Settings | `~/.config/yazses/` | `~/Library/Application Support/yazses/` | `config.toml`, `vocabulary.txt` |
| Model cache | `~/.cache/yazses/` | `~/Library/Caches/yazses/` | downloaded model files — the gaze landmarker, and any GGUF the optional intent router uses (up to 2.2 GB) |
| Diagnostic log | `~/.local/state/yazses/log/` | `~/Library/Logs/yazses/` | `daemon.log` and its rotations |

On Windows all four are nested inside `%LOCALAPPDATA%\yazses\`, so there is only one
folder to think about.

Two of these are worth a second look. The **model cache** holds no content of yours, but
it is the largest thing YazSes leaves behind and it is not where people look. The
**diagnostic log** holds metadata only at the default log level — but `log_level =
"DEBUG"` puts every transcript in it, as the warning above says, and it does not live in
the data directory that the rest of this page is about.

YazSes reads `vscode-context.json` from the model-cache directory if it is there, to
pick up your editor cursor position. Nothing in YazSes writes it, and the companion VS
Code extension that was designed to write it has never been published — so in practice
the file is absent. Removing the cache directory removes it.

## Configuration file

YazSes reads a TOML configuration file at startup:

| Platform | Path |
|---|---|
| Linux | `~/.config/yazses/config.toml` |
| macOS | `~/Library/Application Support/yazses/config.toml` |
| Windows | `%LOCALAPPDATA%\yazses\config.toml` |

It holds your preferences (hotkey, microphone device, model selection, optional EMG
port, feature toggles, and so on). It is read locally and never transmitted anywhere.

## IPC (inter-process communication)

The daemon communicates with the CLI and tray through a **local, host-only** channel:
a Unix domain socket on Linux/macOS, a named pipe on Windows. YazSes does not open a
network port or listen on any external interface for this.

## Editor context (optional)

**Correction (2026-08-17):** this section previously described the daemon reading
your active file path, language and cursor line into every transcription prompt,
controlled by `lsp_enabled`. **That never happened.** The daemon does not construct
the editor bridge, and `lsp_enabled` is read by nothing — so no editor context has
ever reached the transcription prompt. The statement overstated what YazSes
collects, and the mitigation it offered protected against nothing.

What is true: the editor bridge is contacted **only when you run a command that
needs it** — `yazses jump` — which asks your editor for symbols and cursor position
to move the caret, on demand, for that one invocation. Nothing is stored, and
nothing leaves your device.

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
    -v yazses-models:/home/yazses/.cache \
    -v "$PWD/data/librispeech-sample:/data:ro" -v /tmp:/out \
    yazses transcribe jfk.wav -o /out/jfk-heard.txt
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

The one time YazSes needs the network in its **default** configuration is the **first**
run, to download the speech model from Hugging Face. After that, dictation never needs it
again.

That default is most of the product but it is not all of it, and the distinction is worth
stating exactly rather than rounding off. **Every optional feature that runs a model of its
own downloads that model once, when you enable it** — a different speech engine, speaker
diarization, read-back, gaze targeting, offline LLM cleanup. Each of those features is off
until you turn it on; each fetch is a one-time download of weights; and **none of them
sends anything** — not audio, not a transcript, not an identifier.

One deserves naming on its own. The optional `pyannote` diarization backend uses a *gated*
model, so that download carries your Hugging Face token — the host requires it to check you
accepted the licence. It is still a download and it still carries nothing you said, but it
is the only fetch in the product that tells anyone **who** is asking, which is not the same
disclosure as an anonymous one.

`yazses update` is the only other outbound action, and only when you run it yourself —
unless you set `[general] update_check = true`, which is off by default and, when on,
fetches a version string in the background and nothing else.

All of it is enumerated — module, destination, direction and trigger — in the project's
[egress inventory](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-019-egress-inventory-and-escalation.md), and a test fails the build when any module gains a
connection that is not on that list.

## Telemetry, analytics, and updates

YazSes collects **no telemetry, no usage analytics, and no crash reports**, and makes no
automatic outbound connections in its default configuration. Update checks are a manual,
explicit action (`yazses update`); YazSes does not phone home on its own. The one thing
that can become automatic is the release watcher, `[general] update_check`, which is off by
default and which — when you switch it on — reads a version string and announces a new
release once. It carries nothing about you or your machine, and a firewall makes it a
silent no-op rather than a delay.

**"Prepare a bug report" is not an exception to this**, and it is worth being exact
about why. When YazSes cannot identify a failure, its notification offers a button. That
button assembles the same redacted bundle `yazses report` writes and **opens your
browser** at GitHub's issue form with the text already filled in. You read it there,
signed in as yourself, and press submit — or close the tab. YazSes never makes the
request; your browser does, if you decide to. Nothing is transmitted by YazSes at any
point, and the project's [egress inventory](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-019-egress-inventory-and-escalation.md)
— which a test enforces on every build — is unchanged by this feature.

## Third-party dependencies

YazSes builds on open-source libraries — faster-whisper, sounddevice, and (optionally)
llama-cpp-python, among others — all of which run on your device. You can audit them
through the project's dependency manifest (`pyproject.toml`).

**A machine-readable inventory ships with the project**, for anyone whose organisation
requires one before software may be installed:

- [`sbom.cdx.json`](https://github.com/MSKazemi/yazses/blob/main/sbom.cdx.json) — a
  **CycloneDX 1.5** SBOM listing every resolved dependency with its version, package URL
  and, where the lock file records one, the SHA-256 of its source distribution.

Every component carries a CycloneDX `scope`, so the inventory distinguishes what you
receive from what only the maintainer builds with:

| `scope` | Count | What it means for you |
|---|---|---|
| `required` | 57 | Installed by `pip install yazses`, across every supported platform |
| `optional` | 177 | Installed only if you enable the matching feature (`yazses features enable …`) |
| `excluded` | 52 | Test, type-check, benchmark and docs tooling. Never installed by a user |

That distinction matters if you feed the SBOM to a vulnerability scanner: without it,
every advisory against a test or documentation package would be reported against your
installation, and there would be no way to tell which findings apply to you.

It is generated from `uv.lock` rather than from whatever happens to be installed on a
build machine, so it describes what *you* will actually resolve to, and a test fails if
it drifts out of step with the lock file. Regenerate it yourself with
`python scripts/gen-sbom.py`.

## Your rights and controls

| Action | How |
|---|---|
| Disable the learning corpus | Leave `[learning]` off (default), or `yazses features disable learning` |
| Erase all captured data | `yazses corpus destroy` (or delete `corpus.db`) |
| Disable editor context | Nothing to disable — the daemon never reads your editor; only `yazses jump` contacts it, when you run it |
| Disable the offline cleanup LLM | Set `llm_enabled = false` under `[filters.disfluency]` (the default) |
| Inspect stored data | `yazses corpus status` |

Because all data is stored locally and no account is required, there is no
server-side data to request deletion of. You have full control over every file
YazSes writes.

## Contact

YazSes is an open-source project. If you find a privacy concern or a discrepancy
between this statement and the software's actual behaviour, please open an issue on
the project's GitHub repository so it can be investigated and corrected.
