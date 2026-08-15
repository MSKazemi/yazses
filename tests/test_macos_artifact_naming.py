"""The macOS artifact name is agreed on by four places that never see each other.

`scripts/build-macos.sh` produces it, the Homebrew cask downloads it,
`scripts/refresh-package-manifests.py` hashes it, and the release notes tell a user to
look for it. Nothing connected them, and the name just changed: ADR-017 added an Intel
build leg, and `YazSes-<version>.dmg` had to become `YazSes-<version>-macos-<arch>.dmg`
because a name that says nothing about architecture is a large part of why an
Apple-silicon-only bundle went unnoticed for months.

Renaming it is exactly the change that breaks a cask silently. The URL still resolves —
to a 404 — and the first thing a new macOS user sees is a failed download that looks
like the project is broken. The repository already learned this once: the cask sat at
v2.17.0 while v2.18.0 was current, and the comment above it says a wrong hash is worse
than no cask.

So the four are pinned to each other here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
BUILD_SH = ROOT / "scripts/build-macos.sh"
CASK = ROOT / "packaging/homebrew/yazses.rb"
REFRESH = ROOT / "scripts/refresh-package-manifests.py"
WORKFLOW = ROOT / ".github/workflows/build-macos.yml"

#: What the build script emits, as a shape rather than a literal.
_EXPECTED_SHAPE = "YazSes-${VERSION}-macos-${ARCH}.dmg"


def test_the_build_script_puts_the_architecture_in_the_name():
    text = BUILD_SH.read_text(encoding="utf-8")
    assert _EXPECTED_SHAPE in text, (
        f"build-macos.sh no longer emits {_EXPECTED_SHAPE}; every consumer below "
        f"assumes it does"
    )


def test_the_architecture_is_derived_from_the_host_not_passed_in():
    """PyInstaller does not cross-compile, so the host *is* the target. A flag and a
    runner label are two things that can disagree, and the failure is a correctly
    built binary wearing the wrong name."""
    text = BUILD_SH.read_text(encoding="utf-8")
    assert 'ARCH="$(uname -m)"' in text, (
        "the architecture is no longer derived from the build host"
    )


def test_the_cask_url_matches_what_the_build_produces():
    """The check that would have caught this rename breaking the cask."""
    cask = CASK.read_text(encoding="utf-8")
    url = re.search(r'^\s*url "([^"]+)"', cask, re.M)
    assert url, "no url in the cask"
    assert "-macos-arm64.dmg" in url.group(1), (
        f"the cask downloads {url.group(1)!r}, which is not a name build-macos.sh "
        f"produces any more. It would 404, and a failed download is the first thing "
        f"a new macOS user would see."
    )
    assert "#{version}" in url.group(1), "the cask url no longer interpolates the version"


def test_the_manifest_refresher_looks_for_the_same_asset():
    text = REFRESH.read_text(encoding="utf-8")
    assert 'f"YazSes-{version}-macos-arm64.dmg"' in text, (
        "refresh-package-manifests.py looks for an asset name the release does not "
        "contain; it would fail with 'release has no asset named …' at the worst moment"
    )


def test_the_cask_tracks_one_architecture_and_says_which():
    """It is arm64-only on purpose while the Intel leg is unproven. A cask entry whose
    hash was guessed is worse than no entry."""
    cask = CASK.read_text(encoding="utf-8")
    assert "Intel Mac" in cask, "the cask no longer tells Intel users what to do instead"
    assert cask.count("sha256") >= 1


# ---- the workflow that produces both -------------------------------------


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_both_architectures_are_built(workflow):
    legs = workflow["jobs"]["build"]["strategy"]["matrix"]["include"]
    arches = {leg["arch"] for leg in legs}
    assert arches == {"arm64", "x86_64"}, f"expected both architectures, got {arches}"


def test_the_intel_leg_cannot_fail_a_release(workflow):
    """`macos-15-intel` has never run here. A brand-new cross-architecture build must
    not be able to fail a release the arm64 build completed fine — the same rule the
    Windows ARM leg follows."""
    legs = {leg["arch"]: leg for leg in workflow["jobs"]["build"]["strategy"]["matrix"]["include"]}
    assert legs["x86_64"]["experimental"] is True, "the Intel leg is not advisory"
    assert legs["arm64"]["experimental"] is False, "the primary build must be blocking"
    assert "continue-on-error" in WORKFLOW.read_text(encoding="utf-8")


def test_the_two_legs_do_not_collide_on_artifact_names(workflow):
    """Both legs upload to the same run. Without the architecture in the artifact name
    the second would overwrite the first, and the release would quietly carry one .dmg
    labelled as two."""
    text = WORKFLOW.read_text(encoding="utf-8")
    upload = re.search(r"name: yazses-macos-[^\n]*", text)
    assert upload, "no macOS artifact upload found"
    assert "matrix.arch" in upload.group(0), (
        f"the upload name {upload.group(0)!r} does not vary by architecture"
    )
    bundle = re.search(r'cp "\$\{\{ steps\.attest[^\n]*', text)
    assert bundle and "matrix.arch" in bundle.group(0), (
        "the provenance bundle name does not vary by architecture, so one leg would "
        "overwrite the other's attestation"
    )


def test_the_runner_label_is_the_one_that_still_exists(workflow):
    """`macos-13` was retired on 2025-12-04 (ADR-017). Writing it does not buy an Intel
    build; it fails."""
    legs = {leg["arch"]: leg for leg in workflow["jobs"]["build"]["strategy"]["matrix"]["include"]}
    assert legs["x86_64"]["runner"] == "macos-15-intel", (
        f"Intel leg runs on {legs['x86_64']['runner']!r}; macos-13 is retired and "
        f"macos-15-intel is the last x86_64 image Actions offers (until August 2027)"
    )
