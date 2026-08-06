---
title: Record a YazSes demo GIF — contributor guide
description: How to record a short hold-to-talk dictation demo GIF for the YazSes README, including recommended tools and settings on Linux, macOS and Windows.
---

# Record Your Own Demo GIF

A short demo GIF is a convenient way to show YazSes hold-to-talk dictation in action. This guide explains how to record your own demo.

## What to Record

A useful demo should clearly show:

1. Start YazSes.
2. Place the cursor in a text field or editor.
3. Hold the configured hold-to-talk key.
4. Speak a short sentence.
5. Release the key.
6. Show the transcribed text appearing in the active window.

Keep the recording short and focused so the resulting GIF is easy to view.

## Recording Tools

Choose a recording tool based on your Linux display system:

- **Peek** — a simple option for recording short demos, commonly used on X11.
- **wf-recorder** — a screen recorder designed for Wayland.
- **gifski** — converts recorded video frames into a high-quality, optimized GIF.
- **ffmpeg** — can also be used to convert a screen recording into GIF format.

## Recording the Demo

Before recording:

- Open YazSes and make sure dictation is working.
- Open the application where you want the dictated text to appear.
- Resize the windows so only the relevant area needs to be recorded.
- Avoid displaying private or sensitive information.

Start your screen recorder, demonstrate the hold-to-talk workflow, and stop recording once the transcribed text appears.

## Tips for a Good Demo

- Keep the GIF short.
- Record only the relevant part of the screen.
- Make the dictated text easy to read.
- Avoid unnecessary mouse movement.
- Remove or hide personal information before recording.
- Compress the GIF when possible to keep the file size small.

Once your GIF is ready, it can be used in documentation, bug reports, or feature demonstrations.
