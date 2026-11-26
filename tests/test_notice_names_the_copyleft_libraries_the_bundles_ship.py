"""NOTICE names every copyleft library the shipped desktop bundles redistribute.

The Windows `.exe` and the macOS `.dmg` are frozen bundles. `scripts/build-windows.ps1`
and `scripts/build-macos.sh` both run `uv sync ... --extra desktop`, and that extra is
PySide6, which is Qt for Python: licensed `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`
(PyPI metadata, 6.11.2). NOTICE named `pystray` (LGPL-3.0) and said nothing of Qt, so the
one LGPL library a user could most reasonably ask about -- 648 MB of it, 59% of an
install (`docs/install-cost.md`) -- was the one the licence note left out.

The LGPL's first ask of a distributor is to say so. This keeps that sentence from
disappearing again, and it is derived: if a build script stops installing the desktop
extra, the requirement goes with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPTS = ("scripts/build-windows.ps1", "scripts/build-macos.sh")


@pytest.mark.parametrize("script", BUILD_SCRIPTS)
def test_a_bundle_that_installs_the_desktop_extra_credits_qt_in_notice(script: str) -> None:
    text = (ROOT / script).read_text(encoding="utf-8")
    installs_desktop = any(
        "uv sync" in line and "--extra desktop" in line
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )
    if not installs_desktop:
        pytest.skip(f"{script} no longer bundles the desktop extra")
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "PySide6" in notice, (
        f"{script} bundles PySide6 (Qt, LGPL-3.0) but NOTICE does not name it"
    )
    assert "LGPL" in notice


def test_the_scan_reads_both_build_scripts() -> None:
    for script in BUILD_SCRIPTS:
        text = (ROOT / script).read_text(encoding="utf-8")
        assert "--extra desktop" in text, f"{script} changed; revisit this guard"
