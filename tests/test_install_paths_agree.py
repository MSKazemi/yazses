"""Every install path must pull what it claims to pull (ADR-018).

There is no single installer. `install.sh`, the `.deb` postinst, the snap and the
Docker image each decide independently what a user ends up with, and they were
written at different times. That is fine as long as they agree with
`pyproject.toml` — and nothing checked that they did.

The specific hazard, and it is written into the code as a known risk rather than
discovered here: `install.sh` cannot use `yazses[desktop]` because uv resolves
extras from a `--from git+...` source awkwardly, so it names `PySide6` directly and
its comment says *"keep it in step with the `desktop` extra in pyproject"*. A
comment is not a mechanism. The `desktop` extra exists precisely so that adding a
second desktop-only dependency does not mean editing every installer — and if one
were added today, `install.sh` would silently stop installing a working desktop
while continuing to claim it provisions one.

So this file turns "keep it in step" into something that fails a build.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
EXTRAS: dict[str, list[str]] = PYPROJECT["project"]["optional-dependencies"]

INSTALL_SH = ROOT / "install.sh"
DEB_BUILD = ROOT / "scripts/build-deb.sh"


def _distribution(requirement: str) -> str:
    """`PySide6>=6.11.1` -> `pyside6`. Normalised per PEP 503."""
    name = re.split(r"[<>=!~\[;]", requirement, maxsplit=1)[0].strip()
    return re.sub(r"[-_.]+", "-", name).lower()


def _with_requirements(script: str) -> set[str]:
    """Every distribution named by a `--with <requirement>` flag."""
    return {
        _distribution(m.group(1))
        for m in re.finditer(r"--with\s+[\"']?([^\"'\s]+)[\"']?", script)
    }


def test_the_desktop_extra_is_not_empty():
    """Guard the guard: an empty extra would make every check below vacuous."""
    assert EXTRAS.get("desktop"), "no `desktop` extra to compare installers against"


def test_the_universal_installer_covers_the_whole_desktop_extra():
    """`install.sh` provisions a desktop, so it must install all of what that means.

    It names requirements directly rather than asking for the extra (see the module
    docstring). This is the check that makes that safe: add a package to `desktop`
    and this fails until `install.sh` is updated too.
    """
    named = _with_requirements(INSTALL_SH.read_text(encoding="utf-8"))
    required = {_distribution(r) for r in EXTRAS["desktop"]}
    missing = sorted(required - named)
    assert not missing, (
        f"install.sh provisions a desktop but never installs {missing}, which the "
        f"`desktop` extra says a desktop needs. Add `--with <requirement>` to the "
        f"`uv tool install` line, or switch it to the extra if uv can now resolve "
        f"extras from a git source."
    )


def test_the_universal_installer_does_not_pin_below_pyproject():
    """A looser floor in the installer silently ships an unsupported version."""
    script = INSTALL_SH.read_text(encoding="utf-8")
    floors = {
        _distribution(r): r for r in EXTRAS["desktop"] if ">=" in r
    }
    for dist, requirement in floors.items():
        want = requirement.split(">=")[1].strip().strip("\"'")
        pattern = rf"--with\s+[\"']?{re.escape(requirement.split('>=')[0])}>=([0-9][^\"'\s]*)"
        found = re.search(pattern, script)
        assert found, f"install.sh names no version floor for {dist}"
        assert found.group(1) == want, (
            f"install.sh pins {dist}>={found.group(1)} but pyproject requires >={want}"
        )


def test_the_deb_asks_for_the_desktop_extra_by_name():
    """The .deb *can* use the extra, so it must — a hardcoded list is the thing
    `install.sh` only does because it has no choice."""
    postinst = DEB_BUILD.read_text(encoding="utf-8")
    assert "yazses[desktop]" in postinst, (
        "the .deb postinst no longer installs `yazses[desktop]`; a desktop package "
        "that does not pull the desktop extra ships without the tray or the overlay"
    )


def test_the_container_image_does_not_pull_a_desktop():
    """A container has no display; Qt in it is 648 MB that can never be used."""
    dockerfile = (ROOT / "packaging/docker/Dockerfile").read_text(encoding="utf-8")
    assert "[desktop]" not in dockerfile and "PySide6" not in dockerfile, (
        "the Docker image installs a desktop extra it can never use"
    )
