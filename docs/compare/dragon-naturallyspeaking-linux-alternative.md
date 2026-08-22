---
title: Dragon NaturallySpeaking for Linux — why it does not exist, and what to use instead
description: Dragon has never had a Linux version and the Mac version was discontinued in 2018. Here is an honest look at what Dragon actually does better, what the open-source offline options on Linux are, and how close YazSes gets.
---

# Is there a Dragon NaturallySpeaking for Linux?

**Short answer: no, and there never has been.** Dragon is a Windows product.
Nuance's own system requirements for Dragon Professional Individual list only
Windows releases — no Apple and no Linux entry appears anywhere in them. A macOS
version existed between 2014 and 2018 and was
[terminated](https://en.wikipedia.org/wiki/Dragon_NaturallySpeaking); it did not
come back after Microsoft acquired Nuance in March 2022.

So if you are on Linux, the real question is not "how do I run Dragon" but "what
is the closest thing that actually exists". This page answers that honestly,
including the parts where Dragon is still better.

## Running Dragon on Linux anyway: the options, and why they disappoint

People usually arrive here having already tried one of these.

| Route | Verdict |
|---|---|
| Wine / Proton | Dragon depends on deep Windows audio and accessibility APIs. This is not a supported configuration and text injection into Linux apps is the part that breaks. |
| A Windows VM | Dragon will run, but it dictates *into the VM*. Getting text back into your Linux editor is the actual problem, and the VM does not solve it. |
| Dual boot | Works, because you are simply using Windows. It is not a Linux answer. |

The pattern is the same in each case: even when recognition works, **the text has
nowhere to go**. Dictation is only half a dictation tool; the other half is putting
the words into the window you are actually looking at.

## What Dragon genuinely does better

This matters more than a feature table, so it goes first.

- **Specialist vocabularies.** Dragon's medical and legal editions are trained on
  domain vocabularies built over decades. No open-source offline tool on Linux
  matches them for clinical or legal dictation. If that is your work, the honest
  advice is to keep a Windows machine.
- **Maturity.** Dragon has had a very long time to handle accents, correction
  workflows, and long-form dictation.
- **Correction UI.** Dragon's "select that / correct that" flow is a genuinely
  refined interaction that open-source tools generally approximate rather than match.

Dragon is also a **paid commercial product**, and its consumer edition was
discontinued — so the entry price is no longer a small one.

## The Linux options that do exist

All of these run offline and are free and open source.

| Tool | Licence | Engine | Activation | Also macOS / Windows |
|---|---|---|---|---|
| **YazSes** | Apache-2.0 | faster-whisper (CPU int8) | Hold-to-talk key | **Yes** |
| [Vocalinux](https://github.com/VocaHQ/vocalinux) | AGPL-3.0 | whisper.cpp / Whisper / VOSK | Toggle or push-to-talk | No |
| [Speech Note](https://github.com/mkiol/dsnote) | MPL-2.0 | whisper.cpp / faster-whisper / VOSK / Coqui / april-asr | Global shortcut | No (also Sailfish OS) |
| [nerd-dictation](https://github.com/ideasman42/nerd-dictation) | GPL-3.0 | VOSK | `begin` / `end` commands | No |
| [Handy](https://github.com/cjpais/Handy) | MIT | whisper.cpp | Hotkey | Yes |
| [Talon Voice](https://talonvoice.com/) | Not open source | — | Voice + noise + eye tracking | Yes (Linux is X11) |

## How close does YazSes get to Dragon?

**On general prose, closer than most people expect.** YazSes transcribes with
faster-whisper, which is a modern Whisper-class model, and for ordinary writing —
email, notes, documentation, chat — the gap to Dragon is modest.

**On specialist vocabulary, not close.** YazSes has a personal dictionary
(`yazses vocab add`) that fixes words it keeps mis-hearing, and an initial-prompt
vocabulary that biases recognition. That helps with your own jargon, project names
and colleagues' names. It is not a substitute for a medical vocabulary pack.

**On correction workflow, different rather than worse.** There is no
"select that and correct it" dialogue. What exists instead is an opt-in, encrypted,
on-device learning corpus: `yazses tune` reads your own corrections and proposes
concrete config changes.

Where YazSes wins outright is the part Dragon cannot compete on at all: it runs on
Linux, it runs offline with no account and no subscription, and nothing you say
leaves the machine.

## Getting started on Linux

```sh
sudo snap install yazses      # or: pipx install yazses
yazses doctor                 # checks mic, keyboard access and text injection
yazses enroll                 # ~30 s calibration to your voice and room
yazses start
```

Two Linux-specific things `doctor` will catch, because they are the usual causes of
"it installed but nothing happens": `libportaudio2` is needed for microphone capture
and is **not** pulled in by pipx, and reading the keyboard needs membership of the
`input` group — after `sudo usermod -aG input $USER` you must log out and back in.

## Related

- [Full comparison with Talon, Handy, Wispr Flow and others](../comparison.md)
- [YazSes vs nerd-dictation](yazses-vs-nerd-dictation.md)
- [YazSes vs Vocalinux](yazses-vs-vocalinux.md)
- [Offline voice dictation on Linux](../use-cases/voice-dictation-linux.md)
- [Law, medicine and journalism](../use-cases/confidential-professions.md)
