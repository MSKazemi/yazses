---
title: Control your computer by voice — offline voice commands and macros
description: Beyond dictation. Speak to undo, save, select, jump to a line, run tests or fire a multi-step macro, with the same hold-to-talk key that types your words. Runs offline with a fast regex grammar, no cloud assistant involved.
---

# Controlling your computer by voice

**Short answer:** the same key that types your words also runs commands. Say *"the
quick brown fox"* and it is typed; say *"go to line 42"* and it jumps there
instead. The decision is made by a fast regex grammar running on your machine —
there is no assistant, no wake word and no network call.

## Dictation and commands from one key

Most tools make you choose: a dictation tool that only types, or a voice-control
platform you have to program. YazSes classifies each utterance as you release the
key:

```
hold → speak → release → classify → DICTATE: type the text
                                  → COMMAND: send the key sequence
```

| Say something like… | What happens |
|---|---|
| *"the quick brown fox"* | Typed at the cursor |
| *"undo that"* / *"undo five times"* | Sends undo |
| *"delete the last three words"* | Deletes the last 3 words |
| *"save file"* · *"copy"* · *"paste"* | Save / copy / paste |
| *"select all"* · *"select to end"* | Selection commands |
| *"comment this line"* | Toggles a comment |
| *"go to line 42"* | Jumps to line 42 |
| *"go to function parse_config"* | Opens the editor's Go-to-Symbol (Ctrl+Shift+O) and types the name |
| *"run the tests"* / *"run the build"* | Runs the editor/terminal action |
| *"rename this to user_id"* | Renames the symbol |

Commands are **on by default** — you do not need to enable anything.

## How the classification works

Two tiers, and the second one is optional:

- **Tier 1 — regex grammar.** Fast, deterministic and offline. It handles the
  phrasings above with no model inference at all, which is why commands feel
  instant.
- **Tier 2 — optional SLM router.** When Tier 1 finds no command at all, a small
  (~0.5B) language model can be consulted to catch phrasings the grammar did not
  anticipate. Dormant unless you point `[commands] slm_model_path` at a local GGUF.

```toml
[commands]
slm_model_path = ""            # a local GGUF; empty means Tier 1 only
slm_confidence_threshold = 0.75 # the default; below this, the router's answer is discarded
```

!!! note "Tier 2 is off until you give it a model"

    Leave `slm_model_path` empty and **Tier 1 decides every utterance** — no model
    is loaded and no inference runs on the dictation path. That is the default, and
    it is what the command-recognition benchmark measures. Set the path and the
    router is consulted only for utterances Tier 1 classified as plain dictation;
    its answer is taken only above `slm_confidence_threshold`, and a router that
    fails or raises falls back to typing the words rather than losing them.

### When you want to be certain it types, not acts

Ordinary speech sometimes collides with command phrasing. Two escape hatches:

- **A dedicated command key.** Bind a second hotkey that *forces* command mode, so
  your main key never does anything but type:

  ```sh
  yazses hotkey command <key>     # 'off' disables it
  ```

- **The text-target guard**, on by default, means that if no editable field has
  focus your words are copied to the clipboard rather than being interpreted as
  keystrokes by whatever window is in front.

## Macros — multi-step actions from one phrase

When a single key sequence is not enough, define a macro:

```sh
yazses features enable macros
```

A macro binds a spoken phrase to a sequence of steps, so *"start my review"* can
run several actions in order. See
[macros & snippets](../how-to/macros-and-snippets.md) for the format.

Related capabilities worth knowing about:

| Capability | Enable with | What it gives you |
|---|---|---|
| Chorded Shortcut Synthesis | `yazses features enable chords` | Speak a modifier chord instead of contorting your hand |
| Voice Snippets | `yazses features enable snippets` | Hold the command key and say *"insert \<trigger\>"* to expand it into boilerplate |
| Voice Git Choreographer | `yazses gitvoice "<phrase>"` | Turn a spoken git phrase into a git command; destructive ones need `--yes` |
| Spoken Shell Pipeline Builder | `yazses features enable shellpipe` | Compose a shell pipeline by speaking it |
| Terminal Command Safety Gate | on for new installs; `yazses features enable cmdsafety` if you disabled it | Catch destructive commands before they run |
| Voice Window Management | `yazses features enable windowctl` | Move and switch windows by voice |
| Voice Mouse Grid | `yazses features enable mousegrid --force` *(experimental)* | Say "mouse grid", cell numbers, then "click" to move the pointer and click by voice (X11 or macOS) |
| Voice Fuzzy File Open | `yazses features enable fileopen` | Open a file by speaking part of its name |

Browse everything with `yazses features`, and see what any single capability does
— with a worked example — using `yazses features info <name>`.

### Focusing a window by name

With Voice Window Management enabled, you can also say which window you want:

```
"focus the browser"      "switch to gedit"      "bring up my notes"
```

YazSes matches what you said against the visible window titles and raises the
best match. Two behaviours are deliberate:

- **An ambiguous query focuses nothing.** If two windows score alike — say
  `notes.txt — gedit` and `notes.md — gedit` — picking one would send your next
  sentence into a document you were not looking at, so YazSes tells you instead.
- **A command that matches nothing is still not typed.** "focus the browser"
  appearing in your document is a worse outcome than nothing happening.

!!! warning "X11 only, and not by choice"

    Wayland does not let one application focus another's window, and no portal
    exposes it. On Wayland this command is inactive and the words are dictated
    normally; layout commands your compositor binds itself still work.
    `yazses doctor` reports which case you are in.

## Per-application behaviour

By default a command sends VS Code's key bindings in every application: Ctrl+S save,
Ctrl+G go to line, Ctrl+Shift+K delete line, Ctrl+Shift+O go to symbol, F2 rename.
VS Code and the editors that copied its bindings get the right keys. Other editors
may not.

**Editor command profiles** (experimental, off by default) send the keys the
focused editor binds instead:

```toml
[commands]
editor_profiles = true   # pick the keys from the application in focus
profile = "auto"         # or pin one: "default", "vscode", "jetbrains", "sublime"
```

Restart the daemon (`yazses restart`) after changing either key.

| Profile | Chosen when the focused app is | What changes |
|---|---|---|
| `jetbrains` | IntelliJ IDEA, PyCharm, WebStorm, CLion, GoLand, Rider, Android Studio, … | delete line Ctrl+Y · go to class Ctrl+N · go to file Ctrl+Shift+N · go to function Ctrl+F12 (File Structure) · rename Shift+F6, then the new name, without Ctrl+A |
| `sublime` | Sublime Text | go to function/class Ctrl+R · **rename is refused** |
| `vscode` / `default` | VS Code, VSCodium, and anything not recognised | nothing |

A **refused** command sends no keys and types nothing. Sublime Text has no built-in
rename, and its F2 jumps to the next bookmark. The default rename (F2, Ctrl+A, type
the name) would select the whole file there and type over it.

**How the application is found.** YazSes reads the focused application through
AT-SPI or, on an X11 session, `xdotool`. That is the same probe the "no text
target" guard uses. On macOS, on Windows and on a Wayland session without AT-SPI
there is no such source yet. There every command keeps the default keys, and the
daemon log says so once. A pinned `profile` works everywhere, because it does not
need to know the application.

**Limits.** The bindings come from each editor's *default* keymap on Linux and
Windows. They have not yet been tested by sending keys to a running editor. If you
remapped a key, or you use a macOS keymap, you get the default keys. There is no
Vim profile: Vim is modal, so a key chord means something different in each mode.
For any other app-specific action, use a [macro](../how-to/macros-and-snippets.md).

## Honest limits

- **This is not an assistant.** YazSes types text and sends key sequences. It does
  not browse, reason about your files, hold a conversation, or take open-ended
  instructions. If that is what you want, this is the wrong tool.
- **It is not a voice-scripting platform.** Talon is far more powerful for
  programming your desktop by voice, with a large community grammar ecosystem.
  YazSes aims at dictation-first with commands as a built-in extra — see the
  [comparison](../comparison.md).
- **Command phrasing is finite.** Tier 1 recognises the patterns it was written
  for. Macros let you add your own, but there is no open-ended natural-language
  understanding unless you enable the Tier 2 SLM router (`[commands] slm_model_path`),
  which needs a local GGUF model and `llama-cpp-python`.
- **Some capabilities in the table are `optional` rather than `recommended`**, and
  a few desktop-control ones need X11. `yazses features` always states the tier.

## Related

- [Coding by voice](voice-coding.md) — spoken symbols, identifiers, LaTeX, git
- [Macros & snippets](../how-to/macros-and-snippets.md)
- [Accessibility & hands-free use](accessibility-rsi-hands-free.md)
- [Change the hotkey](../how-to/change-hotkey.md)
- [CLI reference](../cli-reference.md)
- [Research: voice control](../research/voice-control.md) — the measured accuracy
  and latency behind the engines, and why whispering can be a command channel
