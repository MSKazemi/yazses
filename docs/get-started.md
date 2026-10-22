---
title: Get started with YazSes — offline voice dictation in five minutes
description: "Install YazSes on Linux, macOS or Windows, grant the permissions it needs, and dictate your first sentence: hold a key, speak, release. Free, open source, and fully offline once the speech model is downloaded."
---

# Get started in five minutes

YazSes types what you say into whatever app has focus, and it does all of the speech
recognition on your own computer. This page takes you from nothing to your first dictated
sentence. Then it shows the three things most people try next.

**What you need:** Linux, macOS 11 or later, or Windows 10/11, with 4 GB of RAM (8 GB is
comfortable) and a microphone. You do not need a GPU, an account or an API key. The
[platform support page](platform-support.md) lists every OS and CPU in detail.

## 1. Install

=== ":material-linux: Linux"

    ```sh
    bash <(curl -fsSL https://raw.githubusercontent.com/MSKazemi/yazses/main/install.sh)
    ```

    The universal installer works on Ubuntu, Debian, Fedora, Arch and their derivatives. It
    installs YazSes and runs `yazses setup`, which adds the audio, hotkey and text-injection
    helpers for your session (X11 or Wayland). It finishes by running `yazses doctor`.

    Prefer a package manager? The [Linux guide](install-linux.md) covers APT, Snap and
    pipx.

=== ":material-apple: macOS"

    On Apple Silicon:

    ```sh
    brew tap MSKazemi/yazses
    brew trust MSKazemi/yazses
    brew install --cask yazses
    ```

    On an Intel Mac, download the x86_64 `.dmg` from the
    [latest release](https://github.com/MSKazemi/yazses/releases/latest). The
    [macOS guide](macos-install.md) explains both routes and the first-launch Gatekeeper
    prompt.

=== ":material-microsoft-windows: Windows"

    ```powershell
    winget install MSKazemi.YazSes
    ```

    winget can trail the newest release by a few weeks. To be sure of the newest one,
    download the installer from the
    [latest release](https://github.com/MSKazemi/yazses/releases/latest), or use Scoop or
    Chocolatey (`choco install yazses`), which track every release. The build is not
    code-signed yet, so SmartScreen warns once. Choose **More info → Run anyway**. The
    [Windows guide](windows-install.md) covers each route and updating.

=== ":material-language-python: Any OS (pipx)"

    ```sh
    pipx install yazses
    ```

    This needs Python 3.11 or newer. On Linux, follow it with `yazses setup`, which installs
    the system helpers that a Python package cannot install itself.

## 2. Allow and check

=== ":material-linux: Linux"

    ```sh
    yazses doctor
    ```

    Every row should read `[OK]`, and a row that does not names its fix. If doctor reports
    that you were added to the `input` group, **log out and back in once**. Group changes
    apply only to new logins.

    Then tune the voice gate to your microphone and room:

    ```sh
    yazses mic-level --set
    ```

=== ":material-apple: macOS"

    Open YazSes from Applications. The app is not notarised yet, so the first launch is
    blocked: on macOS 15 and later, approve it with **Open Anyway** in **System Settings →
    Privacy & Security**; on macOS 14 and earlier, right-click the app and choose **Open**.

    macOS gates the three things a dictation tool needs
    behind three separate switches. All three are in **System Settings → Privacy &
    Security**:

    1. **Accessibility**, so YazSes can type into other apps.
    2. **Input Monitoring**, so it can see the hotkey. This is the one people miss. With
       only Accessibility on, the key does nothing.
    3. **Microphone**, so it can hear you.

    Quit and relaunch YazSes after switching them on. See
    [why there are three switches](macos-install.md#grant-input-monitoring-access--the-second-switch).

=== ":material-microsoft-windows: Windows"

    YazSes starts in the system tray, next to the clock. If Windows asks whether YazSes may
    use the microphone, allow it. The tray icon's colour shows its state at a glance: see
    [what the colours mean](tray-and-overlay.md).

=== ":material-language-python: Any OS (pipx)"

    ```sh
    yazses doctor
    ```

    It checks the microphone, the hotkey, the text-injection backend and permissions, and
    names the fix for anything that is missing.

## 3. Dictate

On macOS and Windows the app you opened is already running, so skip to the hotkey. On
Linux, or after a pipx install, start the daemon:

```sh
yazses start
```

Then **hold the hotkey, speak, and release**:

| OS | Default hotkey |
|---|---|
| Linux | ++right-alt++ |
| macOS | ++right-option++ |
| Windows | ++right-ctrl++ |

The text appears in the focused app one to two seconds after you let go (a median of 1.6 s on a laptop CPU with the default model). The hotkey is a
modifier you rarely use, so it does not interfere with normal typing. You can also
[choose a different key](how-to/change-hotkey.md).

!!! tip "The first dictation downloads the speech model"
    The first time YazSes transcribes, it downloads the Whisper model once. After that,
    dictation never uses the network. To set up a machine that is never online, see
    [running fully air-gapped](how-to/air-gapped.md).

## What to try next

<div class="grid cards" markdown>

- :material-console: **[Voice commands](command-index.md)**: say *"undo that"*,
  *"save file"* or *"go to line 42"* and YazSes sends the keys instead of typing the words.
- :material-file-music: **[Transcribe a recording](tutorials/transcribe-recordings.md)**:
  `yazses transcribe meeting.m4a` produces text or subtitles offline, with optional
  speaker labels.
- :material-book-alphabet: **[Teach it your words](how-to/personal-vocabulary.md)**:
  names, jargon and identifiers it keeps mishearing.
- :material-speedometer: **[Pick a model](models.md)**: trade a little speed for
  accuracy, or the reverse on a low-RAM machine.
- :material-cog: **[The Settings window](settings-gui.md)**: every feature is a checkbox,
  so you do not need to edit a config file.
- :material-lifebuoy: **[Troubleshooting](troubleshooting.md)**: start with
  `yazses doctor`, then find your symptom.

</div>

## If something does not work

Run `yazses doctor` first. It covers most first-run problems, and every check that fails
names its fix. The common ones:

- **Nothing happens when I hold the key.** On Linux, log out and back in after the
  installer adds you to the `input` group. On macOS, turn on **Input Monitoring**, then
  relaunch.
- **It types into the wrong window, or nowhere.** See
  [dictation types into the wrong window](how-to/wrong-window.md).
- **"Silent audio — discarding".** The voice gate is set above your voice. Run
  `yazses mic-level --set` again; see [the guide](how-to/silent-audio-discarding.md).

Still stuck? [Open an issue](https://github.com/MSKazemi/yazses/issues/new/choose) and
paste what `yazses doctor` printed. Read it first: it lists device names and file paths.
