"""Packaging manifests must agree with the project about what it is.

Every channel restates the licence, the homepage and the download URL in its own
syntax, by hand, in a file nobody opens between releases. A wrong licence in a
published manifest is not a cosmetic error — it tells people what they are allowed
to do with the software — and the only reason it was noticed here is that a new
container image was written with the wrong one.

These are drift guards, not style checks: each one compares a hand-written string
against the single source of truth in `pyproject.toml`.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
LICENCE = PYPROJECT["project"]["license"]["text"]

SCOOP = ROOT / "packaging/scoop/yazses.json"
DOCKERFILE = ROOT / "packaging/docker/Dockerfile"
WINGET = ROOT / "packaging/winget/manifests/m/MSKazemi/YazSes"


def _latest_winget_dir() -> Path:
    versions = [p for p in WINGET.iterdir() if p.is_dir()]
    assert versions, "no winget manifests at all"
    return max(versions, key=lambda p: tuple(
        int(part) if part.isdigit() else -1 for part in p.name.replace("-", ".").split(".")
    ))


def test_the_project_states_one_licence():
    assert LICENCE, "pyproject has no licence to compare against"


def test_the_scoop_manifest_states_the_project_licence():
    manifest = json.loads(SCOOP.read_text(encoding="utf-8"))
    assert manifest["license"] == LICENCE


def test_the_container_image_labels_the_project_licence():
    """A published image carries this label into every registry that mirrors it."""
    source = DOCKERFILE.read_text(encoding="utf-8")
    assert f'org.opencontainers.image.licenses="{LICENCE}"' in source


def test_the_winget_manifest_states_the_project_licence():
    locale = _latest_winget_dir() / "MSKazemi.YazSes.locale.en-US.yaml"
    assert f"License: {LICENCE}" in locale.read_text(encoding="utf-8")


# ---- identity --------------------------------------------------------------


@pytest.mark.parametrize("path", [SCOOP, DOCKERFILE])
def test_packaging_points_at_the_canonical_repo(path):
    """One namespace. A manifest under another owner is an impostor, not a mirror."""
    source = path.read_text(encoding="utf-8")
    assert "github.com/MSKazemi/yazses" in source


def test_the_winget_identifier_is_the_current_one():
    """The old NovaFabric moniker is dead; nothing may reintroduce it."""
    for manifest in WINGET.rglob("*.yaml"):
        assert "NovaFabric" not in manifest.read_text(encoding="utf-8"), manifest


def test_no_packaging_file_still_names_the_retired_org():
    for path in (ROOT / "packaging").rglob("*"):
        if path.is_file() and path.suffix in {".json", ".yaml", ".yml", ".toml"}:
            assert "novafabric" not in path.read_text(encoding="utf-8", errors="ignore").lower(), path


# ---- the Scoop manifest has to be able to update itself --------------------


def test_scoop_can_check_for_new_versions():
    manifest = json.loads(SCOOP.read_text(encoding="utf-8"))
    assert manifest.get("checkver"), "without checkver the bucket never sees a release"


def test_scoop_autoupdate_can_produce_a_hash():
    """`autoupdate` rewrites the URL on a new release, but Scoop still needs the
    hash. With no `hash` block and no published `.sha256`, `scoop update` cannot
    complete — the manifest looks self-updating and silently is not.
    """
    manifest = json.loads(SCOOP.read_text(encoding="utf-8"))
    auto = manifest.get("autoupdate", {}).get("architecture", {}).get("64bit", {})
    assert "hash" in auto, "autoupdate has no way to obtain the new installer hash"


def test_scoop_autoupdate_url_matches_the_release_asset_pattern():
    """The templated URL must be the versioned URL with the version substituted."""
    manifest = json.loads(SCOOP.read_text(encoding="utf-8"))
    version = manifest["version"]
    current = manifest["architecture"]["64bit"]["url"]
    template = manifest["autoupdate"]["architecture"]["64bit"]["url"]
    assert template.replace("$version", version) == current


def test_the_autoupdate_hash_regex_actually_extracts_the_right_hash():
    """Simulate what Scoop does, against the real published SHA256SUMS format.

    Scoop substitutes `$version` and replaces `$sha256` with its hash pattern, then
    matches. A regex that compiles but never matches would leave every future
    release failing to update, which is invisible until someone runs `scoop update`.
    """
    import re

    manifest = json.loads(SCOOP.read_text(encoding="utf-8"))
    version = manifest["version"]
    spec = manifest["autoupdate"]["architecture"]["64bit"]["hash"]

    # A real SHA256SUMS.txt from a release, in the format the workflow writes.
    published = (
        "87ee4e8eb0f3f2dc36b15643bd2bc26227364aec27a269a9db4b3211b3a9a789  "
        f"yazses_{version}_amd64.deb\n"
        "f3b24712bf7b65f5ad03cbe12c98f3ef713184d9a16c841820814b9e33103858  "
        f"YazSes-{version}.dmg\n"
        "78d08aa50ea1456b450ab5305d6151778ece3cfe471f4bc04d24073a7534f775  "
        f"YazSes-{version}-windows-x64.exe\n"
    )

    pattern = spec["regex"].replace("$version", version).replace("$sha256", "([a-fA-F0-9]{64})")
    match = re.search(pattern, published)
    assert match, f"regex {pattern!r} matches nothing in a real SHA256SUMS.txt"
    assert match.group(1) == manifest["architecture"]["64bit"]["hash"], (
        "extracted a hash, but not the one for the Windows installer"
    )


def test_the_autoupdate_hash_url_points_at_a_file_releases_publish():
    manifest = json.loads(SCOOP.read_text(encoding="utf-8"))
    url = manifest["autoupdate"]["architecture"]["64bit"]["hash"]["url"]
    assert url.endswith("SHA256SUMS.txt")
    assert "$version" in url, "a fixed URL would pin every update to one release"
