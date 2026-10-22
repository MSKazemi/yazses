---
title: Offline voice input for Claude Code, Codex and other AI agents
description: Dictate long prompts into AI coding agents and chat apps by voice, fully offline. Hold-to-talk never cuts you off mid-thought, staged mode lets you review a prompt before it is typed, and nothing you say leaves your computer.
---

# Voice input for AI coding agents

**Short answer:** hold a key, speak your prompt, let go. YazSes types it into whatever has
focus: a terminal running Claude Code, Codex or Aider, a chat box in a desktop app, or a
browser tab. Speech recognition runs on your own CPU, so the prompt reaches the AI tool
the same way typed text does, and no transcription service ever hears it.

Linux is the best-supported platform. On macOS and Windows YazSes is a
[preview](../validation-matrix.md).

## Why agent prompts are hard for ordinary dictation

A good prompt for a coding agent is long, and you think while you say it. Two common
designs get that wrong:

- **Voice modes that stop on silence** treat your pause for thought as the end of the
  prompt and cut it off. YazSes uses **hold-to-talk**: it listens for as long as you hold
  the key, pauses included, and stops only when you let go.
- **Cloud dictation** sends your audio to a server before the text reaches the agent. That
  audio can contain code, customer names and unreleased plans. YazSes transcribes
  [entirely offline](private-offline-dictation.md).

## The basic flow

```sh
yazses start
```

1. Focus the agent's input: the terminal where `claude` or `codex` is running, or a chat
   box.
2. Hold your hotkey (**Right Alt** on Linux by default), speak the prompt, and release.
3. Read the text, fix anything that is wrong, and press Enter yourself.

This needs no setup on the agent's side, and it works over SSH: if the agent runs on a
remote machine in your local terminal, the keystrokes travel down your SSH session like
typed ones. See [over SSH and in Remote-SSH editors](../how-to/ssh-and-remote.md).

## Review before it types: staged dictation

A terminal agent acts on Enter, and one misheard word can change an instruction. Staged
dictation holds what you say in a buffer instead of typing it:

```sh
yazses features enable staged
yazses restart
```

Dictate one burst or several, then:

```sh
yazses staged status    # what is waiting
yazses staged commit    # type it into the focused window
yazses staged undo      # drop the last burst
```

Bind `yazses staged commit` to a key if you use it often. Saying "commit that" can be
turned on with `[staged] spoken_commit`. It is off by default because, when recognition
goes wrong, the commit phrase is exactly what can be misheard.

## Technical vocabulary

Agents need the names in your codebase spelled correctly. Add the project's identifiers,
library names and acronyms to your [personal vocabulary](../how-to/personal-vocabulary.md).
For symbols and code itself, see [coding by voice](voice-coding.md).

## Let an agent use YazSes: the MCP server

YazSes also works in the other direction: an agent can call it. `yazses mcp-server` is an
[MCP](https://modelcontextprotocol.io) server over stdin/stdout, with no network port. Add
it to an MCP client's configuration:

```json
{"command": "yazses", "args": ["mcp-server"]}
```

It offers `transcribe`, which turns an audio or video file into text on your machine.
With `[mcp] ask_human = true` it also offers `ask_human`: an agent that needs a decision
only you can make asks you out loud, and gets your spoken answer back instead of having
it typed into your editor. A budget limits how often agents may interrupt you. Details
are in the [CLI reference](../cli-reference.md#yazses-mcp-server).

## What is planned

Two small additions are proposed. Both will be off by default:

- **Send to**: hand a dictated prompt to the Claude or Codex desktop app, already filled in
  and never sent, so you review it and press Enter yourself
  ([ADR-031](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-031-send-to-prefill-handoff.md)).
- **One-click MCP**: install the MCP server from a client's extension screen or the MCP
  registry, and an `ask_human` that stops listening when you stop talking
  ([ADR-032](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-032-mcp-discoverability.md)).

Neither is built yet. The [roadmap](../roadmap.md) explains why this is where YazSes is
going next.

## What YazSes will not do

It will not send anything on your behalf, route what you say to an online assistant, or
listen all the time for a wake word. You press Enter, and you choose the tool.
