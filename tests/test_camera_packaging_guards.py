"""Guards that read the packaging artefacts themselves (EYE-PERM-001, #414).

`tests/test_camera_packaging_matrix.py` holds each matrix row against its manifest. This file
closes the gaps that file leaves, each of which is a way the matrix and the shipped bytes
could part company while every existing assertion stayed green:

* **The macOS entitlement.** The signed build runs under the hardened runtime
  (`.github/workflows/build-macos.yml`: `--options runtime --entitlements ...`), where
  `NSCameraUsageDescription` alone is not enough -- `com.apple.security.device.camera` is
  also required, and without it the camera is refused with no prompt. Nothing read the
  entitlements file at all.
* **The reverse direction of R-21.** The old test only failed for a format that declares a
  camera capability it cannot use. Acceptance criterion 4 is the other direction: a format
  that *can* run a camera feature must carry the declaration. `contract_violations` checks
  both, and is shown here to object to a wrong matrix and to an empty one.
* **Which channel is which format.** Chocolatey, Scoop and WinGet were filed as "distribution
  packages that can add a runtime". All three install the frozen Inno Setup `.exe`, which
  cannot. The label is now *derived* from the manifests, not remembered.
* **The container image.** Not an install format a person dictates from, but it is a
  packaging artefact, and "camera not applicable" is a claim worth a test.

No camera, no build, no network.
"""

from __future__ import annotations

import ast
import json
import plistlib
import re
from pathlib import Path

import pytest

from yazses.cameraperm import PACKAGE_PROFILES, contract_violations, profile_for
from yazses.cameraperm.matrix import PackageProfile

ROOT = Path(__file__).resolve().parents[1]
ENTITLEMENTS = ROOT / "packaging" / "macos" / "entitlements.plist"
MACOS_SPEC = ROOT / "packaging" / "macos" / "yazses.spec"
BUILD_MACOS_WORKFLOW = ROOT / ".github" / "workflows" / "build-macos.yml"
SCOOP = ROOT / "packaging" / "scoop" / "yazses.json"
CHOCO = ROOT / "packaging" / "chocolatey" / "tools" / "chocolateyinstall.ps1"
WINGET_DIR = ROOT / "packaging" / "winget" / "manifests" / "m" / "MSKazemi" / "YazSes"
DOCKERFILE = ROOT / "packaging" / "docker" / "Dockerfile"

CAMERA_USAGE_KEY = "NSCameraUsageDescription"
CAMERA_ENTITLEMENT = "com.apple.security.device.camera"
CAMERA_EXTRAS = {"gaze", "all"}


def _profile(**kw) -> PackageProfile:
    base = dict(
        key="x", label="x", can_run_camera=False, can_add_runtime=False,
        declaration=None, declares_camera=False, remedy="r", why="w",
    )
    base.update(kw)
    return PackageProfile(**base)


# --------------------------------------------------------------------------- #
# The checker is shown to object -- on wrong input and on none at all
# --------------------------------------------------------------------------- #
def test_the_shipped_matrix_has_no_violations() -> None:
    assert contract_violations() == []


def test_an_empty_matrix_is_a_violation_not_a_pass() -> None:
    """A loop over zero rows is green. 'The matrix lost every row' must not read as fine."""
    problems = contract_violations(())
    assert problems and "no rows" in problems[0]


def test_a_camera_capable_format_that_forgot_its_declaration_is_caught() -> None:
    """Criterion 4. A frozen bundle that gained mediapipe but not its Info.plist string."""
    bad = _profile(
        key="macos-app", can_run_camera=True, declaration=CAMERA_USAGE_KEY,
        declares_camera=False,
    )
    assert any("not declared" in p for p in contract_violations((bad,)))


def test_a_declaration_nothing_can_use_is_caught() -> None:
    bad = _profile(key="snap", can_run_camera=False, declaration="camera plug",
                   declares_camera=True)
    assert any("no camera code can run" in p for p in contract_violations((bad,)))


def test_a_refusal_without_a_remedy_is_caught() -> None:
    assert any("remedy" in p for p in contract_violations((_profile(remedy=""),)))


def test_a_source_install_with_no_manifest_is_not_flagged_for_having_none() -> None:
    """The permissive row has nowhere to declare anything; flagging it would make the
    checker cry wolf on the one format that is supposed to work."""
    ok = _profile(key="source", can_run_camera=True, can_add_runtime=True, declaration=None)
    assert contract_violations((ok,)) == []


# --------------------------------------------------------------------------- #
# macOS: usage string AND entitlement, both or neither, and both tied to the matrix
# --------------------------------------------------------------------------- #
def _entitlement_keys(text: bytes) -> set[str]:
    data = plistlib.loads(text)
    assert isinstance(data, dict), "entitlements are a dict"
    return set(data)


def _spec_plist_keys() -> set[str]:
    tree = ast.parse(MACOS_SPEC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "info_plist":
            assert isinstance(node.value, ast.Dict)
            return {
                k.value for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            }
    raise AssertionError("no info_plist= in the macOS spec")


def _camera_declaration_problems(plist_keys: set[str], entitlement_keys: set[str]) -> list[str]:
    """Pure, so the odd inputs can be shown to it. Both or neither."""
    has_string = CAMERA_USAGE_KEY in plist_keys
    has_entitlement = CAMERA_ENTITLEMENT in entitlement_keys
    if has_string and not has_entitlement:
        return [f"{CAMERA_USAGE_KEY} without {CAMERA_ENTITLEMENT}: refused with no prompt "
                "under the hardened runtime"]
    if has_entitlement and not has_string:
        return [f"{CAMERA_ENTITLEMENT} without {CAMERA_USAGE_KEY}: macOS kills the process "
                "on first camera access"]
    return []


def test_the_camera_checker_handles_every_combination() -> None:
    assert _camera_declaration_problems(set(), set()) == []
    assert _camera_declaration_problems({CAMERA_USAGE_KEY}, {CAMERA_ENTITLEMENT}) == []
    assert _camera_declaration_problems({CAMERA_USAGE_KEY}, set())
    assert _camera_declaration_problems(set(), {CAMERA_ENTITLEMENT})


def test_the_entitlements_parser_is_not_blind() -> None:
    keys = _entitlement_keys(ENTITLEMENTS.read_bytes())
    assert "com.apple.security.device.audio-input" in keys, "parsed nothing; guard is blind"


def test_an_unreadable_entitlements_file_fails_instead_of_reporting_compliance() -> None:
    with pytest.raises(Exception):  # noqa: B017 - any parse error is the point
        _entitlement_keys(b"<plist><dict><key>unterminated")


def test_the_mac_bundle_declares_the_usage_string_and_the_entitlement_together() -> None:
    problems = _camera_declaration_problems(
        _spec_plist_keys(), _entitlement_keys(ENTITLEMENTS.read_bytes())
    )
    assert not problems, problems


def test_the_mac_entitlement_matches_the_matrix_row() -> None:
    row = profile_for("macos-app")
    declared = CAMERA_ENTITLEMENT in _entitlement_keys(ENTITLEMENTS.read_bytes())
    assert declared is row.declares_camera, (
        "packaging/macos/entitlements.plist and cameraperm/matrix.py disagree about "
        f"{CAMERA_ENTITLEMENT}"
    )
    assert CAMERA_ENTITLEMENT in (row.declaration or ""), (
        "the matrix row names only the usage string; the entitlement is also required"
    )


def test_the_signed_build_really_applies_the_entitlements_file() -> None:
    """The entitlement only matters because the signing step passes it. If the workflow
    stopped doing so, the file would be inert and the test above would guard nothing."""
    workflow = BUILD_MACOS_WORKFLOW.read_text(encoding="utf-8")
    assert "packaging/macos/entitlements.plist" in workflow
    assert "--options runtime" in workflow and "--entitlements" in workflow


# --------------------------------------------------------------------------- #
# Which channel installs which format -- derived, not remembered
# --------------------------------------------------------------------------- #
def _latest_winget_installer() -> str:
    versions = sorted(
        (d for d in WINGET_DIR.iterdir() if d.is_dir()),
        key=lambda d: tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.-]", d.name)),
    )
    assert versions, "no winget manifests found; the channel check is blind"
    files = list(versions[-1].glob("*.installer.yaml"))
    assert files, f"{versions[-1].name} has no installer manifest"
    return files[0].read_text(encoding="utf-8")


def test_chocolatey_scoop_and_winget_all_install_the_frozen_exe() -> None:
    """If any of these moves to a pip-based install, it stops being the windows-exe row."""
    scoop = json.loads(SCOOP.read_text(encoding="utf-8"))
    assert scoop.get("innosetup") is True
    assert all(".exe" in a["url"] for a in scoop["architecture"].values())
    choco = CHOCO.read_text(encoding="utf-8")
    assert re.search(r"fileType\s*=\s*'exe'", choco)
    assert re.search(r"InstallerType:\s*inno", _latest_winget_installer())


def test_those_channels_are_filed_under_the_windows_exe_row_and_not_the_runtime_row() -> None:
    exe, distro = profile_for("windows-exe"), profile_for("distro")
    for channel in ("Chocolatey", "Scoop", "WinGet"):
        assert channel in exe.label, f"{channel} installs the .exe; the row must say so"
        assert channel not in distro.label, (
            f"{channel} is listed as able to add a camera runtime, but it installs a "
            "frozen bundle that cannot"
        )
    assert not exe.can_run_camera and distro.can_run_camera


def test_homebrew_is_only_the_cask() -> None:
    """The formula files are an abandoned Rust v1.0 distribution (their own headers say so);
    the one publishable Homebrew artefact is the .dmg cask, i.e. the macos-app row."""
    assert "Homebrew" not in profile_for("distro").label
    assert "Homebrew cask" in profile_for("macos-app").label
    cask = (ROOT / "packaging" / "homebrew" / "yazses.rb").read_text(encoding="utf-8")
    assert 'cask "yazses"' in cask
    assert ".dmg" in cask


# --------------------------------------------------------------------------- #
# The container image
# --------------------------------------------------------------------------- #
def test_the_container_image_installs_no_camera_extra() -> None:
    """File transcription only, no device passthrough: camera is not applicable there.
    If an image ever ships `gaze`, it needs a `--device /dev/video*` story first."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    installs = re.findall(r'pip install "yazses\[([^\]]+)\]', text)
    assert installs, "no `pip install yazses[...]` found; the scan is blind"
    for group in installs:
        extras = {e.strip() for e in group.split(",")}
        assert not (extras & CAMERA_EXTRAS), f"the image installs {sorted(extras)}"
    assert "mediapipe" not in text and "opencv" not in text


def test_every_matrix_row_is_covered_by_a_manifest_test_or_is_a_pure_runtime_row() -> None:
    """A new row with no artefact to read would make the table decorative."""
    manifest_checked = {"macos-app", "windows-exe", "windows-msix", "snap", "flatpak"}
    runtime_only = {"source", "distro"}
    assert {p.key for p in PACKAGE_PROFILES} == manifest_checked | runtime_only
