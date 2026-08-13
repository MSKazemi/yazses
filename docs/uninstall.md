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

These are yours and are never deleted automatically.

```sh
rm -rf ~/.config/yazses          # settings, vocabulary, hotkey
rm -rf ~/.local/share/yazses     # logs, PID, meetings, learning corpus
```

On **macOS** those are `~/Library/Application Support/yazses/`; on **Windows**,
`%APPDATA%\yazses\`.

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
ls ~/.config/yazses ~/.local/share/yazses 2>/dev/null || echo "data: removed"
```

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
