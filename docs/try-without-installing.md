---
title: Try YazSes without installing it — offline speech-to-text in Docker or your browser
description: Hear how accurate on-device transcription is before you install anything. Run YazSes in Docker with one command, or in a browser via GitHub Codespaces. No account, no API key, no cloud.
---

# Try it without installing it

The honest objection to any offline speech-to-text tool is **"but is it actually
accurate?"** — and no amount of prose answers that. So here are three ways to find out
that cost you nothing and leave nothing behind.

!!! info "What you can and cannot try this way"
    These trials run the **file → text** side of YazSes (`yazses transcribe`). They use
    the same local Whisper engine as live dictation, so the accuracy you see is the
    accuracy you get.

    They **cannot** do hold-to-talk dictation. That needs a real microphone, the kernel
    input device for the hotkey, and the ability to type into whatever window you have
    focused — three things a container does not have. For dictation,
    [install it properly](install-linux.md).

---

## 1. Docker — one command, nothing installed

```sh
git clone https://github.com/MSKazemi/yazses.git && cd yazses
docker build -f packaging/docker/Dockerfile -t yazses .
docker run --rm -v yazses-models:/models -v "$PWD/data/librispeech-sample:/data" \
    yazses jfk.wav
```

That transcribes a clip that ships with the repo. Compare what comes out with
`data/librispeech-sample/jfk.txt`, which is the known-correct text.

**What actually happened when this page was written** (4-core CPU, `base.en`):

| Run | Wall time | Why |
|---|---|---|
| First | **43 s** | includes downloading the 141 MB `base.en` model |
| Every run after | **2.3 s** | model is cached in the `yazses-models` volume |

The clip is 11 seconds of audio, so the cached run is roughly **5× faster than
real time on a CPU**, with no GPU.

Transcribe your own file by pointing the volume at your own folder:

```sh
docker run --rm -v yazses-models:/models -v "$PWD:/data" yazses meeting.m4a
docker run --rm -v yazses-models:/models -v "$PWD:/data" yazses talk.mp4 -f srt
docker run --rm -v yazses-models:/models -v "$PWD:/data" yazses talk.wav --model small.en
```

`wav`, `mp3`, `m4a`, `ogg`, `flac`, `opus` and `mp4` all work. Output formats are
`txt`, `md`, `srt`, `vtt` and `json`.

!!! tip "The container has no network access to anything but the model download"
    After the first run the model is on disk and you can prove the point:
    add `--network none` and it still transcribes. That is the whole pitch, testable
    in one flag.

    ```sh
    docker run --rm --network none -v yazses-models:/models -v "$PWD:/data" yazses jfk.wav
    ```

The image is **833 MB**. It deliberately drops PySide6 (the desktop overlay, ~648 MB),
which transcription never uses.

---

## 2. In your browser — GitHub Codespaces

No Docker, no local install, nothing on your machine at all:

1. Open [the repository](https://github.com/MSKazemi/yazses)
2. **Code → Codespaces → Create codespace on main**
3. Wait for it to finish setting up — it prints these instructions itself — then run:

```sh
uv run yazses transcribe data/librispeech-sample/jfk.wav
cat data/librispeech-sample/jfk.txt      # what it should say
```

The container definition is in [`.devcontainer/`](https://github.com/MSKazemi/yazses/tree/main/.devcontainer).
GitHub's free tier covers this comfortably.

The same container is the project's **contributor** environment, so if you decide you
want to change something, the test suite is already installed and runs fully offline in
about 30 seconds (`uv run python -m pytest tests/ -q`) — no microphone, model or GPU
needed.

---

## 3. Just read the numbers

If you would rather not run anything:

- **[Benchmarks](benchmarks.md)** — word error rate and decode speed per model, measured
  over 200 utterances from 40 speakers.
- **[The 40-second demo](https://www.youtube.com/watch?v=nn8WUKsCvZ4)** — the real loop,
  end to end.
- **[Comparison](comparison.md)** — where YazSes wins and where it honestly does not.

---

## Ready to install?

Dictation is the part worth having, and it needs a real install:

- **[Linux](install-linux.md)** — one command, sets up everything
- **[macOS](macos-install.md)**
- **[Windows](windows-install.md)**

Want to know the cost before you commit? **[What installing actually costs](install-cost.md)**
lists the disk, time and downloads, and **[how to uninstall](uninstall.md)** is a single
page — written before you install, on purpose.
