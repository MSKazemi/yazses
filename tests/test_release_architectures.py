"""Every architecture a channel claims must actually be built and shipped.

The pattern this guards has now bitten twice. `snap/snapcraft.yaml` declared
`platforms: [amd64, arm64]` while the only publisher to `stable` ran on one
amd64 runner (#267). `scripts/update-apt-repo.sh` has always declared
`Architectures "amd64 arm64 all"` and indexes whatever is in the pool — but the
release workflow built a single amd64 `.deb`, so the arm64 slot the repo
advertised was never filled and an arm64 machine had no APT package at all.

In both cases the declaration and the thing that fulfils it lived in different
files with nothing tying them together, so the gap was invisible from either
side. These tests are that tie for the Debian/APT path; `test_snap_publish_matrix`
is the equivalent for the snap.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
APT = ROOT / ".github" / "workflows" / "apt-repo.yml"
APT_SCRIPT = ROOT / "scripts" / "update-apt-repo.sh"

# Native runner per architecture. snapcraft, dpkg and PyInstaller all build for
# the host, so the runner label *is* the architecture selection.
EXPECTED_RUNNERS = {"amd64": "ubuntu-latest", "arm64": "ubuntu-24.04-arm"}


def _release_text() -> str:
    return RELEASE.read_text(encoding="utf-8")


def _deb_matrix_arches() -> set[str]:
    """Architectures the build-deb job actually produces a job for."""
    text = _release_text()
    start = text.index("build-deb:")
    end = text.index("release-linux:")
    return set(re.findall(r"^\s*-\s*arch:\s*([A-Za-z0-9_-]+)\s*$", text[start:end], re.M))


def _apt_declared_arches() -> set[str]:
    """Architectures the APT Release file advertises to apt clients."""
    match = re.search(r'Architectures\s+"([^"]+)"', APT_SCRIPT.read_text(encoding="utf-8"))
    assert match, "update-apt-repo.sh no longer declares Architectures"
    # "all" is the arch-independent slot, not a machine architecture.
    return {a for a in match.group(1).split() if a != "all"}


def test_apt_repo_still_declares_both_architectures() -> None:
    assert _apt_declared_arches() == {"amd64", "arm64"}


def test_every_apt_declared_architecture_is_actually_built() -> None:
    """The regression: the APT Release file advertised arm64 and nothing ever
    built an arm64 .deb, so apt on arm64 found the repo and no package."""
    missing = _apt_declared_arches() - _deb_matrix_arches()
    assert not missing, (
        f"update-apt-repo.sh advertises {sorted(missing)} to apt clients, but "
        f"release.yml builds no .deb for it. An arm64 user adds the repo and finds "
        f"no package."
    )


def test_no_deb_built_for_an_unadvertised_architecture() -> None:
    extra = _deb_matrix_arches() - _apt_declared_arches()
    assert not extra, (
        f"release.yml builds {sorted(extra)} .debs that update-apt-repo.sh does not "
        f"advertise — apt clients on that arch would never see them"
    )


@pytest.mark.parametrize("arch", sorted(EXPECTED_RUNNERS))
def test_each_deb_arch_uses_a_native_runner(arch: str) -> None:
    text = _release_text()
    block = re.search(rf"-\s*arch:\s*{arch}\s*\n\s*runner:\s*(\S+)", text)
    assert block, f"no build-deb matrix entry for {arch}"
    assert block.group(1) == EXPECTED_RUNNERS[arch], (
        f"{arch} .deb builds on {block.group(1)}, expected {EXPECTED_RUNNERS[arch]} — "
        f"dpkg reports the HOST architecture, so a wrong label silently produces a "
        f"second {block.group(1)} package"
    )


def test_deb_matrix_does_not_fail_fast() -> None:
    """One arch failing must not cancel the other and ship a release that
    silently lost an architecture."""
    text = _release_text()
    block = text[text.index("build-deb:") : text.index("release-linux:")]
    assert re.search(r"fail-fast:\s*false", block), (
        "the build-deb matrix must set fail-fast: false"
    )


def test_deb_artifacts_are_arch_qualified() -> None:
    """Two matrix jobs uploading one artifact name collide and the second fails."""
    text = _release_text()
    block = text[text.index("build-deb:") : text.index("release-linux:")]
    upload = re.search(r"name:\s*(deb-package\S*.*)$", block, re.M)
    assert upload, "the build-deb artifact upload step is gone"
    assert "matrix.arch" in upload.group(1), (
        f"artifact name {upload.group(1)!r} is not arch-qualified"
    )


def test_release_job_collects_every_architecture() -> None:
    """The GitHub Release must attach all arches, and must be created once —
    two matrix jobs both calling action-gh-release would race on one tag."""
    text = _release_text()
    block = text[text.index("release-linux:") :]
    assert re.search(r"needs:\s*build-deb", block), (
        "release-linux must depend on build-deb, or it attaches nothing"
    )
    assert re.search(r"pattern:\s*deb-package-\*", block), (
        "release-linux must download every deb-package-* artifact, not a single name"
    )
    assert re.search(r"merge-multiple:\s*true", block), (
        "without merge-multiple the artifacts land in per-artifact subdirectories "
        "and the *.deb glob attaches nothing"
    )


def test_apt_workflow_ingests_every_architecture() -> None:
    """The APT repo is what `apt install yazses` actually reads; if it only
    downloads amd64, building arm64 changes nothing for users."""
    text = APT.read_text(encoding="utf-8")
    assert re.search(r"pattern:\s*deb-package-\*", text), (
        "apt-repo.yml still downloads a single 'deb-package' artifact — the arm64 "
        ".deb would be built and then dropped on the floor"
    )
    assert re.search(r"merge-multiple:\s*true", text), (
        "apt-repo.yml needs merge-multiple so every arch lands in one directory"
    )


def test_nothing_downstream_of_the_download_caps_the_deb_count() -> None:
    """Downloading every arch is useless if the next step rejects more than one.

    This is what broke the APT channel at v2.21.0. `apt-repo.yml` gained the
    multi-arch download and a comment saying the script "indexes whatever lands in
    the pool", but the guard immediately after it still read `-eq 1` and the script
    still took a single `<path-to.deb>`. The release built amd64 **and** arm64, and
    the job died with "Expected 1 .deb, got 2" — so no APT user got 2.21.0 at all,
    on either architecture.

    The download and its consumer live in different files, which is the same
    invisible-from-either-side shape this module already guards for the *declared*
    architectures.
    """
    arches = _deb_matrix_arches()
    assert len(arches) > 1, "this guard assumes a multi-arch build; the matrix shrank"

    for path in (APT, APT_SCRIPT):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if ".deb" not in line and "debs" not in line:
                continue
            assert not re.search(r"\$\{#debs\[@\]\}\s*-eq\s*1", line), (
                f"{path.name} rejects more than one .deb, but the release builds "
                f"{sorted(arches)} — every multi-arch release will fail here:\n"
                f"    {line.strip()}"
            )


def test_the_deb_is_arch_independent_so_the_matrix_ships_one_package() -> None:
    """`build-deb.sh` names the file per runner but stamps `Architecture: all`.

    Both matrix jobs therefore emit the *same package* to apt — v2.21.0's two
    files were `yazses 2.21.0 all` twice, differing only in filename. Publishing
    both puts two entries with one Package/Version into the index, so
    `update-apt-repo.sh` de-duplicates on Package+Version+Architecture rather than
    trusting the filename.

    Pinned because the filename is the misleading part: `yazses_2.21.0_arm64.deb`
    reads like an arm64 build and is not one. If the .deb ever gains a native
    component, `Architecture: all` becomes wrong and this test is where that
    surfaces — the dedupe would then silently drop a real second architecture.
    """
    build = (ROOT / "scripts" / "build-deb.sh").read_text(encoding="utf-8")
    assert re.search(r"^Architecture:\s*all\s*$", build, re.M), (
        "build-deb.sh no longer declares `Architecture: all` — if the .deb is now "
        "arch-specific, update-apt-repo.sh's Package+Version+Architecture dedupe "
        "will collapse two genuinely different packages into one"
    )
    script = APT_SCRIPT.read_text(encoding="utf-8")
    assert "${Architecture}" in script, (
        "update-apt-repo.sh no longer reads the real Architecture field; it would "
        "be back to trusting the filename, which says amd64/arm64 for an `all` package"
    )
    assert r"${Architecture}\n" in script, (
        "the showformat lost its trailing newline — `read` then hits EOF, returns "
        "non-zero, and `set -e` kills the publish with no message"
    )
