---
title: Reliability — what recovers by itself, and what does not
description: Every self-healing mechanism in YazSes, what triggers it, what bounds it, and the failures that are deliberately left for you. Crash recovery, microphone auto-heal, adaptive silence gate, config self-repair.
---

# Reliability: what recovers by itself, and what does not

A dictation daemon fails in a particular way: **silently**. It is a background
process you interact with by holding a key, so a daemon that died an hour ago and
a daemon that is working look identical until you speak into one and nothing
appears. Most of the mechanisms below exist for that reason — not to be clever,
but because the alternative is a user who cannot tell.

This page is the honest inventory. It lists what heals, what bounds each healer,
and — the half that matters more — **what does not heal and why that is the right
call**.

!!! info "Every bound on this page is deliberate"

    A self-healing mechanism with no limit is a crash loop wearing a friendly
    name. Something that restarts forever presents as "working" while achieving
    nothing, which is a worse failure than stopping visibly. Every recovery below
    is capped, and the cap is stated.

## The daemon died

=== "Linux"

    The systemd user unit carries `Restart=on-failure`, so a crash brings the
    daemon back. A clean exit (`yazses stop`) is not a failure and is not
    restarted.

    Bounded by `StartLimitIntervalSec=60` / `StartLimitBurst=5` with
    `RestartSec=5`: five failures inside a minute and systemd stops trying. A
    persistently broken install stays down where `systemctl --user status yazses`
    can explain it, rather than respawning until you notice the CPU.

=== "macOS"

    launchd's `KeepAlive` restarts the agent, and the tray supervises it as below.

=== "Windows"

    There is no equivalent. The autostart is an `HKCU\Run` value, which fires
    **once at login and never again** — so a daemon that crashed at 10am used to
    stay dead until the next logout, while the tray watched it, coloured itself
    red, and did nothing.

    The tray now relaunches it. It was already the right process: it polls
    `status`, it already knew, and it holds the lifecycle handle. Bounded by
    `MAX_DAEMON_RELAUNCHES = 5` with `RELAUNCH_COOLDOWN_S = 15` between attempts,
    and a `_RECONNECT_GRACE_S = 5` window so an ordinary restart is not mistaken
    for a crash.

## The tray died

The daemon watches back. `_supervise_tray` re-checks every 20 seconds and
relaunches, bounded at 5 attempts.

Liveness is read from the **tray lock file**, not a remembered child PID —
correct when the tray was started by hand, or outlived a daemon restart, which a
PID would get wrong in both directions. Before this, a crashed icon simply stayed
gone while dictation carried on unobserved.

## The microphone changed under you

The failure this is built for: a USB-C monitor, a headset, or a meeting app takes
over capture. Nothing errors. The daemon records silence, discards it, and you
watch a green icon type nothing.

| Signal | Default | What happens |
|---|---|---|
| Consecutive silent discards | `silent_streak_threshold = 3` | capture heals back to the last-good device |
| OS default input changed | polled every `device_poll_interval_s = 3.0` s | same |

Controlled by `[audio] auto_heal_device` (on by default). Each heal raises a
desktop notification with **[Re-calibrate] / [Pin this mic] / [Ignore]**, because
a silent fix is only half useful — you need to know the device moved. Pin one for
good with `yazses audio use <name>`.

## The silence gate drifted above your voice

If the VAD threshold sits above how loudly you actually speak, every burst is
discarded and the symptom is, again, silence. `AdaptiveThreshold` notices a run of
discards with no successful transcription between them and proposes a gate that
would have passed them, persisted to your config.

**It only ever lowers the gate**, and that asymmetry is the point: lowering
repairs an *invisible* failure, while raising only trims noise you can already
see and hear. Discards *above* the gate produce no suggestion at all — a muted
microphone produces exactly the same symptom, and guessing wrong there would
raise the gate on a user who is already not being heard.

## The config is broken

Loading is **total**: no config file can stop the daemon starting. Values that can
be repaired are (`"0.004"` → `0.004`), values that cannot fall back to the
documented default, unknown keys and sections are dropped, and unparseable TOML
still yields a working daemon.

Nothing is repaired silently — every decision becomes a `ConfigProblem`, listed at
startup and shown by `yazses doctor` under **Config validity**.

## The model could not be downloaded

A firewall refusing the first model fetch used to kill the daemon with a raw
traceback — which the Windows bundle renders as a modal "Failed to execute
script", telling you nothing about what it wanted.

The daemon now holds itself in `ERROR` state with printable guidance attached: the
cause, a firewall hint when the cause reads like one, and the three ways to get
the model. The tray turns red **with the reason**, and `yazses status` can answer.
Exiting would have taken the tray down too, leaving a vanished window as the only
symptom.

## Two daemons at once

An OS-held lock (`SingleInstanceLock`), not a PID file, so it is never stale after
a crash and never absent during a run. `yazses start` restarts cleanly instead of
spawning a duplicate — duplicates present as **every word typed twice**, which is
easy to misread as a hotkey problem.

---

## What does not heal itself

Equally important, and deliberate:

- **A wrong hotkey, a missing permission, an unconnected snap interface.** These
  need a decision or a password. `yazses doctor` names them; nothing guesses.
- **A dead injection backend.** If `ydotool`/`xdotool` is absent, dictation is
  copied to the clipboard and you are told — it is not silently dropped, and no
  package is installed behind your back.
- **Dictation with no text target.** Words go to the clipboard, the tray turns
  yellow. Typing them into whatever happens to have focus would be worse than
  not typing them.
- **A transcription that is simply wrong.** No mechanism can detect this.
  `yazses mark-wrong` records it for `yazses tune`, which proposes changes you
  approve — it never edits your config behind you.
- **Anything requiring the network.** YazSes is offline by design; nothing
  "recovers" by phoning home.

## Seeing it for yourself

```sh
yazses doctor    # prerequisites, permissions, model, config validity, daemon state
yazses verify    # runs the real chain and names the FIRST broken link with its fix
yazses status    # live daemon state over IPC, including the current input device
yazses logs      # metadata-only diagnostic log
yazses report    # a local-only bundle, redacted — nothing is uploaded
```

`doctor` proves the prerequisites; `verify` proves the thing actually works, and
stops at the first broken link rather than cascading a wall of failures.
