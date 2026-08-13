---
title: Dictating code and technical vocabulary
description: How to make offline voice dictation get identifiers, jargon and punctuation right — yazses vocab, initial_prompt, vocabulary correction and spoken punctuation, with the exact commands.
---

# Dictating code and technical vocabulary

Speech models are trained on speech, and nobody says `kubectl` in a podcast. Out
of the box you will get "cube control", "cooper netties" and prose punctuation in
a file that wanted symbols. All four fixes are one command each.

Everything here is local. Nothing on this page sends a word anywhere.

## 1. Teach it your words — `yazses vocab`

This is the highest-value thing you can do, and it takes seconds:

```bash
yazses vocab add kubectl
yazses vocab add Kubernetes
yazses vocab add PostgreSQL
yazses vocab list
yazses restart
```

The list lives at `~/.config/yazses/vocabulary.txt`, one term per line, and is
merged into the recogniser's prompt on every burst. Add colleagues' names, your
repository names, library names, and any identifier you say often.

**A larger model will not do this for you.** `small.en` cuts the overall error
rate by about a third and costs three times the latency
([the numbers](../models.md)) — and it still has never heard of your internal
service. The dictionary is free and targets exactly the words you care about.

## 2. Repair what it still mishears — `[stt] vocab_correction`

Priming helps; it is not perfect, and with `[stt] engine = "parakeet"` or
`"moonshine"` it does nothing at all, because `initial_prompt` is a Whisper-only
concept. Correction closes that gap after decoding:

```toml
[stt]
vocab_correction = true
```

```bash
yazses restart
```

Now "deploy to cooper netties" becomes "deploy to Kubernetes" — matched
phonetically against your dictionary, including when the recogniser split one
word into two.

It is **off by default** because it rewrites transcribed text, and it is
deliberately cautious about when it fires:

- a word that differs only in **case** is left alone, so `yazses doctor` in a
  terminal is never "corrected" into `YazSes doctor`;
- **short words are never touched** — there is not enough signal in three letters;
- ordinary words are not glued together to reach a term, so "from this" cannot
  become "Prometheus";
- possessives keep their `'s`.

Every substitution is written to the log, so you can see what it changed:

```bash
yazses logs | grep "Vocabulary correction"
```

## 3. Get the punctuation you meant

Prose dictation adds commas and full stops. Code wants symbols, and you want to
say them:

```toml
[commands]
voice_punctuation = true
```

Then "def sync open paren self close paren colon" arrives as `def sync(self):`.
It is off by default because these words occur in ordinary speech — turn it on
for coding, leave it off for prose. The full word list is in the
[configuration reference](../configuration.md).

## 4. Prime one-off context — `[stt] initial_prompt`

For a session spent in one codebase, seed the vocabulary of that codebase:

```toml
[stt]
initial_prompt = "We are editing a Rust crate using tokio, serde and axum."
```

This biases recognition toward those words without adding them permanently to
your dictionary. Whisper only — Parakeet and Moonshine ignore it, which is what
step 2 is for.

## What "working" looks like

Say: **"run kubectl get pods in the yazses namespace"**

| Setting | What you get |
|---|---|
| Nothing configured | `run cube control get pods in the yes says namespace` |
| After `yazses vocab add kubectl` (+ the app name is built in) | `run kubectl get pods in the yazses namespace` |

Check your own setup rather than trusting the table:

```bash
yazses doctor          # model, vocabulary size, engine, injector
yazses vocab list      # the words it is priming
```

If a word is still wrong after adding it, that is worth reporting — include the
word, what you heard back, and your `[stt] model`, and leave out anything private.

## Applies to

YazSes 2.18+, all platforms. `vocab_correction` needs no extra dependency;
`voice_punctuation` needs none either. Neither requires a specific engine.

## Related

- [Choosing a model](../models.md) — why a bigger model is usually the wrong fix
- [Voice commands](voice-commands.md) — editor actions rather than text
- [Dictating in more than one language](multilingual-dictation.md)
- [Personal vocabulary](../how-to/personal-vocabulary.md)
