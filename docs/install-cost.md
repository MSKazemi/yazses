---
title: What installing YazSes actually costs — disk, downloads and time
description: Honest, measured numbers for a YazSes install — how much disk it uses, what gets downloaded, how long it takes, and what it does to your system. Published before you install, not after.
---

# What installing it actually costs

Most projects tell you how to install and never what it costs. These are measured
numbers, not estimates, so you can decide before you start.

## Disk

| What | Size | Notes |
|---|---|---|
| YazSes + all Python dependencies | **1.1 GB** | measured on a `uv tool install` |
| ↳ of which **PySide6 (Qt)** | **648 MB** | the voice-activity overlay — see the note below |
| Speech model — `tiny.en` | 75 MB | fastest, least accurate |
| Speech model — `base.en` | **141 MB** | **the default** |
| Speech model — `small.en` | 464 MB | most accurate of the three |
| Speaker diarization models | ~15 MB | only if you use `--diarize` |
| Docker image (transcription only) | 833 MB | no Qt |

**A normal desktop install is therefore about 1.25 GB**: 1.1 GB of program plus the
141 MB default model. Only one model is downloaded — the one you configure.

!!! warning "Qt is 59% of the install, and on a headless machine you cannot use any of it"
    `PySide6` is a **base dependency**, not an optional extra, because two desktop
    features ship enabled by default: the voice-activity overlay and the system-tray
    icon. Every install therefore pays 648 MB for Qt — including installs that only ever
    run `yazses transcribe` on a server, in a container, in CI, or on any headless
    machine, where neither feature can appear.

    **Do not try to delete it from an existing install.** Both the overlay and the tray
    import it, so removing it breaks two features that are on by default, and a
    `uv tool` environment has no `pip` in it to remove it with anyway.

    If you want the small install today, use
    **[the Docker image](try-without-installing.md)**, which drops Qt and is 833 MB.
    Making it a proper optional extra is
    [tracked as an issue](https://github.com/MSKazemi/yazses/issues) — it is a breaking
    change for desktop users, so it needs a release boundary rather than a quiet edit.

## Downloads

Nothing is downloaded that you did not ask for, and **the speech model is the only large
download**. It happens once, on first use, from Hugging Face — after that YazSes never
needs the network again.

You can prove that rather than trust it:

```sh
docker run --rm --network none -v yazses-models:/models -v "$PWD:/data" yazses jfk.wav
```

That transcribes with networking switched off entirely. It works.

## Time

| Step | Time | Measured how |
|---|---|---|
| First transcription (incl. 141 MB model download) | **43 s** | 4-core CPU, `base.en` |
| Every transcription after | **2.3 s** for 11 s of audio | model cached |
| System provisioning (`yazses setup`) | under a minute | apt packages |
| The one-time log-out and back in | **you pick when** | required on Linux; see below |

Install time itself depends almost entirely on your network and on whether `evdev` has to
be compiled (it has no wheels, so it usually does — this needs a C compiler, which
`install.sh` installs for you if it is missing).

## What it changes on your system

On Linux, a full dictation install touches these and nothing else:

| Change | Why | Reversible |
|---|---|---|
| Installs `libportaudio2`, `xdotool`/`ydotool`/`wtype`, clipboard tools | capture audio, type text | yes — normal apt packages |
| Adds you to the **`input` group** | read the hold-to-talk key from the kernel | yes — `sudo gpasswd -d $USER input` |
| Enables **`ydotoold`** (Wayland only) | the only way to inject keystrokes on GNOME/KDE Wayland | yes — `systemctl --user disable --now ydotoold` |
| Writes config to `~/.config/yazses/` | your settings | yes — delete it |
| Writes data to `~/.local/share/yazses/` | logs, PID, learning corpus if enabled | yes — delete it |
| Optional systemd **user** unit | start at login, if you ask for it | yes — `yazses autostart disable` |

!!! note "The `input` group is the one real security consideration, and it is worth understanding"
    Membership lets any program you run read raw input events — which is how the
    hold-to-talk hotkey works at all, and it is the same mechanism every Linux hotkey
    daemon uses. It is a genuine privilege grant, so it is stated plainly here rather
    than buried. If you are not comfortable with it, `yazses transcribe` needs none of
    it, and neither does Docker.

## What it does *not* do

- **No account, no API key, no licence server, no sign-up.**
- **No telemetry.** Nothing is counted, phoned home, or reported — there is no analytics
  code in the project at all. Downloads on PyPI are the only number the project can see,
  and that is PyPI's counter, not ours.
- **No background network access** after the model is downloaded.
- **No autostart unless you run `yazses autostart enable`.**

## Getting it back off

[Uninstalling is one page](uninstall.md), and it removes everything listed above.

---

**Ready?** [Install on Linux](install-linux.md) · [macOS](macos-install.md) ·
[Windows](windows-install.md) — or
[try it without installing anything](try-without-installing.md) first.
