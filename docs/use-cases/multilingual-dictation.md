---
title: Multilingual offline dictation — non-English speech to text and code-switching
description: YazSes is English-tuned and ships an English-only model. Whisper itself is multilingual, so you can point YazSes at a multilingual checkpoint yourself — this page shows how, including translation, transliteration and code-switching. No accuracy data is published for any non-English language.
---

# Dictating in more than one language

!!! warning "Bottom line first: YazSes is an English dictation tool"

    YazSes ships `base.en` and is tuned for English, and **every accuracy benchmark this
    project publishes is English** ([LibriSpeech](../benchmarks.md)). **We do not claim
    support for any other language.** What follows is a how-to, not a support claim.

**Short answer:** the *underlying Whisper model* is multilingual, so if you supply a
multilingual checkpoint yourself, YazSes will pass your chosen language through to it.
On top of that YazSes adds some conveniences bilingual speakers ask for — translating
as you speak and transliterating Persian into its script. Switching language per
application and routing sentences that mix two languages mid-thought are designed but
do not work yet; the sections below say exactly how far each one goes. **The
recognition quality in any of those languages is Whisper's, and we have not measured
it.**

All of it runs on your machine. This matters for languages where the cloud
alternatives are weakest or absent entirely.

## Dictating in one non-English language

Set the language in your config and use a multilingual model — note that the
`.en` models (`base.en`, `small.en`) are English-only by design, so switch to the
multilingual variant:

```toml
[stt]
model = "small"        # not "small.en" — the .en models are English-only
language = "de"        # or fr, es, it, fa, ar, hi, zh, …
```

Then `yazses restart`. Accuracy varies substantially by language and model size;
larger models help disproportionately for lower-resource languages.

For Mandarin there is a one-command route that writes every key and fetches the
model: `yazses language set zh-CN` (or `zh-TW`); add `--dry-run` to preview it. See
[Chinese voice typing](chinese-voice-typing.md). `yazses language list` shows the
profiles it supports.

### German, French, Spanish

These three are the most common request, so here they are as complete configs.
Drop the block that matches your language into `config.toml` and restart:

```toml
# German
[stt]
model = "small"
language = "de"
```

```toml
# French
[stt]
model = "small"
language = "fr"
```

```toml
# Spanish
[stt]
model = "small"
language = "es"
```

### Downloading the model

faster-whisper fetches `small` (or whichever multilingual model you configured)
automatically the first time the daemon starts with it set, the same way it
fetches `.en` models, and caches it in the Hugging Face cache. To fetch it as a
separate, visible step (recommended behind a firewall or proxy), run
`yazses model download small` first. Multilingual weights are somewhat larger than their
`.en` counterparts at the same size tier, so expect a longer first-run download
and a few hundred MB more disk use. Confirm it landed with:

```bash
yazses doctor
```

which reports the configured model as cached, local, or not yet downloaded.
If the download stalls or fails partway (a slow or interrupted connection is
the usual cause), delete the partial cache entry and restart the daemon to
retry from a clean state — `yazses doctor` output tells you which model is
misbehaving. The cache lives under `~/.cache/huggingface/hub` (or `$HF_HOME/hub`
if you set that), one `models--…` directory per model, so removing just the
offending one leaves your other models intact.

### Letting YazSes detect the language

If you switch languages often and don't want to edit config each time, leave the
language empty and Whisper will detect it per utterance:

```toml
[stt]
model = "small"
language = ""          # auto-detect
```

This costs an extra detection pass on every burst and can occasionally guess
wrong on very short utterances, so prefer an explicit code when you know what
you'll be speaking.

!!! warning "Mismatched model and language: dictation is refused"

    `language` needs a model that can transcribe that language. The English-only
    checkpoints do not fail when you give them Persian. They transcribe it as
    English-looking text. The English-only checkpoints are the `.en` models
    (`base.en`, `small.en`, …), the Distil-Whisper models (`distil-large-v3` and the
    rest, English-only even without the suffix), the default Parakeet engine and
    Moonshine. So YazSes refuses the pairing:

    - `yazses doctor` fails the **Speech language** row and names the model to switch to;
    - the daemon does not start dictation. The tray goes red, a notification says
      what is wrong, and `yazses status` shows the reason;
    - the Settings window will not save the pair, and `yazses transcribe` exits
      with the same message.

    `yazses language status` shows the language, engine, model, whether that model is
    multilingual, and whether the combination is supported, with a link to the
    model card that says so. A custom checkpoint (a Hugging Face id or a local path)
    is reported as *unverified*, never refused.

## Sentences that mix two languages

This is the case ordinary dictation handles worst. Bilingual speakers routinely
switch mid-sentence — a Persian speaker dropping in English technical terms, a
Spanish speaker using English product names — and a single-language recogniser
mangles whichever language it was not set to.

What works today is a multilingual model with auto-detection, which picks one
language per burst:

```toml
[stt]
model = "small"
language = ""          # auto-detect
```

`[polyglot]` (`yazses features enable polyglot`, with `pair = "fa-en"`) is not a
working answer yet. It is a code-switch hook for a separately trained adapter
(`[polyglot] adapter_path`); with none set it does nothing, and `yazses doctor`
reports it as dormant. Even with an adapter set, the daemon does not route any
speech to it yet, so turning it on changes no transcript.

## Per-application language switching

If you write in one language in your email client and another in your editor,
switching by hand every time is friction that makes dictation not worth using.
**Planned — not yet wired**, so `features enable` refuses it for now:

```sh
yazses features enable langroute
```

Language then follows the application you are dictating into.

## Translating as you speak

Two distinct capabilities, often confused:

| Want | Use |
|---|---|
| Speak language X, get text in language X | Set `[stt] language` |
| Speak language X, get **English** text | `yazses features enable translate` |
| Speak language X, get text composed in language Y | `yazses features enable compose` *(planned — not yet wired)* |
| Two people, two languages, back and forth | `yazses features enable interpret` *(planned — not yet wired)* |

For an existing recording rather than live dictation, the same translation path is
one flag:

```sh
yazses transcribe interview.fr.m4a --language fr          # French in, French out
yazses transcribe interview.fr.m4a --language translate   # any language → English
```

`--language` takes any Whisper code, and it now reaches the decoder: until v2.30 only
`translate` did anything, so `--language fr` set nothing and the file was transcribed as
English. A non-English code needs a multilingual model — drop the `.en` suffix from
`[stt] model` (or pass `--model small`). YazSes refuses with exit code 2 and names the
model to use, instead of handing you fluent English for non-English audio.

## Non-Latin scripts

Two different problems here, and they need different tools:

- **Transliteration** (`yazses features enable translit`) — dictate Persian in
  romanized Finglish and get Persian script, by a letter-by-letter table lookup.
  Finglish is currently the only scheme.
- **Diacritics** (`yazses features enable diacritize`) — restores accents dropped
  from common loanwords (*cafe* → *café*, *naive* → *naïve*) from a fixed lexicon.
  It does not vocalise Arabic or Hebrew or restore Vietnamese tones.

There is also **SafeGlyph** (`yazses features enable safeglyph`), which guards
against visually confusable characters — relevant when mixing scripts in
identifiers or URLs.

### Getting a non-Latin script to actually type

Transcribing a script and *injecting* it are separate problems, and they can fail
independently. Text can be recognised perfectly and still not reach your
application, because the injection backend has to synthesise characters that are
not on your physical keyboard layout:

- **X11 (`xdotool`)** maps each character to an X keysym, so it handles non-Latin
  scripts. Verified end-to-end with Devanagari.
- **Clipboard (`[injection] backend = "clipboard"`)** passes UTF-8 straight
  through — script-independent by construction, and the reliable fallback.
- **Wayland (`ydotool`)** injects below the keyboard layout, so it can only press
  keys your active layout has. YazSes checks every non-ASCII character before
  typing: on a Latin layout there is no key for a Devanagari or Arabic character,
  so it pastes the whole burst from the clipboard instead (`[injection]
  fallback_to_clipboard`, on by default), which overwrites your clipboard and does
  nothing in most terminals. Test one sentence before relying on it.

If the transcript is right but nothing appears in the target application, change
the backend before changing the model.

## Pronunciation feedback

If you are dictating in a language you are still learning, there is an optional
capability that gives you feedback on pronunciation rather than silently
transcribing something you did not intend. **Planned — not yet wired**, so
`features enable` refuses it for now:

```sh
yazses features enable pronunciation
```

## Smoke-testing your language, offline

Nothing above is a measurement. The presets are derived from model size and
Whisper's published behaviour, **not** from anyone testing your language — and
per-language quality varies far more than size alone predicts. There is no
substitute for hearing your own voice come back.

Two ways, and the second needs no microphone once you have a clip:

```bash
# Live: hold your hotkey, say a sentence you can check.
yazses restart && yazses status

# From a file — reproducible, and shareable without re-recording.
yazses transcribe path/to/clip.wav
```

### Making your own fixture

YazSes deliberately ships **no recorded speech fixtures for non-English
languages**. A voice recording is personal data; licensing on public speech
corpora varies clip by clip; and a fixture nobody may legally redistribute is
worse than none, because it invites someone to add one that cannot stay. Record
your own — it is a minute of work and it stays yours:

```bash
# 10 s of 16 kHz mono, the format the engine wants
arecord -f S16_LE -r 16000 -c 1 -d 10 my-clip.wav     # Linux
# macOS: QuickTime → export WAV.  Windows: Voice Recorder, then convert.

yazses transcribe my-clip.wav
```

Keep the clip out of the repository. To contribute a *result* rather than audio,
use the table below.

### Report what you found

Open an issue titled "Language report: <code>"
(<https://github.com/MSKazemi/yazses/issues/new>) with one row per language. This is the only way the
project learns which languages are genuinely usable, because no one here speaks
them all.

| Field | Example |
|---|---|
| Language | `fa` |
| Model | `small` |
| YazSes version | the output of `yazses --version` |
| OS / CPU | Ubuntu 26.04, i7-1165G7 |
| Expected text | what you said — only if you are happy to publish it |
| Actual output | what appeared |
| Time to transcribe | 2.1 s for a 6 s clip |
| Verdict | usable / usable with corrections / unusable |
| Limitations noticed | proper nouns wrong, numbers correct |

**Do not paste anything you would rather keep private.** A verdict plus a
description of the errors is worth nearly as much as a transcript, and YazSes
never needs your words to diagnose anything.

## Honest limits

- **Accuracy is not uniform across languages.** Whisper is strong in
  well-resourced languages and noticeably weaker in low-resource ones. No amount
  of surrounding tooling changes that. Test with your own speech before relying
  on it.
- **Code-switching is not routed yet.** `[polyglot] adapter_path` names a
  code-switch-adapted model you train out-of-band, and the feature stays dormant
  until you set it; even then the daemon does not route speech to it yet. For
  mixed-language speech today, use a multilingual model with auto-detection.
- **Multilingual models are larger and slower** than the English-only ones. On a
  modest CPU expect noticeably more latency than `base.en`. See [performance
  tuning](../how-to/performance-tuning.md).
- Several of these capabilities are marked `optional` rather than `recommended`
  precisely because they are less battle-tested than the core dictation path.
  `yazses features` always tells you which tier a capability is in.

## Related

- [Personal vocabulary](../how-to/personal-vocabulary.md) — names and terms the model keeps mishearing
- [Performance tuning](../how-to/performance-tuning.md) — model size vs latency
- [Transcribe recordings offline](transcribe-audio-offline.md)
- [Configuration reference](../configuration.md)
