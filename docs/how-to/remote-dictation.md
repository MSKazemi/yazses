---
title: Voice dictation over SSH — VS Code Remote-SSH, Cursor and remote terminals
description: Dictation that works in remote SSH sessions. Because YazSes types at the OS level rather than inside an application, it works in VS Code Remote-SSH panes, Cursor, integrated terminals and containers with no setup — and can forward text to a remote host's own display over an encrypted tunnel.
---

# Dictate into a remote SSH host

**Read this first — there are two different situations, and the common one needs
no setup at all.**

## Are you in VS Code, Cursor or a local terminal? Then it already works

If you use **VS Code Remote-SSH**, **Cursor**, a JetBrains remote workspace, or
just a terminal emulator with `ssh` open in it, **you do not need anything on
this page.** Install YazSes and dictate — it already works.

The reason is where the typing happens. YazSes does not type *into an
application*; it synthesises keystrokes at the **operating-system level**
(`ydotool` on Wayland, `xdotool` on X11) into whichever window currently has
focus. In a Remote-SSH session the editor window and its integrated terminal are
running **locally** on your laptop — only the backend is remote. So from the
injection layer's point of view there is nothing remote about it, and the text
lands exactly as it does in a local editor.

This is the practical difference between OS-level dictation and the
**in-application** dictation built into editors and AI coding tools. In-app voice
input is bound to that application's own input handling, and commonly does not
reach places the application does not own — Remote-SSH editor panes, integrated
terminals, SSH sessions, containers, VMs, or a second app you alt-tab to.
Keystrokes injected below the application have no such boundary: if a window can
receive a keypress, it can receive dictation.

Concretely, YazSes works in all of these with no extra configuration:

| Where you are typing | Works |
|---|---|
| VS Code / Cursor **Remote-SSH** editor pane | ✅ |
| VS Code / Cursor **integrated terminal** (remote shell) | ✅ |
| A terminal emulator with `ssh` / `tmux` / `mosh` open | ✅ |
| A shell inside a Docker container or VM | ✅ |
| Any other focused window — browser, chat, notes | ✅ |

**When you need the rest of this page instead:** you are sitting at a *different
physical machine* — a bare SSH console, a headless box, a machine with no
microphone — and you want the text to appear in an application running **on that
remote host's own display**. That is what `yazses remote` below is for.

---

## Forwarding to a remote host's own display

Run YazSes on your **local** machine — where the microphone and the STT engine
live — and have the transcribed text typed into an application on a **remote**
host you reach over SSH. Your voice never leaves your laptop as audio; only the
final text is forwarded over the encrypted SSH tunnel.

```
[ your laptop ]                                   [ remote host ]
 mic → STT → text  ──SSH reverse tunnel──▶  yazses-agent → types into the focused app
```

## What runs where

| Machine | What runs | Why |
|---|---|---|
| Local (your laptop) | the YazSes daemon (`yazses start`) | captures audio, runs faster-whisper |
| Remote (SSH host) | `yazses-agent` | receives text and injects it into the focused window |

`yazses-agent` is deliberately lightweight — it has **no** audio or faster-whisper
dependencies, just a text injector. Install YazSes on the remote host the same
way you install it locally.

## 1. Start the daemon locally

```bash
yazses start
```

The `remote` command talks to a running daemon, so it must be up first.

## 2. Forward voice typing to the remote host

```bash
yazses remote dev.example.com                 # forward over SSH (default port 22)
yazses remote dev.example.com -p 2222         # non-default SSH port
yazses remote dev.example.com -i ~/.ssh/id_ed25519   # explicit private key
```

Under the hood this opens an SSH reverse tunnel and launches the agent on the
remote host, roughly equivalent to:

```bash
ssh -R 9875:127.0.0.1:9875 dev.example.com yazses-agent --listen 9875
```

Once connected, hold your hotkey and speak as usual — the text lands in whatever
window is focused **on the remote host**. Make sure the remote application you
want to type into has keyboard focus.

## 3. Disconnect

```bash
yazses remote dev.example.com --stop
```

## Running the agent manually

If you prefer to start the agent yourself on the remote host (for example under a
process manager), run:

```bash
yazses-agent --listen 9875      # default port is 9875
```

Then point the tunnel at that port. The agent listens on `127.0.0.1` only, so it
is reachable exclusively through the SSH tunnel — not exposed on the network.

## Defaults and config

The `[remote]` section of `config.toml` sets the defaults the `remote` command
uses when you omit flags:

```toml
[remote]
default_host = ""        # host to use when none is given
ssh_port = 22
agent_port = 9875        # must match `yazses-agent --listen`
key_file = ""            # SSH private key path
```

## Requirements

- `ssh` must be installed and on your `PATH` locally.
- Key-based SSH auth to the remote host (so the tunnel opens without a password
  prompt).
- YazSes (for `yazses-agent`) installed on the remote host, with a working text
  injector for its display server (the same injection prerequisites as a normal
  local install).

## See also

- [Configuration reference — `[remote]`](../configuration.md)
- [CLI reference — `remote`](../cli-reference.md)
