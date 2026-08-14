"""The app-grid launcher (#59).

A .deb or a snap can write into /usr/share/applications. A pipx or uv-tool
install owns nothing outside its own virtualenv, so those users had a Settings
window reachable only by typing a command — which is the audience least likely to
want to. `yazses settings --install-launcher` is the per-user equivalent.

Everything here runs against a temporary XDG root; no desktop required.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yazses.system.launcher import (
    DESKTOP_FILENAME,
    ICON_SIZES,
    applications_dir,
    icon_dir,
    install_launcher,
    uninstall_launcher,
)

ROOT = Path(__file__).resolve().parent.parent
CONTRIB = ROOT / "contrib"


def test_the_desktop_entry_ships_in_the_repo():
    assert (CONTRIB / DESKTOP_FILENAME).is_file()


def test_the_icon_ships_as_svg_and_as_every_declared_png_size():
    assert (CONTRIB / "icons" / "yazses.svg").is_file()
    for size in ICON_SIZES:
        assert (CONTRIB / "icons" / f"yazses-{size}.png").is_file(), size


def test_the_pngs_are_actually_the_size_they_claim():
    """A renamed file would install a 48px icon into the 256px directory, and the
    desktop would scale it up rather than reject it — visibly bad, silently so."""
    for size in ICON_SIZES:
        data = (CONTRIB / "icons" / f"yazses-{size}.png").read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
        width = int.from_bytes(data[16:20], "big")
        height = int.from_bytes(data[20:24], "big")
        assert (width, height) == (size, size), f"{size}: got {width}x{height}"


def test_the_exec_line_is_the_bare_command():
    """`uv tool` and `pipx` both put `yazses` on PATH; hard-coding today's
    interpreter path is how a launcher breaks at the next upgrade."""
    text = (CONTRIB / DESKTOP_FILENAME).read_text(encoding="utf-8")
    assert "Exec=yazses settings" in text
    assert "Exec=/" not in text


def test_the_entry_names_the_icon_the_installer_writes():
    text = (CONTRIB / DESKTOP_FILENAME).read_text(encoding="utf-8")
    assert "Icon=yazses" in text


@pytest.mark.skipif(
    not __import__("shutil").which("desktop-file-validate"),
    reason="desktop-file-utils not installed",
)
def test_the_entry_passes_the_freedesktop_validator():
    result = subprocess.run(
        ["desktop-file-validate", str(CONTRIB / DESKTOP_FILENAME)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not result.stdout.strip(), f"validator hints: {result.stdout}"


def test_install_writes_the_entry_and_the_icons(tmp_path):
    result = install_launcher(tmp_path, source=CONTRIB)
    assert result.installed
    assert (applications_dir(tmp_path) / DESKTOP_FILENAME).is_file()
    assert (icon_dir(tmp_path, None) / "yazses.svg").is_file()
    for size in ICON_SIZES:
        assert (icon_dir(tmp_path, size) / "yazses.png").is_file(), size


def test_install_is_idempotent(tmp_path):
    """Running it twice must not fail or duplicate anything."""
    install_launcher(tmp_path, source=CONTRIB)
    second = install_launcher(tmp_path, source=CONTRIB)
    assert second.installed
    entries = list(applications_dir(tmp_path).iterdir())
    assert len(entries) == 1


def test_uninstall_removes_exactly_what_install_wrote(tmp_path):
    install_launcher(tmp_path, source=CONTRIB)
    removed = uninstall_launcher(tmp_path)
    # the .desktop, the scalable SVG, and one PNG per size
    assert len(removed) == 2 + len(ICON_SIZES)
    assert not (applications_dir(tmp_path) / DESKTOP_FILENAME).exists()


def test_uninstall_on_a_clean_machine_is_not_an_error(tmp_path):
    assert uninstall_launcher(tmp_path) == []


def test_a_wheel_install_says_why_it_cannot(tmp_path):
    """A wheel does not ship contrib/, and "no such file" is not an explanation."""
    result = install_launcher(tmp_path, source=tmp_path / "not-here")
    assert not result.installed
    assert "wheel" in result.detail
    assert ".deb" in result.detail or "snap" in result.detail


def test_the_deb_installs_the_same_files():
    """The two paths must not drift — a .deb user and a pipx user should see the
    same entry with the same icon name."""
    script = (ROOT / "scripts" / "build-deb.sh").read_text(encoding="utf-8")
    assert "usr/share/applications" in script
    assert "yazses-settings.desktop" in script
    assert "icons/hicolor/scalable/apps" in script
