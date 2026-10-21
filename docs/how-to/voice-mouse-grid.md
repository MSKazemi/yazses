---
title: Click anywhere by voice with the mouse grid
description: Say 'mouse grid', then cell numbers, then 'click' to move the pointer and click by voice on any pixels — what it hears, what it never does, and where it works.
---

# Click anywhere by voice with the mouse grid

The **Voice Mouse Grid** is a way to point and click with no hand on the mouse, where
nothing else can find the button for you: a canvas, a game, a custom-drawn window. You say
**"mouse grid"**, and the screen is split into numbered cells (3 × 3 by default). Saying a
number moves the pointer to the centre of that cell and splits that cell again, so a few
numbers get you to a precise spot. Then you say **"click"**.

It is **experimental** and **off by default**.

## Turn it on

```sh
yazses features enable mousegrid
yazses restart
```

or, in `config.toml`:

```toml
[mousegrid]
enabled = true
cols = 3
rows = 3
```

To see the numbered cells, the overlay must be on too (`[overlay] enabled = true`). Without it
the grid still works — the pointer itself jumps to each cell's centre — but you have to know
the numbering: cells count left to right, top to bottom, like a phone keypad.

## What you can say

| Say | What happens |
|---|---|
| "mouse grid" | Opens a grid over the whole primary screen. Saying it again starts over. |
| "three", "3" | Moves the pointer to the centre of cell 3 and zooms into it. |
| "three seven", "37" | Two zooms in one breath (on grids of nine cells or fewer). |
| "click", "right click", "double click" | Clicks at the pointer and closes the grid. |
| "back" | Zooms out one level. |
| "cancel" | Closes the grid without clicking. |

Every phrase must be the **whole** utterance. "Click the link" is dictation, and so is
"three apples".

## What it never does

- **It never claims words while no grid is open**, except the exact phrase "mouse grid".
  Your dictation is unchanged until you say it.
- **It never swallows speech it does not understand.** While a grid is open, anything that
  is not a grid command closes the grid and is dictated as usual.
- **It never clicks before you have chosen a cell**, so a stray "click" cannot click the
  middle of your screen.
- **It does not stay open by accident**: an open grid closes itself after 30 seconds with no
  grid command.
- It respects the hands-free pause (`yazses handsfree pause`, or the voice stop word) **when
  `[handsfree_safety]` is enabled**: while paused, the grid does not open and the pointer does
  not move. With `[handsfree_safety]` off (the default) there is no pause to respect, and
  `yazses handsfree pause` does not stop the grid; say "cancel" instead.
- Homophones are not accepted. "To", "for" and "tree" are not numbers; if you are misheard,
  say the number again, or "back".

## Where it works

The grid needs a pointer backend that can move to an exact position:

- **X11** (Linux): yes. The screen size is read from `xrandr`.
- **macOS**: yes. The screen size comes from the overlay, so turn the overlay on.
- **Wayland** and **Windows**: not yet. Their pointer backends only move relative to where the
  pointer already is, and the grid refuses rather than guess: saying "mouse grid" draws no
  grid. The daemon log names the reason, and with `[earcon]` on you hear the error tone.

## Limits, stated plainly

- The grammar and the 30-second timeout were tuned on **synthetic input only** (test
  transcripts, not real speech in real rooms). Nobody has measured how often a real
  recogniser hears "click" or a number when you did not say one; check it in your own room
  before you rely on it.
- Number words go up to sixteen. On a larger grid, say the bigger numbers as digits; a bigger
  number spoken as a word ("seventeen") is not a grid command, so it closes the grid and is
  typed. The daemon logs a warning at start-up when `cols × rows` is above sixteen.
- Hyphenated spellings are read as spaces, so "Right-click." and "Mouse-grid." work.
- On a HiDPI X11 setup where Qt scales the overlay, the drawn cells may not line up with the
  pointer positions. This has not been checked on a scaled display.
