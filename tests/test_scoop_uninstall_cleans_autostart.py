"""`scoop uninstall yazses` removes the login entry that `yazses start` wrote.

Scoop unpacks the installer instead of running it, so the installer's own uninstall
step, which deletes the HKCU\\Run value, never runs. `yazses start` sets that value up
(cli._ensure_autostart), so after `scoop uninstall yazses` it pointed at a program
that no longer existed and stayed in Task Manager's Startup list. Found on Windows 11
by installing and uninstalling through the bucket.

The manifest's `pre_uninstall` deletes the value, but only when it points inside this
Scoop app's folder: an entry written by the `.exe` installer, or by anything else, is
not Scoop's to remove.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUCKET = ROOT / "bucket/yazses.json"


def _pre_uninstall() -> list[str]:
    lines = json.loads(BUCKET.read_text(encoding="utf-8")).get("pre_uninstall")
    assert lines, "bucket/yazses.json has no pre_uninstall: the login entry outlives the app"
    return lines


def test_pre_uninstall_removes_only_the_yazses_run_value_inside_this_app():
    script = "\n".join(_pre_uninstall())
    assert r"CurrentVersion\Run" in script
    assert "Remove-ItemProperty" in script and "'YazSes'" in script
    # Scoped to this Scoop app's folder; an unconditional delete would remove the
    # .exe installer's entry too.
    assert "Split-Path $dir" in script and ".Contains(" in script


def test_a_release_refresh_keeps_pre_uninstall():
    """render_scoop rewrites version, url and hash; it must not drop the rest."""
    spec = importlib.util.spec_from_file_location(
        "refresh_package_manifests", ROOT / "scripts/refresh-package-manifests.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve their module by name
    try:
        spec.loader.exec_module(mod)
        exe = mod.Asset(
            name="YazSes-9.9.9-windows-x64.exe",
            url="https://example.invalid/YazSes-9.9.9-windows-x64.exe",
            size=1,
            sha256="0" * 64,
        )
        rendered = json.loads(
            mod.render_scoop("9.9.9", exe, None, BUCKET.read_text(encoding="utf-8"))
        )
    finally:
        sys.modules.pop(spec.name, None)
    assert rendered["version"] == "9.9.9"
    assert rendered["pre_uninstall"] == _pre_uninstall()


# ---- the script itself, on a throwaway registry key (Windows only) ----------

_APPS = r"C:\Users\ada\scoop\apps\yazses"


def _run_pre_uninstall(entry: str | None) -> str | None:
    """Run the manifest's lines with Scoop's $dir set, against a temporary key
    standing in for HKCU\\...\\Run. Returns the value left behind."""
    key = rf"HKCU:\Software\YazSesTest-{uuid.uuid4().hex}"
    lines = _pre_uninstall()
    assert lines[0].startswith("$run = "), "test assumes the first line names the key"
    setup = [f"New-Item -Path '{key}' -Force | Out-Null"]
    if entry is not None:
        setup.append(
            f"New-ItemProperty -Path '{key}' -Name 'YazSes' -Value '{entry}' | Out-Null"
        )
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            *setup,
            rf"$dir = '{_APPS}\2.43.2'",
            f"$run = '{key}'",
            *lines[1:],
            f"$left = (Get-ItemProperty -Path '{key}' -Name 'YazSes' -ErrorAction SilentlyContinue).YazSes",
            f"Remove-Item -Path '{key}' -Recurse -Force",
            "if ($left) { Write-Output $left } else { Write-Output '<none>' }",
        ]
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout.strip()
    return None if out == "<none>" else out


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="runs the PowerShell lines")


@windows_only
def test_the_entry_this_scoop_install_wrote_is_removed():
    assert _run_pre_uninstall(rf'"{_APPS}\current\YazSesApp.exe" --tray') is None


@windows_only
def test_the_console_entry_older_versions_wrote_is_removed_too():
    assert _run_pre_uninstall(rf'"{_APPS.upper()}\CURRENT\yazses-cli.exe" --tray') is None


@windows_only
def test_the_installer_entry_is_left_alone():
    other = r'"C:\Users\ada\AppData\Local\Programs\YazSes\YazSesApp.exe" --tray'
    assert _run_pre_uninstall(other) == other


@windows_only
def test_no_entry_is_not_an_error():
    assert _run_pre_uninstall(None) is None
