---
title: Using YazSes over SSH and in Remote-SSH editors
description: Why dictation into an SSH session works with no setup at all, when it does not, and how the yazses remote agent handles the case where the remote machine owns the window.
---

# Over SSH, and in Remote-SSH editors

The short version: **dictating into an SSH session needs no setup, because the
remote machine is not involved.**

YazSes injects text at the OS level, into whatever window has focus on *your*
machine. If that window is a terminal with an SSH session in it, the characters go
down the same pipe as the ones you type. The remote host cannot tell the
difference, and there is nothing to install on it.

!!! info "Verified on"

    Ubuntu 24.04 · GNOME 46 · X11 · YazSes 2.18.2. The agent behaviour below was
    exercised locally; see *what was not tested* at the end.

## What works with no setup

| You are dictating into | Works? | Why |
|---|---|---|
| `ssh host` in your terminal | ✅ | keystrokes into your local terminal window |
| `vim`/`nano`/`emacs` over SSH | ✅ | same |
| `tmux`/`screen` on the remote host | ✅ | same |
| VS Code **Remote-SSH**, editing a remote file | ✅ | the editor window is local |
| JetBrains Gateway, the local client | ✅ | same |
| A `mosh` session | ✅ | same |

**Remote-SSH editors are the case people expect to be hard and is not.** VS Code
Remote-SSH runs its UI locally and only the server side is remote, so the text
field you are typing into is a local window like any other.

## What does not work

- **A remote *graphical* application** — an X11 or VNC window belonging to the
  other machine. Focus is on your side; the keystrokes are delivered by the remote
  X server. That is the case `yazses remote` exists for.
- **A serial console or an out-of-band KVM.** No text field, no injection.
- **A terminal doing its own bracketed-paste handling** may interpret a burst of
  characters differently from typed ones. If the text arrives mangled, switch the
  injector:

  ```toml
  [injection]
  backend = "type"     # auto | type | clipboard | wtype
  ```

  `clipboard` is the one to avoid here: pasting is a no-op in most terminals.

## The remote agent — for a remote GUI

When the window genuinely belongs to the other machine, run a small agent there and
let your local daemon deliver into it.

**On the remote host:**

```bash
pipx install yazses           # or: pip install yazses
yazses-agent --listen 9875
```

Real output:

```
INFO yazses-agent using injector: XdotoolInjector
INFO yazses-agent listening on 127.0.0.1:9875
```

**Note the address.** The agent binds **127.0.0.1**, never `0.0.0.0` — it is not
reachable from the network, on purpose. Your dictation reaches it through an SSH
tunnel and nothing else, so an open port on a shared host cannot be used to type
into your session.

**On your machine:**

```bash
yazses remote user@host
```

That opens the reverse tunnel and points injection at the far end. Dictate as
normal; the text appears in the remote GUI's focused window.

```bash
yazses status      # state: remote_active while it is connected
```

## Choosing which side transcribes

Transcription happens **where the microphone is** — your machine — in both modes.
The remote host never receives audio, only the finished text. That is deliberate:
sending audio over the network is the thing this project exists to avoid, and it
also means a small remote box needs no model and no CPU budget.

## The one thing to check on a laptop

The tunnel is bound to the SSH session. Suspending the laptop, changing network, or
letting the connection time out drops it, and dictation silently returns to typing
into the local window:

```bash
yazses status | grep -i remote
```

Re-run `yazses remote user@host` to reconnect.

## What was not tested for this page

- **The full `yazses remote` flow against a real second machine.** There is no
  second host here, and `sshd` is not running on this one. What *was* verified is
  that `yazses-agent` starts, selects an injector, and binds loopback-only —
  confirmed both by connecting to it and in `remote/agent.py`.
- **VS Code Remote-SSH and JetBrains Gateway** are listed on the architectural
  argument that their windows are local, not from a session in each. That argument
  is solid, but if one of them surprises you,
  [say so](https://github.com/MSKazemi/yazses/issues) — a report beats a deduction.
