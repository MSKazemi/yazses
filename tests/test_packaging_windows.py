"""Contract tests for the Windows bundle.

The Windows installer is assembled from three files that have to agree with each
other and with the Python entry point, and nothing in the normal test run
touches them — they are only exercised when a tag build runs on a Windows
runner. Every mismatch below has already shipped at least once:

- the bundle spawned the daemon with argv the bundle itself rejects,
- the CLI was built into a windowed binary that cannot print,
- the installer's autostart string diverged from the one the app writes.

These assert the contract on Linux CI, where the whole suite actually runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yazses.__main__ import default_mode
from yazses.platform.windows.lifecycle import resolve_tray_command

_PKG = Path(__file__).resolve().parents[1] / "packaging" / "windows"
_SPEC = _PKG / "yazses.spec"
_ISS = _PKG / "installer.iss"
_CMD = _PKG / "yazses.cmd"


# ---- Entry-point dispatch ----------------------------------------------


@pytest.mark.parametrize(
    "argv0",
    [
        r"C:\Program Files\YazSes\yazses-cli.exe",
        "yazses-cli.exe",
        "/usr/local/bin/yazses-cli",
    ],
)
def test_cli_binary_defaults_to_the_cli(argv0):
    assert default_mode(argv0) == "--cli"


@pytest.mark.parametrize(
    "argv0",
    [
        r"C:\Program Files\YazSes\YazSesApp.exe",
        "YazSesApp.exe",
        "YazSes.exe",  # the pre-2.18.3 name, still dispatched correctly
        "yazses.exe",  # case-insensitive filesystems fold this onto YazSes.exe
    ],
)
def test_windowed_binary_defaults_to_the_tray(argv0):
    assert default_mode(argv0) == "--tray"


def test_the_two_bundle_binaries_do_not_share_a_default_mode():
    """They differ only in case and suffix; if both defaulted the same way, one
    of the two shipped binaries would be unreachable."""
    assert default_mode("YazSes.exe") != default_mode("yazses-cli.exe")


# ---- Bundle contents ---------------------------------------------------


def test_spec_builds_both_a_windowed_and_a_console_binary():
    spec = _SPEC.read_text(encoding="utf-8")
    assert "console=False" in spec, "windowed tray/daemon binary is missing"
    assert "console=True" in spec, (
        "no console binary: a GUI-subsystem exe has no stdout, so every "
        "diagnostic command would print nothing"
    )
    assert 'name="yazses-cli"' in spec


def test_both_binaries_are_collected_into_the_bundle():
    spec = _SPEC.read_text(encoding="utf-8")
    collect = spec[spec.index("COLLECT(") :]
    assert "exe," in collect and "cli_exe," in collect, (
        "a binary was built but not COLLECTed, so it never reaches the installer"
    )


def test_shim_forwards_to_the_cli_binary_relative_to_itself():
    cmd = _CMD.read_text(encoding="utf-8")
    assert "yazses-cli.exe" in cmd
    assert "%~dp0" in cmd, "an absolute path would break for non-default install dirs"
    assert "%*" in cmd, "arguments must be forwarded"


def test_installer_ships_the_shim():
    iss = _ISS.read_text(encoding="utf-8")
    assert "yazses.cmd" in iss


# ---- The shim has to be *reachable* ------------------------------------
#
# Shipping the shim is not the same as it being used. Windows resolves a bare
# `yazses` through PATHEXT, whose default order puts .EXE ahead of .CMD, and
# NTFS is case-insensitive. A windowed binary named YazSes.exe therefore answers
# to `yazses` and the shim beside it is dead code — which is exactly what
# shipped through 2.18.2: `yazses doctor` in PowerShell printed nothing (a GUI
# binary has no stdout) and then crashed in a message box.

_PATHEXT_BEFORE_CMD = (".com", ".exe", ".bat")


def _windowed_exe_name() -> str:
    """The windowed binary's name, from the spec that builds it."""
    spec = _SPEC.read_text(encoding="utf-8")
    # the EXE(...) block carrying console=False
    windowed = spec[: spec.index("console=False")]
    return windowed[windowed.rindex('name="') + len('name="') :].split('"')[0]


def test_no_bundled_binary_shadows_the_yazses_shim():
    """No shipped executable may case-fold onto `yazses` with an extension that
    PATHEXT resolves before .CMD."""
    for name in (_windowed_exe_name(), "yazses-cli"):
        for ext in _PATHEXT_BEFORE_CMD:
            assert (name + ext).lower() != "yazses" + ext, (
                f"{name}{ext} answers to a bare `yazses` and shadows yazses.cmd; "
                "the CLI would reach a binary with no stdout"
            )


def test_installer_exe_define_matches_the_spec():
    """installer.iss shortcuts and the HKCU\\Run entry point at the windowed
    binary by name. If the spec renames it, every shortcut breaks silently."""
    iss = _ISS.read_text(encoding="utf-8")
    assert f'#define MyAppExeName "{_windowed_exe_name()}.exe"' in iss


def test_installer_deletes_the_pre_rename_windowed_binary():
    """Inno only overwrites files it ships. On an upgrade from <= 2.18.2 an
    orphaned YazSes.exe would stay in {app} and keep shadowing the shim, so the
    fix would not reach existing users."""
    iss = _ISS.read_text(encoding="utf-8")
    assert "[InstallDelete]" in iss
    assert r'Name: "{app}\YazSes.exe"' in iss


# ---- Installer / app agreement -----------------------------------------


def test_installer_autostart_matches_what_the_app_writes():
    """installer.iss and WindowsLifecycle manage the same HKCU\\Run value. If
    they disagree, toggling autostart in-app silently rewrites the installer's
    entry into something else."""
    iss = _ISS.read_text(encoding="utf-8")
    assert '""{app}\\{#MyAppExeName}"" --tray' in iss

    app_side = resolve_tray_command(r"C:\X\YazSes.exe", frozen=True, tray_script=None)
    assert app_side == r'"C:\X\YazSes.exe" --tray'


def test_installer_does_not_delete_the_whole_user_path_on_uninstall():
    """`uninsdeletevalue` on the Path value would wipe the user's entire PATH.
    Removal must go through the surgical RemovePath procedure instead."""
    iss = _ISS.read_text(encoding="utf-8")
    path_entry = next(
        line for line in iss.splitlines() if 'ValueName: "Path"' in line
    )
    assert "uninsdeletevalue" not in path_entry
    assert "procedure RemovePath" in iss
    assert "CurUninstallStepChanged" in iss


def test_installer_guards_against_duplicate_path_entries():
    iss = _ISS.read_text(encoding="utf-8")
    assert "NeedsAddPath" in iss
    assert "ChangesEnvironment=yes" in iss, (
        "without this, open shells never see the new PATH"
    )


def test_uninstall_stops_the_daemon_through_the_console_binary():
    iss = _ISS.read_text(encoding="utf-8")
    assert "yazses-cli.exe" in iss


# ---- Version metadata --------------------------------------------------


def test_spec_bundles_package_metadata():
    """`--version` crashed in the frozen bundle with PackageNotFoundError.

    PyInstaller ships no .dist-info unless told to, and
    importlib.metadata.version("yazses") backs --version, about, doctor, update
    and the diagnostic report. Found by the installer smoke test on its first run.
    """
    spec = _SPEC.read_text(encoding="utf-8")
    assert "copy_metadata" in spec
    assert 'copy_metadata("yazses")' in spec


def test_version_lookup_never_raises_without_metadata(monkeypatch):
    """--version is the first thing a bug report quotes; it must not be the
    command that crashes."""
    from importlib.metadata import PackageNotFoundError

    import yazses.cli as cli

    def _boom(_name):
        raise PackageNotFoundError("yazses")

    monkeypatch.setattr(cli, "_pkg_version", _boom)
    assert cli._installed_version() == "0.0.0+unknown"


# ---- Brand icon --------------------------------------------------------


def test_spec_fails_loudly_when_the_brand_icon_is_missing():
    """The silent fallback is why every release shipped a generic icon.

    `icon=str(ICON) if ICON.exists() else None` meant a missing assets/yazses.ico
    produced a perfectly successful build carrying PyInstaller's default artwork
    on the desktop shortcut, the Start menu, the taskbar and Add/Remove Programs.
    A build that cannot brand itself must fail, not shrug.
    """
    spec = _SPEC.read_text(encoding="utf-8")
    # Comments are stripped: the fix's own rationale quotes the old expression.
    code = "\n".join(
        ln for ln in spec.splitlines() if not ln.lstrip().startswith("#")
    )
    assert "if ICON.exists() else None" not in code
    assert "raise SystemExit" in code
    assert "scripts/gen-icons.py" in spec


def test_spec_points_at_an_icon_that_exists():
    spec = _SPEC.read_text(encoding="utf-8")
    assert 'ICON = REPO / "assets" / "yazses.ico"' in spec
    assert (_PKG.parents[1] / "assets" / "yazses.ico").is_file()
    assert spec.count("icon=str(ICON),") == 2  # windowed + console binaries


def test_installer_brands_the_setup_executable():
    """Without SetupIconFile the downloaded installer is a generic unsigned blob."""
    iss = _ISS.read_text(encoding="utf-8")
    assert "SetupIconFile=" in iss
    ref = next(ln for ln in iss.splitlines() if ln.startswith("SetupIconFile="))
    target = (_PKG / ref.split("=", 1)[1].strip().replace("\\", "/")).resolve()
    assert target.is_file(), f"SetupIconFile points at a missing file: {target}"


def test_build_script_preflights_the_icon():
    """Fail in two seconds, not after a ten-minute PyInstaller run."""
    ps1 = (_PKG.parents[1] / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")
    assert r"assets\yazses.ico" in ps1
    assert "gen-icons.py" in ps1


# ---- Add-on packs at uninstall (ADR-028, owner answer to question 4) ----------


def _strip_pascal_comments(text: str) -> str:
    """Drop ``{ ... }``, ``(* ... *)`` and ``//`` comments, but not braces inside a
    ``'...'`` string, where ``{app}`` is an Inno constant, not a comment."""
    out: list[str] = []
    i, n, in_str = 0, len(text), False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            in_str = ch != "'"
            i += 1
        elif ch == "'":
            out.append(ch)
            in_str = True
            i += 1
        elif ch == "{":
            i = text.find("}", i) + 1 or n
        elif text.startswith("(*", i):
            i = text.find("*)", i) + 2 if text.find("*)", i) >= 0 else n
        elif text.startswith("//", i):
            i = text.find("\n", i) if text.find("\n", i) >= 0 else n
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _iss_section(name: str) -> list[str]:
    """The non-comment, non-blank lines of one ``[Section]`` of installer.iss, with
    ``\\``-continued lines joined. ``[Code]`` is returned with its ``{ ... }`` and
    ``//`` comments removed, so a test reads only what Inno executes."""
    import re

    iss = _ISS.read_text(encoding="utf-8")
    parts = re.split(r"^\[([A-Za-z]+)\]\s*$", iss, flags=re.M)
    bodies = [parts[i + 1] for i in range(1, len(parts) - 1, 2) if parts[i] == name]
    text = "\n".join(bodies)
    if name == "Code":
        text = _strip_pascal_comments(text)
        return [ln.strip() for ln in text.splitlines() if ln.strip()]
    text = re.sub(r"\\\s*\n\s*", " ", text)
    return [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.strip().startswith(";")]


def test_iss_section_reads_real_sections():
    """Guard the guard: a parser that returns nothing would pass every test below."""
    assert any("yazses-cli.exe" in ln for ln in _iss_section("UninstallRun"))
    assert any("procedure RemovePath" in ln for ln in _iss_section("Code"))
    assert _iss_section("UninstallDelete"), "the packs entry must exist"


def test_uninstall_deletes_the_running_users_packs_folder():
    """%LOCALAPPDATA%\\yazses\\packs is Paths.data_dir / "packs" (platform/windows/paths.py
    + packs/layout.py). Only that folder: config, logs and models beside it are not
    the uninstaller's to delete."""
    from yazses.packs.layout import PackLayout

    assert PackLayout.under(Path("D")).root.name == "packs"
    lines = _iss_section("UninstallDelete")
    packs = [ln for ln in lines if r'"{localappdata}\yazses\packs"' in ln]
    assert len(packs) == 1, lines
    assert "Type: filesandordirs" in packs[0]
    assert not any(r'"{localappdata}\yazses"' in ln for ln in lines), (
        "never the whole data folder: it holds the user's config"
    )


def test_the_packs_delete_is_for_per_user_installs_only():
    """In an all-users (administrative) uninstall, {localappdata} is the elevated
    administrator's profile, not the profile of whoever installed the packs. Every
    [UninstallDelete] entry naming a per-user folder must be gated on the install mode."""
    user_constants = ("{localappdata}", "{userappdata}", "{userdocs}", "{userprofile}",
                      "{%USERPROFILE", "{%LOCALAPPDATA", "{%APPDATA")
    lines = [ln for ln in _iss_section("UninstallDelete")
             if any(c.lower() in ln.lower() for c in user_constants)]
    assert lines, "the guard needs at least the packs entry to check"
    for ln in lines:
        assert "Check: IsPerUserInstall" in ln, ln
    code = " ".join(_iss_section("Code"))
    assert "function IsPerUserInstall: Boolean;" in code
    body = code.split("function IsPerUserInstall: Boolean;", 1)[1].split("end;", 1)[0]
    assert "Result := not IsAdminInstallMode;" in body, body


def test_no_upgrade_path_deletes_packs():
    """An in-place upgrade (including ADR-027's one-click update) runs Setup, never the
    uninstaller, so [UninstallDelete] cannot fire then. What Setup itself runs —
    [InstallDelete], [Run] and [Code] — must never touch the packs folder, delete a
    tree, or start the uninstaller."""
    for section in ("InstallDelete", "Run", "Files", "Registry"):
        for ln in _iss_section(section):
            assert "packs" not in ln.lower(), (section, ln)
            assert "{localappdata}" not in ln.lower(), (section, ln)
    code = " ".join(_iss_section("Code")).lower()
    assert "expandconstant('{app}')" in code, "the parser must keep constants in strings"
    for forbidden in ("deltree", "deletefile", "removedir", "packs", "unins000",
                      "{uninstallexe}", "localappdata", "shellexec("):
        assert forbidden not in code, f"[Code] contains {forbidden!r}"
    # Starting a program is allowed for exactly one job -- closing the YazSes being
    # upgraded (PrepareToInstall) and bringing its tray back after a silent upgrade --
    # and for nothing else. What may be started is pinned to the three programs that
    # job needs, so the uninstaller or an arbitrary tool cannot slip in unnoticed.
    allowed = ("powershell.exe", "yazses-cli.exe", "{#myappexename}")
    started = re.findall(r"\bexec(?:asoriginaluser)?\(\s*([^,]+),", code)
    assert started, "the close-the-running-app step is gone from [Code]"
    for program in started:
        assert any(a in program for a in allowed), f"[Code] starts {program!r}"
