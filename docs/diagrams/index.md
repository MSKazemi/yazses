---
title: Architecture Diagrams
description: The YazSes subsystem architecture in three formats — Mermaid, ASCII, and a self-contained HTML page.
---

# Architecture Diagrams

The same YazSes subsystem architecture, shipped in three formats so you can read
it wherever you are:

| Format | File | Best for |
|---|---|---|
| **Mermaid** | [`yazses-architecture.mmd`](yazses-architecture.mmd) | Rendered on GitHub / Mermaid Live Editor; embedded below |
| **ASCII** | [`yazses-architecture.txt`](yazses-architecture.txt) | Terminals, code review, and the master reference PDF |
| **HTML** | [`yazses-architecture.html`](yazses-architecture.html) | A styled, self-contained page you can open in any browser (no internet needed) |

For the narrative explanation of each subsystem, see the
[Architecture](../architecture.md) page.

## Mermaid

```mermaid
flowchart TB
  subgraph UI["User-facing control"]
    CLI["yazses CLI (57 commands, 91 with subcommands)"]
    TRAY["yazses-tray (macOS/Windows)"]
  end
  UI -->|"JSON-RPC 2.0 · Unix socket / named pipe"| IPC[["IPC server (ipc/)"]]
  IPC --> DAEMON

  subgraph DAEMON["yazses-daemon — orchestrator (core/daemon.py)"]
    direction TB
    HK["1 · Hotkey — keyboard OR EMG (USB serial)"]
    AUD["2 · Audio — recorder → VAD → padding"]
    STT["3 · STT — faster-whisper (int8) · streaming · disfluency"]
    PP["4 · Post-process — cleaner · voice-punct · spacing · LLM cleanup"]
    CMD["5 · Commands — Tier1 grammar · LSP (Tier2 SLM router: designed, not wired)"]
    DIS{"6 · dispatch()"}
    HK --> AUD --> STT --> PP --> CMD --> DIS
  end

  CFG[("config.toml · config.py")]
  FEAT[("features.py — 140 capabilities (73 wired)")]
  CFG -. reads .-> DAEMON
  FEAT -. drives .-> CLI

  DIS -->|dictate| INJ["Injector — ydotool/xdotool/wtype/clipboard"]
  DIS -->|command| KEYS["Key sequence — ctrl+z, ctrl+s, …"]
  INJ --> APP["Focused app (local)"]
  KEYS --> APP
  INJ -. "SSH tunnel (remote/)" .-> AGENT["yazses-agent (remote host)"]

  subgraph PLAT["Platform abstraction — Protocols (platform/base.py)"]
    direction LR
    LNX["linux"]
    MAC["macos"]
    WIN["windows"]
    EMG["emg"]
  end
  PLAT -. implements .-> DAEMON

  subgraph OPT["Opt-in — OFF by default, deps behind extras"]
    direction LR
    LEARN["Learning loop — crypto · store · tune"]
    V2["v2 cognitive — voiceprint · gaze · personalize · polyglot · cocktail"]
    RECIMP["Recording import — yazses transcribe"]
  end
  DAEMON -. optional .-> LEARN
  DAEMON -. optional .-> V2
  CLI -. optional .-> RECIMP
```

## ASCII

```text
--8<-- "diagrams/yazses-architecture.txt"
```

> The ASCII block above is included verbatim from
> [`yazses-architecture.txt`](https://github.com/MSKazemi/yazses/blob/main/docs/diagrams/yazses-architecture.txt).
