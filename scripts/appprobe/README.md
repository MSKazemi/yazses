# Does this app receive dictated text unchanged?

A contributor writing `examples/config.<app>.toml` is asked not to submit a config
they have not run — rightly. This makes the testable half testable **without a
microphone, and without touching your desktop**.

```bash
docker build -t yazses-appprobe scripts/appprobe
docker run --rm -v "$PWD/scripts/appprobe:/work" yazses-appprobe \
    bash /work/probe.sh kitty "" "" kitty bash -c 'cat > /work/out.txt'
```

```
RESULT|kitty|EXACT|kubectl get pods --namespace prod && cat src/main.py
```

## What it does and does not prove

It drives the **same `xdotool` XTEST path the daemon uses**, which an application
cannot tell apart from a real keypress, against a real window on an isolated
virtual X display. So it answers: *does this application receive dictated text
unchanged?*

It does **not** test speech. Say that in your pull request, the way the shipped
configs do. Half a measurement, honestly labelled, is worth more than a whole one
asserted.

## Results so far

| App | Result |
|---|---|
| kitty, Alacritty, Konsole, tmux, Neovim, Emacs, xterm, Sublime Text | **EXACT** — byte for byte |
| VS Code | **EXACT** — byte for byte, but *not* via `probe.sh`; see the retraction below |
| LibreOffice Writer | **PARTIAL** — see below |

LibreOffice Writer turned `kubectl get pods --namespace prod` into
`Kubectl get pods –namespace prod`: AutoCapitalise changed the command name, and
AutoCorrect replaced the double hyphen with an **en dash**. Neither is something
YazSes can prevent — it happens inside Writer after the characters arrive.

## Editors that need a mode change

`PRE` and `POST` are `xdotool` key sequences sent around the text. The text itself
is never altered.

```bash
# Neovim: enter insert mode first, then :wq
bash /work/probe.sh neovim i "Escape colon w Return colon q Return" \
    xterm -e "nvim /work/out.txt"

# Emacs: save and quit
bash /work/probe.sh emacs "" "ctrl+x ctrl+s ctrl+x ctrl+c" \
    xterm -e "emacs -nw /work/out.txt"
```

## Known limits — where the boundary actually is

Tested, so you do not have to rediscover it:

| Toolkit | Result |
|---|---|
| X11/GTK/Qt native — terminals, Vim, Emacs, Sublime | works, byte for byte |
| **Electron** — VS Code | `probe.sh` finds nothing lands. **This was a wrong conclusion** — see the retraction below. Electron accepts XTEST fine. |
| **Gecko** — Firefox, Thunderbird | no window at all in a bare Xvfb |
| **GTK with a session bus** — GNOME Terminal | no window, even with `dbus-launch` and `gnome-terminal-server` started by hand |
| **Java/Swing** — JetBrains | starts, but stops at a licence agreement. Clicking through a EULA automatically is not something this script should do. |

### Retraction — "Electron never receives a keystroke" was wrong

This file used to state that as a measured fact. It is not. Driving the same
xdotool XTEST path against a live VS Code window and reading the buffer back
returns `kubectl get pods --namespace prod` byte for byte, capitalisation and
both hyphens intact (`examples/config.vscode.toml`).

Two properties of `probe.sh` produced the false negative, and both look exactly
like an application ignoring XTEST:

- **It waits 7 seconds.** VS Code needs roughly 40 to draw in a container. An app
  that has not painted yet cannot receive anything.
- **A first-run modal absorbs every keystroke, silently.** VS Code opens on *"Sign
  in to use GitHub Copilot"*. The keys arrive, go to the dialog, and vanish with no
  error and no log line. Sending Escape first is enough.

The general lesson is worth more than the row it corrects: **a negative result from
a harness is a claim about the harness until you have looked at the screen.**

So `probe.sh` itself still covers native toolkits only. Electron, Gecko and anything
needing a real desktop session want a longer wait, a dismissed modal, and a click
into the editing area rather than the window centre — a side panel that is also a
text target produces a clean pass that proves nothing. Teaching the probe to do that
is a genuinely useful contribution.
- **The first few characters can be lost** in a GUI app if typing starts before a
  text field has the caret. Use a sentinel prefix to tell that apart from the app
  mangling your input — that is how the LibreOffice result above was confirmed to
  be AutoCorrect and not a timing artefact.
