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
| VS Code, Firefox, Thunderbird | **EXACT** — byte for byte (`probe-gui.sh`) |
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

## Electron and Gecko apps — `probe-gui.sh`

```bash
docker build -f scripts/appprobe/Dockerfile.gui -t yazses-appprobe-gui scripts/appprobe
P="-v $PWD/scripts/appprobe:/work"

# Firefox — a local page with a <textarea>
docker run --rm --shm-size=2g $P yazses-appprobe-gui bash /work/probe-gui.sh \
    firefox 50 50 /opt/firefox/firefox --no-remote \
    --profile /tmp/probe-firefox file:///work/page.html

# Thunderbird — a compose window, no account needed
docker run --rm --shm-size=2g $P yazses-appprobe-gui bash /work/probe-gui.sh \
    thunderbird 50 50 /opt/thunderbird/thunderbird \
    --profile /tmp/probe-thunderbird -compose

# VS Code — click at 35% width, so the text lands in the editor, not the Chat panel
docker run --rm --shm-size=2g $P yazses-appprobe-gui bash -c \
    ': > /work/scratch.txt; bash /work/probe-gui.sh vscode 50 35 code --no-sandbox
      --disable-gpu --disable-workspace-trust --password-store=basic
      --user-data-dir=/tmp/probe-vscode /work/scratch.txt'
```

```
RESULT|firefox|EXACT|kubectl get pods --namespace prod
RESULT|thunderbird|EXACT|kubectl get pods --namespace prod
RESULT|vscode|EXACT|kubectl get pods --namespace prod
```

Seed the VS Code scratch file with `:`, not `echo` — `echo` writes a newline, and
`ctrl+a` then selects it, so a perfectly good run reports `PARTIAL`.

Three things differ from a terminal, and each one previously produced a **wrong
conclusion that was published in this file**:

- **Startup is slow.** 40–50 seconds cold. `probe.sh` waits 7 — and an app that
  has not drawn yet is indistinguishable from one that ignores XTEST.
- **A first-run modal swallows every keystroke, silently.** VS Code opens on
  *"Sign in to use GitHub Copilot"*. This is the whole of the former
  *"Electron never receives a keystroke"* entry. **Electron receives keystrokes
  fine.** `probe-gui.sh` sends Escape twice before typing, and saves a screenshot
  so the next person can see a dialog rather than infer a toolkit limitation.
- **`apt install firefox` on Ubuntu 24.04 is a snap stub** — a script that prints
  `snap install firefox` and exits. With no snapd in a container the browser
  never starts, which is why Gecko was recorded as *"no window at all"*.
  `Dockerfile.gui` takes the tarball from Mozilla instead, and both browsers
  come up.

The general lesson, which is worth more than the table: **a negative result from
a harness is a claim about the harness until you have looked at the screen.**

## Known limits — where the boundary actually is

| Toolkit | Result |
|---|---|
| X11/GTK/Qt native — terminals, Vim, Emacs, Sublime | works, byte for byte |
| Electron — VS Code | works, byte for byte, once the first-run modal is dismissed |
| Gecko — Firefox, Thunderbird | works, byte for byte, with the Mozilla build |
| **GTK with a session bus** — GNOME Terminal | no window, even with `dbus-launch` and `gnome-terminal-server` started by hand |
| **Java/Swing** — JetBrains | starts, but stops at a licence agreement. Clicking through a EULA automatically is not something this script should do. |
| **AppImage/`.deb`-only apps** — Obsidian, Logseq, Zed, Slack, Discord | not in any apt repository, so the image cannot install them unattended. Adding one to `Dockerfile.gui` is a good contribution. |

Two remaining traps:

- **The first few characters can be lost** in a GUI app if typing starts before a
  text field has the caret. Use a sentinel prefix to tell that apart from the app
  mangling your input — that is how the LibreOffice result above was confirmed to
  be AutoCorrect and not a timing artefact.
- **Click into the editing area, not just the window.** VS Code's Chat panel on
  the right is also a text target, so a centre click can produce a clean EXACT
  that proves nothing about the editor. `CLICK_PCT` exists for this.
