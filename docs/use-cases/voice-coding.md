---
title: Coding by voice — dictate code, LaTeX and git commands offline
description: Write code by voice on Linux, macOS and Windows. Spoken symbols become punctuation, maths becomes LaTeX, git phrases become git commands you review before running, and a safety gate holds destructive shell commands.
---

# Writing code by voice

**Short answer:** prose dictation is bad at code, because code is mostly symbols
and identifiers rather than sentences. YazSes has a dedicated **Spoken Code Mode**
that converts spoken symbols into punctuation, plus a git-phrase translator and a
safety gate for the terminal. All of it runs offline.

## Why ordinary dictation fails at code

Dictate *"def sync open paren self close paren colon"* into a normal
speech-to-text engine and you get exactly that — an English sentence. What you
wanted was:

```python
def sync(self):
```

The engine has no way to know that "open paren" is a symbol rather than a word.
Code mode is what supplies that missing intent. It runs in command mode, so turn
it on and bind a command key (any key other than your dictation key):

```sh
yazses features enable code
yazses hotkey command right_ctrl
yazses restart
```

Then hold the command key and start the phrase with *"code"*: *"code def sync open
paren self close paren colon"* types `def sync(self):`.

Code mode does **not** join words into identifiers: *"code def get user name open
paren user id close paren colon"* types `def get user name(user id):`. Re-case the
words afterwards with `yazses case` (or the Voice Case Transform capability below),
or add the identifiers to your [personal vocabulary](../how-to/personal-vocabulary.md).

```sh
yazses features info code   # what it does and how to trigger it
```

## Maths and LaTeX

If you write papers rather than programs, spoken maths is injected as LaTeX. It
also runs in command mode, so it needs a command key:

```sh
yazses features enable math
```

Hold the command key and say *"math x squared plus y squared"* — it injects
`x^{2} + y^{2}`. The leading *"math"* (or *"maths"*, *"formula"*, *"equation"*) is
required. Only the built-in grammar exists: Greek letters, the arithmetic operators,
*squared*/*cubed*, square roots and the integral and sum symbols. Anything beyond it
is typed as words, so check the output.

## Driving git by voice

```sh
yazses gitvoice "create branch feature slash login"   # prints: git checkout -b feature/login
```

`yazses gitvoice "<phrase>"` turns a spoken git phrase into a git command and prints
it with how to undo it; `--run` runs it, and a destructive one (force-push, hard
reset, `branch -D`, discarding uncommitted changes) never runs without `--yes`. It is
a command-line tool: there is no spoken confirmation and nothing is spoken back.

Say a branch name the way it is written: *"create branch feature slash login"*
becomes `git checkout -b feature/login`, and the capitalisation you speak is kept,
because git refs are case-sensitive. Most phrases it does not recognise are refused
with a list of what it understands, but not all of them — always read the printed
command before adding `--run`.

## Terminal safety

Dictating into a shell is the highest-risk place a misrecognition can land. The
terminal command safety gate exists for exactly that. It is on by default for new
installs (the first start writes it into your config);
`yazses features enable cmdsafety` turns it back on if you disabled it.

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
| Spoken Regex Builder | `yazses features enable spokenregex` | Say *"regex \<description\>"* and get the pattern |
| Auto-Pairing & Wrap | `yazses features enable autopair` | Balance brackets and quotes |
| Voice Case Transform | `yazses features enable casetransform` | Re-case an identifier by voice |

Browse them all with `yazses features`, and see what any one of them does with
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

!!! warning "These keys are not read"

    The editor-context prompt was designed and never wired — the daemon does not
    construct the editor bridge, so setting these changes nothing. `yazses jump`
    contacts your editor directly and works regardless of them.

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
