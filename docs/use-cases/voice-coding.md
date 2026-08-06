---
title: Coding by voice — dictate code, LaTeX and git commands offline
description: Write code by voice on Linux, macOS and Windows. Spoken symbols become punctuation, word groups become snake_case or camelCase identifiers, maths becomes LaTeX, and git is driven by voice with a confirm gate before destructive commands.
---

# Writing code by voice

**Short answer:** prose dictation is bad at code, because code is mostly symbols
and identifiers rather than sentences. YazSes has a dedicated **Spoken Code Mode**
that converts spoken symbols into punctuation and spoken word-groups into cased
identifiers, plus voice-driven git and a safety gate for the terminal. All of it
runs offline.

## Why ordinary dictation fails at code

Dictate *"def get user name open paren user id close paren colon"* into a normal
speech-to-text engine and you get exactly that — an English sentence. What you
wanted was:

```python
def get_user_name(user_id):
```

The engine has no way to know that "open paren" is a symbol rather than a word,
or that "get user name" is one snake_case identifier rather than three words.
Code mode is what supplies that missing intent.

```sh
yazses features enable code
yazses restart
```

Activate it with the dedicated command key while you dictate. Spoken symbols
become punctuation, and word groups become cased identifiers (snake, camel or
pascal).

```sh
yazses features info code   # exact behaviour and an example
```

## Maths and LaTeX

If you write papers rather than programs, spoken maths is injected as LaTeX:

```sh
yazses features enable math
```

Saying *"x squared plus y squared"* injects `x^{2} + y^{2}`. Common expressions
work with no extra dependency; deeply nested expressions need the optional
`mathspeech` extra.

## Driving git by voice

```sh
yazses features enable gitvoice
```

A structured grammar maps spoken phrases onto git operations. The important part
is the safety design: **destructive operations wait for a spoken confirmation**,
and the undo is always spoken back to you. Say *"force push"* and it does not
immediately force-push — it asks, and it tells you how to reverse it.

## Terminal safety

Dictating into a shell is the highest-risk place a misrecognition can land. The
terminal command safety gate exists for exactly that:

```sh
yazses features enable cmdsafety
```

It intercepts commands that would be destructive before they run, rather than
trusting that the transcription was correct.

!!! tip "The text-target guard is on by default"
    If no editable text field has focus, YazSes does **not** type your words
    somewhere arbitrary. The transcript is copied to the clipboard instead and
    the tray icon turns yellow. This prevents the classic dictation accident of
    a paragraph being interpreted as keystrokes by whatever window happened to be
    in front.

## Editor navigation and commands

Beyond text entry, a fast regex command grammar maps spoken phrases to real key
sequences — *"undo that"*, *"save file"*, *"go to line 42"*. Several optional
capabilities extend this for development work:

| Capability | Enable with | What it does |
|---|---|---|
| Voice Jump-to-Symbol | `yazses features enable jump` | Jump to a symbol by name |
| Voice Fuzzy File Open | `yazses features enable fileopen` | Open a file by speaking part of its name |
| Spoken Shell Pipeline Builder | `yazses features enable shellpipe` | Compose a shell pipeline by voice |
| Spoken Regex Builder | `yazses features enable spokenregex` | Describe a regex in words |
| Auto-Pairing & Wrap | `yazses features enable autopair` | Balance brackets and quotes |
| Voice Case Transform | `yazses features enable casetransform` | Re-case an identifier by voice |

Browse all 139 with `yazses features`, and see what any one of them does with
`yazses features info <name>`.

## Editor context

YazSes can prime the recogniser with context from your editor's language server,
so identifiers already present in the file you are working in are more likely to
be transcribed correctly. It is off by default:

```toml
[commands]
lsp_enabled = true
lsp_editor = "neovim"
```

You can also maintain a [personal vocabulary](../how-to/personal-vocabulary.md)
of project-specific names the model keeps mishearing.

## Honest limits

**If voice coding is your primary interface, look hard at Talon.** Talon is built
around exactly this — a deep, scriptable voice-coding ecosystem with a large
community grammar library. YazSes is dictation-first, with code mode and commands
as strong built-in extras rather than a scripting platform. See the
[comparison](../comparison.md); the two can coexist.

YazSes is the better pick when you want code dictation that works out of the box,
is fully open-source, and shares one offline install with your prose dictation,
meeting capture and transcription.

## Related

- [Macros & snippets](../how-to/macros-and-snippets.md)
- [Dictation over SSH](../how-to/remote-dictation.md) — dictate into a remote dev box
- [Personal vocabulary](../how-to/personal-vocabulary.md)
- [CLI reference](../cli-reference.md)
