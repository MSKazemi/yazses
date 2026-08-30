# ADR-019 — The egress inventory: every way data can leave, and the rule for adding one

**Status:** Accepted (2026-08-15)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-011]] (zero telemetry — the promise this enforces),
[[adr-v2-126-cloud-escalation]] (the same guardrails, scoped to `yazses transcribe`),
[[adr-012-self-improvement-loop]], [[adr-018-feature-packs-and-the-plugin-question]],
the problem space, §A5

---

## Context

ADR-011 promises that nothing leaves the machine. The README says it, the docs site says
it, and it is the project's only durable advantage over better-funded alternatives.

**The promise is only as strong as a complete, true list of the exceptions, and no such
list existed.** ADR-v2-126 wrote excellent guardrails for one prospective path — cloud
escalation of `yazses transcribe` — and stopped there, because that was the question in
front of it. Meanwhile the shipped product already makes outbound connections for
entirely legitimate reasons, and they were documented one page at a time, if at all.

The prompt behind this ADR was a broader question: *could a future YazSes escalate to a
cloud for a peak feature where the compute genuinely is not available locally?* That
cannot be answered honestly without first writing down what already happens.

## The inventory

Every module in `src/yazses/` that contains an outbound network primitive
(`urllib.request`, `socket.create_connection`, an HTTP client), as of 2026-08-15:

| Module | Destination | What crosses the wire | Trigger |
|---|---|---|---|
| `commands/model_manager.py` | `huggingface.co` | ← GGUF weights | user enables an LLM feature |
| `gaze/download.py` | `storage.googleapis.com` | ← MediaPipe model (~3.7 MB) | user enables gaze |
| `recimport/download.py` | `github.com` releases | ← sherpa-onnx models (~15 MB) | user enables diarization |
| `tts/download.py` | `github.com` releases | ← Kokoro voice model | user enables read-back |
| `system/updater.py` | `pypi.org`, GitHub API | ↔ a version string | `yazses update`, or the opt-in watcher |
| `postprocess/llm_cleanup.py` | `[filters.disfluency] llm_endpoint` | **→ dictated text** | LLM cleanup enabled |
| `remote/local_proxy.py` | `127.0.0.1` (the tunnel's local end) | **→ dictated text** | `yazses remote <host>` |

Model weights are fetched by the libraries themselves rather than by any module above;
they have their own section and their own scan below.

## Reached by spawning a program, not by importing a socket

The scan above enumerates modules that import a network primitive. It cannot see
`subprocess.Popen(["ssh", ...])` — and that is how the transport which actually carries
dictated text off the machine sat outside an inventory written to enumerate exactly that.
The limitation this document recorded was *"a dependency making its own call"*; spawning a
program was not mentioned. A second scan now covers it.

| Module | Program | What crosses the wire | Trigger |
|---|---|---|---|
| `remote/forwarder.py` | `ssh` | **→ dictated text**, as the tunnel for `local_proxy` | `yazses remote <host>` |
| `gitvoice/plan.py` | `git` | ← → repository content | `yazses gitvoice … --run` |
| `system/deps.py` | `uv` / `pip` | → package names, ← **code that then runs here** | `yazses features enable <name>` |
| `system/setup.py` | `apt-get` (as root) | → package names, ← OS packages | `yazses setup` |
| `system/updater.py` | `snap` / `uv` / `pipx` / `pip` / `winget` / `choco` / `scoop` | ← a new version of YazSes | `yazses update`, or the tray's Install |

The last three were invisible for the same reason the first two once were, one level
further in: the scan listed *transports* — `ssh`, `curl`, `wget`, `git` — and no
**installers**. So the two programs that fetch code and then run it were the ones no scan
covered. `system/updater.py` already appeared under fetch for reading a version *string*;
what was undeclared is the download that follows a yes.

The scan now matches a tool name inside a list literal, which is the shape an argv has.
Matching any string constant would have declared `windowctl/focus.py` as a spawner of
`snap` — it compares a layout action against `("snap", "center")` — and a false row in a
published table costs more than a narrow rule. Every module the looser rule found is
still found.

`remote/forwarder.py` is deliberately **not** counted as a third path that can send what
you said. The remote route is one logical thing — dictation → loopback TCP → this tunnel →
the agent on the far host — and counting the two files separately would overstate the
exposure. What it does correct is the row above it: `local_proxy` connects to `127.0.0.1`
and nowhere else, and this is the half that makes that loopback reach the named host. The
table used to name the remote host as `local_proxy`'s destination, which described the
route rather than the module.

`gitvoice/plan.py` builds the argv; `cli.py` runs it only under `--run`, and only with
`--yes` when the command is destructive. It carries the user's repository at their explicit
request and never carries dictation — a distinction kept in writing because "it only runs
git" is the reasoning that would wave through a later change piping a transcript into it.

Two more modules import `socket` and **cannot reach the network at all**, because
`AF_UNIX` is a filesystem object rather than an address:

| Module | What it is |
|---|---|
| `ipc/client.py` | `AF_UNIX` stream socket to the daemon's socket path |
| `ipc/server.py` | `AF_UNIX` stream socket, bound to that path |
| `remote/agent.py` | `asyncio.start_server` bound to **127.0.0.1** — the far end of the user's own SSH tunnel |
| `platform/emg/ble_backend.py` | `asyncio` driving a Bluetooth LE sensor; a radio, not an IP network |

They are **recorded rather than excluded from the scan**, deliberately. "It's only IPC"
is exactly the reasoning that would wave through an `AF_INET` socket added to the same
file a year from now — at which point the daemon becomes reachable from another machine.
The guard asserts the address family, so that change fails the build instead of passing
review. (These two were found *by* the guard, not by the audit that preceded it.)

### The two classes, which is the useful part

**Class A — fetch.** Five of the seven only pull *in*: model weights and a version number.
No user content is transmitted. They go to fixed, hard-coded hosts, they run once, and
they are triggered by the user turning something on. (This said "six of the seven" until
2026-08-20 — the inventory table above has always had five fetches and two sends. The
count was written by hand and never recomputed, which is the same failure the enforced
inventory exists to prevent, one level up.)

**Class B — send.** **Exactly two code paths in the entire product can transmit
something the user said**, and both are already constrained:

- `llm_cleanup.py` is restricted to **loopback** by `is_loopback_endpoint()` — and
  deliberately does not trust DNS resolution, because a name that *resolves* to
  127.0.0.1 today can resolve elsewhere tomorrow, and `http://127.0.0.1@evil.com` parses
  to `evil.com`. That guard exists because this path once POSTed dictated text to any
  host the config named.
- `remote/local_proxy.py` sends to a host the user typed on the command line, over their
  own SSH tunnel. The destination is not merely consented to; it is the entire command.

**Class C — handoff.** One path hands a URL to the desktop's browser rather than opening
a connection itself, and one of its callers puts a payload in that URL: the pre-filled
issue report reaches github.com when the page opens. It carries no dictated text — the
body is `report.collect`'s redacted output — but it is a transmission, and counting it as
"not ours because the browser makes the request" is the reasoning this ADR exists to
refuse. See *Reached by handing a URL to another program* above.

**This is the sentence the project can defend:** *two code paths can send your words
anywhere, one is confined to your own machine, and the other goes only where you
explicitly told it to.*

## Reached by handing a URL to another program

The fourth mechanism, and the last one the scans could not see. We open no connection —
the desktop's browser does — but we choose the destination, the moment, and in one case
the payload.

| Module | Program | What crosses the wire | Trigger |
|---|---|---|---|
| `system/browser.py` | the default browser | a fixed docs/release URL, **or** a pre-filled issue report | a tray menu item, or the "Report this" toast button |

Every caller but one passes a constant URL. The exception is
`core/daemon.py::_open_issue_report`, which calls `report.issue_url(title, body)`: the
diagnostic report is percent-encoded into the query string, so **it reaches github.com
when the page opens, not when the user presses submit**. Pressing submit files the issue;
declining leaves no issue, not no transmission.

That is acceptable and stays acceptable for one reason: the body is `report.collect`'s
output, the same redaction `yazses report` performs — versions, daemon state, config with
paths and identifiers removed, a metadata-only log tail. No dictated text, and the
learning corpus is reported by size and never opened. The docstring on `issue_url` says
so in those terms, and `test_the_issue_url_says_when_the_report_actually_travels` fails if
it goes back to implying the content waits for the submit button.

## Reached by asking a dependency to load a model by name

The third mechanism, found the same way as the second: by asking what the existing scans
still cannot see. `WhisperModel("base.en")`, `onnx_asr.load_model(...)`,
`EncoderClassifier.from_hparams(...)` and `Pipeline.from_pretrained(...)` each take a
*repository id* and let the library resolve it against `huggingface.co`. No module in this
repository imports `requests`; the fetch happens anyway.

This document already recorded the limitation — *"a dependency making its own network
calls is not caught — `faster-whisper` fetching a model is the obvious case"* — and then
named only the obvious one. Four more were already in the tree. **A stated limitation is
not a guard**, which is the same lesson the section above it records about `ssh`, and this
is its third instance. A third scan now covers it.

The fourth, `stt/moonshine.py`, arrived later and by a different route: it was caught by
`tests/test_model_cache_first.py`, whose loader vocabulary included `MoonshineOnnxModel`,
while this inventory's did not. Two guards over the same mechanism kept separate lists of
what a loader is called, and a module fell between them -- exactly what this document
records happening once already with `download_model`. The lists are now the same length
for the same reason, and the lesson is that a vocabulary shared by two scanners has to be
shared in fact, not in intent.

| Module | Loader | What crosses the wire | Trigger |
|---|---|---|---|
| `stt/faster_whisper.py` | `WhisperModel(...)` | ← Whisper weights, **local cache tried first** | first run, or a new `[stt] model` |
| `stt/parakeet.py` | `onnx_asr.load_model(...)` | ← Parakeet weights | `[stt] engine = parakeet` |
| `stt/moonshine.py` | `MoonshineOnnxModel(...)` | ← Moonshine weights | `[stt] engine = moonshine` |
| `voiceprint/ecapa.py` | `EncoderClassifier.from_hparams(...)` | ← ECAPA weights (~20 MB) | a voiceprint is enrolled or matched |
| `recimport/pyannote_backend.py` | `Pipeline.from_pretrained(...)` | ← gated pipeline, **→ the user's HF token** | `diarization-pyannote` backend |
| `stt/download.py` | `download_model(...)` | ← Whisper weights, fetched **on purpose** with progress | `yazses model download` (issue #310) |
| `cli.py` | `download_stt_model(...)` | ← the same, from the CLI | `yazses model download` |
| `voiceprint/resemblyzer_backend.py` | `VoiceEncoder(...)` | nothing — weights ship inside the wheel | `voiceprint-resemblyzer` backend |

Two rows deserve their own sentence.

`recimport/pyannote_backend.py` is **the only fetch here that identifies who is asking.**
The pipeline is gated, so the request carries the user's Hugging Face token. Every other
row is an anonymous public `GET` that says nothing about the person making it; this one
tells a third party which account is running a diarization, on a machine whose headline
claim is that nothing leaves it. It stays Class A — the token authenticates a download and
carries no user content — but it is not interchangeable with the rows above it, and
`test_the_one_credentialed_fetch_is_singled_out` fails if a second one appears.

`voiceprint/resemblyzer_backend.py` reaches nothing at all. It is listed because the scan
cannot distinguish a bundled load from a fetch, and this inventory's standing rule is that
a false positive costs one table row while a false negative costs the promise.

`stt/faster_whisper.py` was the first row where the local cache is tried first
(`local_files_only=True`), and that is not a tidiness detail: a hub round-trip on a
blackholed network never returns. Measured on a fully cached machine, **1.9 s with
`HF_HUB_OFFLINE=1` against >180 s and still hanging without it.**

**Every model loader now does this** (2026-08-20). The other three take no such argument —
speechbrain's `from_hparams`, `onnx_asr.load_model` and pyannote's `from_pretrained` expose
no offline switch — so `system/hfcache.py` sets one a layer down, in `huggingface_hub`
itself, which all four fetch through. A cached model loads with no request at all, and a
missing one is downloaded exactly as before. `test_model_cache_first.py` holds the pairing
this inventory exists to hold: the set of modules that fetch a pretrained model must equal
the set that load cache-first, so a **fourth** loader fails the build rather than quietly
reintroducing the hang. It is also why the credentialed row above is now the request most
likely never to be made — a diarization on a machine that has already downloaded the
pipeline sends no token, because it sends nothing.

## Decision

### 1. The inventory is enforced, not documented

A test asserts that the set of modules containing an outbound network primitive equals a
declared allowlist, each entry classified fetch or send. **A new outbound call fails the
build until it is registered and classified.** Documentation decays; this cannot.

This is the same shape as `test_feature_wiring_honesty.py`, which stops the capability
registry lying about what is reachable. The privacy claim deserves at least the guard the
feature list gets.

### 2. Escalation is permitted, under ADR-v2-126's terms, extended to any feature

The answer to "could a future feature use a cloud" is **yes, and only like this** — the
guardrails ADR-v2-126 wrote for `transcribe` are hereby the rule for every feature:

- **Off by default**, and impossible without both an explicit per-invocation opt-in *and*
  a configured credential.
- **Credentials from an environment variable named by the user.** Never in `config.toml`,
  never logged.
- **A one-time consent prompt naming the destination host** and what will be uploaded.
- **Never an implicit quality fallback.** Offline is not "the default"; it is the only
  path unless the user asks otherwise, per invocation.
- **Never touches the encrypted learning corpus** (ADR-012).
- **Visible while it is happening.** Anything that escalates must be evident in the UI at
  the time — the tray already carries state colour, and an escalating burst must not look
  identical to a local one.

### 3. What may never escalate, whatever the guardrails

Three categories are excluded permanently, because consent cannot make them safe:

- **Voiceprint embeddings.** Biometric, irrevocable, and derived without the speaker
  necessarily being the consenting user — a meeting recording contains other people.
  ADR-012 already keeps them encrypted and local; this makes it a boundary, not a default.
- **The learning corpus, in whole or in part.** Its contents are precisely the material
  the user was promised stays local, and it accumulates over months. A consent prompt at
  upload time cannot be informed consent about data gathered before the prompt existed.
- **Anything captured from a third party who did not consent** — Meeting Mode audio and
  any speaker other than the operator. The operator can consent for themselves and cannot
  consent for the room.

### 4. Model downloads stay Class A, and stay honest about it

The one-time model fetch is the pragmatic exception every offline tool makes. It is
disclosed on the install-cost page, it is verifiable (`--network none` after first run),
and issue #310 — a real user behind a firewall — is why it must fail with an actionable
message rather than a traceback. **A Class A path must never be widened into a Class B
one**: adding "and while we're connected, send a little telemetry" to a model download is
exactly the erosion §A5 of the problem space warns about.

## Consequences

**Good.** The privacy claim becomes checkable rather than asserted. A future cloud feature
has a written path to acceptance instead of an argument. Anyone auditing the project can
read one table instead of grepping.

**Accepted cost.** A contributor adding a legitimate download has to register it. That is
a small tax, paid by exactly the change that should be reviewed most carefully.

**What this does not do.** It does not implement escalation, and nothing here schedules
it. ADR-v2-126 remains deferred; this ADR generalises its rules and enumerates the present
state so that the deferral is a decision rather than an absence.

**Known limitation, stated plainly.** Three scans now run: outbound *primitives* by static
import analysis, network-capable *programs* by the string names passed to `subprocess`, and
*model loaders* by the call names a dependency exposes. Each was added after the previous
set was found to have a blind spot, and the pattern is worth naming: **every one of them
enumerates a mechanism, so every one of them is blind to a mechanism nobody has thought of
yet.** The loader scan matches on call *names* — a dependency that fetches from a
differently-named entry point is not caught. That residual gap is the reason the
`--network none` Docker check exists in the docs: the tests guard our code, and the
container check guards the whole process.
