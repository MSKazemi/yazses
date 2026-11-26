---
title: MCP client compatibility
description: Which MCP protocol revision each major client asks for, whether it still sends initialize, and what that means for yazses mcp-server under MCP 2026-07-28. Dated rows, mostly from docs and source.
---

# MCP client compatibility

`yazses mcp-server` speaks MCP revision **2025-06-18** and also accepts 2025-03-26 and
2024-11-05 (`SUPPORTED_PROTOCOL_VERSIONS` in `src/yazses/mcp/protocol.py`). It is a
*legacy* server in the terms of the 2026-07-28 revision: it expects an `initialize`
handshake. This page records which clients still open that way, so that a migration is
planned from evidence rather than guesswork.

**Every row has a date and a source. Clients change with each release, so a row is true
on its date and not necessarily after it.** Only the Claude Code row was observed by
running the client; the others come from documentation or source code, and none of them
has been run against YazSes.

## The matrix

Recorded 2026-11-20.

| Client | Version checked | Asks for | Sends `initialize`? | Probes `server/discover` first? | Result with YazSes | Evidence |
|---|---|---|---|---|---|---|
| Claude Code | 2.1.329 | 2026-07-28 probe, then `initialize` at 2025-11-25 | Yes, after the probe fails | Yes | Works: YazSes answers 2025-06-18 and `tools/list` succeeds | **Observed** (see below) |
| Claude Desktop | not determined | not determined | not determined | not determined | Unknown | **Unverified**: closed source; the [release notes](https://support.claude.com/en/articles/12138966-release-notes) (latest entry 2026-11-17) state no revision |
| OpenAI Codex CLI | rust-v0.170.0 (2026-11-18) | 2025-06-18 | Yes | No (default). Yes, only with the `mcp_2026_07_28` feature on *and* the server opted in | Expected to work: 2025-06-18 is echoed | From source, not run: [`protocol_mode.rs`](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/rmcp-client/src/protocol_mode.rs), [`features/src/lib.rs`](https://github.com/openai/codex/blob/rust-v0.170.0/codex-rs/features/src/lib.rs) |
| Cursor | 3.21.16 (reported in the forum thread) | 2025-11-25 | Yes | No | Expected to work: YazSes answers 2025-06-18, which Cursor lists as supported | From docs, not run: [forum reply, 2026-09-21](https://forum.cursor.com/t/mcp-client-cannot-connect-to-modern-only-2026-07-28-streamable-http-servers-legacy-initialize-rejected/172536) (an account that writes "our client"; not confirmed as staff). The [changelog](https://cursor.com/changelog) (latest entry 2026-11-06) names no revision |
| VS Code (Copilot agent mode) | 1.147.0 (2026-11-18), and `main` `1dedb183` | 2025-11-25 | Yes | No | Expected to work: no check of the answered version found in the client | From source, not run: [`mcpServerRequestHandler.ts`](https://github.com/microsoft/vscode/blob/1.147.0/src/vs/workbench/contrib/mcp/common/mcpServerRequestHandler.ts), [`modelContextProtocol.ts`](https://github.com/microsoft/vscode/blob/1.147.0/src/vs/platform/mcp/common/modelContextProtocol.ts) |
| Gemini CLI | v0.70.0 (2026-11-19), and `main` `d4cb1713` | 2025-11-25 (via `@modelcontextprotocol/sdk` 1.32.2) | Yes | No | Expected to work: the SDK accepts 2025-06-18 | From source, not run: [`packages/core/package.json`](https://github.com/google-gemini/gemini-cli/blob/v0.70.0/packages/core/package.json), [SDK `client/index.ts` at 1.32.2](https://github.com/modelcontextprotocol/typescript-sdk/blob/1.32.2/src/client/index.ts) |

"Asks for" is the `protocolVersion` the client puts in `initialize`, or in `_meta` for the
probe. `tools/call` was not exercised for any client. `ask_human` was not tested from any
client.

### How the Claude Code row was observed

On 2026-11-20, Claude Code 2.1.329 was run once with
`claude -p --strict-mcp-config --mcp-config <file in a temp directory>`, so the user's own
MCP configuration was neither read nor changed. The temporary configuration started a
throwaway script that ran YazSes's real `protocol.handle` on stdio and logged both
directions. The frames, in order:

1. `server/discover` with `_meta["io.modelcontextprotocol/protocolVersion"] = "2026-07-28"`.
   YazSes answered `-32601` (unknown method).
2. `initialize` with `protocolVersion: "2025-11-25"`. YazSes answered `2025-06-18`.
3. `notifications/initialized`.
4. `tools/list`, answered with the `transcribe` tool.

Claude Code accepted the downgrade and listed the tool.

## What 2026-07-28 changed for a stdio server

From the [2026-07-28 changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog),
the [versioning page](https://modelcontextprotocol.io/specification/2026-07-28/basic/lifecycle)
and the [stdio transport page](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio),
read 2026-11-20:

- **No handshake.** `initialize` and `notifications/initialized` are removed. Every request
  carries its revision and the client's capabilities in `_meta`
  (`io.modelcontextprotocol/protocolVersion`, `io.modelcontextprotocol/clientCapabilities`,
  and optionally `io.modelcontextprotocol/clientInfo`).
- **Version negotiation per request.** A server that does not implement the requested
  revision answers `UnsupportedProtocolVersionError`, code `-32022`, with
  `data.supported` and `data.requested`. Codes `-32020` to `-32099` are reserved for the
  specification.
- **`server/discover`.** Servers MUST implement it. On stdio, a client that also speaks
  older revisions SHOULD send it first. A `DiscoverResult` or a recognised modern error
  means a modern server. Any other error, or no answer, means a legacy server, and the
  client falls back to `initialize`. The fallback must not depend on one error code.
- **No sessions.** List results no longer vary per connection.
- **No server-initiated requests.** A server writes no requests to stdout. Roots, sampling
  and elicitation requests are replaced by Multi Round-Trip Requests: a result with
  `resultType: "input_required"` and the client retrying with `inputResponses`.
- **New required result fields.** Every result carries `resultType`; clients treat a
  result without it, from an older server, as `"complete"`. `tools/list` results carry
  `ttlMs` and `cacheScope`.
- **Removed:** `ping`, `logging/setLevel`, `notifications/roots/list_changed`.
- **Deprecated, still working for at least twelve months:** Roots, Sampling and Logging.
  The suggested replacement for Logging on stdio is writing to stderr, which YazSes already
  does.

There is also a revision between ours and 2026-07-28: **2025-11-25**, which four of the
six clients ask for. YazSes does not list it and answers those clients with 2025-06-18,
which the spec allows and which they accept.

## What this means for YazSes today

- **Every client in the matrix still sends `initialize`.** Claude Code probes first, gets
  an ordinary "method not found" error, and falls back, as the spec describes. So **no
  migration is needed yet**, and `2026-07-28` is not added to `SUPPORTED_PROTOCOL_VERSIONS`:
  that would claim support the server does not have.
- A client that asks `initialize` for 2026-07-28 or any other revision YazSes does not
  list is answered with 2025-06-18, not an error.
- YazSes keeps no session, so a client that skips `initialize` and sends `tools/list`
  still gets the tool list. That is a side effect, not 2026-07-28 support: the reply has
  no `resultType` or `ttlMs`.
- A **modern-only** client that probes `server/discover` would fail against YazSes,
  because it has no legacy fallback. None of the six is one today. When one appears, the
  server needs a dual-era code path: answer `server/discover`, serve requests that carry
  `_meta` statelessly, and keep `initialize` for older clients. That change needs a
  Proposed ADR under ADR-032 and its own pull request.

## Replay fixtures

The opening frames for each client are kept under `tests/fixtures/mcp/`, one JSON file per
client, each with the date, the evidence class (`observed`, `source`, `docs` or
`unverified`) and the link it came from. `tests/test_mcp_protocol.py` replays them through
`protocol.handle` and checks that each client reaches `tools/list` with a version it
accepts. The fixtures are synthetic: no user audio, transcript or path. Only the Claude
Code frames are verbatim; the others reproduce the method and protocol version from the
source, and the remaining fields are illustrative. The Claude Desktop fixture is an
assumption until someone records the real frames.

One test fails when a fixture opens without `initialize`. That failure is the signal to
write the migration ADR, not a fixture to delete.

## Updating this page

Re-check a row when a client's release notes mention MCP, and at least once per MCP
revision. To observe a client yourself, point it at a throwaway logging stdio script with
a configuration file in a temporary directory, never your real client configuration, and
record the frames into the client's fixture with the date and the client version.

See also: [Connect YazSes to an MCP client](how-to/connect-mcp-client.md).
