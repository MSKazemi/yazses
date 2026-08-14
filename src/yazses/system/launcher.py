"""Install a desktop launcher so YazSes appears in the app grid (#59).

A `.deb` or a snap can drop files into `/usr/share/applications`. A `pipx` or
`uv tool` install cannot — it owns nothing outside its own virtualenv — so those
users have a Settings window with no way to reach it except by typing a command,
which is the audience least likely to want to.

This is the per-user equivalent: XDG says an application may install into
`~/.local/share/applications` and `~/.local/share/icons/hicolor/…`, and desktops
pick both up without a privileged step.

Pure path/text work with the destination injected, so it is testable without a
desktop. `Exec=yazses settings` deliberately uses the bare command rather than an
absolute path: `uv tool` and `pipx` both put it on PATH, and hard-coding today's
interpreter path is how a launcher breaks at the next upgrade.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

# Sizes rendered from contrib/icons/yazses.svg. hicolor wants each in its own
# directory; the scalable SVG covers everything modern, and the PNGs are for
# environments that still index only rasters.
ICON_SIZES = (48, 64, 128, 256)

DESKTOP_FILENAME = "yazses-settings.desktop"
ICON_NAME = "yazses"


@dataclass(frozen=True)
class InstallResult:
    """What was written, so the caller can print it rather than guess."""

    desktop_file: Path
    icons: tuple[Path, ...]
    installed: bool
    detail: str = ""

    def describe(self) -> str:
        if not self.installed:
            return f"Could not install the launcher: {self.detail}"
        return (
            f"Installed {self.desktop_file}\n"
            f"  + {len(self.icons)} icon file(s)\n"
            "It may take a moment to appear; some desktops need a re-login."
        )


def applications_dir(data_home: Path) -> Path:
    return Path(data_home) / "applications"


def icon_dir(data_home: Path, size: int | None) -> Path:
    """hicolor directory for *size*, or the scalable one when size is None."""
    leaf = "scalable" if size is None else f"{size}x{size}"
    return Path(data_home) / "icons" / "hicolor" / leaf / "apps"


def _source_dir() -> Path:
    """`contrib/` as shipped in the repo, or None-ish when running from a wheel.

    A wheel does not carry `contrib/`, so this returns a path that may not exist
    and the caller reports that rather than crashing.
    """
    return Path(__file__).resolve().parents[3] / "contrib"


def install_launcher(data_home: Path, *, source: Path | None = None) -> InstallResult:
    """Copy the .desktop entry and icons into *data_home* (``$XDG_DATA_HOME``)."""
    src = Path(source) if source is not None else _source_dir()
    desktop_src = src / DESKTOP_FILENAME
    if not desktop_src.is_file():
        return InstallResult(
            desktop_file=desktop_src, icons=(), installed=False,
            detail=(
                f"{desktop_src} is missing — this is expected in a wheel install, "
                "which does not ship contrib/. Copy it from the repository, or use "
                "the .deb or snap package, which install the launcher for you."
            ),
        )

    apps = applications_dir(data_home)
    apps.mkdir(parents=True, exist_ok=True)
    desktop_dst = apps / DESKTOP_FILENAME
    shutil.copyfile(desktop_src, desktop_dst)

    written: list[Path] = []
    svg = src / "icons" / f"{ICON_NAME}.svg"
    if svg.is_file():
        target = icon_dir(data_home, None)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(svg, target / f"{ICON_NAME}.svg")
        written.append(target / f"{ICON_NAME}.svg")
    for size in ICON_SIZES:
        png = src / "icons" / f"{ICON_NAME}-{size}.png"
        if not png.is_file():
            continue
        target = icon_dir(data_home, size)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(png, target / f"{ICON_NAME}.png")
        written.append(target / f"{ICON_NAME}.png")

    return InstallResult(desktop_file=desktop_dst, icons=tuple(written), installed=True)


def uninstall_launcher(data_home: Path) -> list[Path]:
    """Remove what :func:`install_launcher` wrote. Returns what was removed."""
    removed: list[Path] = []
    desktop = applications_dir(data_home) / DESKTOP_FILENAME
    if desktop.exists():
        desktop.unlink()
        removed.append(desktop)
    for size in (None, *ICON_SIZES):
        suffix = "svg" if size is None else "png"
        icon = icon_dir(data_home, size) / f"{ICON_NAME}.{suffix}"
        if icon.exists():
            icon.unlink()
            removed.append(icon)
    return removed
