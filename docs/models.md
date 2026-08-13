---
title: Choosing a speech model — accuracy vs speed
description: Which Whisper model to run for offline voice dictation, with measured word-error rate, latency and memory for tiny.en, base.en and small.en, plus when Parakeet or Moonshine is the better choice.
---

# Choosing a model

Every number on this page is **measured on this project's own benchmark harness**,
not quoted from a model card. The method and the machine are in
[benchmarks](benchmarks.md); if your CPU is slower, expect the same *ordering* with
different absolute numbers.

## The short answer

`base.en` is the default because it is the point where accuracy stops being
annoying and latency is still under two seconds. Change it only if one of the
rows below describes you.

## English models, measured

| Model | Word-error rate | Median latency | Download | RSS after load | Pick it when |
|---|---|---|---|---|---|
| `tiny.en` | 4.82 % | **0.89 s** | 75 MB | 857 MB | An old or very slow machine, or you value latency over the occasional wrong word |
| `base.en` **(default)** | 4.07 % | 1.56 s | 141 MB | 874 MB | You have no specific reason to change |
| `small.en` | **2.59 %** | 5.05 s | 464 MB | 1,340 MB | Accuracy matters more than waiting — names, jargon, long-form writing |

Read the two ends of that table together: `small.en` cuts errors by roughly a
third, and costs **more than three times the wait** on the same machine. For a
sentence of dictation that is the difference between 1.5 s and 5 s, every time.
Most people who try `small.en` for accuracy go back to `base.en` for the latency,
which is why the default is where it is.

!!! tip "Fix the words it gets wrong, rather than buying a bigger model"

    A larger model does not know your colleagues' names or your codebase's
    identifiers. `yazses vocab add <word>` teaches the recogniser those directly,
    and `[stt] vocab_correction` repairs them after the fact — both are free and
    both help more than a model tier for the words *you* care about. See
    [dictating code and technical vocabulary](use-cases/dictating-code.md).

## How to change it

```toml
[stt]
model = "small.en"
```

Then apply it:

```bash
yazses restart
yazses doctor        # confirms which model is configured and whether it is cached
```

The model downloads once, on first use, and is cached in
`~/.cache/huggingface/hub`. Only the model you configure is downloaded — there is
no bundle of all three.

## Non-English

**Drop the `.en`.** `base.en` is English-only — those checkpoints carry no
language tokens at all, so pointing one at German does not fail, it transliterates
into fluent-looking English nonsense. `base` is the multilingual build of the same
size. Full detail, presets and a smoke test:
[dictating in more than one language](use-cases/multilingual-dictation.md).

## The other engines

Whisper is not the only option; `[stt] engine` selects among three.

| Engine | Choose it for | Cost |
|---|---|---|
| `faster-whisper` **(default)** | works everywhere, multilingual, word timings | — |
| `parakeet` | best English accuracy per unit of CPU | ~600 MB model, English only, no `initial_prompt` |
| `moonshine` | short bursts on a small machine; installs without torch | English only, no word timings |

Both alternatives ignore `initial_prompt`, which is a Whisper concept. Your
personal dictionary still reaches them — `[stt] vocab_correction` repairs
mis-heard vocabulary after decoding, which is why it was built to be
engine-agnostic.

Enable either with `yazses features enable stt-parakeet` / `stt-moonshine`; that
installs only that engine's dependencies. Disabling restores faster-whisper.

## What this page does not claim

These are English figures from one benchmark corpus on one machine. They are
useful for *ranking* the models, which is the decision this page exists for. They
are not a claim about your accent, your microphone, or your room — and per-language
quality varies far more than model size alone predicts.
