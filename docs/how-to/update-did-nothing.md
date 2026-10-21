---
title: The update said it worked, but the version did not change
description: YazSes reported 'Update installed', you restarted, and it came back on the old version. Why a package manager exits 0 without upgrading anything, and the reinstall command that gets you out — per install method.
---

# The update said it worked, but the version did not change

You ran `yazses update` (or clicked **Check for updates…** in the tray, or **Install
update…** in the Settings window), it said the update was installed, you restarted the
daemon — and it came back on exactly the version you had. Possibly more than once.

Nothing is corrupted, and nothing needs uninstalling. **The upgrade command ran, did
nothing, and reported success.** This page is the way out.

!!! info "Why this page exists separately from the fix"

    A build that carries the check tells you this itself. But if you are reading
    this because your copy *didn't*, then your copy is the one without the check —
    which is exactly why the correction cannot be delivered through the updater. Every
    command below is one you run by hand.

## First, confirm it

The update surfaces report what they *ran*. This reports what is actually installed:

```bash
yazses --version
```

Run it in a **new terminal**. A process that has already started keeps running the
code it loaded, so asking a running YazSes about its own version can answer with the
one it started with rather than the one on disk.

If the number is the version you expected, the upgrade did work and only the running
daemon is stale — `yazses restart` is the whole fix. If it is the old number, continue.

## What actually happened

An exit code of `0` means *the command completed*, not *the upgrade happened*. Several
package managers exit 0 while deliberately changing nothing:

- **`uv tool upgrade` prints "Nothing to upgrade"** when the tool was installed with an
  exact version pin — `uv tool install yazses==2.19.0`. It is behaving correctly: you
  asked for that exact version, so that is what it keeps. This is the case this page
  was first written for; it was reported from a real install.
- **`pip install --upgrade` is a no-op against a pin or a constraint file**, for the
  same reason.
- **A held snap refuses to refresh** and exits 0.

In each case the package manager usually prints the reason — and until the check
existed, YazSes printed a success message straight over the top of it.

## Get out of it — by install method

Not sure which one you have? `yazses update --check` names the install method it
detected.

=== "uv"

    Reinstall unpinned. **Keep the extras** — a bare `yazses@latest` installs base
    dependencies only, which takes PySide6 with it and silently removes the Qt tray
    and the overlay:

    ```bash
    uv tool install 'yazses[desktop]@latest'
    ```

=== "pip"

    Force the reinstall so a pin or constraint cannot quietly win:

    ```bash
    pip install --upgrade --force-reinstall 'yazses[desktop]'
    ```

=== "snap"

    Release the hold first, then refresh:

    ```bash
    sudo snap refresh --unhold yazses
    sudo snap refresh yazses
    ```

=== "Windows"

    Since the one-click update ([ADR-027](https://github.com/MSKazemi/yazses/blob/main/design/adr/adr-027-one-click-windows-update.md)),
    tray → *Check for updates…* or `yazses update --yes` downloads the installer,
    verifies it and installs it for you. The notification on the next start says
    whether the version really moved. If it did not, it gives the reason (a declined
    administrator prompt, a cancelled install, an installer exit code) and the log
    path, `%TEMP%\yazses-update\update.log`.

    The way out that always works is still a download. Get the current
    `YazSes-<version>-windows-<arch>.exe` from the
    [releases page](https://github.com/MSKazemi/yazses/releases/latest) and run it. It
    upgrades in place and keeps your settings and models.

    If you installed through **Chocolatey, winget or Scoop**, there is a second cause
    worth knowing: those manifests are published *after* a release rather than with it,
    so for a while after a new version ships they still point at the previous one.
    `choco upgrade` then correctly reports nothing to do. That is the channel lagging,
    not your install — retrying will not change it, and the direct installer above gets
    you the current release now. Otherwise:

    ```powershell
    winget upgrade --id MSKazemi.YazSes -e
    choco upgrade yazses -y
    scoop update yazses
    ```

=== "macOS"

    Like the Windows installer, there is no command that upgrades the `.app` — the
    upgrade **is** a download. Get the current
    `YazSes-<version>-macos-<arch>.dmg` from the
    [releases page](https://github.com/MSKazemi/yazses/releases/latest), open it, and
    drag YazSes to Applications, replacing the copy that is there. Your settings,
    models and vocabulary live outside the bundle and are untouched.

    If you installed with **Homebrew**:

    ```bash
    brew upgrade --cask yazses
    ```

    The tap publishes after a release rather than with it, so `brew` reporting
    nothing to do shortly after a new version ships is the tap lagging, not your
    install — the `.dmg` above gets you the current release now.

=== "pipx / something else"

    Reinstall the way you first installed it, then confirm with `yazses --version` in a
    new terminal. If the number still does not move, that is worth
    [an issue](https://github.com/MSKazemi/yazses/issues/new/choose) — include the
    output of `yazses update --check`, which names the install method and the source it
    checked.

Then restart the daemon so the new version is what is running:

```bash
yazses restart
```

And confirm, in a new terminal, that the number actually moved:

```bash
yazses --version
```

## The update finished, but the camera features stopped working

If YazSes says *"The upgrade to YazSes X finished, but OpenCV (cv2), which the camera
features use, does not load any more"*, the version did move. What broke is OpenCV.

Up to 2.43.2 the camera features (gaze, face gestures, head pointer, hand gestures,
hands-free) installed two OpenCV builds, `opencv-python` and `opencv-contrib-python`.
They share the same `cv2/` folder. Later releases need only contrib, so an upgrade
removes `opencv-python`, and removing it deletes the files the two builds shared.
`import cv2` still succeeds afterwards, but `cv2.VideoCapture` is missing.

`yazses update`, the tray and the Settings window prevent this on a `uv tool` install:
when both builds are present, they add `--reinstall-package opencv-contrib-python` to the
upgrade command they show and run. After every `uv`, `pipx` or `pip` upgrade they also
check that `cv2` still works. If it does not, they print the exact repair for your
install.

Other routes reach the same broken state without going through that check: an upgrade
run by an older YazSes, `uv sync` in a source checkout, or `pip uninstall opencv-python`.
For those, YazSes checks again whenever it starts and whenever you run `yazses doctor`:

- **At start**, each camera feature that is switched on and has a half-deleted `cv2` is
  reported as not ready, the same way as a feature whose libraries are missing. The
  notification says *"OpenCV (cv2) is half-deleted"* and gives the repair command. It has
  no **Install now** button, because installing a package that is already installed does
  not repair it.
- **`yazses doctor`** shows an **OpenCV** row whenever an OpenCV build is installed:
  `OK` when `cv2` is whole, and `FAIL` with the repair command when it is not.

The check does not import OpenCV. It looks for OpenCV's native module inside the `cv2/`
folder, and it reads the package list only when that module is missing. So it adds
almost nothing to start-up, and it does not run at all unless a camera feature is
switched on (doctor checks whenever an OpenCV build is installed).

The repair has this shape, pinned to the version that is installed now:

=== "uv"

    ```bash
    uv pip install --python <your YazSes environment's python> --reinstall --no-deps opencv-contrib-python==<version>
    ```

=== "pipx"

    ```bash
    pipx runpip yazses install --force-reinstall --no-deps opencv-contrib-python==<version>
    ```

=== "pip"

    ```bash
    <your YazSes environment's python> -m pip install --force-reinstall --no-deps opencv-contrib-python==<version>
    ```

Copy the command YazSes printed rather than these templates, because it already has the
right interpreter path and version. Then restart the daemon (`yazses restart`).

In a virtual environment that has no pip (uv does not install pip into the environments
it creates, including a source checkout's `.venv`), YazSes prints the `uv` form instead,
because `python -m pip` would fail there.

The `uv` repair was run on Linux against an environment broken this way, and it worked.
The start-up and doctor check was also run there: it reported the broken environment as
half-deleted and the whole one as healthy, and after the repair it reported the repaired
one as healthy. The `pipx` and `pip` forms were not run, and Windows and macOS were not
tested.

## Your settings, models and vocabulary are not affected

None of the commands above touch your data. Configuration lives in
`~/.config/yazses/` (`%LOCALAPPDATA%\yazses\` on Windows), models and the learning corpus
in `~/.local/share/yazses/` — all outside the installed package. A reinstall replaces
code only.

## See also

- [Installing on Linux](../install-linux.md) — the install methods and what each gives you.
- [Installing on Windows](../windows-install.md) — the four Windows channels.
- [The tray icon does not appear](tray-icon-missing.md) — if the tray went missing after a reinstall, the dropped-extras case above is the usual cause.
