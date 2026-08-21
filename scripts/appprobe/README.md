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
| GNOME Terminal | **EXACT** — byte for byte (needs a session bus, see below) |
| VS Code, Firefox, Thunderbird, Obsidian, Zed | **EXACT** — byte for byte (`probe-gui.sh`) |
| Logseq | **EXACT** — byte for byte, including `/` and `[[` (`probe-gui.sh`, AppImage) |
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

Obsidian needs a vault to exist, or it opens on its vault picker and there is
nothing to type into; Zed stacks two modals that Escape cannot answer, so its
`PROBE_PRE_KEYS` starts with Return:

```bash
docker run --rm --shm-size=2g $P yazses-appprobe-gui bash -c '
    mkdir -p /tmp/vault /root/.config/obsidian
    echo "{\"vaults\":{\"0123456789abcdef\":{\"path\":\"/tmp/vault\",\"ts\":1700000000000,\"open\":true}}}" \
        > /root/.config/obsidian/obsidian.json
    bash /work/probe-gui.sh obsidian 45 60 obsidian --no-sandbox --disable-gpu'

docker run --rm --shm-size=2g -e PROBE_PRE_KEYS="Return Escape" $P yazses-appprobe-gui bash -c '
    mkdir -p /tmp/proj; : > /tmp/proj/a.txt
    bash /work/probe-gui.sh zed 55 50 /opt/zed.app/bin/zed /tmp/proj/a.txt'
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

## AppImage apps — Logseq

An AppImage is usually where this harness is said to stop: there is no apt
repository to install from, and mounting one needs FUSE, which a container does
not have. Neither is actually a blocker — `--appimage-extract` unpacks the
squashfs with no FUSE at all, and `Dockerfile.gui` runs the extracted `AppRun`.
The same recipe should fit any other AppImage-only app.

```bash
docker run --rm --shm-size=2g -e PROBE_CLICK_Y_PCT=30 $P yazses-appprobe-gui \
    bash /work/probe-gui.sh logseq 60 20 /opt/logseq/AppRun --no-sandbox --disable-gpu
```

```
RESULT|logseq|EXACT|kubectl get pods --namespace prod
```

Logseq 2.0.1 opens straight onto today's journal — no first-run modal, unlike
VS Code — but it is an **outliner**, and that changes where you have to click:

- **`PROBE_CLICK_Y_PCT` exists because of this app.** Clicking the empty page
  *below* the last bullet focuses nothing, so the default centre click typed
  into a window that was fully drawn and perfectly responsive, and the probe
  reported `NOTHING`. Two runs differing only in the vertical click position
  gave `EXACT` at 30% and `NOTHING` at 50%. The horizontal one is an argument
  because a side panel is the usual wrong target; this one is an env var
  because only an outliner needs it.
- **`PROBE_TEXT` overrides the typed string** for a second, app-specific run.
  The default is what every row in the table above was measured with and should
  stay that way, but a notes app rewrites `/` and `[[` as you type and the
  default string contains neither:

  ```bash
  docker run --rm --shm-size=2g -e PROBE_CLICK_Y_PCT=30 \
      -e PROBE_TEXT='see /etc/hosts and [[my note]] ok' $P yazses-appprobe-gui \
      bash /work/probe-gui.sh logseq-markup 60 20 /opt/logseq/AppRun --no-sandbox --disable-gpu
  ```

  Also `EXACT`: neither the slash command menu nor the page-reference popup ate
  the rest of the line, and neither was left on screen.

## GNOME Terminal

It is a thin client for `gnome-terminal-server`, which needs a session D-Bus
**and refuses to start under a non-UTF-8 locale** — the base image now sets
`LANG=C.UTF-8` for exactly that reason. Give it the bus as part of the launch
command, not as a wrapper around the probe:

```bash
docker run --rm -e PROBE_WAIT=25 -v "$PWD/scripts/appprobe:/work" yazses-appprobe \
    bash /work/probe.sh gnome-terminal "" "ctrl+d" \
    dbus-run-session -- gnome-terminal --wait -- bash -c 'cat > /work/out.txt'
```

`PROBE_WAIT` exists because the D-Bus activation puts this well past the
7-second default, and a slow start is indistinguishable from a dead one in the
output.

## Known limits — where the boundary actually is

| Toolkit | Result |
|---|---|
| X11/GTK/Qt native — terminals, Vim, Emacs, Sublime | works, byte for byte |
| Electron — VS Code | works, byte for byte, once the first-run modal is dismissed |
| Gecko — Firefox, Thunderbird | works, byte for byte, with the Mozilla build |
| GTK with a session bus — GNOME Terminal | works, byte for byte, under `dbus-run-session` in a UTF-8 locale |
| **Java/Swing** — JetBrains | starts, but stops at a licence agreement. Clicking through a EULA automatically is not something this script should do. |
| **Apps behind a login** — Slack, Discord | the message composer is the interesting part and it is behind an account. Only the login field is reachable, and a config asserting the untested half would be worse than no config. |
| AppImage-only apps — Logseq | **no longer a limit.** `--appimage-extract` needs no FUSE and no apt repository; see the Logseq section above. Another AppImage app is still a good contribution. |

Two remaining traps:

- **The first few characters can be lost** in a GUI app if typing starts before a
  text field has the caret. Use a sentinel prefix to tell that apart from the app
  mangling your input — that is how the LibreOffice result above was confirmed to
  be AutoCorrect and not a timing artefact.
- **Click into the editing area, not just the window.** VS Code's Chat panel on
  the right is also a text target, so a centre click can produce a clean EXACT
  that proves nothing about the editor. `CLICK_PCT` exists for this.
