---
title: Voice typing for RSI, motor impairment and hands-free computing
description: Offline dictation built for accessibility — reduce typing with RSI, work hands-free with motor impairment, use a stutter-friendly dysfluency mode, drive the mouse by voice, and hear transcripts read back for eyes-free use.
---

# Accessibility, RSI and hands-free use

**Short answer:** if typing hurts, is slow, or is not possible, dictation stops
being a convenience and becomes the interface. YazSes is built with that in mind —
it calibrates to *your* voice rather than expecting broadcast-clear speech, it has
a mode for dysfluent speech, and it can be triggered without a keyboard at all.

Everything here runs offline, which matters more than usual for this audience:
assistive tooling that stops working when the network does is not dependable
assistive tooling.

## Repetitive strain injury

The common pattern is that you can still type, but every keystroke has a cost, so
you want to move the bulk of your text entry off the keyboard without changing how
you work.

- **Hold-to-talk keeps you in control.** One key held, speak, release. No wake
  word, no always-listening.
- **It types into whatever has focus** — your editor, browser, Slack, terminal —
  so nothing about your workflow has to change.
- **Voice commands cover the repetitive keystrokes** that hurt most: *"undo
  that"*, *"save file"*, *"go to line 42"*.

If holding a key is itself the problem, see [non-keyboard
triggers](#triggers-that-are-not-a-keyboard) below.

## Dysfluent speech — stutter and dysarthria

Mainstream speech recognition is trained on fluent speech and transcribes a
stutter literally: *"b-b-because"* comes out as *"b b because"*. YazSes has an
explicit mode for this:

```sh
yazses features enable dysfluency
yazses restart
```

It collapses stutters and repeats — *"b-b-because"* → *"because"* — as a
post-processing pass. It is recommended (not experimental), and it is opt-in
because collapsing repeats is wrong for people who do not need it.

Related capabilities worth knowing about:

| Capability | Enable with | For |
|---|---|---|
| Hesitation-Hold Endpointing | `yazses features enable hesitation` *(planned — not yet wired)* | Not being cut off mid-sentence when you pause |
| Breath-Paced Dictation | `yazses features enable breath` *(planned — not yet wired)* | Pacing around breath, not clock timeouts |
| Whisper-Aware Mode | `yazses features enable whispermode` | Speaking quietly, or with limited volume |
| Involuntary-Vocalization Excision | `yazses features enable involuntary` *(planned — not yet wired)* | Filtering involuntary sounds |
| Vocal-Strain Guard | `yazses features enable voicehealth` *(planned — not yet wired)* | Warning before you overuse your voice |

## Calibrating to your voice

The single biggest accuracy factor is the voice-activity threshold. If it is set
for a loud room and you speak quietly, your speech is discarded as silence — the
daemon logs `Silent audio -- discarding` and nothing is typed.

```sh
yazses enroll            # guided calibration wizard
yazses mic-level --set   # measure your actual level and write the threshold
yazses doctor --mic      # compare room noise against the current threshold
```

Lower the threshold for quiet or breathy speech. This is a five-minute fix that
resolves the majority of "it doesn't hear me" reports.

## Triggers that are not a keyboard

If holding a key is difficult or impossible, the trigger is replaceable — the rest
of the pipeline is unchanged:

- **EMG muscle sensor.** A USB muscle sensor over serial can act as the
  hold-to-talk trigger, so a small muscle contraction starts and stops dictation.
  Configure it under `[emg]` with the serial device path.
- **Hands-Free Auto-Stop** (`yazses features enable autostop` *(planned — not yet wired)*) ends the burst on
  silence rather than on key release.
- **Wake-word activation** exists but is marked experimental and is not
  recommended yet — it is listed honestly as such in `yazses features`.

## Eyes-free use

If you cannot or do not want to look at the screen:

```sh
yazses features enable read-back
```

The transcript is spoken back to you with an on-device TTS model (downloaded on
first use — still no cloud). Complementary capabilities include Earcon Feedback
for non-speech audio cues, Screen-Reader Pacing to cooperate with a screen
reader, and Interruptible Proofreading.

## Driving the pointer by voice

Where there is no accessibility tree to target, a numbered grid overlay lets you
move and click by voice. **Planned — designed and tested, not yet wired**, so
`features enable` refuses it for now:

```sh
yazses features enable mousegrid
```

Say a grid number to move the cursor, then *"click"*. There is also a Head-Pointer
capability, and an experimental camera-based Glance-Type mode that focuses the
window you look at (X11 only — Wayland does not allow an application to focus
another window).

## Honest limits

- Several of the more exotic input modalities (vocal joystick, mouth-sound switch
  access, pitch-contour gestures, lip-reading, sign-language input) are marked
  **experimental — not advised yet** in `yazses features`. They exist, they are
  not yet dependable, and the CLI says so rather than pretending otherwise.
- Dictation accuracy for heavily dysarthric speech varies a great deal by
  individual. The opt-in learning loop (`yazses tune`) is designed to close that
  gap from *your own* corrections over time, but it needs usage to work.
- Accessibility feedback is the most valuable feedback this project can receive.
  If something does not work for you, [please open an
  issue](https://github.com/MSKazemi/yazses/issues).

## Related

- [Install on Linux](../install-linux.md) · [macOS](../macos-install.md) · [Windows](../windows-install.md)
- [Change the hotkey](../how-to/change-hotkey.md)
- [Troubleshooting](../troubleshooting.md)
- [Private offline dictation](private-offline-dictation.md)
- [Research: muscle & brain control](../research/muscle-brain-control.md) — why a
  ~$50 muscle sensor beats a $1,000 EEG headset as a hands-free trigger, and what
  the $10,000–20,000 assistive-tech market leaves unserved on Linux
- [Research: eye control](../research/eye-control.md) — what a webcam can honestly
  know about where you look, and where gaze dwell can replace a keypress
