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

**It also records why.** The tray is a separate process, and both launch sites used
to send its output to `/dev/null` — so a log could show four relaunches in an evening
with nothing about the cause, and the give-up message could only suggest running
`yazses tray` by hand to reproduce a failure that had already happened. What the tray
printed on the way down is now captured and logged with each relaunch:

```
Tray supervisor: tray is not running — relaunching
  it said:
    qt.qpa.plugin: Could not load the Qt platform plugin "xcb"
```

That reaches `yazses logs` and the bundle `yazses report` writes, so "the tray keeps
dying" arrives with its own evidence.

## The microphone changed under you

The failure this is built for: a USB-C monitor, a headset, or a meeting app takes
over capture. Nothing errors. The daemon records silence, discards it, and you
watch a green icon type nothing.

| Signal | Default | What happens |
|---|---|---|
| Consecutive silent discards | `silent_streak_threshold = 3` | capture heals back to the last-good device |
| OS default input changed | polled every `device_poll_interval_s = 3.0` s | same — **but see below** |

!!! warning "The second trigger does not fire on most Linux desktops"

    The watcher notices a switch by comparing the default input's **name** over time.
    On PipeWire and PulseAudio the default is a routing alias literally called
    `default`, and the name does not change when the device behind it does — so it
    compares `default` with `default` for ever and sees nothing. Reading through the
    alias needs a PipeWire or PulseAudio client library, which YazSes does not take on
    as a dependency for one diagnostic.

    **The first trigger is unaffected**, and it is the one that catches this in
    practice: it counts *outcomes* — bursts that produced no text — not device names.
    So a monitor that steals your microphone is still healed, after the silent streak
    rather than at the moment of the switch.

    **Pinning removes the question entirely**: `yazses audio use <name>` means nothing
    can take capture away in the first place. `yazses audio status` and `yazses doctor`
    name the microphone actually behind the alias, so you can see which one it is.

Controlled by `[audio] auto_heal_device` (on by default). Each heal raises a
desktop notification with **[Re-calibrate] / [Pin this mic] / [Ignore]**, because
a silent fix is only half useful — you need to know the device moved. Pin one for
good with `yazses audio use <name>`.

**Healing needs somewhere to heal to.** The first trigger fires on outcomes, so it
also catches the case where the microphone never moved and is simply capturing
audio the recogniser cannot use — too quiet, muted at the mixer, a gate set above
your voice. There is no other device to switch to then, so the guard notifies and
changes nothing. Either way it now writes one line to the diagnostic log:

```
No text from 3 burst(s) in a row (device 'default', threshold 3) -- no different
last-good device to switch to.
```

That line is the record. A desktop notification is delivered and gone — if you were
away from the machine, had notifications silenced, or are on a headless or SSH
session, it never reached you at all, and until v2.30 nothing else was written down.
`yazses logs` is where to look, and `yazses report` carries the same tail into a bug
report. It is logged even with `[audio] silent_streak_notify = false`, which is
exactly the setting where the log is the only record that can exist.

### Answering that toast without a pointer

Those are buttons, and until now they were *only* buttons — so the daemon asked you
a question about your microphone that needed a mouse. The person seeing it is the
one whose dictation has just stopped working, which is the worst moment to be sent
to the pointer.

Turn on `[audio] voice_answer` and you can hold your dictation key and **say** one
of them instead:

```toml
[audio]
voice_answer = true            # off by default
voice_answer_window_s = 45.0   # how long the question stays answerable
```

| Say | Does |
|---|---|
| “re-calibrate” / “calibrate the mic” | the same as clicking **Re-calibrate** |
| “pin this mic” / “pin the microphone” | the same as clicking **Pin this mic** |
| “ignore” / “ignore that” / “dismiss” | dismisses the toast |

“never mind” is deliberately *not* one of these. It already means **cancel the held
command** to the [command-safety gate](how-to/command-safety.md), and it is a
self-correction trigger for the disfluency filter besides — a phrase that means a
different thing depending on which invisible thing is pending is exactly what these
guards are designed to avoid.

Two limits, both deliberate. The **whole utterance** must be the answer — “please
ignore the second paragraph” is prose and gets typed, because a control word that
eats your sentences is worse than no control word. And the words only count inside
`voice_answer_window_s` of the toast; after that “ignore” is an ordinary word again
and types normally, rather than staying armed for the rest of your session.

It is off by default because it consumes a burst that would otherwise be typed —
the same reason `[cmdsafety]` and `[checkdigit]` are opt-in.

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

## A recording that holds no speech

A speech model answers non-speech audio with words rather than with nothing: four
seconds of faint room hiss decodes to **"You"**. So an empty recording does not
produce an empty transcript — it produces a short, confident, completely invented
one, and no check on the *output* can tell it from a real short utterance.

Both file paths measure the **input** instead, and they ask two separate questions:

| Verdict | What it means | Where to look |
|---|---|---|
| no signal | nothing was captured at all (peak below `1e-4`) | the microphone was muted, another app held the device, or the wrong device was recorded — `yazses audio devices` |
| no speech | sound was captured and a speech detector found none in it | the file holds music or room noise, the wrong source was recorded, or the speech is too faint to detect |

The detector is Silero, which `faster-whisper` already ships as a bundled ONNX
asset — nothing is downloaded and nothing leaves the machine.

- `yazses transcribe` prints the matching note and still writes the transcript. The
  text is the evidence; deleting it would only hide the problem.
- A **meeting** records the verdict in its `meeting.json` and `yazses meeting list`
  says so on the meeting's line. This matters more than on `transcribe`: a meeting is
  unattended, and its audio is deleted when the post-pass finishes unless
  `[meeting] retain_audio = true`.
- **Minutes are refused** for such a meeting, at finalize and again if you run
  `yazses meeting notes <id>` by hand. A summary of invented words reads exactly like
  a real one, which makes it the one output nobody can audit afterwards. Pass
  `--force` if you have read the transcript and it does hold speech — a detector can
  be wrong about a very quiet talker.

It is a detector, not a filter: it runs beside the decode and changes nothing about
how real speech is transcribed. Filtering the audio through it first would also stop
the hallucination, and it re-segments the audio — measured on six LibriSpeech clips,
that changed two transcripts, one of them for the worse.

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
