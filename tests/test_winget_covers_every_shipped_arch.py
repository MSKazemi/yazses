"""winget must offer every Windows architecture the release actually ships.

The renderer took the x64 asset and nothing else, while Scoop's took both. So a
Windows-on-ARM machine could install YazSes from the Scoop bucket and **not** from
winget — the channel that is built into Windows 10/11, needs no setup, and is
therefore the one an ARM laptop owner is most likely to reach for. The release has
carried `YazSes-<version>-windows-arm64.exe` since v2.22.0.

The entry stays conditional: the arm64 build leg is `continue-on-error`, so a
release may legitimately ship x64 alone, and an arm64 entry left pointing at the
previous version's URL fails its hash check at *install* time — on the user's
machine, long after anyone could notice.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh-package-manifests.py"


def _module():
    spec = importlib.util.spec_from_file_location("refresh_pkg_manifests", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Registered before exec: the script's dataclasses use PEP 563 annotations and
    # `dataclasses` resolves them through `sys.modules[__module__]`, which is None
    # for a module that was built but never registered.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mod():
    return _module()


def _asset(mod, name: str, sha: str):
    return mod.Asset(
        name=name,
        url=f"https://github.com/MSKazemi/yazses/releases/download/v9.9.9/{name}",
        size=1,
        sha256=sha,
    )


_X64 = "9d07af8615f554de3ee641fc4ef611378bbbe7f2f4ad382b5eb8786df37a876c"
_ARM = "de85ff3e98db88bca8f2a2d69a09d317a2680d79d03504e76ede7233e7c8fc64"


def test_an_arm64_release_asset_reaches_the_winget_manifest(mod) -> None:
    files = mod.render_winget(
        "9.9.9",
        _asset(mod, "YazSes-9.9.9-windows-x64.exe", _X64),
        "2026-08-27",
        _asset(mod, "YazSes-9.9.9-windows-arm64.exe", _ARM),
    )
    installer = files["MSKazemi.YazSes.installer.yaml"]
    assert "Architecture: arm64" in installer
    assert "YazSes-9.9.9-windows-arm64.exe" in installer
    assert _ARM.upper() in installer


def test_x64_is_still_first_and_present(mod) -> None:
    """Order matters only for readability, but the x64 entry must never be lost."""
    files = mod.render_winget(
        "9.9.9",
        _asset(mod, "YazSes-9.9.9-windows-x64.exe", _X64),
        "2026-08-27",
        _asset(mod, "YazSes-9.9.9-windows-arm64.exe", _ARM),
    )
    installer = files["MSKazemi.YazSes.installer.yaml"]
    assert installer.index("Architecture: x64") < installer.index("Architecture: arm64")
    assert _X64.upper() in installer


def test_a_release_without_an_arm64_build_gets_no_arm64_entry(mod) -> None:
    """The arm64 leg is continue-on-error; a guessed URL fails on the user's machine."""
    files = mod.render_winget(
        "9.9.9", _asset(mod, "YazSes-9.9.9-windows-x64.exe", _X64), "2026-08-27", None
    )
    installer = files["MSKazemi.YazSes.installer.yaml"]
    assert "arm64" not in installer
    assert "Architecture: x64" in installer


def test_the_yaml_stays_parseable_with_two_installers(mod) -> None:
    yaml = pytest.importorskip("yaml")
    files = mod.render_winget(
        "9.9.9",
        _asset(mod, "YazSes-9.9.9-windows-x64.exe", _X64),
        "2026-08-27",
        _asset(mod, "YazSes-9.9.9-windows-arm64.exe", _ARM),
    )
    data = yaml.safe_load(files["MSKazemi.YazSes.installer.yaml"])
    assert [i["Architecture"] for i in data["Installers"]] == ["x64", "arm64"]
    assert data["PackageIdentifier"] == "MSKazemi.YazSes"
    assert data["InstallerType"] == "inno"


def test_scoop_and_winget_agree_on_which_arches_ship() -> None:
    """The two Windows manifests in this repo must not disagree about the machine.

    They drifted silently: Scoop offered arm64 and winget did not, so the answer to
    "does YazSes run on my ARM laptop?" depended on which installer you asked.
    """
    import json
    import re

    bucket = json.loads((ROOT / "bucket" / "yazses.json").read_text(encoding="utf-8"))
    scoop_arches = set(bucket.get("architecture", {}))
    version = bucket["version"]

    manifest = (
        ROOT / "packaging" / "winget" / "manifests" / "m" / "MSKazemi" / "YazSes"
        / version / "MSKazemi.YazSes.installer.yaml"
    )
    if not manifest.exists():  # pragma: no cover - only before the post-tag refresh
        pytest.skip(f"no winget manifest for {version} yet")
    winget_arches = set(re.findall(r"Architecture:\s*(\S+)", manifest.read_text(encoding="utf-8")))

    translate = {"64bit": "x64", "arm64": "arm64"}
    assert {translate[a] for a in scoop_arches} == winget_arches, (
        f"Scoop offers {sorted(scoop_arches)} and winget offers {sorted(winget_arches)} "
        f"for {version} — the same release, two different answers about the machine"
    )
