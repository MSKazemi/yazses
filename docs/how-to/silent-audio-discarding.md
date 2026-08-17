---
title: "\"Silent audio -- discarding\" — what it means and how to fix it"
description: The most common YazSes report explained end to end — the VAD threshold, measuring your microphone with yazses mic-level, and the cases where the real cause is a muted or switched microphone instead.
---

# "Silent audio -- discarding"

You hold the key, speak, release — and nothing is typed. The log says:

```
Silent audio -- discarding
```

This is the single most common report, and it has two quite different causes. The
first thing to establish is which one you have.

!!! info "Verified on"

    Ubuntu 24.04 · GNOME 46 · X11 · YazSes 2.18.2 · Python 3.14. Every command
    below was run on that machine and the output is real.

## What the message means

Before transcribing, YazSes checks whether the clip contains speech at all, by
comparing the mean absolute sample value against `[accessibility] vad_threshold`.
Below it, the clip is discarded rather than sent to Whisper — because Whisper
hallucinates confident sentences out of silence, and a made-up sentence typed into
your document is worse than nothing.

So the message means exactly one thing: **what was recorded was quieter than the
threshold.** It does not say whether that is because you were quiet or because
nothing was recorded at all.

## Step 1 — measure your microphone

```bash
yazses mic-level
```

Real output from the machine above, recorded in a quiet room **without speaking**:

```
Recording 4s -- speak normally now...
  mean level:            0.0101
  peak level:            0.0866
  current vad_threshold: 0.0005
  recommended:           0.0051
```

Read it as three facts:

- **mean level** — what the microphone actually heard.
- **current vad_threshold** — the line your speech has to clear.
- **recommended** — half the measured mean, which is what `--set` would write.

!!! warning "Speak during the four seconds"

    The recommendation is computed from whatever it heard. The run above is what
    happens when you *don't* speak: it measured room noise and recommended a
    threshold *below* it, which would make ambient noise trigger recording. If your
    recommended value looks implausibly low, you measured your room, not your voice.

## Step 2 — decide which case you are in

| What `mic-level` shows | What it means | Fix |
|---|---|---|
| mean level **well above** the threshold | your voice is getting in; the discard is something else | see step 4 |
| the log says **`Empty transcription`**, not `Silent audio` | audio cleared the gate and the model still returned nothing | step 5 |
| mean level **below** the threshold | the gate is set above your voice | step 3 |
| mean level ≈ **0.0000** | nothing is being recorded at all | step 4 |

## Step 3 — the gate is too high

```bash
yazses mic-level --set    # writes the recommendation to config.toml
yazses restart
```

Or by hand:

```toml
[accessibility]
vad_threshold = 0.005
```

**Lower** it if quiet speech is being discarded. **Raise** it if silence produces
spurious transcripts — the same number controls both directions, and there is no
value that is right for every room.

YazSes also adjusts this on its own when it can prove it should: a run of discards
with no successful transcription between them means the gate sits above your voice,
so it proposes one that would have passed them (`audio/adaptive_vad.py`). That is
deliberately one-directional — lowering repairs an *invisible* failure, while
raising only trims noise you can already see.

## Step 4 — nothing is being recorded

A level near zero is not a threshold problem. In order of likelihood:

```bash
yazses doctor            # says which device it will use
yazses audio devices     # ● = OS default, ★ = pinned
yazses audio status      # what the running daemon has open
```

- **The microphone is muted.** In hardware, or in your mixer. `pavucontrol` →
  *Recording* shows whether YazSes is receiving anything at all while you hold the
  key.
- **The wrong device is selected.** A USB-C monitor, a webcam or a headset that
  appeared later can become the OS default and take capture with it. Pin the one
  you want so it cannot be stolen:

  ```bash
  yazses audio use "Yeti"      # substring of the name from `audio devices`
  ```

- **The device changed while the daemon was running.** YazSes notices a run of
  silent clips and heals back to the last-good device automatically
  (`[audio] auto_heal_device`, on by default), and pops a notification with
  *Re-calibrate* / *Pin this mic* buttons. If you dismissed it,
  `yazses audio status` still shows the streak.

## Step 5 — "Empty transcription", not "Silent audio"

These are two different failures with the same outcome, and the log distinguishes
them:

```
Silent audio -- discarding (level 0.0003 < vad_threshold 0.0005 …)
Empty transcription -- discarding.
```

The second one means the audio **passed** the gate, reached the model, and decoded to
nothing. So the gate is not your problem and raising or lowering it will not help.
Measured on a machine in exactly this state: four bursts in a row at levels
0.0022–0.0069, against **0.0199** for that same machine's last successful dictation.
Audible, and far too quiet to recognise.

That gap is nearly always **which microphone you are actually recording, or at what
gain** — and on Linux you often cannot tell from the device name, because the default
is a routing alias:

```bash
yazses audio status      # names the device behind `default`, and its volume
```

```
OS default:    default
               → Raptor Lake-P/U/H cAVS Digital Microphone  (volume 65%)
```

A far-field laptop array at 65% is a different instrument from a headset at 100%. Two
things fix it:

```bash
wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 1.0   # or pick the other source in your mixer
yazses mic-level --set                        # then recalibrate the gate to the new level
```

Pin the device afterwards (`yazses audio use <name>`) so a later hotplug cannot move
capture again without telling you.

!!! note "The guard counts these now"

    A run of empty transcriptions trips the same mic-change guard as a run of silent
    ones — it notifies and can auto-heal after three. Before that it counted only
    silent discards, so a microphone that heard you but yielded nothing was invisible
    to the thing built to notice.

## What "fixed" looks like

```bash
yazses status
```

```
YazSes is running (PID 4084).
  state:    idle
  hotkey:   right_ctrl
  model:    base.en
  mic:      default
  latency:  base.en p50 740 ms / p95 1210 ms (n=143)
```

A `latency:` line at all means clips are reaching the decoder — the discard path
never produces one. `yazses logs` should show `Transcribed …` lines rather than
`Silent audio -- discarding`.

## Where this page stops

- **Bluetooth headsets** are a known rough edge: many negotiate a low-quality
  mono profile when the microphone is opened, and the level can drop sharply at
  that moment. Nothing here was tested against one.
- **PipeWire vs PulseAudio** made no difference in this testing, but only PipeWire
  (Ubuntu 24.04's default) was actually exercised.
