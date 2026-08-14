"""Every tray offers the same entries, on every OS (#63).

Linux had "Settings…"; macOS and Windows did not, so the same menu meant different
things depending on where you ran it. Clicking cannot be tested without the
target OS — that part needs a Mac or Windows user — but *presence and wiring*
can, and those are what silently drifted.

The same guard now covers About / Help / Check for updates, which arrived with the
same failure mode already visible: Windows shipped a ``Help`` item wired to nothing.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

from yazses.tray import menu as menu_mod
from yazses.tray.menu import SETTINGS_LABEL

TRAYS = {
    "linux": Path("src/yazses/platform/linux/tray.py"),
    "macos": Path("src/yazses/platform/macos/tray.py"),
    "windows": Path("src/yazses/platform/windows/tray.py"),
}
ROOT = Path(__file__).resolve().parent.parent

# Every user-visible label that must mean the same thing on all three OSes.
SHARED_LABELS = [
    menu_mod.SETTINGS_LABEL,
    menu_mod.ABOUT_LABEL,
    menu_mod.HELP_LABEL,
    menu_mod.DOCS_LABEL,
    menu_mod.TROUBLESHOOTING_LABEL,
    menu_mod.REPORT_BUG_LABEL,
    menu_mod.UPDATE_LABEL,
]

# entry -> the names a tray may use to render it. The Help sub-links are driven by
# ``about.help_links()`` on Linux and Windows and by the constants on macOS; either
# way the labels and URLs come from the one shared source.
SHARED_ENTRIES = {
    "Settings…": ("SETTINGS_LABEL", "settings_label"),
    "About": ("ABOUT_LABEL",),
    "Help": ("HELP_LABEL",),
    "Help links": ("help_links", "DOCS_LABEL"),
    "Check for updates…": ("UPDATE_LABEL",),
}

# entry -> the names that prove a click actually does something.
ENTRY_HANDLERS = {
    "Settings…": ("launch_settings", "_launch_settings", "_on_settings"),
    "About": ("about_html", "about_lines", "_on_about", "_about_clicked"),
    "Help links": ("open_url", "open_link", "_open", "_link_clicked", "_on_open_url"),
    "Check for updates…": (
        "check_and_describe", "check_updates", "_on_check_updates", "_update_clicked",
    ),
}


@pytest.mark.parametrize("entry", sorted(SHARED_ENTRIES))
@pytest.mark.parametrize("os_name", sorted(TRAYS))
def test_every_tray_offers_the_shared_entries(os_name, entry):
    """The parity gap this closes: only Linux had them.

    Linux reads "Settings…" off the shared ``TrayModel``; the rumps and pystray
    menus are built before any model arrives, so they import the constant. Both
    resolve to the same string — what matters is that neither invents its own.
    """
    source = (ROOT / TRAYS[os_name]).read_text(encoding="utf-8")
    assert any(marker in source for marker in SHARED_ENTRIES[entry]), (
        f"{os_name} tray has no {entry} entry"
    )


@pytest.mark.parametrize("os_name", sorted(TRAYS))
def test_every_tray_module_actually_imports(os_name):
    """The toolkits are lazy, so a bad top-level import is invisible until the
    tray runs — on the one OS that cannot run it in CI. Import it here instead.
    """
    importlib.import_module(f"yazses.platform.{os_name}.tray")


def test_the_macos_menu_handlers_are_not_crossed():
    """Each rumps label *path* routes to exactly one handler.

    ``@rumps.clicked`` binds by label, so stacking a second one on the wrong
    function silently re-points an existing menu entry — "Pause hotkey" opening
    Settings, with nothing to see in a diff-free read of the file. Submenu items
    bind on the full path (``clicked(HELP_LABEL, DOCS_LABEL)``), so the whole
    argument tuple is the identity — comparing only the first argument would read
    three distinct Help sub-entries as one label bound three times.
    """
    module = ast.parse((ROOT / TRAYS["macos"]).read_text(encoding="utf-8"))
    paths = [
        tuple(ast.unparse(a) for a in node.args)
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "clicked"
        and node.args
    ]
    assert len(paths) == len(set(paths)), f"a label path is bound twice: {paths}"


@pytest.mark.parametrize("entry", sorted(ENTRY_HANDLERS))
@pytest.mark.parametrize("os_name", sorted(TRAYS))
def test_every_tray_actually_wires_the_entry_to_something(os_name, entry):
    """A label with no handler is a menu item that does nothing when clicked.

    Not hypothetical: the Windows tray shipped ``MenuItem("Help", None,
    enabled=False)`` — a Help entry that could not be clicked at all.
    """
    source = (ROOT / TRAYS[os_name]).read_text(encoding="utf-8")
    assert any(marker in source for marker in ENTRY_HANDLERS[entry]), (
        f"{os_name} renders {entry} but wires no handler"
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


def test_the_shared_labels_are_used_rather_than_three_copies():
    """One label each, so the menus cannot say three different things.

    Checked against the parsed source, not the text: prose in a comment that
    happens to quote the label is not a second copy of it.
    """
    assert SETTINGS_LABEL
    shared = set(SHARED_LABELS)
    for path in TRAYS.values():
        module = ast.parse((ROOT / path).read_text(encoding="utf-8"))
        literals = [
            node.value for node in ast.walk(module)
            if isinstance(node, ast.Constant) and node.value in shared
        ]
        assert not literals, f"{path} hardcodes {literals} instead of importing the constant"


def test_the_help_links_point_at_pages_that_exist():
    """A Help entry that 404s is worse than no Help entry.

    The docs site builds with ``use_directory_urls: false``, so every page is a
    ``.html`` file — a link written as a directory would break silently.
    """
    from yazses import branding
    from yazses.tray.about import help_links

    # Read as text: mkdocs.yml carries custom !ENV/!!python tags a safe loader rejects.
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "use_directory_urls: false" in mkdocs
    assert f"site_url: {branding.WEBSITE}" in mkdocs, "branding.WEBSITE is not the docs site"
    site = branding.WEBSITE

    for label, url in help_links():
        assert url.startswith(("https://github.com/MSKazemi/", site)), label
        if url.startswith(site):
            page = url[len(site):] or "index.html"
            assert page.endswith(".html"), f"{label} is not a built page URL: {url}"
            source = ROOT / "docs" / page.replace(".html", ".md")
            assert source.is_file(), f"{label} links to {url}, but {source} does not exist"
