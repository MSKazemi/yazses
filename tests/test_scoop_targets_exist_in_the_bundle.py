"""Every executable a Scoop manifest names must be one the installer actually ships.

`scoop install yazses` printed

    Creating shortcut for YazSes (yazses.exe) failed:
        Couldn't find C:\\scoop\\apps\\yazses\\current\\yazses.exe

on a real Windows host, and carried on to report success. So every Scoop install
has silently had no Start Menu entry -- while the manifest's own `notes` tell the
user "Launch the tray app from the Start Menu", which was therefore impossible.

There is no `yazses.exe` in the bundle and never was. `packaging/windows/yazses.spec`
builds exactly two: `YazSesApp.exe` (windowed -- the tray and daemon) and
`yazses-cli.exe` (console -- the CLI, shimmed onto PATH as `yazses`). The `bin`
entry named the second one correctly, which is why the CLI worked and the gap stayed
invisible: the half that is exercised on every install was right, and the half that
only shows up in the Start Menu was not.

The names are read out of the PyInstaller spec rather than listed here, so renaming a
binary fails this test instead of silently breaking the shortcut again. That is the
same reasoning as the icon guard reading its size list out of `build-deb.sh`: a fact
copied into a test is a fact that can drift.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "windows" / "yazses.spec"
MANIFESTS = (ROOT / "bucket" / "yazses.json", ROOT / "packaging" / "scoop" / "yazses.json")


def shipped_executables() -> set[str]:
    """The `name=` of every PyInstaller EXE() in the Windows spec, as a filename."""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "EXE"):
            continue
        for kw in node.keywords:
            if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                names.add(f"{kw.value.value}.exe")
    return names


def test_the_spec_still_declares_the_two_binaries_we_expect() -> None:
    """Anti-vacuity: an empty parse would make every check below pass."""
    shipped = shipped_executables()
    assert shipped == {"YazSesApp.exe", "yazses-cli.exe"}, (
        f"the Windows spec now builds {sorted(shipped)}. That is allowed, but the "
        f"Scoop manifests below must be updated to match -- fix them, not this test."
    )


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.parent.name)
def test_every_shortcut_target_is_a_shipped_executable(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    shipped = shipped_executables()
    targets = [entry[0] for entry in data.get("shortcuts", [])]
    assert targets, f"{path.name} declares no shortcuts -- this guard is checking nothing"
    missing = [t for t in targets if t not in shipped]
    assert not missing, (
        f"{path.name} makes a Start Menu shortcut to {missing}, which the installer "
        f"does not ship. Scoop prints 'Couldn't find' and installs anyway. "
        f"Shipped: {sorted(shipped)}"
    )


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.parent.name)
def test_every_bin_target_is_a_shipped_executable(path: Path) -> None:
    """The half that was already right, held so it stays right."""
    data = json.loads(path.read_text(encoding="utf-8"))
    shipped = shipped_executables()
    targets = [e[0] if isinstance(e, list) else e for e in data.get("bin", [])]
    assert targets, f"{path.name} declares no bin -- this guard is checking nothing"
    missing = [t for t in targets if t not in shipped]
    assert not missing, f"{path.name} shims {missing}, which the installer does not ship"


def test_the_shortcut_points_at_the_windowed_app_not_the_console_cli() -> None:
    """A Start Menu entry that opens a console window is the wrong one of the two.

    Both binaries exist, so a target can be *shipped* and still be the wrong choice:
    the manifest's notes say "Launch the tray app from the Start Menu", and the tray
    app is the windowed build.
    """
    for path in MANIFESTS:
        data = json.loads(path.read_text(encoding="utf-8"))
        targets = [entry[0] for entry in data["shortcuts"]]
        assert targets == ["YazSesApp.exe"], (
            f"{path.name} points its Start Menu entry at {targets}; it must be the "
            f"windowed tray app, not the console CLI."
        )
