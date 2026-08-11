"""The generated CycloneDX SBOM.

The SBOM exists so someone whose organisation requires a dependency inventory can install
YazSes without doing that work by hand. That only holds if the committed file is current,
so the staleness check is the point of this module -- a stale SBOM is worse than none,
because it is trusted.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SBOM = REPO_ROOT / "sbom.cdx.json"


def _load_generator():
    """Import the hyphenated script by path (it is not an importable module name)."""
    spec = importlib.util.spec_from_file_location(
        "gen_sbom", REPO_ROOT / "scripts" / "gen-sbom.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_sbom"] = module
    spec.loader.exec_module(module)
    return module


def test_committed_sbom_matches_the_lock_file() -> None:
    """If uv.lock moved and the SBOM did not, this fails -- which is the whole point."""
    gen = _load_generator()
    expected = gen.render(
        gen.build_sbom((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"), gen._project_version())
    )
    assert SBOM.read_text(encoding="utf-8") == expected, (
        "sbom.cdx.json is out of date — run `python scripts/gen-sbom.py`"
    )


def test_sbom_is_well_formed_cyclonedx() -> None:
    doc = json.loads(SBOM.read_text(encoding="utf-8"))
    assert doc["bomFormat"] == "CycloneDX"
    assert doc["specVersion"] == "1.5"
    subject = doc["metadata"]["component"]
    assert subject["name"] == "yazses"
    assert subject["licenses"][0]["license"]["id"] == "Apache-2.0"

    components = doc["components"]
    assert len(components) > 100, "suspiciously few dependencies — did the lock parse?"
    for c in components:
        assert c["name"] and c["version"]
        assert c["purl"].startswith("pkg:pypi/")


def test_the_subject_is_not_listed_as_its_own_dependency() -> None:
    doc = json.loads(SBOM.read_text(encoding="utf-8"))
    assert not [c for c in doc["components"] if c["name"] == "yazses"]


def test_output_is_reproducible() -> None:
    """No timestamps or serial numbers: a diffable SBOM is a reviewable one."""
    gen = _load_generator()
    lock = (REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    first = gen.render(gen.build_sbom(lock, "1.2.3"))
    second = gen.render(gen.build_sbom(lock, "1.2.3"))
    assert first == second
    assert "timestamp" not in first
    assert "serialNumber" not in first


def test_declared_hashes_are_real_sha256() -> None:
    doc = json.loads(SBOM.read_text(encoding="utf-8"))
    hashed = [c for c in doc["components"] if "hashes" in c]
    assert hashed, "no component carried a digest — the sdist hashes stopped parsing"
    for c in hashed:
        for h in c["hashes"]:
            assert h["alg"] == "SHA-256"
            assert len(h["content"]) == 64, f"{c['name']}: not a sha256 digest"
            int(h["content"], 16)  # raises if it is not hex


@pytest.mark.parametrize("name,version,expected", [
    ("faster-whisper", "1.2.1", "pkg:pypi/faster-whisper@1.2.1"),
    ("PySide6_Addons", "6.11.1", "pkg:pypi/pyside6-addons@6.11.1"),
])
def test_purl_normalisation(name: str, version: str, expected: str) -> None:
    """purl requires the lowercase, hyphenated PyPI name, not the raw distribution name."""
    gen = _load_generator()
    assert gen._purl(name, version) == expected
