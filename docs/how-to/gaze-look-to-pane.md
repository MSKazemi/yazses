---
title: Aim dictation with your gaze (Glance-Type)
description: Look at a window and hold-to-talk — your speech lands in whichever pane you glanced at, hands-free.
---

# Aim dictation with your gaze (Glance-Type look-to-pane)

Normally YazSes types into **whatever window has keyboard focus**. With
Glance-Type turned on, the moment you start holding your hold-to-talk key,
YazSes takes one webcam frame, works out **which window you are looking at**,
focuses it, and *then* types your speech there.

**The use case:** you have two or more windows open — say a code editor on the
left and a chat or browser on the right. You are reading the chat but want to
dictate a note into the editor. Instead of clicking the editor to switch focus,
just **glance at it and hold-to-talk** — the text lands where you *looked*, not
where the cursor was. It is hands-free window targeting.

Glance-Type is **coarse by design**: it aims at a screen *region* (a pane), not a
pixel. Put the windows you want to switch between in clearly different parts of
the screen (left half vs right half) and it works well.

> **Experimental + off by default.** Webcam gaze is approximate. Glance-Type is
> opt-in and, if the estimate is uncertain, it safely falls back to the focused
> window rather than typing in the wrong place.

## Requirements

Glance-Type needs all of these:

| Requirement | Why |
|---|---|
| An **X11** session | Focusing another app's window is only possible on X11. Wayland forbids it, so Glance-Type stays dormant there (see [Troubleshooting](#troubleshooting)). |
| **`xdotool`** installed | Used to list and focus windows. `sudo apt install xdotool` |
| A **webcam** | To see where your eyes point. |
| The **gaze Python deps** (`mediapipe`, `opencv`) | The face/iris tracker. **Installed automatically** — you do not run `pip` yourself. |

Check your session type with `echo $XDG_SESSION_TYPE` — it should print `x11`.

## Set it up

### 1. Turn it on (installs the deps automatically)

```bash
yazses features enable gaze --force
```

`--force` is required because Glance-Type is experimental. This writes
`[gaze] enabled = true` and `[gaze] route_dictation = true` to your config **and**
installs the webcam deps (`mediapipe`, `opencv`) into the running environment on
demand. Add `--no-install` if you want to install them yourself later.

### 2. Calibrate your webcam

Calibration teaches YazSes how your eye positions map to screen locations. It is a
one-time step (redo it if you change your seating, monitor, or camera).

```bash
yazses stop            # free the webcam first — see the note below
yazses gaze calibrate
```

A prompt appears for each of nine on-screen points:

```
Look at the top-left of your screen (192, 120), then press Enter
```

For each one: **actually move your eyes to that spot, hold your gaze steady, then
press Enter.** Keep your head fairly still and your face well-lit and centred in
the webcam. YazSes needs a face on **at least 3 of the 9** points; it saves the
result to `~/.local/share/yazses/gaze_calibration.json`.

> **Important — one webcam at a time.** Stop the daemon before calibrating.
> If the daemon (or any other app, like a video call) is using the camera, you
> will see `can't open camera by index` and `0 point(s) captured a face`. Close
> the other camera user and retry.

### 3. Start dictating

```bash
yazses start
```

### Check readiness at any time

```bash
yazses gaze status
```

```
Glance-Type (look-to-pane) status:
  ✓ [gaze] enabled = True
  ✓ route_dictation = True
  ✓ gaze backend/deps (mediapipe)
  ✓ X11 desktop backend (xdotool)
  ✓ calibration (/home/you/.local/share/yazses/gaze_calibration.json)

Ready — dictation will land in the window you look at.
```

Every line must be a `✓`. If one is `✗`, the message tells you the next step.

## Use it

With the daemon running and calibration done:

1. Have two or more windows open, in **clearly different screen regions**.
2. **Look at** the window you want the text in.
3. Hold your hold-to-talk key (see `yazses hotkey show`) and speak.
4. Release. The text appears in the window you looked at — focus jumps there
   automatically.

That is the whole workflow. You never click to switch windows; you just glance.

## Test that it actually works

The clean test proves gaze *overrides* the currently-focused window:

1. Open **two terminals** side by side — one filling the **left half** of the
   screen, one the **right half**.
2. **Click the right terminal** so it has keyboard focus.
3. **Look at the left terminal**, hold your key, and say a few words.
4. ✅ **Success:** the text appears in the **left** terminal — the one you looked
   at — even though the right one had focus. Focus visibly jumps left.
5. Flip it: click left, look right, dictate. It should land on the right.

### Watch it decide, live

In a second terminal, tail the log while you test:

```bash
tail -f ~/.local/state/yazses/log/daemon.log | grep "Gaze routed"
```

On each hold you should see the chosen window, and the **id should change** as you
look left vs right:

```
INFO yazses.gaze.targeter: Gaze routed dictation to window 46613379
INFO yazses.gaze.targeter: Gaze routed dictation to window 46816234
```

If you instead see the **same id every time** regardless of where you look, your
calibration is not discriminating between regions — [re-calibrate](#it-routes-to-the-wrong-window-or-always-the-same-one).

## Troubleshooting

### "Gaze unavailable" or a `✗` on the deps line

The webcam deps are not installed in the environment YazSes runs from. Re-run
`yazses features enable gaze --force` (it auto-installs), or run
`yazses gaze calibrate`, which installs them on first use.

### `can't open camera by index` / `0 point(s) captured a face`

Something else is holding the webcam — most often the YazSes **daemon itself**.
Stop it first, then calibrate:

```bash
yazses stop
yazses gaze calibrate
yazses start
```

Also close any video-call app or browser tab using the camera. If your webcam is
not at index 0, set `[gaze] camera_index` in `config.toml` to the right index.

### Only 1–2 points captured a face

The camera could not see your face clearly. Improve lighting (light on your face,
not behind you), centre yourself in the frame, and hold still on each point. You
need at least 3 of 9.

### It routes to the wrong window, or always the same one

This is a calibration-accuracy problem. Re-calibrate carefully:

```bash
yazses stop
yazses gaze calibrate      # move your eyes deliberately to each point, hold steady
yazses start
```

Tips that make the biggest difference:

- Sit at roughly the **same distance and posture** you use day-to-day.
- **Big, well-separated windows** (left half vs right half). The estimate cannot
  tell apart two windows crammed into the same corner.
- Keep your **head still** and move only your **eyes** during calibration and use.
- Good, even lighting on your face.

### Nothing routes on Wayland

Glance-Type is **X11-only**. On Wayland (the default on many GNOME systems) a
program cannot focus another app's window, so YazSes leaves dictation on the
focused window and logs that gaze is dormant. Check with
`echo $XDG_SESSION_TYPE`; if it says `wayland`, log out and pick an **"Xorg"** /
X11 session at the login screen, or use an X11-based desktop.

## Turn it off

```bash
yazses features disable gaze
yazses restart
```

Your calibration file is left in place, so you can re-enable later without
re-calibrating.

## Privacy

Webcam frames are processed **entirely in memory** during a hold and are **never
stored and never sent anywhere** — like everything in YazSes, gaze runs fully
offline on your machine. The only thing written to disk is the numeric calibration
map (a small matrix), not any image. See the
[privacy statement](../privacy-statement.md).

## See also

- [Feature reference](../features.md) — every capability and how to turn it on.
- [Configuration reference](../configuration.md) — the full `[gaze]` config section.
- [Change the hold-to-talk key](change-hotkey.md) — pick the key you hold to dictate.
- [CLI reference](../cli-reference.md) — `yazses gaze` and `yazses features` commands.
- [Research: eye control](../research/eye-control.md) — the measured accuracy
  budget behind this feature (why it targets panes, not the caret), and the open
  questions we would like community measurements on.
