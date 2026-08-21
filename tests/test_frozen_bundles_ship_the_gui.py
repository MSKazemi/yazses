"""A frozen bundle must install the extra that carries Qt, or its GUI cannot open.

`97a34a0` moved PySide6 out of the base dependencies and into the `desktop` extra.
`snap/snapcraft.yaml` was updated in the same breath and says so in a comment:

    # PySide6: the tray icon and the voice-activity overlay. It used to arrive
    # as a base dependency; it is now the `desktop` extra, so it MUST be listed

The two PyInstaller builds were not. Both run a bare `uv sync --no-dev`, so PySide6
was simply absent from the build environment, PyInstaller had nothing to collect, and
the shipped `.exe` and `.app` contained no Qt at all.

The user-visible result is the worst available shape: **the tray's "Settings…" entry
opens nothing and says nothing**. `settingsui/app.py` handles the missing import
correctly — it prints an explanation and exits 1 — but the tray launches it as a
*windowed* process, which on Windows has no console for stderr to reach, and
`TrayController.launch_settings` has already returned True by then because `Popen`
succeeded. A click, then silence.

Nothing caught it: the installer smoke test checks that three files exist and runs
`--version` and `doctor`, and never opens the window.

This pins the invariant at the only place it can be checked cheaply — the build
scripts — rather than by building a 200 MB bundle in a unit test.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: The build scripts that produce a frozen, self-contained bundle. Each must install
#: the GUI extra explicitly, because a bundle cannot pip-install anything later.
FROZEN_BUILDS = [
    Path("scripts/build-windows.ps1"),
    Path("scripts/build-macos.sh"),
]


def _extras_providing_pyside() -> set[str]:
    """Every optional-dependency group that would install PySide6."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    return {
        name
        for name, deps in (project.get("optional-dependencies") or {}).items()
        if any("pyside" in dep.lower() for dep in deps)
    }


def _pyside_is_a_base_dependency() -> bool:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return any("pyside" in dep.lower() for dep in data["project"].get("dependencies", []))


def _sync_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if re.search(r"\buv\s+sync\b", ln)]


@pytest.mark.parametrize("script", FROZEN_BUILDS, ids=lambda p: p.name)
def test_a_frozen_build_installs_the_extra_that_carries_qt(script: Path):
    if _pyside_is_a_base_dependency():
        pytest.skip("PySide6 is a base dependency again; the extra is not needed")

    path = ROOT / script
    assert path.exists(), f"{script} is gone — update FROZEN_BUILDS"

    extras = _extras_providing_pyside()
    assert extras, "no extra installs PySide6 — has the packaging changed?"

    syncs = _sync_lines(path.read_text(encoding="utf-8"))
    assert syncs, f"{script} no longer runs `uv sync`; this guard is looking at the wrong step"

    satisfied = [
        line
        for line in syncs
        if any(re.search(rf"--extra[= ]+{re.escape(name)}\b", line) for name in extras)
    ]
    assert satisfied, (
        f"{script} builds a frozen bundle without Qt: none of its `uv sync` lines "
        f"request an extra that installs PySide6 (any of {sorted(extras)}).\n"
        f"  found: {syncs}\n"
        "A bundle cannot install it later, so the settings window can never open — "
        "and it fails silently, because a windowed process has no stderr to complain on."
    )


def test_the_guard_would_notice_a_bare_sync():
    """Guards the guard: prove the matcher rejects the line that caused the bug."""
    extras = _extras_providing_pyside()
    bare = "uv sync --no-dev"
    assert not any(re.search(rf"--extra[= ]+{re.escape(n)}\b", bare) for n in extras)

    fixed = "uv sync --no-dev --extra desktop"
    assert any(re.search(rf"--extra[= ]+{re.escape(n)}\b", fixed) for n in extras), (
        "the matcher does not accept a correctly fixed line, so it would fail forever"
    )
