---
title: YazSes — Hosted Speech Recognition Preview
emoji: 🔥
colorFrom: green
colorTo: pink
sdk: gradio
sdk_version: 6.22.0
python_version: '3.12'
app_file: app.py
pinned: false
license: apache-2.0
short_description: Hosted preview of YazSes speech recognition, not the app
---

# YazSes — Hosted Speech Recognition Preview

> This is a hosted demonstration. Audio submitted here is processed on Hugging Face infrastructure. For private, offline voice typing, install YazSes on your own computer.

This Space transcribes one recording at a time, using the speech-recognition engine
family that [YazSes](https://github.com/MSKazemi/yazses) uses. It is a preview of
transcription quality. It is not the YazSes desktop application.

## What this Space is, and is not

- **Is:** a browser page where you record or upload a short clip and read back a
  transcript from `faster-whisper` running on a CPU in the Space.
- **Is not:** the YazSes desktop app. It does not provide desktop-wide hold-to-talk
  dictation, it does not type text into other applications, and it does not run
  offline. The desktop app is the private, offline product.

## Settings this Space uses

Verified against the code in this Space (`app.py`) and the YazSes source:

| Setting | This Space | YazSes desktop default |
|---|---|---|
| Model | `base.en` (English-only) | `base.en` |
| Engine | faster-whisper (CTranslate2) | faster-whisper (Parakeet is opt-in) |
| Device / precision | CPU, `int8` | CPU, `int8` |
| Beam size | 5 | 0, which faster-whisper resolves to 5 |
| Previous-text conditioning | faster-whisper default (on) | on |
| Voice-activity handling | `vad_filter=True`: the decoder removes non-speech and re-segments the audio before decoding | No `vad_filter`. A silence gate (mean amplitude against `vad_threshold`) drops silent bursts; the decoder sees the audio unsegmented |
| Built-in prompt | none | `"The app is called YazSes."` is always primed |
| Post-processing | none; segments are joined | the desktop app applies its own text filters |

**Parity is not claimed beyond the shared engine and model family.** The first four rows
match the desktop defaults. The voice-activity row does not: the Space trims non-speech
before decoding, which the desktop app deliberately does not, and the project's own
measurements found that this can change the transcript of some clips. The built-in
prompt and post-processing also differ. A transcript here is therefore an indication
of accuracy, not a guarantee of what the desktop app would type.

## Limits

- Recordings up to **60 seconds** and **25 MB**. Longer input is refused with a message
  rather than transcribed.
- Supported formats: WAV, FLAC, MP3, OGG, M4A, WebM.
- English only, because the model is `base.en`.
- Shared hosting: a queue or a cold start can make a request slow. The model is loaded
  on the first request after a restart.

## Your audio and this Space

- The Space's code does not write audio or transcripts to disk, a database, a log or an
  analytics service, and it has no telemetry. Analytics are disabled in the Gradio
  configuration.
- Gradio keeps uploaded files in a temporary cache on the server. The Space sweeps that
  cache every 10 minutes and deletes files older than 10 minutes.
- Hugging Face runs this Space on its own infrastructure. This README makes no promise
  about what Hugging Face itself logs or retains. Read Hugging Face's own policies if
  that matters to you.

## Get the private, offline app

- Install (Linux): <https://mskazemi.com/yazses/install-linux.html>. The macOS and Windows guides are linked from the documentation home page.
- Try it with nothing installed: <https://mskazemi.com/yazses/try-without-installing.html>
- Documentation: <https://mskazemi.com/yazses/>
- Source code (Apache-2.0): <https://github.com/MSKazemi/yazses>

## Paper

The system is described in an arXiv preprint: <https://arxiv.org/abs/2607.28878>

If you use YazSes in research, please cite the paper:

```bibtex
@article{seyedkazemiardebili2026yazses,
  title   = {YazSes: An Offline, Privacy-First, Cross-Platform Hold-to-Talk Voice-Dictation System},
  author  = {Seyedkazemi Ardebili, Mohsen},
  journal = {arXiv preprint arXiv:2607.28878},
  year    = {2026},
  month   = jul,
  url     = {https://arxiv.org/abs/2607.28878}
}
```

To cite the software itself, use the concept DOI, which always resolves to the latest
release: <https://doi.org/10.5281/zenodo.21856271>
