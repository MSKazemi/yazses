#!/usr/bin/env bash
# Printed at the end of devcontainer setup.
#
# This installs nothing. `postCreateCommand` has already run `uv sync`, so the whole
# project is available; this only tells the visitor what they can usefully do here.
#
# Two audiences open this container and they want different things:
#   - contributors, who want the test suite (offline, no mic, no model needed);
#   - people evaluating YazSes, who want to hear whether the transcription is any good
#     before installing anything on their own machine.
# Both are possible here, so both are shown.
set -euo pipefail

cat <<'BANNER'

  ╭──────────────────────────────────────────────────────────────────────╮
  │  YazSes — offline voice dictation. Ready.                            │
  ╰──────────────────────────────────────────────────────────────────────╯

  ▸ Just looking? Hear the transcription quality for yourself.
    A real clip ships with the repo, with the known-correct text beside it:

        uv run yazses transcribe data/librispeech-sample/jfk.wav -o /tmp/heard.txt
        cat /tmp/heard.txt                       # what YazSes heard
        cat data/librispeech-sample/jfk.txt      # what it should say

    The -o matters: without it the transcript is written beside the input as
    jfk.txt, overwriting the reference you are comparing against. Expect
    punctuation to differ — the reference has none, YazSes adds it — so
    "Americans, ask not" against "Americans ask not" is a pass.

    First run downloads the base.en model (~141 MB); after that it is a
    couple of seconds. It runs right here — nothing is sent anywhere.

        uv run yazses transcribe data/librispeech-sample/jfk.wav -f srt   # subtitles
        uv run yazses about                                              # what it is

  ▸ Here to contribute? The suite is fully offline and takes ~30 seconds.
    No microphone, no model and no GPU required. These are exactly the
    commands CI runs, so green here means green there:

        uv run python -m pytest tests/ -q
        uv run ruff check src tests scripts && uv run mypy src

    Pick a task: https://mskazemi.com/yazses/contribute/start.html

  ⚠  Hold-to-talk dictation does NOT work in a container — it needs a real
     microphone, the kernel input device for the hotkey, and a window to type
     into. Test hardware-facing changes on a real machine:
     https://mskazemi.com/yazses/install-linux.html

BANNER
