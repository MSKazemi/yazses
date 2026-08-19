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

Plus the STT engine's own first-run model fetch, which is `faster-whisper`'s, not ours.

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

They are **recorded rather than excluded from the scan**, deliberately. "It's only IPC"
is exactly the reasoning that would wave through an `AF_INET` socket added to the same
file a year from now — at which point the daemon becomes reachable from another machine.
The guard asserts the address family, so that change fails the build instead of passing
review. (These two were found *by* the guard, not by the audit that preceded it.)

### The two classes, which is the useful part

**Class A — fetch.** Six of the seven only pull *in*: model weights and a version number.
No user content is transmitted. They go to fixed, hard-coded hosts, they run once, and
they are triggered by the user turning something on.

**Class B — send.** **Exactly two code paths in the entire product can transmit
something the user said**, and both are already constrained:

- `llm_cleanup.py` is restricted to **loopback** by `is_loopback_endpoint()` — and
  deliberately does not trust DNS resolution, because a name that *resolves* to
  127.0.0.1 today can resolve elsewhere tomorrow, and `http://127.0.0.1@evil.com` parses
  to `evil.com`. That guard exists because this path once POSTed dictated text to any
  host the config named.
- `remote/local_proxy.py` sends to a host the user typed on the command line, over their
  own SSH tunnel. The destination is not merely consented to; it is the entire command.

**This is the sentence the project can defend:** *two code paths can send your words
anywhere, one is confined to your own machine, and the other goes only where you
explicitly told it to.*

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

**Known limitation, stated plainly.** The guard detects outbound *primitives* by static
import analysis. A dependency making its own network calls is not caught — `faster-whisper`
fetching a model is the obvious case. That gap is the reason the `--network none` Docker
check exists in the docs: the test guards our code, and the container check guards the
whole process.
