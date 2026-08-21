"""How the tray opens the settings window, on an install that has no `yazses`.

Reported from a live Windows install (2026-08-15, v2.21.0 era): clicking
**Settings…** in the tray produced a toast reading

    YazSes
    Could not open Settings — is `yazses` on PATH?

and nothing opened. Every tray backend — Linux, macOS and Windows — launched the
window with the literal argv ``["yazses", "settings"]``, which assumes a console
script on PATH. The PyInstaller bundle has no such thing: it ships `YazSesApp.exe`
and `yazses-cli.exe` side by side and puts neither on PATH, so the one build most
likely to be used by someone who has never seen a terminal was the one build where
the button could not work.

The codebase already knew the answer in another file: `settingsui/app.py::_run_restart`
runs `[sys.executable, "-m", "yazses.cli", …]` precisely so it does not depend on
PATH. This resolver is that knowledge, in one place, for the three backends that
were each getting it wrong separately.

Order matters and is asserted below:

1. **Frozen** → the bundle itself, with the `--settings` flag its `__main__.py`
   dispatches on. `sys.executable` is the app there, so `-m` is meaningless: passing
   `-m yazses.cli` to `YazSesApp.exe` falls through to the CLI, exits 2, and has no
   console to say so. (This first read "the sibling `yazses-cli`", which was wrong
   twice over — the macOS .app ships no such file, and Settings is a window that
   should not drag a console along. See `tests/test_system_relaunch.py`.)
2. **`yazses` on PATH** → use it. Cheapest, and it is what a pipx/uv install gives.
3. **Otherwise** → `[sys.executable, "-m", "yazses.cli", "settings"]`, which works for
   any interpreter that can import the package, including a venv whose `bin/` was
   never added to PATH.
"""
from __future__ import annotations

import sys
from pathlib import Path

from yazses.tray.launch import settings_command


def test_a_frozen_bundle_asks_the_binary_for_the_window_not_dash_m() -> None:
    """`sys.executable` in a bundle is the app; `-m` would re-open the GUI.

    The expectation here **changed**, and the old one was wrong. It asserted the
    console `yazses-cli.exe`, but Settings is a window: `__main__.py` carries a
    `--settings` branch precisely so the Start-menu shortcut and this button open it
    without dragging a console window along for the life of the process. Routing a
    GUI through the console binary was contradicting the entry point's own docstring.
    """
    exe = Path("C:/Program Files/YazSes/YazSesApp.exe")
    cmd = settings_command(frozen=True, executable=exe, which=lambda _: None, windows=True)
    assert cmd == [str(exe), "--settings"]


def test_the_macos_app_has_no_sibling_to_point_at() -> None:
    """This test used to assert the bug, which is the worst place for one to live.

    It read "macOS ships the same layout without `.exe`". It does not:
    `packaging/macos/yazses.spec` builds exactly one `EXE(...)`, and the .app's
    `Contents/MacOS/` holds that single multi-call binary. So the resolver returned
    `.../MacOS/yazses-cli` — a path that exists nowhere — and the Settings… button
    was broken on every macOS bundle while a green test said otherwise.

    The sibling is now *tested for* rather than inferred from the platform, which is
    also what makes this correct if the macOS spec ever grows a second executable.

    Expectation built with `Path`, not a "/"-joined literal: on a Windows runner
    `str(Path(...))` renders backslashes, and an earlier version of this test failed
    there while the code under test was perfectly correct. The separator is the
    host's business, not this assertion's.
    """
    exe = Path("/Applications/YazSes.app/Contents/MacOS/YazSes")
    cmd = settings_command(frozen=True, executable=exe, which=lambda _: None, windows=False)
    assert cmd == [str(exe), "--settings"]


def test_a_normal_install_uses_the_console_script() -> None:
    """PATH is consulted when the interpreter has no `yazses` beside it.

    `exists` is injected false on purpose. Without that this reads the *real*
    filesystem, finds `.venv/bin/yazses` beside the running interpreter, and passes
    through the sibling branch instead — testing a different decision than its name
    claims, which is the quiet way a suite stops covering what you think it does.
    """
    cmd = settings_command(
        frozen=False, executable=Path(sys.executable), which=lambda n: f"/usr/bin/{n}",
        exists=lambda _p: False,
    )
    assert cmd == ["/usr/bin/yazses-settings"]


def test_without_a_console_script_it_falls_back_to_dash_m() -> None:
    """A venv whose bin/ is not on PATH still has an interpreter that can import us."""
    exe = Path("/venv/bin/python")
    cmd = settings_command(
        frozen=False, executable=exe, which=lambda _: None, exists=lambda _p: False
    )
    assert cmd == [str(exe), "-m", "yazses.settingsui.app"]


def test_path_is_not_consulted_when_frozen() -> None:
    """A *different* yazses on PATH must not win over the bundle's own CLI.

    A machine can easily have both — the installer's app and an old pip install.
    Launching the wrong one silently opens a settings window for another version.
    """
    exe = Path("C:/Program Files/YazSes/YazSesApp.exe")
    cmd = settings_command(
        frozen=True, executable=exe, which=lambda n: "C:/Python311/Scripts/yazses.exe",
        windows=True,
    )
    assert cmd[0] == str(exe)
    assert "Python311" not in cmd[0]


def test_the_subcommand_is_configurable() -> None:
    """`restart` needs the same resolution; only the verb differs."""
    exe = Path("/venv/bin/python")
    cmd = settings_command(
        "restart", frozen=False, executable=exe, which=lambda _: None,
        exists=lambda _p: False,
    )
    assert cmd == [str(exe), "-m", "yazses.cli", "restart"]


def test_the_real_call_returns_something_runnable() -> None:
    """No arguments: it must read the live process and still produce a command."""
    cmd = settings_command()
    assert cmd and all(isinstance(part, str) for part in cmd)
    assert cmd[-1].endswith(("yazses-settings", "yazses-settings.exe", "--settings"))
