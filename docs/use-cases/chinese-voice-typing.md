---
title: "Offline Chinese voice typing on a PC — how to configure it with YazSes"
description: "YazSes is an English-tuned dictation tool and its default model cannot decode Mandarin at all. This page shows how to point it at a multilingual Whisper model, the Simplified/Traditional trap that costs more accuracy than it looks, and the numbers we actually measured. No promises about Chinese — a how-to, not a support claim."
---

# Offline Chinese voice typing on a PC, with YazSes

!!! warning "Bottom line first: YazSes is an English dictation tool"

    YazSes ships `base.en` and is tuned for English. **We do not claim Chinese support.**
    Every accuracy benchmark this project publishes is English
    ([LibriSpeech](../benchmarks.md)). The multilingual decoding below is
    **Whisper's** capability, not YazSes's — YazSes passes a `language` flag through and you
    supply the model. If you want a tool marketed for Chinese, use one built for Chinese.

**What this page is:** a how-to for people who already use YazSes for English and want to
point it at Mandarin anyway, plus one Chinese-specific problem we did fix (the
Simplified/Traditional trap) and the numbers we measured while fixing it.

It is deliberately specific about what works and what does not, because Chinese support in
offline speech recognition is usually oversold. There is also a
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

## Chinese voice commands: safe core only

When `[commands] enabled = true` (the default), the Tier-1 command grammar follows
`[stt] language` when `[commands] language = "auto"`. With Mandarin selected, YazSes
recognizes a conservative, whole-utterance command set in both Simplified and Traditional
forms: undo/save/copy/cut/paste, bounded word/line deletion and selection, Enter/Tab/Escape/
Backspace, line/page/cursor navigation, and explicit go-to function/class/file commands.

```toml
[commands]
language = "auto"  # follows [stt] language; explicit "en" or "zh" overrides
```

This is intentionally **not full parity with the English command grammar yet**. Mandarin
terminal execution (the English `run ...` family) and open-ended refactor/create commands
are not registered in P1. An unmatched Chinese phrase remains dictation on the normal
dictation key; in dedicated command mode it remains unmatched and is not executed. The
Chinese Tier-1 path also does not fall through to the English SLM router — which is
opt-in and off unless `[commands] slm_model_path` names a local model anyway — so
ordinary Chinese prose cannot become a fuzzy English command.

## Getting Chinese characters into the app

Recognising Mandarin is half the job; the other half is typing 汉字 into whatever window
has focus, and that depends on your platform's injection backend. What each one does
with a Han character, from the code — **none of this has yet been confirmed on real
hardware for Chinese text**, which is tracked in
[#501](https://github.com/MSKazemi/yazses/issues/501):

| Platform / backend | How a Han character is sent | Known limitation |
|---|---|---|
| Windows (`SendInput`) | One Unicode key event per UTF-16 unit; characters outside the BMP (such as 𠮷) as a surrogate pair | Some applications ignore Unicode key events — see the "one app gets `????`" entry in [Troubleshooting](../troubleshooting.md) |
| macOS (Quartz) | Unicode key events in chunks of 20 UTF-16 units, never splitting a surrogate pair | Needs the Accessibility permission, like all typing |
| Linux X11 (`xdotool`) | `xdotool type`, which handles characters missing from the keyboard layout itself | — |
| Linux Wayland (`ydotool`, the usual default) | ASCII through `ydotool`; anything else through a layout-aware key press | A Latin keyboard layout has **no key for any Han character**, so a burst containing Chinese is **pasted from the clipboard** instead (`[injection] fallback_to_clipboard`, on by default). That overwrites your clipboard and does nothing in most terminals. |
| Linux Wayland (`wtype`, wlroots compositors) | `wtype`, which sends any character | — |
| GNOME Wayland (RemoteDesktop portal) | One Unicode keysym per character | Whether the compositor accepts a keysym your layout lacks is unverified |

On the `ydotool` path, a burst that mixes English and Chinese — `YazSes 版本 v2.0` — is now
checked **before the first keystroke**: if any character cannot be typed, nothing is typed
and the whole burst is pasted once. Earlier versions typed the English part, failed on the
first Han character, and then pasted the whole burst after it, so the English appeared
twice.

Spacing follows Chinese typography: no space is inserted between two consecutive Chinese
dictation bursts, or after full-width punctuation such as `，` and `。`. A space is kept
where Chinese meets a Latin word or a number spoken as a separate burst (`测试 YazSes`).

Numbers in commands are bounded and exact. Counts ("撤销三次", "删除最后两行") run from 0 to 99,
and line numbers ("转到第一百二十三行", "前往第 150 行") from 0 to 999. A form outside that
set — 一千, the elided 一百一, 两十 — is typed as text, not guessed. Deletion only fires on
the explicit "删除最后 … 词/行" form. Every Mandarin command phrase is **provisional**
until a native Mandarin speaker has reviewed it; until then, treat the set as a preview.

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
