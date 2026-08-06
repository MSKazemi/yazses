---
title: Offline meeting transcription & minutes — no cloud, no upload
description: Record, transcribe and summarise whole meetings entirely on-device with speaker labels. A private alternative to Otter.ai, Fireflies and Granola for confidential meetings.
---

---
title: Offline meeting notes — a local, open-source Otter.ai alternative
description: Record a meeting and get a speaker-labelled transcript and minutes entirely on your own machine. No cloud, no account, no per-seat fee, and no bot joining the call. Free and open source.
---

# Offline meeting notes — transcripts and minutes without the cloud

**Short answer:** if your meetings must not be uploaded anywhere — clinical, legal,
HR, pre-publication research, or just internal — YazSes records them on the machine
in front of you, writes a **speaker-labelled transcript**, and can draft **minutes**
with a local LLM. Nothing is uploaded, no account is required, no bot joins the call,
and there is no per-seat fee.

This page is deliberately honest about what YazSes does *not* do. There are good
tools in this space; some will fit you better.

## The 60-second version

```sh
pipx install 'yazses[diarization]'     # speaker labels need this extra (~15 MB of models, fetched once)

yazses meeting start                   # hands-free — no key to hold
# … the meeting happens …
yazses meeting stop                    # → speaker-labelled transcript
```

You get a transcript like:

```
Speaker 1: Right, let's start with the migration timeline.
Speaker 2: We're blocked on the staging database until Thursday.
Speaker 1: Then we move the cutover to Monday. I'll tell the customer.
```

Then, optionally:

```sh
yazses meeting relabel <id> --rename speaker_1=Amara         # fix the labels once
yazses meeting enroll  <id> --speaker speaker_1 --name Amara # …or teach it a voice, so it's named next time
yazses meeting notes   <id>                                  # summary, decisions, action items (needs a local LLM)
```

Everything above runs on CPU. No network access is used at any point.

## How it compares

| | **YazSes** | Otter.ai | Fireflies / tl;dv / Granola | Meetily, TalkTrack & similar local tools | Whisper + your own scripts |
|---|---|---|---|---|---|
| Audio leaves your machine | **Never** | Yes | Yes | No | No |
| A bot joins your call | **No** | Yes (or app recording) | Yes | Varies | No |
| Account required | **No** | Yes | Yes | Usually no | No |
| Cost | **Free, Apache-2.0** | Paid per seat — Business is [$30/user/month, or $19.99 annual, minimum 5 seats](https://sonix.ai/resources/otter-ai-pricing/) | Paid per seat | Free | Free |
| Speaker labels | **Yes** (opt-in extra) | Yes | Yes | Usually yes | You build it |
| Minutes / action items | **Yes** (opt-in, local LLM) | Yes | Yes | Often yes | You build it |
| Captures a remote call's *other* participants | **Only via the room mic** — see below | Yes | Yes | Often yes (system audio) | Depends |
| Also a hold-to-talk dictation tool | **Yes** | No | No | No | No |
| Also transcribes existing recordings | **Yes** (`yazses transcribe`) | Yes | Some | Some | Yes |
| Install | `pipx` · APT · Snap | SaaS | SaaS | Often Docker | n/a |

### Where YazSes is genuinely different

Local meeting transcription is **not** a category YazSes invented — [Meetily](https://meetily.ai/),
[TalkTrack](https://github.com/ObscureAintSecure/TalkTrack), and others do it well, and
several are excellent if a meeting recorder is all you want.

What is different here is that Meeting Mode is **one mode of a general on-device speech
daemon**, not a separate product:

- The same install, the same downloaded Whisper model, and the same config also give you
  **hold-to-talk dictation into any app** and **voice commands** for your editor and terminal.
- The same speaker-embedding machinery powers `yazses transcribe <file>` for interviews and
  lectures you recorded elsewhere.
- **No bot, no browser extension, no Docker.** It is a daemon you install from `pipx`, APT,
  or Snap, and it records the room.
- Enrolled voiceprints are stored **encrypted, on-device only**, and are never created
  without you explicitly asking. Biometric data never leaves the machine.

If you want a meeting recorder *and* you dictate every day, that consolidation is the
argument. If you only ever need meeting notes, a dedicated tool is a reasonable choice.

### Where YazSes is the wrong tool

Read this part before you install anything.

- **It records the microphone, not the call.** For an **in-person meeting** — a room, a
  table, a phone in the middle — this is exactly right, and it is the case Meeting Mode was
  built for. For a **remote call**, YazSes hears only what your microphone hears, so remote
  participants come through your speakers or not at all. If you need clean per-participant
  audio from Zoom or Teams, use a tool that captures system audio or joins the call.
- **Minutes need a model you supply.** `yazses meeting notes` runs a local GGUF LLM you
  point it at (the `notes` extra plus, e.g., a Q4_K_M Phi-4-mini or Qwen2.5-3B). There is
  no bundled model and no API fallback. Without it you still get the full transcript.
- **Speaker labels are `Speaker 1..N` until you name them.** Diarization finds *how many*
  distinct voices there were and groups turns; it does not know who anyone is. You name
  them once with `relabel`, or enroll a voiceprint so they are recognised next time. Note
  that `meeting enroll` reads the stored recording, so it only works for a meeting captured
  with `[meeting] retain_audio = true` — by default the audio is already gone.
- **Accuracy is CPU Whisper accuracy.** On a good mic in a quiet room this is strong. In a
  large echoey room with six people talking over each other, a cloud service with per-channel
  audio will beat it. That is the trade you are making for privacy.
- **English-tuned by default.** It ships `*.en` models; other languages need a different one.

## What actually happens to your audio

| Stage | Where it lives |
|---|---|
| During the meeting | Streamed to a WAV file in the YazSes data directory on your machine, plus a `live.jsonl` rolling transcript so a crash does not lose the meeting |
| At `meeting stop` | Transcribed and diarized locally, then the **recording is deleted** unless `[meeting] retain_audio` is on |
| Afterwards | The transcript, and any notes, stay in the meeting folder — plain files you own |
| Enrolled voiceprints | Encrypted in the on-device learning corpus, machine-bound, never transmitted |

No telemetry is collected and no network request is made by the meeting pipeline. See the
[privacy statement](privacy-statement.md).

## Recording other people — please read

Consent rules for recording conversations vary by country and, in the US, by state; some
jurisdictions require **all** parties to consent. YazSes gives you the technical ability to
record; it does not give you the legal right to. Tell people they are being recorded, and
follow the law where you are. Voiceprint enrollment in particular is biometric data — only
enroll people who have agreed to it.

## Related

- [Meeting Mode reference](features.md#meeting-mode) — every flag and config key
- [Transcribe recordings offline](use-cases/transcribe-audio-offline.md) — the `yazses transcribe` path for files you already have
- [Private & confidential work](use-cases/private-offline-dictation.md) — the wider case for keeping audio on the machine
- [YazSes vs. other dictation tools](comparison.md) — Dragon, Talon, Wispr Flow
- [Install guide](install-linux.md) · [Configuration](configuration.md) · [FAQ](faq.md)
