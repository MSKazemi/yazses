---
title: "Offline Hindi voice typing on a PC — how to configure it with YazSes"
description: "YazSes is an English-tuned dictation tool and its default model cannot decode Hindi at all. This page shows how to point it at a multilingual Whisper model for Hindi and other Indian languages. No accuracy data is published for any of them — a how-to, not a support claim."
---

# Offline Hindi voice typing on a PC, with YazSes

!!! warning "Bottom line first: YazSes is an English dictation tool"

    YazSes ships `base.en` and is tuned for English. **We do not claim Hindi support, or
    support for any other Indian language.** Every accuracy benchmark this project publishes
    is English ([LibriSpeech](../benchmarks.md)); we have published **no** measurement for
    Hindi or any language on this page. The multilingual decoding below is **Whisper's**
    capability, not YazSes's — YazSes passes a `language` flag through and you supply the
    model. Quality will vary by language and you should test it on your own voice before
    relying on it.

**What this page is:** a how-to for pointing YazSes at Whisper's multilingual models.
You hold a key, speak, release, and the text appears where your cursor is. Nothing is
uploaded by default, there is no account, and there is no per-minute charge.

Most Hindi voice typing tools are websites or Android keyboards: you dictate into
their text box and then copy the result out, and they stop working the moment your
connection does. YazSes is a background program on your own computer, so it types
into Word, a browser, a code editor, WhatsApp Web or a terminal directly, and it
works on a train, in a village with patchy data, or on a machine that never touches
the internet.

## Which Indian languages Whisper can decode

**The model shipped with YazSes is `base.en` — English-only. It cannot decode any of the
languages below.** You must switch to a multilingual checkpoint first (see the
configuration section). Once you have, these are the language codes Whisper accepts;
**this project has measured none of them**, and accuracy varies a great deal between
them — larger models help disproportionately for lower-resource languages:

| Language | Code | Language | Code |
|---|---|---|---|
| Hindi (हिन्दी) | `hi` | Kannada (ಕನ್ನಡ) | `kn` |
| Bengali (বাংলা) | `bn` | Malayalam (മലയാളം) | `ml` |
| Tamil (தமிழ்) | `ta` | Punjabi (ਪੰਜਾਬੀ) | `pa` |
| Telugu (తెలుగు) | `te` | Urdu (اردو) | `ur` |
| Marathi (मराठी) | `mr` | Assamese (অসমীয়া) | `as` |
| Gujarati (ગુજરાતી) | `gu` | Nepali (नेपाली) | `ne` |
| Sanskrit (संस्कृतम्) | `sa` | Sindhi (سنڌي) | `sd` |

Accuracy is **not** the same across all of them — see [honest limits](#honest-limits)
below. Hindi, Bengali, Tamil and Urdu have more training data behind them than
Assamese or Sanskrit.

## Setting it up for Hindi

Two settings matter. The default model is English-only, so you must switch to a
multilingual one:

```toml
[stt]
model = "small"        # NOT "small.en" — the .en models cannot do Hindi at all
language = "hi"
```

Then restart:

```sh
yazses restart
```

That is the whole configuration. The model downloads automatically the first time
the daemon starts with it, and after that it never needs the network again. To fetch
it as a separate, visible step (recommended behind a firewall or proxy), run
`yazses model download small` first.

For another Indian language, change `language` to the code from the table above:

```toml
# Tamil
[stt]
model = "small"
language = "ta"
```

### Which model size to choose

Indic languages benefit disproportionately from a larger model — more than English
does. If Hindi output looks roughly right but keeps garbling word endings, the model
size is usually the cause, not your microphone.

| Model | Suitability for Indian languages |
|---|---|
| `small.en`, `base.en` | **Will not work.** English-only, no language tokens. |
| `small` | Usable starting point for Hindi. Weak on the smaller languages. |
| `medium` | Noticeably better across Indic languages. A good default if your CPU allows. |
| `large-v3` | Best available quality; slowest on CPU. |

See [performance tuning](../how-to/performance-tuning.md) for the latency trade-off.

## Hinglish — sentences that mix Hindi and English

Mixing English words into a Hindi sentence is normal Indian speech, and it is the
case that trips up most dictation tools. For Hinglish today, use a multilingual model
with auto-detection:

```toml
[stt]
model = "small"
language = ""          # auto-detect
```

Whisper then detects one language per burst rather than switching inside it, so
mixed sentences come out best when the model is large enough to transcribe the
English words in Hindi context.

`[polyglot]` is not the answer yet: it is planned, not wired. Its design routes a
burst that mixes a declared pair (`[polyglot] pair = "hi-en"`) to a separately trained
code-switch adapter (`[polyglot] adapter_path`), but nothing yet detects where a burst
switches language. Every burst is decoded by the `[stt]` model, with or without an
adapter, so turning it on changes no transcript.

## Will Devanagari actually type into my applications?

This is a fair question, because transcribing Hindi and *typing* Hindi are two
different problems. YazSes has to synthesise keystrokes into whatever window has
focus, and not every method can produce characters that are absent from your
physical keyboard layout.

- **Linux on X11 — works in the project's own end-to-end test.** Devanagari types
  correctly through the `xdotool` backend, which maps each character to an X keysym
  rather than to a physical key: `नमस्ते हिंदी` dictated in, `नमस्ते हिंदी` received by
  the target application, byte for byte. That run is not yet a dated, versioned record
  in the [validation matrix](../validation-matrix.md) ([#642](https://github.com/MSKazemi/yazses/issues/642)).
- **Any platform — the clipboard backend works by construction.** It passes UTF-8
  text straight through, so script is irrelevant to it:

  ```toml
  [injection]
  backend = "clipboard"
  ```

- **Linux on Wayland — verify it yourself before relying on it.** The default
  Wayland backend, `ydotool`, injects at the kernel input layer *below* the keyboard
  layout, so it can only press keys your active layout has. YazSes checks every
  non-ASCII character before typing: on a Latin keyboard layout there is no key for a
  Devanagari character, so YazSes pastes the whole burst from the clipboard instead
  (`[injection] fallback_to_clipboard`, on by default). That overwrites your
  clipboard and does nothing in most terminals. With a Devanagari layout active, the
  characters are typed. We have not confirmed Devanagari output end to end on
  Wayland; dictate one Hindi sentence into a text editor first.

If your text is transcribed but nothing lands in the application, that is an
injection problem, not a language problem — [troubleshooting](../troubleshooting.md)
covers it.

## Honest limits

- **Test it on your own voice before depending on it.** Whisper's accuracy varies
  by language and by accent, and Indian-language performance is well behind its
  English performance. This page is not claiming parity.
- **Smaller Indian languages are genuinely weaker.** Assamese, Sindhi, Sanskrit and
  Nepali have far less training data than Hindi. A larger model helps but does not
  erase the gap.
- **Multilingual models are slower** than the English-only ones. On a modest CPU,
  `medium` in Hindi is meaningfully slower than `base.en` in English.
- **Wayland + Devanagari is unverified**, as described above. X11 and clipboard
  injection are the paths we have actually tested.

## Related

- [Multilingual dictation](multilingual-dictation.md) — code-switching, transliteration and translation in depth
- [Personal vocabulary](../how-to/personal-vocabulary.md) — names and terms the model keeps mishearing
- [Install on Windows](../windows-install.md) · [Install on Linux](../install-linux.md) · [Install on macOS](../macos-install.md)
- [Performance tuning](../how-to/performance-tuning.md) — model size vs latency
