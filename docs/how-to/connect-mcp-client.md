---
title: Connect YazSes to an MCP client
description: Let an AI agent transcribe files on your machine, and optionally ask you a question out loud, by connecting yazses mcp-server to Claude Desktop, Claude Code or any other MCP client.
---

# Connect YazSes to an MCP client

`yazses mcp-server` is an [MCP](https://modelcontextprotocol.io) server. An MCP client,
such as Claude Desktop, Claude Code or an editor with MCP support, starts it as a child
process and talks to it over stdin and stdout. It opens no network port, and
transcription runs on your machine.

It offers two tools:

| Tool | What it does | Offered when |
|---|---|---|
| `transcribe` | Turns an audio or video file into text on this machine. Nothing is uploaded. | always |
| `ask_human` | Lets an agent ask you a question out loud and get your spoken answer back. | `[mcp] ask_human = true` |

`ask_human` needs the YazSes daemon running (`yazses start`). An hourly budget limits how
often agents may interrupt you, and your answer goes back to the agent, never into the
window you had open. See the [CLI reference](../cli-reference.md#yazses-mcp-server) for
the details.

**Install YazSes first.** Every route below runs the `yazses` command already installed
on your machine. None of them installs YazSes for you. If you have not installed it, start
with [Get started](../get-started.md), and check that `yazses --version` works in a
terminal.

## Route 1: the one-click bundle (`.mcpb`)

An MCP Bundle is a single file a desktop client installs by double-click or drag-and-drop.
The YazSes bundle, `yazses-<version>.mcpb`, contains no copy of YazSes: it tells the
client to run `yazses mcp-server`, so your model, your settings and your microphone
permission stay with the install you already have.

1. Get the bundle. From the release that first ships it, it is attached to the
   [GitHub release](https://github.com/MSKazemi/yazses/releases) beside the other
   downloads and listed in `SHA256SUMS.txt`. Until then, build it from a checkout of the
   repository with `python3 scripts/build-mcpb.py`; it is written to `dist/`.
2. Open the file with your client: double-click it, or drag it onto the client's
   extension settings.
3. Restart the client if it asks you to, then check that the YazSes tools appear.

The bundle has not yet been tried in a real client, so if a step above does not match what
your client shows, please [open an issue](https://github.com/MSKazemi/yazses/issues).

## Route 2: add it to the client's configuration by hand

This works with any MCP client. The server entry is:

```json
{"command": "yazses", "args": ["mcp-server"]}
```

Clients that use an `mcpServers` map, such as Claude Desktop's
`claude_desktop_config.json`, take it under a name of your choice:

```json
{
  "mcpServers": {
    "yazses": {"command": "yazses", "args": ["mcp-server"]}
  }
}
```

With Claude Code, one command does the same:

```bash
claude mcp add yazses -- yazses mcp-server
```

## If the client says `yazses` was not found

A desktop app started from the Dock, the Start menu or an application launcher does not
always see the same `PATH` as your terminal. This is common on macOS when YazSes was
installed with `pipx` or `uv tool`, which put `yazses` in `~/.local/bin`.

Use the full path instead. Run `which yazses` (macOS, Linux) or `where yazses` (Windows) in
a terminal, and put the result in the `command` field of route 2, for example
`{"command": "/Users/you/.local/bin/yazses", "args": ["mcp-server"]}`. The bundle in
route 1 always uses the bare `yazses` command, so this fix needs route 2.

## Turn on `ask_human`

`ask_human` is off by default and not listed until you turn it on. Add this to your
YazSes `config.toml`, then restart the MCP client so it starts a new server:

```toml
[mcp]
ask_human = true
ask_human_per_hour = 3   # spoken questions allowed per hour, shared by every agent
```
