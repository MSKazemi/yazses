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
| **Electron** — VS Code | window opens with the right title, and **no keystroke ever lands**. Not a timing problem: a 90-second wait and a click into the editor produced an empty buffer and an empty clipboard. |
| **Gecko** — Firefox, Thunderbird | no window at all in a bare Xvfb |
| **GTK with a session bus** — GNOME Terminal | no window, even with `dbus-launch` and `gnome-terminal-server` started by hand |
| **Java/Swing** — JetBrains | starts, but stops at a licence agreement. Clicking through a EULA automatically is not something this script should do. |

So the probe covers native toolkits. Electron, Gecko and anything needing a real
desktop session are still best tested by a human on a real desktop — and making
the probe handle them would itself be a useful contribution.
- **The first few characters can be lost** in a GUI app if typing starts before a
  text field has the caret. Use a sentinel prefix to tell that apart from the app
  mangling your input — that is how the LibreOffice result above was confirmed to
  be AutoCorrect and not a timing artefact.
