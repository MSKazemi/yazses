---
title: Transcribe research interviews on your own computer
description: A tool-neutral guide for qualitative researchers and journalists — why cloud transcription raises consent and ethics questions, and the free local options.
---

# Transcribing research interviews without the audio leaving your computer

**Short answer:** you can transcribe interview recordings on your own machine, for free,
including speaker labels. Installation and a one-time model download need a network
connection; after that the audio and the transcript stay on the computer. Whatever tool you
choose, the output is a **first draft that must be checked against the recording** before it
becomes data.

This page is written for people transcribing interviews under an ethics approval — PhD
researchers, qualitative and health-services researchers, oral historians, and journalists
protecting sources. It names the realistic options rather than only this project's.

## Why this comes up

Automated transcription services are fast, accurate and cheap, and for a lot of research
they are simply not usable, because using one means sending participant audio to a third
party. That raises three separate questions, and they are not the same question:

1. **Consent.** Did participants agree to their recording being processed by a named
   external company? A generic "recordings will be transcribed" clause usually does not
   cover it.
2. **Ethics approval.** Many protocols specify how data is handled end to end. Introducing
   a processing service that was not in the approved protocol can require an amendment.
3. **Onward use.** Some services reserve the right to use uploaded material to improve
   their models. That is a use participants did not agree to, and it is difficult to undo.

None of this makes cloud transcription wrong — plenty of institutions permit it, some with a
data-processing agreement in place. It does mean the decision belongs in the protocol rather
than in a moment of convenience.

## What "local transcription" actually means

The honest version, because this gets overstated:

- **The speech model runs on your own CPU.** Your recording is not uploaded to anyone.
- **Installing the software needs a network connection**, and so does the first download of
  the speech model — typically a few hundred megabytes, once.
- **After that, transcription works with networking disabled.** You can verify this yourself:
  disconnect, and transcribe.
- It is **slower than a cloud service** on the same file, but it is unattended. Start it and
  come back.
- It is **free**, which matters when the alternative is per-minute pricing on a backlog of
  two-hour interviews.

## The realistic options

All three are free and open source, and all three run entirely on your machine.

| | Best for |
|---|---|
| [**whisper.cpp**](https://github.com/ggerganov/whisper.cpp) | A single C++ binary, no Python. Good if you want the fewest moving parts and are comfortable on a command line. |
| [**faster-whisper**](https://github.com/SYSTRAN/faster-whisper) | A Python library. Good if you are already scripting your analysis pipeline and want to call transcription from it. |
| [**YazSes**](https://github.com/MSKazemi/yazses) | A packaged tool with speaker labelling and named speakers built in, plus subtitle output. Good if you want one command rather than a pipeline. *(This is the project whose documentation you are reading.)* |

If a colleague already uses one of these successfully, use that one. The differences matter
much less than the correction pass described below.

## A worked example

Install once:

```sh
pipx install yazses
```

Transcribe a two-person interview, labelling who spoke:

```sh
yazses transcribe interview.m4a --diarize --names "Interviewer,Participant"
```

That writes `interview.txt` next to the recording, with each utterance attributed. Speaker
labelling needs one extra component — `pipx install 'yazses[diarization]'` — which downloads
about 45 MB of speaker models on first use.

Other output formats, for different analysis workflows:

```sh
yazses transcribe interview.m4a --format srt     # timestamped, for playback alongside audio
yazses transcribe interview.m4a --format json    # structured, for import into other tools
yazses transcribe interview.m4a --model small.en # slower, noticeably more accurate
```

Any common audio or video container works — MP3, M4A, WAV, FLAC, OGG, MP4, MKV — with no
conversion step.

## The correction pass is not optional

**An automated transcript is a draft.** Every system on this page makes mistakes, and the
mistakes are not random: they cluster exactly where qualitative research is most sensitive.

- Proper nouns, place names, institutions and technical vocabulary are frequently wrong.
- Overlapping speech is where speaker labels break down, and interviews overlap constantly.
- Accents, dialects, quiet speakers and poor room acoustics all degrade accuracy sharply.
- A confident-looking transcript can contain a fluent sentence the participant never said,
  which is far more dangerous than an obvious garble.

Play the audio and read along at least once before treating the text as data. If you are
quoting a participant, verify that quotation against the recording specifically. Automated
transcription changes the transcription task from typing to checking; it does not remove it.

Several transcription guides recommend a foot pedal and playback software for exactly this
correction pass. That advice is still good — the draft just starts from something better
than a blank page.

## What this does *not* do

Stated plainly, because the temptation to overclaim here is strong:

- It does **not** make your project compliant with any regulation, and it is **not**
  IRB-approved, GDPR-compliant or HIPAA-compliant. Compliance is a property of your whole
  protocol — consent, storage, retention, access, disposal — not of one tool. Running
  transcription locally removes *one* risk: third-party processing.
- It has **not** been reviewed or endorsed by any institution or ethics committee.
- It does not protect the recording on your disk. Storage, encryption, backup and disposal
  are still yours to handle, exactly as they were before.
- It does not remove the need to describe your transcription method in your protocol. If
  your approval names a transcription service, changing it is still a change.

If you are unsure whether local transcription satisfies your approval, ask your ethics
committee or research data management team. They will answer this faster than you expect —
it is an increasingly common question.

## Related

- [Transcribing recordings offline](transcribe-audio-offline.md) — the full command reference
- [Meeting notes & minutes](../meeting-notes-offline.md) — whole-session capture with speaker labels
- [Privacy statement](../privacy-statement.md) — what YazSes does and does not send anywhere
- [Benchmarks](../benchmarks.md) — measured accuracy and speed, with the method
