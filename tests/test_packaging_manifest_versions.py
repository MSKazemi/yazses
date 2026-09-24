"""Every packaging manifest must declare the same version.

The manifests in `packaging/` are hand-maintained copies of one fact — the
current release — restated once per package manager, in a different file format
each time. They drift silently: at the 2.18.2 release, Arch, Scoop, Chocolatey,
Flatpak and the winget manifests were all still pinned to 2.17.0, so an Arch or
Scoop user who followed them would have installed a two-release-old build with a
checksum that no longer matched anything published.

Which files are compared was itself the defect. The list named four, and
`packaging/fedora/yazses.spec` was not one of them, so the spec sat at 2.36.0
while four releases went past with this module green throughout — a repeat of a
drift a contributor had already fixed once, when the same file was pinned at
2.18.2. A guard that iterates a literal is green forever on everything the
literal omits.

Reading a manifest still needs one reader per format, so `_SINGLE_FILE_MANIFESTS`
remains. What is no longer a matter of memory is *membership*: `_version_bearing_
files` derives from the tree every file that declares a release version, and
`test_every_version_bearing_file_under_packaging_is_covered` fails on one that no
rule here reaches. A new manifest is caught by the commit that adds it.

Nothing caught the original because nothing compared them. This module does, **offline** —
it only cross-checks the files against each other, never the network, so it runs
in the same fully-offline suite as everything else. Checking the declared version
against the *actually released* asset needs the network and stays where it
belongs: `scripts/refresh-package-manifests.py --check`, run at release time.

Scope note: "manifest" here means a file that resolves a **download** — usually a
URL and a checksum, and in the RPM spec's case the version an sdist URL is built
from. Flatpak's AppStream metainfo is release *history* and is excluded; see
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


def _fedora_version() -> str:
    text = (PKG / "fedora" / "yazses.spec").read_text(encoding="utf-8")
    match = re.search(r"^Version:\s*(\S+)\s*$", text, re.M)
    assert match, "the RPM spec no longer declares a Version"
    return match.group(1)


def _srcinfo_version() -> str:
    """.SRCINFO is generated from PKGBUILD, and the AUR reads *this* file.

    A regenerated PKGBUILD with a stale .SRCINFO beside it publishes the old version:
    `makepkg --printsrcinfo` is a step someone runs, and steps someone runs get skipped.
    """
    text = (PKG / "arch" / ".SRCINFO").read_text(encoding="utf-8")
    match = re.search(r"^\s*pkgver = (\S+)\s*$", text, re.M)
    assert match, ".SRCINFO no longer declares pkgver"
    return match.group(1)


def _choco_install_version() -> str:
    """The Chocolatey install script declares no version — it only downloads one.

    `yazses.nuspec` says which version the package *is*; this script says which asset
    `choco install` actually fetches. Nothing tied the two together, so the nuspec could
    be refreshed and this left behind, which installs the previous release under the new
    release's name.
    """
    text = (PKG / "chocolatey" / "tools" / "chocolateyinstall.ps1").read_text(encoding="utf-8")
    match = re.search(r"^\s*url64bit\s*=\s*'[^']*/v(\d+\.\d+\.\d+)/", text, re.M)
    assert match, "chocolateyinstall.ps1 no longer downloads a versioned release asset"
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


#: Single-file manifests: one copy, rewritten in place at each release. The winget
#: tree is deliberately absent — its manifests live in per-version directories, so an
#: old directory naming an old version is the format working as intended, not drift.
#:
#: This is the only place a manifest is named. Adding one here puts it in *every* check
#: in this module at once, and `test_every_version_bearing_file_under_packaging_is_
#: covered` fails until a version-declaring file is either here or accounted for below.
_SINGLE_FILE_MANIFESTS = {
    "chocolatey/yazses.nuspec": _chocolatey_version,
    "chocolatey/tools/chocolateyinstall.ps1": _choco_install_version,
    "scoop/yazses.json": _scoop_version,
    "homebrew/yazses.rb": _homebrew_version,
    "arch/PKGBUILD": _arch_version,
    "arch/.SRCINFO": _srcinfo_version,
    "fedora/yazses.spec": _fedora_version,
}


def _all_versions() -> dict[str, str]:
    """The manifests that resolve the **download** a user installs.

    Most carry a URL and a checksum; `fedora/yazses.spec` instead names the version
    that `%{pypi_source}` expands into an sdist URL, which is the same dependency on
    the release having been published and so the same timing.

    `flatpak/metainfo.xml` is deliberately **not** here. Its `<releases>` block is
    AppStream release *history* for a software centre — it carries no asset URL and
    no checksum (its only URLs are homepage, bugtracker, vcs and help), and Flathub
    builds from the manifest rather than from this file. So it cannot "fetch the
    wrong asset", which is the whole failure this test exists to prevent.

    Keeping it in this set made two guards contradict each other, and the v2.21.0
    release is where they collided: `test_flatpak_metainfo` requires metainfo to
    track `pyproject`, while the manifests in this set legitimately lag it. `packaging/README.md`
    states that lag as intended — *"between a release-prep bump and the assets being
    published those two legitimately differ, so such a test would fail on every
    release commit and get disabled."* Grouping them forced every checksummed
    manifest to be bumped at the moment of the release commit, which is exactly the
    ahead-of-release state that makes Homebrew and winget refuse the download.
    """
    versions = {name: read() for name, read in _SINGLE_FILE_MANIFESTS.items()}
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


def _refresh_module():
    """`scripts/refresh-package-manifests.py`, imported by path.

    The hyphens make it un-importable by name, and it is a script rather than a package
    member on purpose: a release job runs it under a bare `/usr/bin/python3`.
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
    return mod


def test_the_generator_moves_the_release_notes_link_as_well_as_the_version() -> None:
    """Pinned on the generator, not only on its output.

    Fixing the committed nuspec by hand would leave the next release re-introducing the
    same staleness, and `--check` would not notice: it compares the file to what this
    same generator produces, so a generator that stopped rewriting the link would agree
    with a file that had not been rewritten.
    """
    mod = _refresh_module()

    before = (PKG / "chocolatey" / "yazses.nuspec").read_text(encoding="utf-8")
    after = mod.render_nuspec("9.9.9", before)
    assert "<version>9.9.9</version>" in after
    assert "releases/tag/v9.9.9</releaseNotes>" in after
    assert "v2.19.0" not in after


# --- coverage: a manifest is swept because it exists, not because it was remembered ---


#: How each packaging format spells "this package is version X", plus the one way a file
#: pins a release without saying so — naming the asset it downloads.
#:
#: These are *forms*, not filenames, which is the whole point. `_SINGLE_FILE_MANIFESTS`
#: used to name four files and a fifth, `fedora/yazses.spec`, was written without being
#: added to it; it then sat at 2.36.0 through four releases with every test in this
#: module green, because a guard that iterates a literal cannot see past the literal.
#: A new manifest in any of these formats is swept from the moment it is committed.
_DECLARATION_FORMS = (
    re.compile(r"^Version:\s*\d+\.\d+\.\d+\s*$", re.M),            # RPM spec
    re.compile(r"^\s*pkgver\s*=\s*\d+\.\d+\.\d+\s*$", re.M),       # PKGBUILD and .SRCINFO
    re.compile(r"<version>\d+\.\d+\.\d+</version>"),               # nuspec
    re.compile(r'"version"\s*:\s*"\d+\.\d+\.\d+"'),                # scoop
    re.compile(r'^\s*version\s+"\d+\.\d+\.\d+"', re.M),            # homebrew cask
    re.compile(r"^PackageVersion:\s*\d+\.\d+\.\d+\s*$", re.M),     # winget
    re.compile(r'<release\s+version="\d+\.\d+\.\d+"'),             # AppStream metainfo
    # No version field at all, only the asset it fetches — chocolateyinstall.ps1, and
    # every manifest whose URL is a literal rather than an interpolation.
    re.compile(r"(?i)(?:releases/(?:download|tag)/v|yazses@v|/yazses-|/YazSes-)\d+\.\d+\.\d+"),
)

#: Version-bearing files this module does **not** hold to the common version, and the
#: guard that holds each of them instead. An entry here is a statement about which rule
#: applies to a file — never that nothing checks it.
_CHECKED_UNDER_A_DIFFERENT_RULE = {
    "flatpak/com.mskazemi.YazSes.metainfo.xml": (
        "release history, which leads the download manifests by design: "
        "test_the_release_history_may_lead_the_download_manifests above, and "
        "test_the_newest_release_entry_matches_the_project_version in "
        "tests/test_flatpak_metainfo.py"
    ),
    "flatpak/python3-yazses.json": (
        "the wheel a Flathub install actually contains, pinned by URL and hash: "
        "test_the_pinned_wheel_is_the_project_version_or_the_one_before_it in "
        "tests/test_flatpak_metainfo.py allows the project version or the one before "
        "it, because the wheel for the version being released does not exist on PyPI "
        "until after the tag is pushed"
    ),
}


def _version_bearing_files(root: Path) -> set[str]:
    """Every file under `root` that pins a YazSes version, as a `/`-joined relative path.

    Takes a root rather than reading `PKG` directly so the classifier can be run against
    a fabricated tree — see `test_a_new_manifest_is_uncovered_until_a_rule_reaches_it`.
    A completeness guard nobody has watched fail is a completeness guard nobody knows
    works, and writing a probe file into `packaging/` to prove it would edit the
    developer's own checkout.

    Two exclusions, both by rule rather than by name:

    * `*.md` — prose. `packaging/README.md` walks a reader through assembling a winget
      directory by hand and quotes `0.4.0` throughout; a document being accurate about
      the past is not drift.
    * `DEAD_FILES` — the abandoned v1 formulas, which pin releases that were never
      published and are kept as history.
    """
    found: set[str] = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix == ".md" or path.name in DEAD_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # an icon or a screenshot; it declares nothing
        if any(form.search(text) for form in _DECLARATION_FORMS):
            found.add(path.relative_to(root).as_posix())
    return found


def _uncovered(root: Path, covered: set[str]) -> set[str]:
    """Version-bearing files under `root` that no rule in this module reaches."""
    return {
        rel
        for rel in _version_bearing_files(root)
        if rel not in covered
        and rel not in _CHECKED_UNDER_A_DIFFERENT_RULE
        # winget keeps one directory per version, so an old directory naming an old
        # version is the format working as intended. `_winget_versions` reads the
        # newest, which is the only one a release moves.
        and not rel.startswith("winget/manifests/")
    }


def test_every_version_bearing_file_under_packaging_is_covered() -> None:
    """The guard the fedora spec needed and did not have.

    `packaging/fedora/yazses.spec` was added, declared `Version:`, and was checked by
    nothing — so it went stale exactly the way the contributor who first fixed it had
    already documented. This fails on the *next* such file, on the commit that adds it.
    """
    uncovered = _uncovered(PKG, set(_SINGLE_FILE_MANIFESTS))
    assert not uncovered, (
        "these files under packaging/ declare a release version that nothing checks:\n  "
        + "\n  ".join(sorted(uncovered))
        + "\n\nGive each one a reader in _SINGLE_FILE_MANIFESTS — which also puts it in "
        "the same-version, release-version and stale-URL checks — or, if a different "
        "rule genuinely applies, record it in _CHECKED_UNDER_A_DIFFERENT_RULE naming "
        "the test that holds it."
    )


def test_the_coverage_sweep_sees_the_manifests_it_is_meant_to_see() -> None:
    """A sweep that parses nothing reports a clean tree.

    Every manifest this module reads must also be found by the classifier: if the two
    disagree, the classifier is reading past the real files and would stay green through
    any drift, which is the failure mode the `_SEMVER_IN_TEXT` probe was wrong in twice.
    """
    found = _version_bearing_files(PKG)
    missed = set(_SINGLE_FILE_MANIFESTS) - found
    assert not missed, (
        f"the sweep does not recognise the version in {sorted(missed)} — a format it "
        "cannot read is a format it cannot police"
    )
    assert "fedora/yazses.spec" in found, (
        "the RPM spec is the file the hand-written list omitted; if it is gone, say so "
        "here rather than leaving the check hollow"
    )
    assert set(_CHECKED_UNDER_A_DIFFERENT_RULE) <= found, (
        "a file is excused from this module's rule but the sweep no longer finds it at "
        "all — the excuse now hides nothing, or it hides everything"
    )


def test_a_new_manifest_is_uncovered_until_a_rule_reaches_it(tmp_path: Path) -> None:
    """Watch the guard fail, on a tree that is not this repository.

    Built as a fake `packaging/` so the demonstration costs the checkout nothing. The
    negative half matters as much as the positive one: a classifier that flagged every
    file would be turned off within a week.
    """
    (tmp_path / "opensuse").mkdir()
    (tmp_path / "opensuse" / "yazses.spec").write_text(
        "Name:           yazses\nVersion:        9.9.9\nRelease:        1\n", encoding="utf-8"
    )
    (tmp_path / "opensuse" / "install.ps1").write_text(
        "url64bit = 'https://github.com/MSKazemi/yazses/releases/download/v9.9.9/"
        "YazSes-9.9.9-windows-x64.exe'\n",
        encoding="utf-8",
    )
    # Neither of these pins a YazSes release: one is a dependency, one is prose.
    (tmp_path / "opensuse" / "requirements.txt").write_text("numpy==2.4.6\n", encoding="utf-8")
    (tmp_path / "opensuse" / "README.md").write_text(
        "Build it the way 0.4.0 was built.\n", encoding="utf-8"
    )

    assert _uncovered(tmp_path, covered=set()) == {
        "opensuse/yazses.spec",
        "opensuse/install.ps1",
    }
    assert _uncovered(tmp_path, covered={"opensuse/yazses.spec", "opensuse/install.ps1"}) == set()


def test_the_refresher_rewrites_every_manifest_this_module_checks() -> None:
    """Covered by a test and rewritten by the release script are two different things.

    A manifest that is checked but never regenerated makes every release red at the tag,
    and a red gate at the tag is one someone edits by hand and stops reading. The spec
    was neither: `scripts/refresh-package-manifests.py` did not name it, so four
    releases moved every other manifest and left it where it was.
    """
    mod = _refresh_module()
    written = {
        path.resolve()
        for path in vars(mod).values()
        if isinstance(path, Path) and path.suffix != ".py"
    }
    assert written, "no manifest paths found in the refresher — this check is reading nothing"
    missing = sorted(
        name for name in _SINGLE_FILE_MANIFESTS if (PKG / name).resolve() not in written
    )
    assert not missing, (
        f"{missing} are held to the release version by this module but "
        "scripts/refresh-package-manifests.py does not rewrite them, so the next "
        "release will leave them behind and fail this suite at the tag"
    )
