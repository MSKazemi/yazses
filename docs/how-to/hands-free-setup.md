---
title: Set up hands-free input
description: Turn on the hands-free preset with one command, see exactly what it sets, find out what your machine is missing, and learn every way to stop it and to recover when a signal fails.
---

# Set up hands-free input

The **hands-free preset** is one switch that turns on the camera-driven inputs YazSes already has
and wires them to work together:

| Role | What does it | Feature it is |
|---|---|---|
| Words | your voice | the normal dictation |
| Where words land | where you look | Glance-Type (gaze) |
| Moving the pointer | your head | Head-Pointer |
| Committing a click | holding the pointer still (dwell) | Head-Pointer dwell-click |
| Hold to talk | holding a jaw-open | Face switch |
| Recenter and stop | a brow-raise plus a nod or a shake | Gesture Chords |
| Stop by voice | saying a short phrase | the voice stop word |

It adds **no new engine**. `[handsfree] enabled = true` is expanded, when the config is loaded, into the
ordinary settings of those features, exactly as if you had typed them. You can read every one of them
before you turn anything on, and any value you write yourself wins.

> **Experimental, off by default, and every value is provisional.** Nobody has yet measured how these
> inputs behave across people, rooms and cameras, so the numbers the preset supplies are starting points
> chosen to do *less* when unsure (a switch that ignores low-confidence frames, a destructive command that
> is refused rather than guessed). A default install is unchanged until you run the commands below.

## What you need

- A **webcam**.
- The camera features' Python packages. `yazses handsfree enable` installs them for you unless you pass
  `--no-install`; you do not run `pip` yourself.
- For **dwell-click** (a click by holding still): the on-screen overlay that draws the progress ring, see
  [Dwell-click needs the overlay](#dwell-click-needs-the-overlay).

## Set it up

1. **Read what it will do.** This changes nothing and never opens the camera:

   ```bash
   yazses handsfree explain
   ```

   Each line is an ordinary setting, with where it came from (`preset` or `yours`) and, for the safety
   floor, a `[safety floor]` mark. A text or table value you wrote is described by its kind and size and
   never printed, so the output is safe to paste into an issue.

2. **Turn it on.** The preset uses experimental features, so it asks for `--force`:

   ```bash
   yazses handsfree enable --force
   ```

   This writes **one** line, `[handsfree] enabled = true`, and nothing else. It refuses, and writes
   nothing, if one of your own settings would weaken the safety floor (the global stop, the confirmation
   of dangerous dictated commands, or refusing a destructive action when gaze cannot choose a window); the
   message names the key.

   The preset is also an ordinary capability: `yazses features enable handsfree --force` is the same
   command, with the same checks and the same refusals, and `yazses features` lists it as
   **Hands-Free Preset** under *Accessibility & input modalities*. `yazses features disable handsfree`
   is likewise `yazses handsfree disable`.

3. **Apply it:**

   ```bash
   yazses restart
   ```

4. **Check what your machine is missing.** `doctor` reports a missing camera, a missing pointer backend
   or an undecided permission with the reason, instead of leaving a feature that silently does nothing:

   ```bash
   yazses doctor
   yazses handsfree status
   ```

   While YazSes is running, the **Hands-free perception** line tells apart the causes that otherwise look
   the same, because each has a different fix. The camera is busy or unplugged. A camera package is not
   installed, and the line names it. The one-time face-model download was blocked, while the camera itself
   is fine. Or the camera is open but has stopped sending frames, which is reported as `stale` and not as
   tracking. It never prints a face, gaze or head value, only states, names and ages.

   Your desktop may show a one-time permission dialog (for pointer control on some Wayland sessions, and
   your operating system may ask before a program uses the camera). Answer it; `yazses handsfree status`
   says when one is still waiting.

   On macOS, moving the pointer needs the same **Accessibility** grant the dictation key uses. If it has
   not been given, the Head-Pointer does not start, and `yazses headpointer status` says so when it is
   enabled: *macOS has denied YazSes permission to post mouse events*, followed by the pane to open. Enable
   YazSes in System Settings > Privacy & Security > Accessibility, then restart YazSes. macOS reads the
   grant when a program starts. This macOS path has so far been tested only against a simulated macOS
   layer, not on a real Mac.

5. **Calibrate once** so the inputs are judged against *your* face and screen. Both are optional, and
   without them the plain thresholds are used and a log line says so:

   ```bash
   yazses facegesture calibrate
   yazses gaze calibrate
   ```

6. **Arm it.** Hands-free starts **paused**, and the first arming needs a fresh signal from the camera,
   so nothing moves the instant the camera comes up. Re-arm from any terminal, or from Tray →
   **Settings…** → **Hands-free controls…**:

   ```bash
   yazses handsfree resume
   ```

Every terminal step above is listed; there is no other one. Checking status, pausing and resuming are
also in the settings window (`yazses settings`), which shows the same panel as `yazses handsfree status`.

### Turn it on from the settings window (no terminal)

1. Tray icon → **Settings…**.
2. Under **Accessibility & input modalities**, tick **Hands-Free Preset**, answer **Yes** to the
   experimental warning, then click **Apply**. The window runs the same safety-floor check as
   `yazses features enable handsfree`: if one of your own settings would weaken it, nothing is written
   and the message names the key. On a Python install (pip, pipx, uv) that lacks the camera libraries,
   Apply installs them (mediapipe and OpenCV) first; the winget and Homebrew app bundles cannot add them.
3. Tray icon → **Restart daemon**.
4. Tray icon → **Settings…** → **Hands-free controls…** → **Resume hands-free input** to arm it.

To turn it off the same way, untick **Hands-Free Preset**, click **Apply**, and restart the daemon from
the tray. To stop what is moving *before* that restart, press **Pause** in the hands-free controls first.

### Choose only some of the roles

All roles default to on. Switch any off under `[handsfree]` in your `config.toml` before step 3:

```toml
[handsfree]
enabled = true
pointer = false   # no head pointer, so also no dwell-click and no recenter chord
chords = false
```

The roles are `gaze`, `pointer`, `dwell`, `switch`, `chords` and `voice_stop`. A role you turn off is not
set, and the pieces that depended on it are not left waiting for it.

## Eyes closed instead of jaw-open, from the tray (no terminal)

The preset's dictation switch is jaw-open. To use a deliberate eye closure instead, without editing any file:

1. Tray icon → **Settings…** → **Hands-free controls…**
2. **Turn Face switch on**, answer **Yes** to the experimental warning, then **Apply staged changes**. On a Python
   install (pip, pipx, uv) that lacks the camera libraries, Apply installs them (mediapipe and OpenCV) first, as
   `yazses features enable` does; the app bundles from winget and Homebrew cannot add them — use
   `pipx install "yazses[gaze,desktop]"` for camera features.
3. **Turn the global stop on**, so **Pause hands-free input** reaches the face switch.
4. Under **Face switch mapping**: *Eyes closed* → **Hold to dictate** → **Set**, then *Jaw open* → **Not mapped** →
   **Set**. Mapping eyes closed also raises the hold before any face switch counts to 0.8 s, longer than a blink,
   and the panel says so.
5. Tray icon → **Restart daemon**.
6. Tray icon → **Settings…** → **Hands-free controls…** → **Resume hands-free input**. With the global stop on,
   every camera input starts paused after each start of YazSes and only an explicit Resume arms it — once the
   camera has delivered its first frame. The tray menu has no hands-free item; `yazses handsfree resume` does the
   same from a terminal. After that, looking away is fine: a switch bound only to dictation re-arms by itself
   about a second after your face is back in view. **Pause** stays paused until you press Resume.

Then click into a text box, close your eyes for about a second, speak, and open them: the words are typed when
your eyes open. **Pause hands-free input** in the same window (or `yazses handsfree pause`) stops it. Test it
with ordinary blinking first; `[facegesture] min_hold_frames` lengthens the hold further. The window's
**Ways to stop without pointing** list, one Tab stop after **Recenter**, names only the stop routes your saved
settings set up: Alt+P in the window, `yazses handsfree pause`, your stop phrase, and any face switch or chord
mapped to pause. It also says which of these is missing.
The switch compares against a fixed threshold until you run `yazses facegesture calibrate` and set
`[facegesture] use_baseline = true` (this step still needs a terminal).

## Dwell-click needs the overlay

Dwell-click only clicks while the overlay that draws its progress ring is on screen: a click you were
never shown coming is the failure this feature is judged on. The preset does **not** turn the overlay on
(it is opt-in). Turn it on yourself:

```bash
yazses features enable overlay
yazses restart
```

Without it the pointer still moves, but dwell-click stays off and `yazses headpointer status` says why.
On a native Wayland session the overlay is not launched by default because it would take keyboard focus
and your dictation would be typed into it; the pointer moves and nothing clicks there until you pick
another way to commit.

## Not part of the preset

- The **Voice Mouse Grid** (click by voice) is experimental and the preset does not turn it on, so the
  precision fallback is yours to enable: `yazses features enable mousegrid --force`, then say "mouse grid",
  cell numbers, and "click". It needs absolute pointer motion (X11 or macOS), and the numbered grid is
  drawn only when `[overlay]` is on.
- No face gesture is bound to select, confirm or cancel by the preset. The commit is dwell-click unless you
  add a `[[facegesture.switches]]` entry yourself.

## Stopping, and getting back

Every one of these needs neither a precise pointer nor the camera, except the chord:

| Way to stop | Needs |
|---|---|
| `yazses handsfree pause` | a terminal or script; no pointer, no camera |
| the **Pause** button in the hands-free controls of the settings window (keyboard letter **P**) | the settings window |
| saying the stop phrase as a whole utterance, see [Stop hands-free input by voice](hands-free-voice-stop.md) | a dictation burst; it only pauses |
| the chord brow-raise + shake | the camera, so it cannot help once the camera is lost |
| a face switch you bound to `pause_pointer` (`[[facegesture.switches]]`) | the camera; with the global stop off it pauses the Head-Pointer only |
| `yazses handsfree disable` | pauses everything now; `yazses restart` then releases the camera |

A pause or a fault is never undone by itself. To come back, run `yazses handsfree resume`. The first frame
after re-arming only observes: it never moves the pointer or clicks, and nothing recorded while you were
stopped is replayed. A face gesture or head gesture you had begun before the Resume does not count either:
make it again, in full, after the Resume. This applies to a face switch and to a Gesture Chord token (a jaw
held open, a nod, a tilt). A gesture still held across the Resume must be relaxed and made again.

`yazses handsfree disable` writes `[handsfree] enabled = false`. It keeps your calibration and every
setting you wrote yourself, and the rest of your `config.toml` is untouched.

## When a signal fails

If the signal an action preferred is not usable, YazSes tries the next rung of this ladder and always tells
you when it did not use the first:

1. the **preferred** signal when it is healthy and confident (for example gaze, for "close this");
2. a **lower-risk alternate you chose** (a window you named by voice, the pointer already resting on it);
3. the **focused** window, only for actions that can be undone;
4. **"cannot act"**, with a notification, and nothing is done.

Two rules hold on every rung. A fallback never raises the consequence: the *action* is never changed,
only the target it lands on. And a destructive action only recovers onto a target **you** chose; an inferred
stand-in such as "whatever is focused" is refused. Every irreversible action still asks for confirmation
first, on every route. So if gaze cannot tell which window you meant, "close this" closes nothing and
says so.

## What this does not tell you

The preset is software that has been tested against fakes of a camera, a pointer and a desktop. It has not
been shown to work for any particular person, face, room or webcam, and its default phrase, thresholds and
chords are unmeasured. Check each input in your own setup before you rely on it, and keep
`yazses handsfree pause` within reach. Nothing here leaves your machine: frames stay in memory and are
never written to disk or sent anywhere.
