---
title: Docker — offline transcription and diarization in a box
description: Run YazSes's offline speech-to-text and speaker diarization from a container. No install, no Python environment, no cloud. What the image can and cannot do, honestly.
---

# Docker

```bash
docker run --rm -v "$PWD:/data" ghcr.io/mskazemi/yazses \
    transcribe /data/meeting.m4a --diarize -f md
```

That transcribes `meeting.m4a` and writes `meeting.md` beside it, with **who said
what**, entirely on your machine. No account, no API key, and after the models are
cached, no network at all.

## What this image is not

**It does not do hold-to-talk dictation.** That is the main thing YazSes does, and
it is deliberately absent here.

Dictation needs a microphone, access to `/dev/input` to see the hotkey, and the
ability to inject keystrokes into your desktop session. A container is the wrong
shape for all three, and an image that pretended otherwise would waste your
evening. For dictation, [install natively](install-linux.md) — it takes about as
long as reading this page.

What the image *is* good for: transcribing recordings on a machine you would rather
not install Python on, on a server, or in a pipeline.

## Models and caching

Nothing is baked in. Mount a volume so the models download once instead of on every
run:

```bash
docker volume create yazses-models

docker run --rm \
    -v "$PWD:/data" \
    -v yazses-models:/home/yazses/.cache \
    ghcr.io/mskazemi/yazses transcribe /data/talk.wav --model small.en
```

| What | Size | When |
|---|---|---|
| Whisper `tiny.en` | 78 MB | `--model tiny.en` |
| Whisper `base.en` | 148 MB | the default |
| Whisper `small.en` | 486 MB | `--model small.en` |
| Diarization models | ~45 MB | only with `--diarize` |

Speaker labels need the diarization models, fetched once:

```bash
docker run --rm -v yazses-models:/home/yazses/.cache \
    -v yazses-data:/home/yazses/.local/share \
    ghcr.io/mskazemi/yazses transcribe --download-models
```

Keep `-v yazses-data:/home/yazses/.local/share` on your `--diarize` runs too, or
they will be downloaded again each time.

## Air-gapped use

Pull the image and populate both volumes on a connected machine, export them, and
the container never needs the network again — the whole point of the project is
that none of your audio leaves the machine, and nothing here changes that.

## Common flags

```bash
# subtitles with timestamps
docker run --rm -v "$PWD:/data" ghcr.io/mskazemi/yazses \
    transcribe /data/talk.mp4 -f srt

# a different output path
docker run --rm -v "$PWD:/data" ghcr.io/mskazemi/yazses \
    transcribe /data/talk.wav -o /data/transcripts/talk.txt

# every option
docker run --rm ghcr.io/mskazemi/yazses transcribe --help
```

See the [CLI reference](cli-reference.md#yazses-transcribe) for the full set.

## Notes on the image

- **Non-root.** It runs as uid 1000 (`yazses`). **If your own uid is not 1000, add
  `--user "$(id -u):$(id -g)"`** — otherwise the container cannot write the
  transcript back into your mounted directory and the run fails with a permission
  error. With a matching uid it works without the flag, which is exactly why this
  is easy to miss; it is how our own CI first broke. The cache and data
  directories are world-writable so the flag is all you need — no extra setup.

  ```bash
  docker run --rm --user "$(id -u):$(id -g)" -v "$PWD:/data" \
      ghcr.io/mskazemi/yazses transcribe /data/talk.wav
  ```
- **`/data` is the convention**, not a requirement — mount wherever you like and
  give the container that path.
- **Size: ~1.5 GB.** Most of it is PyTorch-free but still substantial ML wheels
  (ctranslate2, onnxruntime, numpy). It is a fair bit of disk for a transcription
  tool and we would rather say so than let you find out.
- **`linux/amd64` and `linux/arm64`.**
- Built by [`.github/workflows/docker.yml`](https://github.com/MSKazemi/yazses/blob/main/.github/workflows/docker.yml)
  from [`packaging/docker/Dockerfile`](https://github.com/MSKazemi/yazses/blob/main/packaging/docker/Dockerfile),
  published on tags only, with build provenance attested.
