"""Every packaging manifest must declare the same version.

The manifests in `packaging/` are hand-maintained copies of one fact — the
current release — spread across six package managers in five file formats. They
drift silently: at the 2.18.2 release, Arch, Scoop, Chocolatey, Flatpak and the
winget manifests were all still pinned to 2.17.0, so an Arch or Scoop user who
followed them would have installed a two-release-old build with a checksum that
no longer matched anything published.

Nothing caught it because nothing compared them. This module does, **offline** —
it only cross-checks the files against each other, never the network, so it runs
in the same fully-offline suite as everything else. Checking the declared version
against the *actually released* asset needs the network and stays where it
belongs: `scripts/refresh-package-manifests.py --check`, run at release time.

Scope note: "manifest" here means a file that resolves a **download** — a URL and
a checksum. Flatpak's AppStream metainfo is release *history* and is excluded; see
`_all_versions`.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "packaging"

# The abandoned v1.0 Rust distribution. Those releases were never published and
# the files are kept only as history — see packaging/README.md.
DEAD_FILES = {"yazses-formula.rb", "yazses-v1.rb"}

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _arch_version() -> str:
    text = (PKG / "arch" / "PKGBUILD").read_text(encoding="utf-8")
    match = re.search(r"^pkgver=(\S+)$", text, re.M)
    assert match, "PKGBUILD no longer declares pkgver"
    return match.group(1)


def _scoop_version() -> str:
    return json.loads((PKG / "scoop" / "yazses.json").read_text(encoding="utf-8"))["version"]


def _chocolatey_version() -> str:
    text = (PKG / "chocolatey" / "yazses.nuspec").read_text(encoding="utf-8")
    match = re.search(r"<version>([^<]+)</version>", text)
    assert match, "the chocolatey nuspec no longer declares a version"
    return match.group(1)


def _homebrew_version() -> str:
    text = (PKG / "homebrew" / "yazses.rb").read_text(encoding="utf-8")
    match = re.search(r'^\s*version\s+"([^"]+)"', text, re.M)
    assert match, "the homebrew cask no longer declares a version"
    return match.group(1)


def _flatpak_version() -> str:
    root = ET.parse(PKG / "flatpak" / "com.mskazemi.YazSes.metainfo.xml").getroot()
    releases = root.find("releases")
    assert releases is not None and len(releases), "metainfo.xml declares no releases"
    return releases[0].get("version") or ""


def _winget_versions() -> dict[str, str]:
    """Every manifest in the newest winget version directory."""
    base = PKG / "winget" / "manifests" / "m" / "MSKazemi" / "YazSes"
    newest = max(
        (d for d in base.iterdir() if d.is_dir() and SEMVER.match(d.name)),
        key=lambda d: tuple(int(p) for p in d.name.split(".")),
    )
    out: dict[str, str] = {}
    for path in sorted(newest.glob("*.yaml")):
        match = re.search(r"^PackageVersion:\s*(\S+)\s*$", path.read_text(encoding="utf-8"), re.M)
        assert match, f"{path.name} declares no PackageVersion"
        out[f"winget/{path.name}"] = match.group(1)
    # The directory name is itself a declaration winget enforces.
    out["winget/<dirname>"] = newest.name
    return out


def _all_versions() -> dict[str, str]:
    """The manifests that resolve a **download**: a URL plus a checksum.

    `flatpak/metainfo.xml` is deliberately **not** here. Its `<releases>` block is
    AppStream release *history* for a software centre — it carries no asset URL and
    no checksum (its only URLs are homepage, bugtracker, vcs and help), and Flathub
    builds from the manifest rather than from this file. So it cannot "fetch the
    wrong asset", which is the whole failure this test exists to prevent.

    Keeping it in this set made two guards contradict each other, and the v2.21.0
    release is where they collided: `test_flatpak_metainfo` requires metainfo to
    track `pyproject`, while these five legitimately lag it. `packaging/README.md`
    states that lag as intended — *"between a release-prep bump and the assets being
    published those two legitimately differ, so such a test would fail on every
    release commit and get disabled."* Grouping them forced every checksummed
    manifest to be bumped at the moment of the release commit, which is exactly the
    ahead-of-release state that makes Homebrew and winget refuse the download.
    """
    versions = {
        "arch/PKGBUILD": _arch_version(),
        "scoop/yazses.json": _scoop_version(),
        "chocolatey/yazses.nuspec": _chocolatey_version(),
        "homebrew/yazses.rb": _homebrew_version(),
    }
    versions.update(_winget_versions())
    return versions


def test_the_release_history_may_lead_the_download_manifests() -> None:
    """AppStream history tracks the version being released; checksums follow it.

    Pinned because the natural-looking simplification — "everything in packaging/
    agrees" — deadlocks the release it is meant to protect.
    """
    assert "flatpak/metainfo.xml" not in _all_versions()
    assert SEMVER.match(_flatpak_version())


def test_every_manifest_declares_the_same_version() -> None:
    versions = _all_versions()
    distinct = set(versions.values())
    assert len(distinct) == 1, (
        "packaging manifests disagree about the current version — an install from "
        "the odd one out fetches the wrong asset, or a checksum that matches "
        "nothing published:\n"
        + "\n".join(f"  {name:42} {ver}" for name, ver in sorted(versions.items()))
        + "\n\nRegenerate with: uv run python scripts/refresh-package-manifests.py "
        "--version <x.y.z>"
    )


@pytest.mark.parametrize("name", sorted(_all_versions()))
def test_declared_version_is_a_release_version(name: str) -> None:
    """A placeholder or a `-dev` suffix here ships a manifest that resolves to no
    published asset."""
    value = _all_versions()[name]
    assert SEMVER.match(value), f"{name} declares {value!r}, which is not a release version"


def test_winget_directory_matches_the_manifests_inside_it() -> None:
    """winget requires the directory name to equal PackageVersion; a mismatch is
    rejected at submission, after the PR is opened."""
    winget = _winget_versions()
    dirname = winget.pop("winget/<dirname>")
    mismatched = {k: v for k, v in winget.items() if v != dirname}
    assert not mismatched, f"winget dir is {dirname} but {mismatched} disagree"


def test_winget_ships_all_three_required_manifests() -> None:
    """winget rejects a submission missing any of version / installer / locale."""
    kinds = {name.split(".")[-2] for name in _winget_versions() if name.endswith(".yaml")}
    # e.g. {"MSKazemi.YazSes", "installer", "locale.en-US"} -> normalise by suffix
    names = {n for n in _winget_versions() if n.endswith(".yaml")}
    assert any("installer" in n for n in names), "winget installer manifest missing"
    assert any("locale" in n for n in names), "winget locale manifest missing"
    assert any(n.endswith("MSKazemi.YazSes.yaml") for n in names), "winget version manifest missing"
    assert kinds  # the parse produced something


def test_dead_v1_manifests_are_still_marked_as_dead() -> None:
    """They point at releases that were never published. If one is ever revived
    by copy-paste, the marker is what stops it shipping a PLACEHOLDER checksum."""
    for name in DEAD_FILES:
        path = PKG / "homebrew" / name
        if not path.exists():
            continue
        head = path.read_text(encoding="utf-8")[:600].lower()
        assert "never" in head or "abandoned" in head or "dead" in head, (
            f"{name} is a dead v1 manifest but no longer says so at the top"
        )
