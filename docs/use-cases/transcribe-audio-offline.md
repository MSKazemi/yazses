---
title: Transcribe audio files offline with speaker labels — local Whisper transcription
description: Convert an existing audio or video recording into text on your own machine, with optional speaker diarization and named speakers. No upload, no account, no per-minute fee — one command.
---

# Transcribing recordings offline

**Short answer:** `yazses transcribe <file>` turns an existing recording into text
on your own machine. Add `--diarize` and it labels who spoke when. Nothing is
uploaded, there is no per-minute charge, and it works on a laptop CPU.

```sh
yazses transcribe interview.m4a
yazses transcribe interview.m4a --diarize          # label Speaker 1, Speaker 2, …
yazses transcribe interview.m4a --diarize --format srt
```

## Why not just upload it

Online transcription services are convenient and often accurate, but they come
with three costs that rule them out for a lot of recordings:

1. **The recording leaves your control.** For an interview with a confidential
   source, a patient consultation, a legal deposition, or an internal meeting,
   that is frequently unacceptable.
2. **Per-minute pricing.** A backlog of long recordings gets expensive quickly.
3. **They need to be online.** Large media files over a slow connection are
   painful, and on a restricted network the upload may not be permitted at all.

Local transcription trades wall-clock speed for privacy and cost. On a CPU it is
not instantaneous, but it is unattended — start it and come back.

## Any format

Input decoding handles essentially any audio or video container, because it
decodes through PyAV (with an ffmpeg CLI fallback) down to the 16 kHz mono the
model expects. MP3, M4A, WAV, FLAC, OGG, MP4, MKV — you do not need to convert
anything first, and there is no extra dependency to install for it.

## Speaker labels (diarization)

With `--diarize`, the transcript is attributed by speaker:

```
Speaker 1:  So the question I keep coming back to is …
Speaker 2:  Right, and that's exactly where the previous approach broke down.
```

Speakers are distinguished by **voice embeddings and clustering** — not by pitch
— using a small int8 ONNX model (about 15 MB, fetched once). Diarization is an
optional extra, so if you do not need it you do not pay for it in install size:

```sh
yazses features enable diarize
```

### Naming speakers

Three levels, in priority order:

1. **Tell it directly** — `--names "Alice,Bob"` or `--rename` to relabel after
   the fact.
2. **Enrolled voiceprints** — if someone has explicitly enrolled, they are
   recognised and named automatically in future recordings. This is opt-in and
   consent-gated by design; YazSes never silently enrolls a voice it hears.
3. **Otherwise** — `Speaker 1`, `Speaker 2`, …

## Output formats

| Format | Use |
|---|---|
| `txt` | Plain text |
| `md` | Markdown, speaker-attributed |
| `srt` | Subtitles |
| `vtt` | Web subtitles |
| `json` | Structured, with word-level timings |

Subtitle output makes this a practical local workflow for captioning your own
video — transcribe, then load the `.srt` alongside the file.

## Whole meetings, live

Transcribing a file after the fact is one job; capturing a meeting as it happens
is another. YazSes does both from the same install:

```sh
yazses meeting start
# … the meeting happens …
yazses meeting stop      # → labelled transcript, and optional minutes
```

Meeting Mode keeps a rolling live transcript during capture, then re-runs accurate
batch diarization at stop — so you get both immediacy and quality. It can also
generate speaker-aware minutes with a local LLM. See [offline meeting
notes](../meeting-notes-offline.md) for the full workflow and how it compares to
Otter.ai, Fireflies and Granola.

## Honest limits

- **It is not real-time on CPU.** A long recording takes a meaningful fraction of
  its own duration to process. Plan for unattended runs.
- **Diarization is good, not perfect.** Heavy crosstalk, more than a handful of
  speakers, or poor room audio will degrade attribution. Fix labels afterwards
  with `--rename` rather than re-running.
- **Diarization needs the optional extra.** If you ask for speaker labels without
  it installed, YazSes warns you rather than silently producing an
  un-attributed transcript.
- **Accuracy tracks the model you chose.** A larger local model is more accurate
  and slower; pick per job.

## Related

- [Transcribe recordings tutorial](../tutorials/transcribe-recordings.md)
- [Offline meeting notes](../meeting-notes-offline.md)
- [Private offline dictation](private-offline-dictation.md)
- [CLI reference](../cli-reference.md)
