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

- **The `hotwords` feature** (`[hotwords]`, off by default) repairs your vocabulary
  *after* decoding, with any engine, instead of hinting it before. When a transcript
  contains a word that sounds the same as one of your terms and is spelled almost the
  same ("cooper netties" for Kubernetes), it is replaced, and every replacement is
  logged. It does not bias the decoder itself, so it cannot add a word the recogniser
  never produced a near-miss for. It is the same switch as `[stt] vocab_correction`.

  ```bash
  yazses features enable hotwords
  yazses restart
  ```

  Enabling it writes two lines, `enabled = true` and `opted_in = true`, and it runs
  only when both are there. If your config was first created by v2.11.0-dev.9 through
  v2.13.0 it may already say `[hotwords] enabled = true`: first-run setup wrote that line
  on its own back then, so it is not treated as your choice and does nothing. `yazses
  doctor` and `yazses features info hotwords` say so; run the command above to turn it on.

  It reads the same personal dictionary you build with `yazses vocab`. To correct
  toward a few extra words without adding them to the dictionary, list them in the
  config; they are read only while `hotwords` is on:

  ```toml
  [hotwords]
  enabled = true
  opted_in = true
  terms = ["Kubernetes", "Grafana"]
  ```

  Words under four letters are never corrected, and a word you spoke correctly is
  left alone, so a correct transcript comes back unchanged.

## See also

- [Configuration reference — `[stt]` and `[hotwords]`](../configuration.md)
- [Feature reference](../features.md)
- [Tune for speed and accuracy](performance-tuning.md)
