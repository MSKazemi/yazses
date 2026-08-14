---
title: The tray icon does not appear
description: Why the YazSes tray icon is missing on GNOME, KDE and other desktops — the AppIndicator requirement, how to run the tray by hand to see the real error, and what each desktop needs.
---

# The tray icon does not appear

Dictation works, but there is no "Y" in the top bar. Almost always this is the
desktop, not YazSes: **GNOME removed system tray support**, and what puts icons
back is an extension.

!!! info "Verified on"

    Ubuntu 24.04 · GNOME Shell 46.0 · X11 · YazSes 2.18.2. The GNOME section was
    confirmed on that machine; the other desktops are described from their own
    documentation and are marked where they were not tested.

## First: is it even running?

```bash
pgrep -af "yazses.tray"
```

Real output when it is running:

```
4528 /home/mohsen/.local/share/uv/tools/yazses/bin/python -m yazses.tray.app
```

Two different problems hide behind one symptom, and this tells them apart:

- **A process exists** → the tray is running and the desktop is not showing it.
  Go to *your desktop* below.
- **Nothing** → the tray is not starting. Go to *run it by hand*.

## Run it by hand to see the real error

The daemon launches the tray in the background, so its error message goes nowhere
you would look. Run it in a terminal instead:

```bash
yazses tray
```

This blocks and prints. The two failures worth knowing:

- `ModuleNotFoundError: No module named 'PySide6'` — the Linux tray is Qt.
  `uv sync` / `pipx install yazses` include it; a minimal install may not.
- It starts, prints nothing, and no icon appears → the process is fine and the
  desktop is not showing it. That is the next section.

## GNOME — needs an AppIndicator extension

GNOME Shell has had no built-in tray since 3.26. Icons come back through an
extension implementing the AppIndicator/StatusNotifierItem protocol.

**Ubuntu already ships one and enables it by default.** On the machine above:

```bash
gnome-extensions list | grep -i appindicator
```

```
ubuntu-appindicators@ubuntu.com
```

If that returns nothing, or the extension is disabled:

```bash
# Ubuntu / Debian
sudo apt install gnome-shell-extension-appindicator
gnome-extensions enable ubuntu-appindicators@ubuntu.com

# Fedora
sudo dnf install gnome-shell-extension-appindicator
```

On other distributions install
[AppIndicator and KStatusNotifierItem Support](https://extensions.gnome.org/extension/615/appindicator-support/)
from extensions.gnome.org.

**Then log out and back in.** Enabling a shell extension does not take effect in an
existing X11 session for an app that has already registered.

## KDE Plasma — works without anything extra

Plasma implements StatusNotifierItem natively. If the icon is missing there, check
that it has not been hidden: *right-click the system tray* → **Configure System
Tray** → **Entries**, and set YazSes to *Shown* rather than *Hidden*. Plasma hides
unknown icons by default in some versions, which looks identical to a crash.

*(Described from Plasma's documentation — not tested here.)*

## Xfce, MATE, Cinnamon, LXQt

These keep a real notification area and generally need nothing. If it is missing,
confirm the panel actually has a *Notification Area* / *Status Notifier* plugin
added — a customised panel may simply not have one.

*(Not tested here.)*

## Wayland

The tray works the same way on Wayland — it is the same Qt code and the same
desktop-side protocol. Note that **`yazses tray` is unrelated to the two features
that genuinely cannot work on Wayland** (voice window focus and gaze routing); see
the [capability matrix](../capability-matrix.md).

## It crashed and never came back

The daemon supervises the tray and relaunches it, bounded at five attempts, reading
liveness from the tray lock rather than a remembered PID — so a tray you started by
hand, or one that outlived a daemon restart, is still counted correctly. If it has
given up:

```bash
yazses restart
```

## Turning it off deliberately

If you do not want it:

```bash
yazses features disable tray
yazses restart
```

"Quit tray" from the menu closes only the icon and leaves dictation running — which
is a common way to end up here on purpose and forget.

## What this page does not cover

Only GNOME on X11 was actually exercised. If your desktop is not GNOME and this
page did not help, [say what happened](https://github.com/MSKazemi/yazses/issues) —
the sections above marked *not tested* are the ones most likely to be wrong.
