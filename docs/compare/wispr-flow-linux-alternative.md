---
title: Wispr Flow for Linux — the offline, open-source alternative
description: Wispr Flow has no Linux client and its own documentation states that offline transcription is not available. Here is what it does well, and how YazSes compares for people who need Linux, offline dictation, or both.
---

# Wispr Flow alternative for Linux

**Short answer:** [Wispr Flow](https://wisprflow.ai/) does not ship a Linux
client — it lists Mac, Windows, iPhone and Android — and it is a cloud service.
Its own documentation is explicit about the second point: under system
requirements it states *"Offline transcription is not available."*

If either of those is a hard requirement for you — you are on Linux, or your
work cannot leave the machine — you need a different tool, not a workaround.
YazSes is built for exactly that constraint. This page is honest about what you
give up.

## The two things that decide this

| | Wispr Flow | YazSes |
|---|---|---|
| Linux | Not offered | **Primary platform** (X11 and Wayland) |
| Works offline | No — cloud transcription | **Yes** — on-device faster-whisper |
| Account required | Yes | **No** |
| Cost | Freemium (a weekly word allowance, then Flow Pro) | **Free** |
| Licence | Proprietary | **Apache-2.0** |
| macOS / Windows | Yes | Yes |
| Mobile | iPhone and Android | No |

## What Wispr Flow does better — this is the real trade

Do not switch expecting a like-for-like replacement. Wispr Flow's whole product is
the **cleanup layer**, and it is good at it: you speak messily, and what lands is
polished, formatted prose with the filler removed. It also carries the things a
funded commercial product can carry — a very wide language list, per-context
writing styles, mobile apps, and formal compliance certifications.

YazSes can do a version of this, but you have to opt in and supply the model. Its
LLM cleanup runs a **local** model and is off by default, and its guards are
deliberately conservative: a rewrite that changes the length too much or drops your
tokens is rejected rather than typed. That is the correct trade for an offline tool
— but it is a smaller, stricter feature than Wispr Flow's, and pretending otherwise
would waste your time.

If polished AI reformatting is the reason you want dictation at all, and Linux and
privacy are not constraints for you, **Wispr Flow is a reasonable thing to keep paying for.**

## What YazSes does that Wispr Flow structurally cannot

These follow from running on your own machine rather than from being newer:

- **It works with no network.** On a plane, in a SCIF, on an air-gapped box.
  There is no allowance to run out of and no service to be down.
- **Nothing you say is transmitted.** This is the difference between a vendor
  *promising* not to retain your audio and there being no audio to retain. For
  clinical, legal, and interview work that distinction is often the whole
  compliance argument.
- **It runs on Linux**, which is the reason most people read this page.
- **The same install does three jobs** — live dictation, transcribing existing
  recordings (`yazses transcribe`), and hands-free meeting capture with speaker
  labels (`yazses meeting`).
- **Voice commands**, mapped by a regex grammar to real key sequences.
- **Accessibility work** — VAD calibration, a dysfluency-friendly mode for
  stuttered or dysarthric speech, and an optional EMG muscle-sensor trigger for
  people who cannot hold a key.

## What you should expect to give up

Said plainly, so there are no surprises:

- **No mobile app.** YazSes is a desktop tool.
- **Setup is not one click.** There is a model download, and on Linux there are
  microphone and keyboard permissions to get right. `yazses doctor` and
  `yazses verify` exist because this step is where people get stuck.
- **Formatting is more literal by default.** Turning spoken punctuation into
  symbols is opt-in (`[commands] voice_punctuation`), because those words also
  occur in ordinary speech.
- **It uses your CPU.** Transcription happens on your machine, so it costs you
  some CPU per utterance instead of costing a server somewhere.

## Trying it

```sh
sudo snap install yazses      # or: pipx install yazses
yazses doctor
yazses enroll
yazses start
```

Hold your chosen key, speak, release. The text is typed into whatever window has
focus.

## Related

- [Full comparison with Dragon, Talon, Handy and others](../comparison.md)
- [Dragon NaturallySpeaking on Linux](dragon-naturallyspeaking-linux-alternative.md)
- [Private and confidential work](../use-cases/private-offline-dictation.md)
- [Running fully air-gapped](../how-to/air-gapped.md)
