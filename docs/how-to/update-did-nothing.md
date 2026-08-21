---
title: The update said it worked, but the version did not change
description: YazSes reported 'Update installed', you restarted, and it came back on the old version. Why a package manager exits 0 without upgrading anything, and the reinstall command that gets you out — per install method.
---

# The update said it worked, but the version did not change

You ran `yazses update` (or clicked **Check for updates…** in the tray), it said the
update was installed, you restarted the daemon — and it came back on exactly the
version you had. Possibly more than once.

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

    There is no command that upgrades the installer channel — the upgrade **is** a
    download. Get the current `YazSes-<version>-windows-<arch>.exe` from the
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

## Your settings, models and vocabulary are not affected

None of the commands above touch your data. Configuration lives in
`~/.config/yazses/` (`%APPDATA%\yazses\` on Windows), models and the learning corpus
in `~/.local/share/yazses/` — all outside the installed package. A reinstall replaces
code only.

## See also

- [Installing on Linux](../install-linux.md) — the install methods and what each gives you.
- [Installing on Windows](../windows-install.md) — the four Windows channels.
- [The tray icon does not appear](tray-icon-missing.md) — if the tray went missing after a reinstall, the dropped-extras case above is the usual cause.
