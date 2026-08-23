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
`%LOCALAPPDATA%\yazses\`.)

## Add words

```bash
yazses vocab add YazSes                  # add one name
yazses vocab add Kubernetes kubectl      # add several at once
yazses vocab list                        # check what is in the dictionary
```

Adding is case-insensitively de-duplicated, so re-adding a word is harmless.
No restart is needed: the daemon re-reads `vocabulary.txt` on every burst, so a word
added now is in effect on your next dictation.

## List and remove

```bash
yazses vocab list                # show every word in the dictionary
yazses vocab remove kubectl      # drop a word
yazses doctor                    # confirm what reaches the recogniser
```

## Confirm the words are actually in use

`yazses vocab list` shows what is in the file. To see what reaches the recogniser,
ask `doctor`:

```console
$ yazses doctor
...
  [OK] STT prompt: app name + 24 from `yazses vocab` (YazSes, NovaFabric, KubeIntellect, +21 more)
```

That row names every source that is folded into the prompt, so you can tell them
apart at a glance:

| The row says | What it means |
|---|---|
| `app name only` | Nothing of yours is primed yet — only the coined name `YazSes`. |
| `N from \`yazses vocab\`` | Your personal dictionary, this many words. |
| `[stt] initial_prompt '…'` | The prompt set directly in `config.toml`. |
| `N from YAZSES_VOCABULARY` | Terms passed in through the environment variable. |
| `terms mined from your corpus` | `[personalize]` is on and adding your frequent phrases. |

You do not need to restart to change the dictionary — the daemon re-reads
`vocabulary.txt` on every burst.

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
  tune` learning loop proposes additions to `initial_prompt` from your corpus —
  but only from terms **you** corrected. A spelling taken from `tune`'s own
  re-transcription would be one Whisper model's guess at a word Whisper cannot
  spell, which is the case `initial_prompt` exists for, so `tune` refuses that
  source. If you never correct a dictation, expect no vocabulary proposal; add the
  term here instead.

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
