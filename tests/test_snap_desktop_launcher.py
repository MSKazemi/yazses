"""The snap must export an application-grid launcher.

It did not, for the whole life of the package. Four apps were declared and none
carried a `desktop:` key, so snapd exported nothing to
/var/lib/snapd/desktop/applications/ -- firefox, vlc and snap-store were all
there and yazses was not. Every install from App Center, KDE Discover or the
snapcraft.io web button therefore ended with nothing to click, and nothing
anywhere said a terminal was required.

These are wiring assertions rather than content ones: the failure mode is a
file that exists in the tree and is referenced by nothing.
"""

from __future__ import annotations

import configparser
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "snap/snapcraft.yaml"
DESKTOP = ROOT / "snap/local/yazses.desktop"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def entry() -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(DESKTOP)
    return parser["Desktop Entry"]


def test_an_app_declares_a_desktop_launcher(manifest: dict) -> None:
    declared = {
        name: app.get("desktop")
        for name, app in manifest["apps"].items()
        if app.get("desktop")
    }
    assert declared, (
        "no app in snapcraft.yaml has a `desktop:` key, so snapd will export no "
        "launcher and a GUI install has nothing to click"
    )


def test_the_declared_path_is_actually_installed(manifest: dict) -> None:
    """A `desktop:` key pointing at a file the build never installs fails the build.

    This is the half that rots: the key and the `install -Dm644` line live in
    different parts of the manifest and neither mentions the other.
    """
    declared = next(
        app["desktop"] for app in manifest["apps"].values() if app.get("desktop")
    )
    override = manifest["parts"]["yazses"]["override-build"]
    assert f'"$CRAFT_PART_INSTALL/{declared}"' in override, (
        f"apps.*.desktop points at {declared!r} but override-build installs "
        "nothing there"
    )
    assert "snap/local/yazses.desktop" in override


def test_the_source_file_exists() -> None:
    assert DESKTOP.is_file()


def test_exec_names_the_snap_command(entry) -> None:
    """snapd rejects a desktop file whose Exec is not one of the snap's commands."""
    assert entry["Exec"].split()[0] == "yazses"


def test_the_launcher_opens_settings_not_dictation(entry) -> None:
    """An app-grid activation has no terminal, and dictation has nothing to show.

    A launcher that starts a background daemon looks broken; the settings window
    is the one surface that can show the hotkey, the microphone and -- in a snap
    -- that the interfaces are not connected.
    """
    assert entry["Exec"] == "yazses settings"


def test_icon_uses_the_snap_variable(entry) -> None:
    """`Icon=yazses` would render blank: the host icon theme cannot see inside a snap.

    ${SNAP} is what firefox and vlc ship and what snapd rewrites at export.
    `desktop-file-validate` warns about it for every snap; that warning is wrong here.
    """
    assert entry["Icon"].startswith("${SNAP}/")


def test_the_icon_file_is_actually_shipped(entry) -> None:
    """meta/gui is populated from snap/gui by snapcraft, so check the source."""
    name = entry["Icon"].rsplit("/", 1)[-1]
    assert (ROOT / "snap/gui" / name).is_file(), (
        f"the launcher points at meta/gui/{name}, which snapcraft fills from "
        f"snap/gui/{name} — and that file is missing"
    )


def test_it_is_findable_by_what_people_search_for(entry) -> None:
    """The desktop file is a search surface in every app grid, not just a label."""
    haystack = (entry.get("Keywords", "") + entry.get("GenericName", "")).lower()
    for term in ("voice", "dictation", "speech", "transcription", "accessibility"):
        assert term in haystack, f"{term!r} missing from the launcher's search terms"


def test_it_is_categorised_for_the_accessibility_section(entry) -> None:
    assert "Accessibility" in entry["Categories"]
