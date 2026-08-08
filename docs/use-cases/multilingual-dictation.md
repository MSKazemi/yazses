---
title: Multilingual offline dictation — non-English speech to text and code-switching
description: Dictate in languages other than English, translate speech to English as you speak, transliterate into a non-Latin script, and handle sentences that naturally mix two languages — all running on-device with no cloud service.
---

# Dictating in more than one language

**Short answer:** the underlying Whisper model is multilingual, so dictation is not
English-only. YazSes adds the layers around it that bilingual speakers actually
need — switching language per application, transliterating into a non-Latin
script, translating as you speak, and handling sentences that mix two languages
mid-thought.

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

There is no separate "download" step to run by hand — faster-whisper fetches
`small` (or whichever multilingual model you configured) the first time the
daemon starts with it set, the same way it fetches `.en` models, and caches it
in the Hugging Face cache. Multilingual weights are somewhat larger than their
`.en` counterparts at the same size tier, so expect a longer first-run download
and a few hundred MB more disk use. Confirm it landed with:

```bash
yazses doctor
```

which reports the configured model as cached, local, or not yet downloaded.
If the download stalls or fails partway (a slow or interrupted connection is
the usual cause), delete the partial cache entry and restart the daemon to
retry from a clean state — `yazses doctor` output tells you which model is
misbehaving.

## Sentences that mix two languages

This is the case ordinary dictation handles worst. Bilingual speakers routinely
switch mid-sentence — a Persian speaker dropping in English technical terms, a
Spanish speaker using English product names — and a single-language recogniser
mangles whichever language it was not set to.

```sh
yazses features enable polyglot
```

```toml
[polyglot]
pair = "fa-en"          # the two languages you actually mix
```

The routing layer detects the dominant language of each span and handles the
switch, rather than forcing the whole utterance through one language setting.

## Per-application language switching

If you write in one language in your email client and another in your editor,
switching by hand every time is friction that makes dictation not worth using:

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
| Speak language X, get text composed in language Y | `yazses features enable compose` |
| Two people, two languages, back and forth | `yazses features enable interpret` |

For an existing recording rather than live dictation, the same translation path is
one flag:

```sh
yazses transcribe interview.fr.m4a --language translate   # any language → English
```

## Non-Latin scripts

Two different problems here, and they need different tools:

- **Transliteration** (`yazses features enable translit`) — you speak the
  language but want it written in a different script, or you type Latin and want
  the native script.
- **Diacritics** (`yazses features enable diacritize`) — restoring diacritical
  marks that speech does not distinguish, which matters a great deal in Arabic,
  Hebrew and Vietnamese.

There is also **SafeGlyph** (`yazses features enable safeglyph`), which guards
against visually confusable characters — relevant when mixing scripts in
identifiers or URLs.

## Pronunciation feedback

If you are dictating in a language you are still learning, there is an optional
capability that gives you feedback on pronunciation rather than silently
transcribing something you did not intend:

```sh
yazses features enable pronunciation
```

## Honest limits

- **Accuracy is not uniform across languages.** Whisper is strong in
  well-resourced languages and noticeably weaker in low-resource ones. No amount
  of surrounding tooling changes that. Test with your own speech before relying
  on it.
- **Code-switching routing is a routing layer.** A dedicated code-switch-adapted
  transcription model can be plugged in via `[polyglot] adapter_path`, but that
  adapter is trained out-of-band and the feature stays dormant until you set it.
  Without it you get sensible routing over a general multilingual model, not a
  purpose-trained code-switch model.
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
