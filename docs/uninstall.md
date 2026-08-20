---
title: How to uninstall YazSes — remove it completely from Linux, macOS or Windows
description: Complete, honest uninstall instructions for YazSes, including the model cache, config, learning corpus, systemd unit and input-group membership. Published up front, so you know the exit before you take the entrance.
---

# Uninstalling

This page exists **before** you install, on purpose. Software that hides its exit is
software you should be suspicious of, and knowing you can leave cleanly is a reasonable
thing to want up front.

Nothing here needs YazSes to be working. If it is already broken or half-installed, the
manual steps below still remove everything.

## 1. Stop it

```sh
yazses stop                      # stop the daemon
yazses autostart disable         # stop it starting at login
```

If `yazses` no longer runs, that is fine — skip ahead. On Linux you can force it with
`systemctl --user disable --now yazses.service` and `pkill -f yazses-daemon`.

## 2. Remove the program

Use whichever line matches how you installed it. If you are not sure, run them all —
each one is harmless when the package is not there.

```sh
uv tool uninstall yazses         # the install.sh / uv path (most common)
pipx uninstall yazses            # the pipx path
pip uninstall yazses             # a plain pip install
sudo apt remove yazses           # the APT / .deb path
sudo snap remove yazses          # the Snap path
```

On **macOS**, run `brew uninstall --zap --cask yazses` if you installed from the
Homebrew tap, or drag `YazSes.app` to the Trash if you used the `.dmg`.
On **Windows**, use *Settings → Apps → Installed apps → YazSes → Uninstall*.

## 3. Remove your data

These are yours and are never deleted automatically. YazSes writes under **four**
directories on Linux, not one — the two obvious ones plus a model cache and a log
directory that follow the XDG layout and therefore sit somewhere else entirely.

```sh
rm -rf ~/.config/yazses          # settings, vocabulary, hotkey
rm -rf ~/.local/share/yazses     # meetings, learning corpus, voiceprints, models
rm -rf ~/.cache/yazses           # cached models — a GGUF here can be 2.2 GB
rm -rf ~/.local/state/yazses     # the diagnostic log (`yazses logs` reads this)
```

On **macOS**:

```sh
rm -rf ~/Library/Application\ Support/yazses   # settings + data (both live here)
rm -rf ~/Library/Caches/yazses                 # cached models
rm -rf ~/Library/Logs/yazses                   # the diagnostic log
```

On **Windows** everything is nested under one folder, so a single removal is enough —
and note it is **Local**AppData, not the roaming `%APPDATA%` that this page used to name:

```powershell
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\yazses"
```

!!! warning "The log is the one that can hold what you dictated"
    At the default `log_level = "INFO"` the diagnostic log records metadata only —
    timings and states, never your text. If you ever set `log_level = "DEBUG"` to chase
    a problem, that log also holds every transcript from then on, and it is not in either
    of the two directories people usually think to delete. See
    [the privacy statement](privacy-statement.md).

!!! warning "If you enabled the learning corpus, this is the step that erases it"
    The corpus holds encrypted recordings and transcripts of things you dictated. It is
    off by default, but if you turned it on, `~/.local/share/yazses/` is where it lives.
    `yazses corpus destroy` does the same thing with a confirmation prompt, if YazSes
    still runs.

## 4. Remove the speech models

The models are the big item — up to 464 MB each — and they live in the shared Hugging
Face cache, so they survive uninstalling the program.

```sh
rm -rf ~/.cache/huggingface/hub/models--Systran--faster-whisper-*
```

Add these too if you ever used speaker labelling or voiceprints:

```sh
rm -rf ~/.cache/huggingface/hub/models--speechbrain--spkrec-ecapa-voxceleb
```

!!! note
    That cache is shared with any other tool you have that uses Hugging Face models.
    The glob above is limited to the Whisper models YazSes downloads, so it will not
    take anything else with it.

## 5. Undo the system changes (Linux)

```sh
sudo gpasswd -d "$USER" input                    # leave the input group
systemctl --user disable --now ydotoold          # stop the Wayland injection daemon
rm -f ~/.config/systemd/user/yazses.service      # only if you skipped step 1
```

The `input` group change, like joining it, only takes effect at your next login.

The packages `yazses setup` installed — `libportaudio2`, `xdotool`, `ydotool`, `wtype`,
`xclip`, `wl-clipboard` — are ordinary system packages that other software may also use.
They are deliberately **not** removed for you. If you are sure nothing else needs them:

```sh
sudo apt remove libportaudio2 xdotool ydotool wtype xclip wl-clipboard
```

## 6. Check it is gone

```sh
command -v yazses || echo "yazses: removed"
ls -d ~/.config/yazses ~/.local/share/yazses ~/.cache/yazses ~/.local/state/yazses \
      ~/.config/systemd/user/yazses.service 2>/dev/null || echo "data: removed"
```

The check lists **every** path YazSes writes to, on purpose. It used to name two of
them, so it printed `data: removed` while the model cache and the log directory were
still there.

---

## Before you go — was it something we can fix?

If you are uninstalling because something did not work, that is a bug worth knowing
about, and it is far more useful to the project than a silent uninstall:

- **[Open an issue](https://github.com/MSKazemi/yazses/issues/new/choose)** — even a
  one-liner about what broke.
- **`yazses report`** builds a local diagnostic bundle you can paste in. It redacts paths
  and identifiers, never opens the learning corpus, and uploads nothing anywhere — you
  choose what to share.
- **[Troubleshooting](troubleshooting.md)** covers the common ones, especially
  *"the hotkey does nothing"* (almost always the `input`-group re-login) and
  *"Silent audio — discarding"* (the mic threshold, fixed by `yazses mic-level --set`).

No hard feelings either way — it is your machine.
