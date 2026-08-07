---
title: Record a YazSes demo GIF — contributor guide
description: How to record a short hold-to-talk dictation demo GIF for the YazSes README, with a one-command recorder that needs no system packages on X11.
---

# Record a demo GIF

A dictation tool is hard to explain and easy to show: hold a key, speak, watch the text
appear. A 10–15 second GIF does that better than any paragraph, which is why it belongs at
the top of the README.

The repo ships a recorder so you don't have to install anything:

```sh
uv run scripts/record-demo.py --window --seconds 15 --out docs/screenshots/demo.gif
```

It asks you to click the window to record, counts down from three, captures, then writes a
size-optimised GIF. `uv` fetches its two dependencies (`mss`, `pillow`) into its own cache
on first run — nothing is installed system-wide, no `sudo`, and they are not added to the
project's dependencies.

**Don't race the countdown.** Motionless frames at the start and end are trimmed
automatically, so give yourself room and perform when you're ready:

```sh
uv run scripts/record-demo.py --window --seconds 40 --out docs/screenshots/demo.gif
```

Forty seconds of recording in which you dictate one sentence yields a clip as long as the
sentence. A pause in the *middle* is kept — that one is content, it's the wait while your
speech is transcribed. Pass `--no-trim` to keep everything.

X11 only. On Wayland the screen cannot be read this way; see [Wayland](#wayland) below.

## What to show

Keep it to one idea. The demo answers *"what happens when I hold the key?"* — nothing else.

| Time | On screen |
|---:|---|
| 0–2 s | A real editor with the cursor already blinking in it. No terminal. |
| 2–3 s | You press and hold the key. The tray icon turns **green** and the overlay rings appear — that is the visible feedback that it is listening. |
| 3–8 s | You speak one natural sentence. Nothing appears yet; that is correct and worth showing, because it is what a real user sees. |
| 8–11 s | You release. The text appears in the editor. |
| 11–13 s | One beat of stillness on the finished text, so the loop doesn't cut mid-word. |

Say something that demonstrates the product rather than the technology. A sentence with
ordinary punctuation reads better than "testing one two three", because the transcript
shows capitalisation and a full stop — details a viewer notices without being told.

## Before you hit record

- **Check dictation actually works right now** — `yazses status`, then dictate once into a
  scratch file. Re-recording because the daemon was in a bad state is the most common waste.
- **Raise the editor's font size** to ~16–18 pt. The GIF is scaled down to 900 px wide; text
  that is comfortable on your screen is unreadable after scaling.
- **Shrink the window** to roughly 900×500. A tighter region means fewer pixels per frame,
  which is the single biggest lever on file size.
- **Clear the screen of anything private** — file paths, tabs, notifications, email. The GIF
  is permanent and public.
- **Include the tray icon** in the region if you can. Watching it turn green mid-recording
  demonstrates the state feedback for free.

## Size

GitHub renders README images at about 900 px wide, and a demo that takes seconds to load
has already lost the visitor it was meant to convert. The script targets **under 5 MB** and
warns when it misses. If it warns, in order of what costs least:

| Knob | Effect |
|---|---|
| Tighter `--region` | Biggest win — pixels are multiplied by every frame |
| `--fps 10` | Barely visible at this length |
| `--colors 64` | Fine for text on a flat background |
| Shorter `--seconds` | Cut the lead-in, not the result |

The recorder already collapses runs of identical frames, so the still parts of the clip —
the pause while you speak — cost almost nothing.

## Stills

Same script, `--shot`, for screenshots such as the tray in a particular state:

```sh
uv run scripts/record-demo.py --window --shot --out docs/screenshots/tray-green.png
```

## Wayland

`mss` cannot capture the screen under Wayland. Record with
[`wf-recorder`](https://github.com/ammen99/wf-recorder), then convert:

```sh
wf-recorder -g "$(slurp)" -f demo.mp4          # select a region, record, Ctrl-C to stop
ffmpeg -i demo.mp4 -vf "fps=12,scale=900:-1" -f gif - | gifski -o demo.gif -
```

`gifski` produces noticeably better GIFs than ffmpeg's own encoder at the same size.

## Where it goes

Above the fold in `README.md` — before the `yazses doctor` screenshot, which shows a
diagnostic rather than the result. The same file is reused in the docs landing page and in
any launch post, so record it once and use it everywhere.
