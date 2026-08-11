---
title: "Chinese voice typing, offline — free Mandarin speech to text for PC"
description: "Dictate Chinese into any application with no internet, no account and no subscription. Offline Mandarin voice typing for Windows, Linux and macOS, with Simplified or Traditional output you choose rather than the model guessing."
---

# Chinese voice typing on a PC, fully offline

**In short:** YazSes is free, open-source dictation software that types Chinese into any
application on your computer, and it keeps working with the network cable pulled out. You
hold a key, speak, release, and the characters appear where your cursor is. Nothing is
uploaded by default, no account is needed, and there is no per-minute charge.

This page is deliberately specific about what works and what does not, because Chinese
support in offline speech recognition is usually oversold. There is also a
[Simplified Chinese version of this page](../zh/chinese-voice-typing.md).

## It is not on by default — you must switch models

YazSes ships with `base.en`, an **English-only** Whisper checkpoint. English-only
checkpoints have no language tokens at all, so they cannot decode Mandarin: fed Chinese
speech they produce fluent-looking English nonsense rather than an error, which is the
worst possible failure mode. YazSes warns about this at start-up, but you still have to
change the setting yourself.

In `~/.config/yazses/config.toml`:

```toml
[stt]
model = "small"                  # multilingual (no .en suffix): base / small / medium / large-v3
language = "zh"                  # Mandarin
chinese_script = "simplified"    # or "traditional" for Taiwan and Hong Kong
```

Then:

```sh
yazses features enable chinese-script   # installs the `chinese` extra
yazses restart
```

## Why `chinese_script` matters more than it sounds

Whisper decides **per utterance** whether to answer in Simplified or Traditional
characters, and it is not consistent about it. Measured on 20 clean 16 kHz Mandarin
utterances (the ASCEND test split, `small` model), **13 came back in Traditional
characters** — including ones where the recognition itself was completely correct. A
mainland user dictating 简体中文 watches 繁體字 land in their editor.

That inconsistency costs far more accuracy than it appears to, because the recognition is
usually right and only the script is wrong. Character error rate against Simplified
references:

| Model | `chinese_script = ""` | `chinese_script = "simplified"` |
|---|---|---|
| `small` | 35.9% | **16.9%** |
| `large-v3` | 12.3% | **11.3%** |

Same audio, same model, one config key. **The setting matters most for the small models,
which is exactly what CPU users run** — `small` improves by 19 points, `large-v3` by only
one, because the larger model already tends to answer in Simplified. If you are dictating
on a laptop CPU rather than a GPU, this setting is doing most of the work.

The measurement and its caveats are documented in
[`postprocess/han_script.py`](https://github.com/MSKazemi/yazses/blob/main/src/yazses/postprocess/han_script.py).

Conversion is a reversible character mapping, so it cannot repair a mishearing — it only
stops a correct transcription from arriving in the wrong script.

## How accurate is it really?

Those figures come from ASCEND, which is **spontaneous conversation** by Hong Kong
speakers with Mandarin-English code-switching — a deliberately hard case, and only 20
utterances. Read speech into a decent microphone in a quiet room does better; a noisy room
or a strong regional accent does worse. Model size is the biggest lever available to you:
on the same clips, `large-v3` reached 11.3% where `small` reached 16.9%.

Do not take anyone's benchmark as a promise about your voice. Test it on your own audio
before you rely on it:

```sh
yazses transcribe my-recording.m4a
```

Larger models are more accurate and slower to decode on CPU. `small` is a reasonable
starting point; move to `medium` or `large-v3` if your machine can afford the latency.

Chinese dictation in YazSes is best described as **usable but still rough**. Field reports
are genuinely wanted — [open an issue](https://github.com/MSKazemi/yazses/issues) with
what worked and what did not.

## Why offline matters here specifically

Most Chinese voice input is either a website or a mobile keyboard: you speak into their
text box and copy the result out, and it stops working the moment the network does.
YazSes runs as a background program on your own computer, so it types straight into Word,
a browser, a code editor, or a terminal — on a train, on a bad connection, or on a machine
that never touches the internet at all.

That property is the point for anyone whose audio must not leave the building: clinical
notes, legal drafting, unpublished research, interview recordings covered by an ethics
approval, or work on an air-gapped machine. See
[private and confidential dictation](private-offline-dictation.md) and the
[privacy statement](../privacy-statement.md).

## Related

- [Multilingual dictation](multilingual-dictation.md) — the general non-English setup
- [Hindi and Indian languages](hindi-voice-typing.md) — the same pattern for another script
- [Transcribe recordings offline](transcribe-audio-offline.md)
- [简体中文版本](../zh/chinese-voice-typing.md)
