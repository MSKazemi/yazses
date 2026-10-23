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
post-processing pass. It is in the recommended tier, so a fresh install already
switches it on in the first config the daemon writes; the commands above matter only
if your config predates that or you turned it off. If you do not stutter and want
repeats kept verbatim, run `yazses features disable dysfluency`.

Related capabilities worth knowing about:

| Capability | Enable with | For |
|---|---|---|
| Hesitation-Hold Endpointing | `yazses features enable hesitation --force` *(experimental; needs `autostop`)* | Not being cut off mid-sentence when you pause |
| Whisper-Aware Mode | `yazses features enable whispermode` | Speaking quietly, or with limited volume |
| Involuntary-Vocalization Excision | `yazses features enable involuntary` | Filtering involuntary sounds |
| Vocal-Strain Guard | `yazses features enable voicehealth --force` *(experimental; needs the `prosody` extra)* | A break suggestion when your voice shows rising strain |

Breath-Paced Dictation — pacing around breath rather than clock timeouts — is planned:
[designed, not built](../v2-features.md#designed-not-built), so `yazses features enable
breath` refuses it in this build.

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

- **Face-gesture switch.** `yazses features enable facegesture --force` makes a held
  facial movement the hotkey: open your jaw (or raise your brows) to start dictating,
  relax to stop. It needs only the webcam already in your laptop — no armband, no key —
  and runs entirely on your machine, frames in RAM and never stored (ADR-011). Pick the
  movement with `[facegesture] gesture` (`jaw_open`, `brow_raise`, `mouth_pucker`,
  `smile`, `eyes_closed`); if it fires while you talk or laugh, raise `hold_threshold` or
  `min_hold_frames`. Experimental: it has been built and unit-tested, but the thresholds
  that suit *your* face have not been measured, so please report what worked.
- **Face and head chords.** `yazses features enable gesture` lets a *combination* of
  face and head movements trigger an action, with the same webcam and the same
  on-device rule (nothing leaves your machine). It binds nothing until you add a
  chord under `[gesture.chords]`, for example:

  ```toml
  [gesture]
  enabled = true

  [gesture.chords]
  "brow_raise+nod" = "recenter"      # raise your brows and nod: make this head pose neutral
  "jaw_open+hold"  = "pause_pointer" # keep your jaw open for 0.8 s: stop the pointer
  ```

  The tokens are the five face movements above plus `nod`, `shake`, `tilt` and `hold`.
  `hold` means "what you are holding has stayed held" for `[gesture] hold_ms`
  (800 ms by default, a starting value nobody has measured). It is measured in time,
  not frames, so it takes the same time on a slow camera as a fast one. It needs a
  token you can hold -- a face movement or `tilt`; `nod` and `shake` are over as soon as
  they happen, so `nod+hold` is refused. A chord and the same chord with `+hold` cannot
  both be bound, because the plain one would always fire first; YazSes tells you which
  line it ignored (it appears in `yazses doctor` and `yazses gesture status`).

  While a facial expression moves your head, the Head-Pointer is held still. The pointer
  runner and the gesture runner look at the same camera frame independently, so the pointer
  can follow the first frame before the hold lands; YazSes then moves it back by exactly
  that step (`[gesture] onset_rewind_ms`, 150 by default, 0 turns it off). You may see
  the pointer twitch for one frame; it does not drift. Head tokens (`nod`, `shake`) are
  different: the pointer follows the head while the nod is being made, because nothing
  knows a nod has started until it is finished. Chord actions are limited to pausing or
  recentering the pointer and reversible spoken commands (`command:undo`); anything else
  is refused. Every number here is provisional: no false-activation study exists yet.
- **EMG muscle sensor.** A USB muscle sensor over serial can act as the
  hold-to-talk trigger, so a small muscle contraction starts and stops dictation.
  Configure it under `[emg]` with the serial device path.
- **Hands-Free Auto-Stop** (`yazses features enable autostop`, then restart) lets you tap the hotkey once
  instead of holding it: the burst ends on silence (or a second tap) rather than on key release. A tap is a
  press shorter than `[hotkey] hold_threshold_ms`; a longer hold is still ordinary hold-to-talk. It needs a
  modifier hotkey, which is the default.
- **Hesitation-hold** (`yazses features enable hesitation --force`, experimental) works on top of Hands-Free
  Auto-Stop: when you trail off with a held "uhh…" or "mmm…", the turn waits `[hesitation] hold_extra_ms`
  (1200 ms by default) longer than `[autostop] silence_timeout_ms` before it ends, so a thinking pause is
  not cut off. The auto-stop timeout stays the only base threshold; it has no effect in hold-to-talk. Its
  detector was tuned on synthetic signals only, not on recorded speech.
- **Wake-word activation** is planned — designed, not yet wired, so
  `yazses features enable wakeword` refuses it. It is listed honestly as such in
  `yazses features`.

## Eyes-free use

If you cannot or do not want to look at the screen:

```sh
yazses features enable read-back
```

The transcript is spoken back to you with an on-device TTS model (downloaded on
first use — still no cloud). Complementary capabilities include Earcon Feedback
for non-speech audio cues and Screen-Reader Pacing to cooperate with a screen
reader.

Interruptible Proofreading (`proofback`, experimental) builds on read-back: while a
dictation is being read to you, hold the dictation key at the word you want to change
and say the correction. Everything from that word to the end of that dictation is
replaced by what you say. It only ever deletes text YazSes itself just typed (with
backspaces from the end, as "scratch that" does); when it cannot be sure where that
text is, it types your correction as ordinary dictation instead. If the correction
cannot be typed after the old words were erased, YazSes types them back. If that fails
too, it puts them on the clipboard and tells you. Word timing is estimated, and it is
untested on real hardware.

```sh
yazses features enable proofback --force
```

## Driving the pointer by voice

Where there is no accessibility tree to target, a numbered grid overlay lets you
move and click by voice. It is **experimental** (tuned on synthetic input only),
so `features enable` asks for `--force`; it needs absolute pointer motion (X11 or
macOS), and the numbered grid is drawn by the overlay when `[overlay]` is on:

```sh
yazses features enable mousegrid --force
```

Say *"mouse grid"*, then a grid number to move the cursor, then *"click"*. See
[click anywhere by voice](../how-to/voice-mouse-grid.md). There is also an experimental
Head-Pointer (`yazses features enable headpointer`), which moves and clicks by head pose,
and an experimental camera-based Glance-Type mode that focuses the window you look at
(X11 only — Wayland does not allow an application to focus another window). Both are
off by default, neither has been validated with users yet, and every speed and dwell
setting is a provisional starting value — please report what works for you.

## Switch scanning with mouth sounds

If you cannot speak reliably at all, Mouth-Sound Switch Access gives you a few actions
from two short mouth sounds. It is single-switch scanning, the common switch-access method
in AAC. It is **experimental**, so `features enable` asks for `--force`. The overlay draws
the highlight when `[overlay]` is on and the `desktop` extra is installed. Where the overlay
cannot run, you can hear the scan instead (see below):

```sh
yazses features enable mouthswitch --force
yazses restart
yazses handsfree resume      # opens the microphone; nothing listens before this
```

**Pop your lips** and a row of items appears across the top of the screen: Enter, Undo,
Scroll up, Scroll down, Click. One item is lit at a time, and the light moves on every
1.2 s (`[mouthswitch] dwell_s`). **Click your tongue** to run the lit item. Pop again to
stop the scan, whether or not you chose anything.

- After a click the scan keeps going. The item you chose stays lit for one more step, so
  clicking again runs it again: scroll down, then scroll down once more, with no pop in
  between. Then the light moves on as before.
- A tongue click does nothing unless a scan is running.
- A scan stops after three passes with no click, counted from your last click.
- Nothing is heard while you dictate.
- "Click" and "Scroll" act on the pointer where it already is. Enter and Undo work like the
  spoken commands. You can change the list with `[mouthswitch] scan_items`. A phrase YazSes
  does not know, or one that would need a confirmation (such as "save"), is left out when
  the daemon starts, and the log says so.
- `yazses handsfree pause`, or your stop phrase if you set one, closes the microphone.

**Hearing the scan instead of seeing it.** The overlay is not started on a native Wayland
session, and it needs the `desktop` extra. Without it, YazSes announces each step instead,
using what you have turned on:

- with earcons on (`yazses features enable earcon`), a short tick plays at every step. The
  first item has a lower tick, so you can count the steps;
- with read-back on (`yazses features enable read-back`), the offline voice also says the
  item's name ("enter", "undo", "scroll down"). An item stays lit until its name has been
  said, however long that takes. Read-back needs the `tts` extra,
  fetches its voice model on first use, and also reads your dictation back;
- to hear the names **without** your dictation being read back, leave read-back off and
  set `speak_names = true` under `[mouthswitch]`. The switch then builds the same offline
  voice for itself, using your `[tts]` voice and speed. It needs the `tts` extra and a
  voice model that is already on this computer, because it never downloads one. To fetch
  the model, turn read-back on once, start YazSes, then turn read-back off again. Without
  the extra or the model, the steps are announced with earcon ticks only, and the log
  says why.

```toml
[mouthswitch]
enabled = true
speak_names = true   # say each item's name; your dictation is still not read back
```

What you hear is what a click selects: the item announced when your click began is the item
that runs. With neither earcons nor a voice, the switch does not start, and
`handsfree resume` says why. Headphones are a good idea. The scan's microphone also hears
the speakers, and a click is not detected while a tick or a name is sounding, or for
0.4 s after it ends. So when the scan is announced, each item stays lit for its tick or
name, then those 0.4 s, then a full `dwell_s` in which your click is heard: click after
the name has finished. A long name makes the scan slower, not the time to click shorter.
With names on and the default 1.2 s, a step takes about 2.3 to 2.8 s instead of 1.2 s (by
the estimate of how long each name takes to say), so a pass over the five default items
takes about 12 s; lower `dwell_s` if that is slower than you need. A click
right at the very end of a step may still be missed if the next item's tick starts on top
of it.

It has not been tried with real mouth sounds yet. Its thresholds were tuned on synthetic
clicks and pops. A keyboard tap or a knock on the desk may count as a tongue click, so a
click during a scan can run the lit item. Because the scan keeps going after a click, pop
to stop it when you are done. The spoken announcements have only been tested
with a simulated voice, and how long a name takes to say is estimated, not measured.
Please report what works for you.

## Typing by Morse with your voice

If you can make one sound reliably but not words, Vocal Morse lets you type every letter
and digit with it. A short hum is a dot, a long hum is a dash, and each decoded letter is
typed. Speech-to-text is not run. It is **experimental** and off by default:

```sh
yazses features enable morsevox --force
yazses restart
```

- **Start:** hum one long, steady tone (1.5 s, `[morsevox] entry_hum_s`), or say
  "morse mode".
- **Letters and words:** a pause of about 0.6 s ends a letter, and about 1.4 s adds a space.
- **Stop:** stay silent for 3 s (`[morsevox] exit_silence_s`), or send **SK**, the
  end-of-work prosign: `...-.-`, keyed as one character with no letter pause between the
  S and the K. SK is not typed, and Morse mode ends as soon as the letter pause after it
  has passed.
- SK counts only as one whole character. "S", a letter pause, then "K" types the letters
  `sk`. If you send SK in the middle of a word, the letters before it stay typed and
  the mode ends there.

The timings were tuned on synthetic signals only, not on a real voice or a real room.
Please report what works for you.

## Honest limits

- Three of the more exotic input modalities, the vocal joystick (`vocaljoystick`),
  pitch-contour gestures (`contour`) and mouth-sound switch access (`mouthswitch`), are
  wired but marked **experimental — not advised yet** in `yazses features`: they need
  `--force`, and their thresholds were tuned on synthetic signals only. Lip-reading and
  sign-language input are **planned — designed, not yet wired**, so
  `yazses features enable` refuses them. The CLI says which is which rather than
  pretending otherwise.
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
