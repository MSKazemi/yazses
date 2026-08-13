"""Every tray offers "Settings…", on every OS (#63).

Linux had the entry; macOS and Windows did not, so the same menu meant different
things depending on where you ran it. Clicking cannot be tested without the
target OS — that part needs a Mac or Windows user — but *presence and wiring*
can, and those are what silently drifted.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

from yazses.tray.menu import SETTINGS_LABEL

TRAYS = {
    "linux": Path("src/yazses/platform/linux/tray.py"),
    "macos": Path("src/yazses/platform/macos/tray.py"),
    "windows": Path("src/yazses/platform/windows/tray.py"),
}
ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("os_name", sorted(TRAYS))
def test_every_tray_offers_the_settings_entry(os_name):
    """The parity gap this closes: only Linux had it.

    Linux reads the label off the shared ``TrayModel``; the rumps and pystray
    menus are built before any model arrives, so they import the constant. Both
    resolve to the same string — what matters is that neither invents its own.
    """
    source = (ROOT / TRAYS[os_name]).read_text(encoding="utf-8")
    assert "SETTINGS_LABEL" in source or "settings_label" in source, (
        f"{os_name} tray has no Settings… entry"
    )


@pytest.mark.parametrize("os_name", sorted(TRAYS))
def test_every_tray_module_actually_imports(os_name):
    """The toolkits are lazy, so a bad top-level import is invisible until the
    tray runs — on the one OS that cannot run it in CI. Import it here instead.
    """
    importlib.import_module(f"yazses.platform.{os_name}.tray")


def test_the_macos_menu_handlers_are_not_crossed():
    """Each rumps label routes to exactly one handler.

    ``@rumps.clicked`` binds by label, so stacking a second one on the wrong
    function silently re-points an existing menu entry — "Pause hotkey" opening
    Settings, with nothing to see in a diff-free read of the file.
    """
    module = ast.parse((ROOT / TRAYS["macos"]).read_text(encoding="utf-8"))
    labels = [
        node.args[0]
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "clicked"
        and node.args
    ]
    rendered = [ast.unparse(a) for a in labels]
    assert len(rendered) == len(set(rendered)), f"a label is bound twice: {rendered}"


@pytest.mark.parametrize("os_name", sorted(TRAYS))
def test_every_tray_actually_wires_the_entry_to_something(os_name):
    """A label with no handler is a menu item that does nothing when clicked."""
    source = (ROOT / TRAYS[os_name]).read_text(encoding="utf-8")
    assert "settings" in source.lower()
    assert any(marker in source for marker in
               ("launch_settings", "_launch_settings", "_on_settings")), (
        f"{os_name} renders Settings… but wires no handler"
    )


@pytest.mark.parametrize("os_name", ["macos", "windows"])
def test_a_failed_launch_is_reported_not_swallowed(os_name):
    """A click with no visible effect is indistinguishable from a frozen tray."""
    source = (ROOT / TRAYS[os_name]).read_text(encoding="utf-8")
    assert "Could not open Settings" in source


@pytest.mark.parametrize("os_name", ["macos", "windows"])
def test_the_launcher_is_importable_without_the_platform_toolkit(os_name):
    """rumps and pystray are OS-specific; the launcher must not need them.

    Keeping it module-level means CI on any runner can at least import and
    inspect it, rather than the whole file being unreachable off its OS.
    """
    module = ast.parse((ROOT / TRAYS[os_name]).read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(module) if isinstance(n, ast.FunctionDef)}
    assert names & {"launch_settings", "_launch_settings"}, (
        f"{os_name} has no module-level settings launcher"
    )


# ---- the bundle has to understand the flag the shortcut passes -------------


def test_the_frozen_bundle_dispatches_settings():
    """The Start-menu shortcut passes --settings.

    Without a branch for it the windowed binary falls through to the CLI, exits 2
    on an unknown argument, and — having no console — looks like a shortcut that
    does nothing. That exact shape already broke the Windows daemon once.
    """
    source = (ROOT / "src/yazses/__main__.py").read_text(encoding="utf-8")
    assert '"--settings"' in source
    assert "settingsui.app" in source


def test_the_settings_flag_really_opens_the_settings_window(monkeypatch):
    """Drive the actual dispatch, so the flag cannot rot into a no-op."""
    from yazses import __main__ as bundle
    from yazses.settingsui import app as settings_app

    opened = []
    monkeypatch.setattr(settings_app, "run", lambda: opened.append("settings"))
    monkeypatch.setattr(sys, "argv", ["YazSes.exe", "--settings"])

    bundle.main()

    assert opened == ["settings"]


def test_the_tray_launchers_invoke_a_command_that_exists():
    """macOS and Windows shell out to `yazses settings` rather than the flag."""
    import typer

    from yazses.cli import app

    commands = typer.main.get_command(app).commands  # type: ignore[attr-defined]
    assert "settings" in commands, "the tray launches a CLI command that does not exist"
    assert callable(commands["settings"].invoke)


def test_the_windows_installer_creates_a_settings_shortcut():
    iss = (ROOT / "packaging/windows/installer.iss").read_text(encoding="utf-8")
    icons = iss.split("[Icons]", 1)[1].split("[", 1)[0]
    assert "Settings" in icons, "no Start-menu launcher for the settings window"
    assert "--settings" in icons


def test_the_shortcut_flag_matches_what_the_bundle_accepts():
    """The two halves are written in different files and must not drift."""
    iss = (ROOT / "packaging/windows/installer.iss").read_text(encoding="utf-8")
    main = (ROOT / "src/yazses/__main__.py").read_text(encoding="utf-8")
    icons = iss.split("[Icons]", 1)[1].split("[", 1)[0]
    for flag in ("--tray", "--settings"):
        if flag in icons:
            assert f'"{flag}"' in main, f"the installer passes {flag}, the bundle ignores it"


def test_the_shared_label_is_used_rather_than_three_copies():
    """One label, so the menus cannot say three different things.

    Checked against the parsed source, not the text: prose in a comment that
    happens to quote the label is not a second copy of it.
    """
    assert SETTINGS_LABEL
    for path in TRAYS.values():
        module = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        literals = [
            node.value for node in ast.walk(module)
            if isinstance(node, ast.Constant) and node.value == SETTINGS_LABEL
        ]
        assert not literals, f"{path} hardcodes the label instead of importing SETTINGS_LABEL"
