---
title: Change the hold-to-talk key
description: Pick a hotkey — and an optional dedicated command key — that never clashes with typing.
---

# Change the hold-to-talk key

YazSes is **hold-to-talk**: you hold a key, speak, and release. By default the
key is a modifier that never collides with normal typing:

- Linux: `right_alt`
- macOS: `right_option`
- Windows: `right_ctrl`

## Show the current key

```bash
yazses hotkey show
```

This prints the hold-to-talk (dictation) key, the command key if one is set, and
the full list of valid choices.

## Set a new key

```bash
yazses hotkey set right_ctrl     # hold Right-Ctrl to dictate
yazses restart                   # apply the new key
```

Valid keys are:

```
right_alt  left_alt  right_ctrl  left_ctrl
right_shift  left_shift  right_meta  left_meta  space
```

**Choose a dedicated modifier** (`right_alt`, `right_ctrl`, or `right_shift`) that
you don't otherwise use. Avoid `space` — you'd trigger dictation every time you
type a space. A right-hand modifier is a good pick because most shortcuts use the
left-hand ones, so it stays free.

> Tip: on some Linux desktops `right_alt` (AltGr) is bound to compose/special
> characters, and in VS Code a bare `Alt` press can open the menu bar. If your
> chosen key does something unexpected, switch to `right_ctrl`.

## Add a dedicated command key

By default, voice **commands** (like "scratch that", "new line", "undo") are
auto-detected on the same key you dictate with. If you want an unambiguous split
— one key that always types text, another that always runs commands — set a
**command key**:

```bash
yazses hotkey command right_ctrl    # dictate on right_alt, commands on right_ctrl
yazses restart                      # apply
```

Now:

- Hold the **dictation key** → whatever you say is typed as text.
- Hold the **command key** → whatever you say is parsed as a command and never
  typed as literal text. An unrecognised phrase is simply ignored, not inserted.

The command key **must differ** from your dictation key — YazSes refuses to set
them to the same key. Remove the command key (back to auto-detect) with:

```bash
yazses hotkey command off
yazses restart
```

## Under the hood

`yazses hotkey set` writes `[hotkey] key` and `yazses hotkey command` writes
`[hotkey] command_key` in your `config.toml`, using a comment-preserving writer.
You can also edit these keys by hand; run `yazses restart` afterward either way.

## See also

- [Configuration reference — `[hotkey]`](../configuration.md)
- [Feature reference](../features.md)
- [Create spoken macros and snippets](macros-and-snippets.md)
