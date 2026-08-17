---
title: Add words to your personal dictionary
description: Teach YazSes the names, jargon, and acronyms your STT keeps mis-hearing.
---

# Add words to your personal dictionary

Whisper sometimes mis-spells names, technical terms, or acronyms it hasn't seen
in context — `Kubernetes` comes out as "Cuber Netties", a colleague's name gets
mangled. Your **personal dictionary** fixes that: the words you add are primed
into the STT prompt so recognition is biased toward spelling them correctly.

The dictionary lives in a plain text file, one word or phrase per line, at:

```
~/.config/yazses/vocabulary.txt
```

(On macOS it is under `~/Library/Application Support/yazses/`, on Windows under
`%APPDATA%\yazses\`.)

## Add words

```bash
yazses vocab add YazSes                  # add one name
yazses vocab add Kubernetes kubectl      # add several at once
yazses restart                           # apply so STT spells them right
```

Adding is case-insensitively de-duplicated, so re-adding a word is harmless.
After adding, `yazses restart` reloads the daemon with the updated prompt.

## List and remove

```bash
yazses vocab list                # show every word in the dictionary
yazses vocab remove kubectl      # drop a word
yazses restart                   # apply the removal
```

## How it works — and its limits

The dictionary words are merged into Whisper's `initial_prompt`. That **biases**
recognition; it does not force it. A soft prompt nudges the decoder toward your
terms but a badly mis-heard word can still slip through, especially rare proper
nouns spoken quickly.

For stubborn terms, two stronger, related mechanisms exist:

- **`[stt] initial_prompt`** in `config.toml` is a free-form context string primed
  into the same prompt. Your dictionary is merged *ahead* of it, so both take
  effect together. Use `initial_prompt` for a sentence of context ("A talk about
  Kubernetes and GitOps"); use the dictionary for individual terms. The `yazses
  tune` learning loop proposes additions to `initial_prompt` from your corpus.

- **The `hotwords` feature** (`[hotwords]`, off by default) goes further than a
  soft prompt: it biases recognition toward your vocabulary with a hotword trie,
  so rare names and jargon actually *win* the decode rather than just being
  hinted. **Planned — not yet wired**, so `features enable` refuses it for now;
  when it lands, turn it on where a soft prompt isn't enough:

  ```bash
  yazses features enable hotwords
  yazses restart
  ```

  `hotwords` reads the same personal dictionary you build with `yazses vocab`, so
  there is nothing extra to configure — enable it and your existing words get the
  stronger biasing.

## See also

- [Configuration reference — `[stt]` and `[hotwords]`](../configuration.md)
- [Feature reference](../features.md)
- [Tune for speed and accuracy](performance-tuning.md)
