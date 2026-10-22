# ADR-032 — Make the MCP server discoverable, and let `ask_human` stop when the user does

**Status:** Proposed (2026-10-22)
**Deciders:** Mohsen Seyedkazemi Ardebili
**Context links:** [[adr-030-agent-era-direction]] (Pillar 2, bridge 2),
[[adr-020-agent-protocols]] (§1 an MCP server, stdio only, two tools; §2 no HTTP; §4 the
interrupt budget), [[adr-019-egress-inventory-and-escalation]],
[[adr-v2-029-semantic-autostop]] (the pure auto-stop decision this reuses).

Evidence labels: **[M]** measured in this repository on `origin/main` `f821884e` ·
**[F]** a primary source says so (accessed 2026-10-22) · **[S]** a secondary source ·
**[O]** engineering judgement · **[U]** not verified.

---

## Context

ADR-020 decided that YazSes exposes exactly two tools over MCP, on stdio only:
`transcribe` (a file the caller already has → text) and `ask_human` (an agent asks the
user a question out loud and gets the spoken answer back, under an interrupt budget).
`yazses mcp-server` has shipped since v2.22.0 [M]. Three things keep it from being used:

1. **Nobody can find it.** Connecting it means hand-writing
   `{"command": "yazses", "args": ["mcp-server"]}` into a client's config. The two places
   an MCP user looks — a one-click bundle for their desktop client, and the MCP registry —
   have no YazSes entry [M].
2. **`ask_human` listens for a fixed time.** `Daemon._ask_human_listener` starts the
   recorder, `time.sleep`s for the whole timeout (at least one second, up to the caller's
   wait, capped at 120 s), then transcribes [M] (`core/daemon.py`). A two-word answer
   holds the microphone — and blocks dictation — for the full wait.
3. **The help text is stale.** `yazses mcp-server --help` says `ask_human` "is not offered
   yet", while `mcp/server.py::build_tools` offers it whenever `[mcp] ask_human` is on [M].

## Decision

### 1. A one-click bundle (`.mcpb`) that points at the installed YazSes

An MCP Bundle is a zip with a `manifest.json` describing a local MCP server; desktop
clients install it by double-click or drag-and-drop [F]
([Desktop Extensions](https://www.anthropic.com/engineering/desktop-extensions),
[modelcontextprotocol/mcpb](https://github.com/modelcontextprotocol/mcpb)).

The YazSes bundle **contains no YazSes**. Its manifest runs the `yazses` command already
installed on the machine with `mcp-server`. The speech model, the daemon and the
microphone permission belong to that install; a second copy inside a client's extension
directory would double the disk cost, miss the user's config, and be updated by nobody.
If `yazses` is not found, the bundle fails with the install URL.

The manifest fields and the server type for a command-only bundle are checked against the
spec's `MANIFEST.md` at implementation time [U]; third-party pages disagree on the current
manifest version.

The bundle is built in CI from a template, attached to each GitHub release beside the
other assets, and covered by the release checksum file.

### 2. An entry in the MCP registry

The registry at `registry.modelcontextprotocol.io` stores metadata only, one `server.json`
per server, pointing at a package on a public registry — here PyPI's `yazses`, transport
stdio, arguments `["mcp-server"]` [S]. Ownership of a PyPI package is proven by a marker in
the package README, and publishing is done with the registry's `mcp-publisher` [S]. Both
are checked against the registry's own publishing guide at implementation time.

Publishing to the registry is an outward-facing release step. It joins the release
workflow only after the owner approves it, under `.github/CI_POLICY.md`.

### 3. `ask_human` stops listening when the user stops speaking

The listener records until **speech has started and then a trailing silence** of
`[mcp] ask_human_end_silence_s` (default 1.2 s) has passed, or until the caller's timeout,
whichever comes first. No speech at all within the first `ask_human_no_speech_s` (default
8 s) ends the wait with an empty answer, which the caller already treats as "no answer".

The decision is a pure function of a stream of speech/no-speech frames and the clock, in
the house pattern: it reuses the energy/VAD gate the dictation path already runs and the
timeout/cap logic of ADR-v2-029's `endpoint/autostop.py`, and it is tested without a
microphone. All five ADR-020 restraints are unchanged: off by default, the budget, never
during a hold, the caller named, the answer returned to the caller and never injected.

### 4. The help text says what is true

`mcp-server --help` names both tools and says `ask_human` appears only when
`[mcp] ask_human = true`. A test pins the help text against `build_tools`, so the two
cannot drift again.

### 5. What does not change

stdio only; no HTTP, no port, no remote MCP (ADR-020 §2). Two tools, no more. No ADR-019
row: a bundle and a registry entry change how a client *finds* the server, not what the
server sends.

## Consequences

- An MCP user can connect YazSes from a client's extension screen or a registry search, and
  a docs page shows both routes plus the manual JSON.
- `ask_human` answers in about the time the user takes to speak plus the end silence,
  instead of the caller's full wait.
- One template, one CI step, one registry file, one pure endpoint policy, two config keys
  (both with dormant-safe defaults), one help-text test.

## Alternatives considered

- **A bundle that ships its own YazSes.** Rejected (§1): a second install with no model, no
  permission and no updater.
- **An HTTP or "streamable HTTP" transport so remote clients can connect.** Rejected by
  ADR-020 §2 and not reopened: a daemon that holds a live microphone does not listen on a
  port.
- **Keep the fixed listen window and lower its default.** Rejected: any fixed window is
  either too short for a sentence or too long for a "yes".
