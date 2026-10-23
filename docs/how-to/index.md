---
title: How-To Guides
description: Short, task-focused guides for getting the most out of YazSes.
---

# How-To Guides

Practical, copy-pasteable recipes for common YazSes tasks. Each guide is
self-contained — pick the one that matches what you want to do.

| Guide | What it covers |
|---|---|
| [Add words to your personal dictionary](personal-vocabulary.md) | Teach STT names, jargon, and acronyms it keeps mis-hearing. |
| [Create spoken macros and snippets](macros-and-snippets.md) | Say a trigger phrase to expand canned boilerplate or templates. |
| [Apply a house style to your dictation](house-style.md) | Keep terminology and spellings consistent from a rules file. |
| [Set a tone per application](app-profiles.md) | Casual in Slack, formal in email, verbatim in a terminal — chosen by the window you speak into. |
| [Jump to a symbol by voice](editor-jump.md) | Say "go to line 240" or "jump to function tokenize" and the editor moves there. |
| [Change the hold-to-talk key](change-hotkey.md) | Pick a hotkey (and a dedicated command key) that never clashes with typing. |
| [Dictate into a remote SSH host](remote-dictation.md) | Type with your voice into a shell or editor on another machine. |
| [Aim dictation with your gaze](gaze-look-to-pane.md) | Glance at a window and hold-to-talk — the text lands in the pane you looked at (X11). |
| [Set up hands-free input](hands-free-setup.md) | One preset that composes gaze, head pointer, face switch and chords; what it sets, what it needs, every way to stop it, and how it recovers. |
| [Stop hands-free input by voice](hands-free-voice-stop.md) | Say a short phrase and the pointer, chords and face switch pause, with no key and no pointer. |
| [Click anywhere by voice](voice-mouse-grid.md) | Say "mouse grid", cell numbers, then "click" — pointer control on any pixels (experimental; X11 or macOS). |
| [Transcribe recordings to text](../tutorials/transcribe-recordings.md) | Turn an existing audio/video file into text — offline, with speaker labels. |
| [Tune for speed and accuracy](performance-tuning.md) | Choose the STT model, set the VAD threshold, and manage CPU load. |
| [The update said it worked but the version did not change](update-did-nothing.md) | A package manager can exit 0 without upgrading anything — the reinstall command per install method. |
| [Stop a misheard command from running](command-safety.md) | Hold `rm -rf`, `mkfs`, `curl \| sh` until you say confirm — on in a fresh install. |
| [Over SSH and in Remote-SSH editors](ssh-and-remote.md) | Why dictation into an SSH session needs no setup, and when the remote agent is needed. |
| [Connect YazSes to an MCP client](connect-mcp-client.md) | Let an agent transcribe files on your machine, and optionally ask you a question out loud: the one-click bundle or the manual config. |
| [Install only what you need](install-only-what-you-need.md) | Read the DOWNLOAD column before you turn a capability on, and keep an install small. |
| [Choose a model on a low-RAM machine](low-ram-models.md) | Measured memory per Whisper model, and which features load a model of their own. |
| [Reduce CPU use and battery drain](cpu-and-battery.md) | What dictation costs on a laptop, and the settings that actually lower it. |
| [Run fully air-gapped](air-gapped.md) | Which files YazSes downloads, how to carry them to an offline machine, and how to check nothing phones home. |
| [Fix "Silent audio -- discarding"](silent-audio-discarding.md) | Set the voice-activity threshold with `yazses mic-level`, or find the muted microphone. |
| [Dictation types into the wrong window](wrong-window.md) | The causes, the no-text-target guard, and precise detection with AT-SPI on Linux. |
| [The tray icon does not appear](tray-icon-missing.md) | The AppIndicator requirement, the tray's own error log, and what each desktop needs. |
| [Dictation stopped after a distro upgrade](after-a-distro-upgrade.md) | A moved Python, a switch to Wayland, lost input-group access, or a stopped `ydotoold`. |

## See also

- [Configuration reference](../configuration.md) — every `config.toml` section and key.
- [Feature reference](../features.md) — every capability and how to turn it on.
- [CLI reference](../cli-reference.md) — every `yazses` command and flag.
