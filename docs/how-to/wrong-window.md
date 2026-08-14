---
title: Dictation types into the wrong window
description: Why dictated text lands somewhere unexpected, what the no-text-target guard does about it, and how to make the detection precise with AT-SPI on Linux.
---

# Dictation types into the wrong window

You hold the key, speak, release — and the words appear in the wrong place, or
nowhere at all. There are three distinct causes, and they need different fixes.

!!! info "Verified on"

    Ubuntu 24.04 · GNOME 46 · X11 · YazSes 2.18.2. Commands and their output are
    from that machine.

## First: what does YazSes think the target is?

```bash
yazses doctor | grep -i "text-target\|injection"
```

Real output here:

```
  [OK] Injection: xdotool (X11)
  [OK] Text-target guard: clipboard (best-effort; apt install python3-pyatspi gir1.2-atspi-2.0 for precision)
```

That second line is the important one, and **"best-effort" is the usual cause of
this whole page**.

## Cause 1 — there was no text field, so it went to the clipboard

YazSes checks whether the focused element actually accepts text. When it does not,
it does **not** type into whatever happens to have focus — it copies the transcript
to the clipboard and notifies you, so the words are recoverable instead of being
scattered into a browser's keyboard shortcuts.

That is the `[injection] target_guard` setting, `clipboard` by default:

```toml
[injection]
target_guard = "clipboard"   # clipboard (default) | warn | off
```

- `clipboard` — copy, notify, do not type. The tray turns **yellow**.
- `warn` — notify, then type anyway.
- `off` — no check at all.

**If your words keep ending up on the clipboard**, the detector is deciding your
field is not editable. That is cause 2.

## Cause 2 — the detection is guessing (Linux)

Precise detection uses AT-SPI, the desktop accessibility bus. Without it, YazSes
falls back to window heuristics that are right most of the time and wrong for
exactly the applications people complain about — Electron apps, Java apps, and
anything drawing its own text field.

**This is a system package, not a pip one:**

```bash
sudo apt install python3-pyatspi gir1.2-atspi-2.0     # Debian/Ubuntu
sudo dnf install python3-pyatspi                      # Fedora
```

Verify it is now importable *by the interpreter YazSes runs under*:

```bash
python3 -c "import pyatspi; print('ok')"
```

!!! warning "A pipx / uv-tool install cannot see system site-packages"

    This is the trap. `pyatspi` installs into the system Python, and an isolated
    environment does not include it, so `apt install` alone changes nothing. If you
    installed with `pipx` or `uv tool`, recreate the environment with system
    packages visible, or accept best-effort detection. On this machine `pyatspi`
    was **not** importable, which is exactly why `doctor` says "best-effort".

Then `yazses restart` and re-check `yazses doctor`.

## Cause 3 — the wrong window genuinely had focus

Two ordinary causes, both worth ruling out:

- **You changed focus during the hold.** Injection happens on release, into
  whatever has focus *then*, not when you started speaking.
- **A notification or dialog stole focus** mid-utterance.

Nothing detects this for you; the clipboard fallback is what makes it recoverable.

## The Wayland case

On Wayland, one application cannot inspect or focus another's window — that is the
security model, not a bug. Text injection still works through `ydotool`, but the
"is this a text field" question has a smaller answer, so best-effort detection is
more often all there is. See the [capability matrix](../capability-matrix.md).

## What "fixed" looks like

```bash
yazses doctor | grep -i text-target
```

```
  [OK] Text-target guard: clipboard (AT-SPI precise)
```

…and dictating into a non-text surface (a browser page with nothing focused)
notifies you and copies, rather than typing shortcuts into the page.

## What this page does not cover

- **macOS and Windows** use best-effort detection with no AT-SPI equivalent wired
  up; the guard still works, and is still `clipboard` by default. Neither was
  tested for this page.
- The AT-SPI verification above was done by observing the *absence* of `pyatspi`
  on this machine. The "fixed" output is read from `system/doctor.py`, not observed
  — installing a system package to screenshot a docs page was not worth changing
  this machine's state.
