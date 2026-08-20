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

import importlib.util
import json
import re
import sys
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


# --- a manifest's URLs must name the version the manifest declares --------------


#: `\b` will not do: the char before the digit in `v2.19.0` is `v`, a word character,
#: so `\bv?\d+\.\d+\.\d+\b` never matches the v-prefixed form — which is precisely the
#: form a GitHub release URL uses. The probe is self-tested below for that reason.
_SEMVER_IN_TEXT = re.compile(r"(?<![\d.])v?(\d+\.\d+\.\d+)(?![\d.])")

#: Single-file manifests: one copy, rewritten in place at each release. The winget
#: tree is deliberately absent — its manifests live in per-version directories, so an
#: old directory naming an old version is the format working as intended, not drift.
_SINGLE_FILE_MANIFESTS = {
    "chocolatey/yazses.nuspec": _chocolatey_version,
    "scoop/yazses.json": _scoop_version,
    "homebrew/yazses.rb": _homebrew_version,
    "arch/PKGBUILD": _arch_version,
}


def test_the_version_probe_matches_both_spellings() -> None:
    """The regex is the risk here, and it has been wrong twice in this repo.

    A word-boundary before the digits silently skips every `v`-prefixed URL, so the
    sweep would report a clean tree while looking at nothing.
    """
    assert _SEMVER_IN_TEXT.findall("releases/tag/v2.19.0") == ["2.19.0"]
    assert _SEMVER_IN_TEXT.findall('"version": "2.29.0"') == ["2.29.0"]
    assert _SEMVER_IN_TEXT.findall("core24 and python 3.11") == []


@pytest.mark.parametrize("name", sorted(_SINGLE_FILE_MANIFESTS))
def test_no_url_in_a_manifest_names_a_version_the_manifest_is_not(name: str) -> None:
    """A release moves a manifest's version *and* every URL that carries one.

    `render_nuspec` rewrote only `<version>`, so `<releaseNotes>` sat at v2.19.0 while
    the package shipped 2.29.0 — the *Release Notes* link on the chocolatey.org package
    page, and what `choco info yazses` prints, pointing ten versions back.

    `test_every_manifest_declares_the_same_version` could not see it: it compares each
    manifest's declared version against the others, and this one is a second version
    *inside* a manifest that declares the right one.

    Only URL-bearing lines are read. A version in prose can legitimately name an older
    release — `packaging/arch/PKGBUILD` explains that Qt moved out of the base install
    in v2.18.0, and that sentence stays true forever.
    """
    path = PKG / name
    declared = _SINGLE_FILE_MANIFESTS[name]()
    stale = [
        f"line {i}: {found} in {line.strip()[:100]}"
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "http" in line
        for found in _SEMVER_IN_TEXT.findall(line)
        if found != declared
    ]
    assert not stale, (
        f"packaging/{name} declares {declared} but a URL names another version:\n  "
        + "\n  ".join(stale)
        + "\n\nRegenerate with: uv run python scripts/refresh-package-manifests.py "
        "--version <x.y.z>"
    )


def test_the_sweep_has_something_to_inspect() -> None:
    """A guard over an empty set passes on everything.

    Not "every manifest carries a literal version in a URL" — two of them deliberately
    do not, and that is the *stronger* form: `homebrew/yazses.rb` writes
    `releases/download/v#{version}/…` and `arch/PKGBUILD` writes `${pkgver}`, so their
    URLs cannot drift from their declared version at all. The nuspec and the scoop
    manifest interpolate nothing, which is why one of them could and did.

    So what must hold is that the sweep sees at least one literal — otherwise it is
    reading nothing and would stay green through any drift.
    """
    literal = {
        name
        for name in _SINGLE_FILE_MANIFESTS
        for line in (PKG / name).read_text(encoding="utf-8").splitlines()
        if "http" in line and _SEMVER_IN_TEXT.findall(line)
    }
    assert literal, "no manifest carries a literal version in a URL — the sweep is vacuous"
    assert "chocolatey/yazses.nuspec" in literal, (
        "the nuspec is the manifest this guard was written for; if it no longer carries "
        "a literal version in a URL, say so here rather than leaving the check hollow"
    )


def test_the_generator_moves_the_release_notes_link_as_well_as_the_version() -> None:
    """Pinned on the generator, not only on its output.

    Fixing the committed nuspec by hand would leave the next release re-introducing the
    same staleness, and `--check` would not notice: it compares the file to what this
    same generator produces, so a generator that stopped rewriting the link would agree
    with a file that had not been rewritten.
    """
    spec = importlib.util.spec_from_file_location(
        "refresh_package_manifests", ROOT / "scripts" / "refresh-package-manifests.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: the module defines `@dataclass`es, and dataclasses
    # resolves annotations through `sys.modules[cls.__module__]`, which is `None`
    # for a module that was created from a spec but never registered.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)

    before = (PKG / "chocolatey" / "yazses.nuspec").read_text(encoding="utf-8")
    after = mod.render_nuspec("9.9.9", before)
    assert "<version>9.9.9</version>" in after
    assert "releases/tag/v9.9.9</releaseNotes>" in after
    assert "v2.19.0" not in after
