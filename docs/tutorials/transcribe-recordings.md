# Transcribe recordings to text (offline)

`yazses transcribe <file>` turns an existing audio or video recording into a text
file — a meeting, an interview, a voice memo, a lecture — **entirely on your
machine**. It runs the same local `faster-whisper` engine as live dictation:
no cloud, no account, no upload. With `--diarize` it also labels **who said
what**.

This guide walks from the simplest case to a named, multi-speaker transcript.

## 1. The one-liner

```sh
yazses transcribe talk.mp3
```

This writes `talk.txt` next to the input. That's it — no daemon, no hotkey, no
config change. The command accepts most common formats out of the box
(wav, mp3, m4a, ogg, flac, opus, mp4, and other ffmpeg-decodable media); the
audio is decoded to 16 kHz mono internally, so you don't convert anything first.

Choose the output path or format if you like:

```sh
yazses transcribe talk.mp3 -o notes.txt          # explicit output path
yazses transcribe lecture.mp3 --format srt        # subtitles with timestamps
yazses transcribe lecture.mp3 -f md               # Markdown (also: vtt, json)
```

`srt` and `vtt` carry per-cue timestamps (drop them into a video player);
`json` is lossless — per-word timestamps plus speaker, for downstream tooling.

## 2. Pick the right model for the job

By default `transcribe` uses your configured `[stt]` model (often `base.en`,
which is fast). For anything you care about — a real meeting, an accented
speaker, background noise — a larger model is noticeably more accurate:

```sh
yazses transcribe interview.mp3 --model small.en
```

`small.en` roughly doubles or triples the runtime versus `base.en` but makes
far fewer word errors. Rule of thumb: **`base.en` for a quick gist, `small.en`
(or larger) for a transcript you'll actually read or share.**

Transcription is CPU-bound and proportional to the recording's length. A long
recording (tens of minutes) can take several minutes on `base.en` and longer on
`small.en`, so it's fine to leave it running in the background.

## 3. Other languages

To transcribe non-English audio and get **English** text back:

```sh
yazses transcribe note.fr.m4a --language translate
```

To keep the original language instead, name it — `--language fr`. That needs a
multilingual model (`small`, not `small.en`); an `.en` checkpoint has no language tokens
and would transliterate French into English-looking nonsense, so YazSes warns instead.

## 4. Tag who said what (diarization)

Speaker tagging is opt-in and needs a small one-time setup, because it uses a
separate speaker model (sherpa-onnx — CPU-only, no PyTorch, no GPU, no account).

**One-time:** install the extra and fetch the models (~45 MB):

```sh
uv sync --extra diarization                 # or: pipx inject yazses sherpa-onnx
yazses transcribe any.m4a --download-models  # downloads, then exits
```

Then diarize:

```sh
yazses transcribe meeting.m4a --diarize
```

Each utterance is now prefixed with a label:

```
Speaker 1: Good morning, shall we start?
Speaker 2: Yes — I sent the doc earlier.
```

If diarization isn't available, `--diarize` degrades gracefully to a plain
transcript and tells you why.

### Give the speakers real names

If you know who's in the recording, name them. Two ways:

```sh
# Positional — names map to speakers in order of first appearance:
yazses transcribe meeting.wav --diarize --names "Alice,Bob,Carol"

# Explicit — map a specific detected speaker to a name (repeatable):
yazses transcribe meeting.wav --diarize --rename speaker_0=Alice --rename speaker_1=Bob
```

### Help the model with the speaker count

Diarization auto-detects how many people are talking, but if you *know* the
count, telling it usually improves the split:

```sh
yazses transcribe call.ogg --diarize --speakers 2
```

!!! warning "There is no range option on the shipped diarizer"

    `--min-speakers` and `--max-speakers` read like a range and are not one.
    Measured against the `sherpa` diarizer this build ships:

    - `--max-speakers N` becomes an **exact** cluster count, not a cap. On a
      three-person recording `--max-speakers 6` does not allow up to six, it
      manufactures six by splitting real speakers apart.
    - `--min-speakers` is read only by the pyannote adapter, which this build does
      not ship, so it is **ignored**. The run says so before transcribing rather
      than quietly dropping the floor.

    If you know the count, `--speakers N` is the flag that does what you mean. If
    you do not, leave all three alone: auto-detection is the default and is what
    these were measured against.

### Let your own voice name itself

If you've enrolled a voiceprint (`yazses enroll-voice`), YazSes recognises
**your** voice in the recording and labels it **"You"** automatically; everyone
else stays `Speaker N` unless you name them.

## 5. A realistic accuracy note

Diarization on a long, casual multi-person recording is genuinely hard, and the
result improves a lot with model size and a correct speaker count. Expect:

- **Two distinct speakers** to separate cleanly.
- A **third speaker who joins late or talks little** to sometimes get
  under-attributed (their lines folded into another speaker) on the fast model.

If a diarized transcript looks rough, re-run with `--model small.en` and either
let the speaker count auto-detect or set it explicitly — both help. The
transcript files you already have are never overwritten unless you reuse the
same `-o` path.

## Privacy

Everything here runs on your machine — the audio and the transcript never leave
it. Speaker voiceprints are biometric data: they are stored **encrypted**, used
only to label **you**, and **no one is ever enrolled automatically**. You are
responsible for having permission to record and transcribe other people.

## Quick reference

| Goal | Command |
|---|---|
| Fast transcript beside the file | `yazses transcribe talk.mp3` |
| Accurate transcript | `yazses transcribe talk.mp3 --model small.en` |
| Subtitles | `yazses transcribe talk.mp3 --format srt` |
| Non-English → English | `yazses transcribe talk.mp3 --language translate` |
| Non-English, kept as-is | `yazses transcribe talk.mp3 --language fr --model small` |
| Tag speakers | `yazses transcribe mtg.m4a --diarize` |
| Name speakers | `yazses transcribe mtg.m4a --diarize --names "Alice,Bob"` |
| Force speaker count | `yazses transcribe mtg.m4a --diarize --speakers 3` |
| One-time model download | `yazses transcribe mtg.m4a --download-models` |

Full flag list: `yazses transcribe -h`, or the [CLI reference](../cli-reference.md).
