"""The release-manifest refresher must cover every channel it claims to.

Every tag left Chocolatey and Flatpak sitting at the previous version, and every
winget refresh produced a version directory with no defaultLocale manifest —
which winget rejects outright, so the submission could never succeed. Both were
gaps in the *tool*, not in the manifests: `test_every_manifest_declares_the_same
_version` caught the drift each time, and the fix was a hand-edit nobody
remembered. These cover the renderers directly (no network, no released assets).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "refresh-package-manifests.py"


def _load():
    spec = importlib.util.spec_from_file_location("refresh_manifests", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Register before executing: @dataclass resolves annotations through
    # sys.modules[cls.__module__], which is None for a module that is not there
    # yet — the failure is an opaque AttributeError inside dataclasses.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


refresh = _load()


@pytest.fixture
def exe():
    return refresh.Asset(
        name="YazSes-9.9.9-windows-x64.exe",
        url="https://github.com/MSKazemi/yazses/releases/download/v9.9.9/YazSes-9.9.9-windows-x64.exe",
        size=1234,
        sha256="a" * 64,
    )


# ---- winget locale -----------------------------------------------------


def test_locale_prose_survives_but_the_version_moves():
    previous = (
        "PackageIdentifier: MSKazemi.YazSes\n"
        "PackageVersion: 2.18.2\n"
        "ShortDescription: Offline voice dictation — hold a key, speak, release.\n"
        "ReleaseNotesUrl: https://github.com/MSKazemi/yazses/releases/tag/v2.18.2\n"
        "ManifestType: defaultLocale\n"
    )
    out = refresh.render_winget_locale("9.9.9", previous)

    assert "PackageVersion: 9.9.9" in out
    assert "releases/tag/v9.9.9" in out
    assert "2.18.2" not in out
    # the hand-written prose is the whole reason this is carried rather than generated
    assert "Offline voice dictation — hold a key, speak, release." in out
    assert "ManifestType: defaultLocale" in out


def test_the_repo_ships_a_locale_manifest_for_every_winget_version():
    """winget rejects a version directory missing defaultLocale, so an incomplete
    one is not a partial success — it is a submission that cannot be made."""
    for version_dir in refresh.WINGET_DIR.glob("*"):
        if not version_dir.is_dir():
            continue
        assert (version_dir / refresh.LOCALE_NAME).exists(), (
            f"{version_dir.name} has no {refresh.LOCALE_NAME}"
        )


def test_locale_is_carried_from_the_newest_previous_version(tmp_path, monkeypatch):
    """2.19.0 must carry from 2.9.0's successor, not from whatever sorts last as
    a string — 2.19.0 < 2.9.0 lexically, which would pick up stale prose."""
    monkeypatch.setattr(refresh, "WINGET_DIR", tmp_path)
    for name, marker in (("2.9.0", "OLD"), ("2.18.2", "NEW")):
        d = tmp_path / name
        d.mkdir()
        (d / refresh.LOCALE_NAME).write_text(
            f"PackageVersion: {name}\nShortDescription: {marker}\n", encoding="utf-8"
        )

    carried = refresh.latest_winget_locale("2.19.0")
    assert carried is not None and "NEW" in carried


def test_no_previous_locale_is_reported_not_invented(tmp_path, monkeypatch):
    monkeypatch.setattr(refresh, "WINGET_DIR", tmp_path)
    assert refresh.latest_winget_locale("1.0.0") is None


# ---- chocolatey --------------------------------------------------------


def test_nuspec_version_is_restamped():
    previous = "<package>\n  <metadata>\n    <version>2.18.2</version>\n  </metadata>\n</package>\n"
    assert "<version>9.9.9</version>" in refresh.render_nuspec("9.9.9", previous)


def test_choco_install_gets_this_release_url_and_checksum(exe):
    previous = (
        "$packageArgs = @{\n"
        "  url64bit       = 'https://github.com/MSKazemi/yazses/releases/download/v2.18.2/YazSes-2.18.2-windows-x64.exe'\n"
        "  checksum64     = '78d08aa50ea1456b450ab5305d6151778ece3cfe471f4bc04d24073a7534f775'\n"
        "  checksumType64 = 'sha256'\n"
        "}\n"
    )
    out = refresh.render_choco_install("9.9.9", exe, previous)

    assert exe.url in out
    assert exe.sha256 in out
    assert "2.18.2" not in out
    # the algorithm line must not be mistaken for the checksum line
    assert "checksumType64 = 'sha256'" in out


# ---- flatpak -----------------------------------------------------------


def test_metainfo_gains_the_new_release_at_the_top():
    previous = '  <releases>\n    <release version="2.18.2" date="2026-08-13"/>\n  </releases>\n'
    out = refresh.render_metainfo("9.9.9", "2026-09-01", previous)

    assert '<release version="9.9.9" date="2026-09-01"/>' in out
    assert '<release version="2.18.2"' in out, "history must not be discarded"
    assert out.index("9.9.9") < out.index("2.18.2"), "newest release comes first"


def test_metainfo_refresh_is_idempotent():
    previous = '  <releases>\n    <release version="9.9.9" date="2026-09-01"/>\n  </releases>\n'
    assert refresh.render_metainfo("9.9.9", "2026-09-01", previous) == previous


# ---- coverage ----------------------------------------------------------


def test_every_versioned_manifest_has_a_renderer():
    """The failure mode this whole file exists for: a channel nobody regenerates.
    If a new manifest is added to the version check, it needs a renderer here."""
    for path in (
        refresh.CASK, refresh.SCOOP, refresh.SCOOP_REVIEWED, refresh.PKGBUILD,
        refresh.SRCINFO, refresh.NUSPEC, refresh.CHOCO_INSTALL, refresh.METAINFO,
    ):
        assert path.exists(), f"{path} is referenced by the refresher but absent"
