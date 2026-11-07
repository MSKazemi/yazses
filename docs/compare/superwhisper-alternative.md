---
title: "SuperWhisper alternative — YazSes vs SuperWhisper for offline dictation"
description: "SuperWhisper vs YazSes: both can dictate offline. Price, open source, Linux, voice commands, meetings, and where SuperWhisper is the better tool."
---

# SuperWhisper alternative

**Short answer:** [SuperWhisper](https://superwhisper.com/) is a commercial,
closed-source dictation app with a free tier and a paid Pro plan. It can run
offline with on-device models, which makes it a much closer comparison to YazSes
than the cloud-only tools are. If you want a polished, commercially supported app
with mobile versions, SuperWhisper is a reasonable thing to pay for. YazSes is the
better choice if you want **free and open source (Apache-2.0)**, **voice
commands**, **offline transcription of existing recordings**, or **meeting capture
with speaker labels** from one install.

All statements about SuperWhisper on this page were read from its own website on
**2026-11-07**, and each carries its source in [Sources](#sources). Its Linux
support is days old as of that date, and its own pages disagree with each other
about it (see below), so check its site before you decide.

## At a glance

| | SuperWhisper | YazSes |
|---|---|---|
| Licence | Closed source, commercial product | **Apache-2.0** |
| Cost | Free tier that does not expire; Pro starts at $8.49/mo | **Free** |
| Works offline | Yes, with local models (cloud models optional) | **Yes** — on-device faster-whisper |
| Linux | Launched 2026-11-03: Wayland (Hyprland, KDE Plasma, GNOME) plus systemd | **Primary platform** (X11 and Wayland) |
| macOS / Windows | Yes | Yes (preview — see the [validation matrix](../validation-matrix.md)) |
| Mobile | iOS and Android | No |
| Voice commands | Not stated on its site | **Yes** (regex grammar → key sequences) |
| Transcribe existing files | Yes, on Pro | **Yes** (`yazses transcribe`, free) |
| Meeting capture + speaker labels | Not stated on its site | **Yes** (`yazses meeting`) |

## Where SuperWhisper is the better tool

Being straight about this matters, because for a lot of people it is the right
answer.

- **It is a commercial product with mobile apps.** SuperWhisper lists macOS,
  Windows, iOS and Android. YazSes is a desktop tool and has no phone app.
- **macOS and Windows are its established desktop targets.** Its documentation
  lists both as desktop apps. YazSes on macOS and Windows is a *preview*: supported,
  not yet verified on hardware by a person on a current build (see the
  [validation matrix](../validation-matrix.md)).
- **It offers cloud models when you want them.** Pro includes its cloud models
  (S1-Voice and S1-Language) as well as its local ones, with no usage limits or
  extra costs according to its docs, and one licence covers all your devices.
  YazSes keeps everything local by design, and its optional LLM cleanup is a local
  model that is off by default.
- **AI formatting modes.** SuperWhisper has formatting modes (Message, Mail) that
  rewrite what you said. Offline, that needs its local S1-mini model, which its docs
  say is English only. YazSes can do a version of this, but you opt in and its
  guards are deliberately conservative: a rewrite that changes the length too much
  or drops your tokens is rejected rather than typed.
- **A refund window.** Its Linux announcement mentions a 30-day refund on Pro.
  YazSes is free, so there is nothing to refund, but there is also no vendor
  behind it, only an issue tracker.
- **Hardware fit.** SuperWhisper's site says offline models "only run really well
  on Apple Silicon macs" and that Intel Macs work best with cloud models. Its Linux
  post says local models can use your CPU or GPU. YazSes deliberately targets CPU
  int8, so a strong GPU sits idle.

## Where YazSes does something SuperWhisper's site does not describe

(Absence from a vendor's site is not proof of absence; see
[What I could not verify](#what-i-could-not-verify).)

- **Free, with no tiers.** SuperWhisper's free tier does not expire, but Pro
  features beyond a 3,000-word trial need a paid plan, and its docs say file
  transcription requires Pro. YazSes has no paid tier.
- **Open source.** SuperWhisper's own comparison page calls it closed-source. You can read, build and audit YazSes, and the
  list of everything that could ever send bytes off your machine is published and
  enforced by a test ([ADR-019](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-019-egress-inventory-and-escalation.md)).
- **Voice commands.** Spoken phrases mapped by a regex grammar to real key
  sequences — *"undo that"*, *"save file"*, *"go to line 42"*.
- **Whole meetings.** `yazses meeting` captures hands-free and produces a
  speaker-labelled transcript, optionally with minutes written by a local LLM.
- **X11 as well as Wayland on Linux.** SuperWhisper's Linux page says it needs a
  Wayland desktop. YazSes probes the session at runtime and selects a working
  injection backend (`ydotool`, `wtype`, `xdotool` or clipboard paste), and
  `yazses doctor` reports which it picked. A hardware-verified record on GNOME
  and KDE Wayland is still to come
  ([#643](https://github.com/MSKazemi/yazses/issues/643)).
- **Accessibility.** VAD calibration, a dysfluency-friendly mode for stuttered or
  dysarthric speech, and an experimental, off-by-default EMG muscle-sensor trigger
  as a possible alternative to holding a key (no real-device evidence yet).

## What you should expect to give up

- **No mobile app.**
- **Setup is not one click.** There is a model download, and on Linux there are
  microphone and keyboard permissions to get right. `yazses doctor` and
  `yazses verify` exist because this step is where people get stuck.
- **It uses your CPU.** Transcription costs you some CPU per utterance.
- **macOS and Windows are previews.** If those are your only machines, weigh that
  honestly against SuperWhisper's longer track record there.

## What I could not verify

SuperWhisper's site did not state the following in any page read for this
comparison, so this page makes no claim about them: whether it has a voice-command or meeting-capture
feature, which specific local speech models it uses, whether an account is
required, and what the Linux version costs. Its homepage, docs and comparison pages
still listed macOS, Windows, iOS and Android (the docs said Linux was "Coming soon")
on 2026-11-07, while its Linux page and blog post said Linux had launched on
2026-11-03. Treat the Linux page and blog post as current.

## The honest summary

If you want a commercially supported app with mobile versions, and a monthly fee is
fine, SuperWhisper is a good choice and probably the easier one to live with.

If you want free, open source, auditable offline dictation, or *"…and run commands"*,
*"…and handle my recordings"*, *"…and take my meeting notes"*, or you work on X11,
those are the jobs YazSes was built for.

## Trying it

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)
yazses doctor
yazses enroll
yazses start
```

Hold your chosen key, speak, release. The text is typed into whatever window has
focus. They can coexist as long as you do not bind them to the same key.

## Sources

All fetched 2026-11-07.

- Platforms (macOS, Windows, iOS, Android), offline operation, "Intel Macs work best with Cloud models", free tier that does not expire, Pro from $8.49/mo: [superwhisper.com](https://superwhisper.com/) and [superwhisper.com/best-speech-to-text](https://superwhisper.com/best-speech-to-text)
- Local models work without internet, S1-mini for offline formatting, Pro includes cloud and local models, 3,000-word trial, file transcription requires Pro, one licence for all devices, Linux "Coming soon" (stale): [superwhisper.com/docs](https://superwhisper.com/docs)
- S1-mini is English only and runs on macOS and Windows: [superwhisper.com/docs/models/language](https://superwhisper.com/docs/models/language)
- Linux: Wayland (Hyprland, KDE Plasma or GNOME) and systemd, install by script: [superwhisper.com/linux](https://superwhisper.com/linux)
- Linux launch dated Nov 3, 2026, local or cloud processing on your own CPU or GPU, free tier that does not expire, 30-day refund: [superwhisper.com/blog/linux](https://superwhisper.com/blog/linux)
- "A commercial product with a free tier" and "closed-source": [superwhisper.com/vs/handy](https://superwhisper.com/vs/handy)

## Related

- [Full comparison with Dragon, Talon, Handy and others](../comparison.md)
- [YazSes vs Handy](yazses-vs-handy.md)
- [Wispr Flow for Linux](wispr-flow-linux-alternative.md)
- [Private and confidential work](../use-cases/private-offline-dictation.md)
- [Voice dictation on Wayland](../use-cases/voice-dictation-wayland.md)
