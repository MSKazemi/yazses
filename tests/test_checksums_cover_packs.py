"""SHA256SUMS.txt and the release audits must cover the ADR-028 add-on packs.

The installed app cross-checks a pack against the release's SHA256SUMS.txt (ADR-028
§3.2), so a pack the checksum job does not hash is a pack nobody can install -- and
nothing would turn red. ADR-028 §7 names the hand-written lists that must learn the new
asset kinds: checksums.yml's download patterns, its file glob and its "prove" regex, and
`scripts/verify-release-assets.py`'s ARTIFACT_SUFFIXES.

The expected names are DERIVED from `scripts/build-packs.py`, never written here, so a
renamed asset fails this test instead of silently leaving the lists behind.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML ships with the docs group")

ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS = ROOT / ".github" / "workflows" / "checksums.yml"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def names() -> list[str]:
    bp = _load("build_packs_for_checksums", ROOT / "scripts" / "build-packs.py")
    out = [
        bp.pack_asset_name("2.44.0", "windows", "x64", "parakeet"),
        bp.pack_asset_name("2.44.0", "windows", "x64", "diarization"),
        bp.index_asset_name("2.44.0", "windows", "x64"),
    ]
    assert out, "guard the guard: no pack asset names were derived"
    return out


def _step(prefix: str) -> str:
    doc = yaml.safe_load(CHECKSUMS.read_text(encoding="utf-8"))
    hits = [s for s in doc["jobs"]["checksums"]["steps"] if s.get("name", "").startswith(prefix)]
    assert len(hits) == 1
    return hits[0]["run"]


def test_the_download_patterns_match_every_pack_asset(names):
    run = _step("Download assets and generate")
    line = next(ln for ln in run.splitlines() if ln.strip().startswith("for pat in"))
    patterns = re.findall(r"'([^']+)'", line)
    assert patterns
    for n in names:
        assert any(fnmatch.fnmatchcase(n, p) for p in patterns), (n, patterns)


def test_the_hashed_file_glob_matches_every_pack_asset(names):
    run = _step("Download assets and generate")
    line = next(ln for ln in run.splitlines() if ln.strip().startswith("files=("))
    globs = line.split("(", 1)[1].rsplit(")", 1)[0].split()
    for n in names:
        assert any(fnmatch.fnmatchcase(n, g) for g in globs), (n, globs)


def test_the_hashed_glob_cannot_pick_up_the_checksum_file_itself():
    run = _step("Download assets and generate")
    line = next(ln for ln in run.splitlines() if ln.strip().startswith("files=("))
    globs = line.split("(", 1)[1].rsplit(")", 1)[0].split()
    assert not any(fnmatch.fnmatchcase("SHA256SUMS.txt", g) for g in globs)


def test_the_prove_regex_matches_every_pack_asset(names):
    run = _step("Prove SHA256SUMS.txt describes")
    m = re.search(r'test\("((?:[^"\\]|\\.)*)"\)', run)
    assert m, "the prove step no longer selects artifacts with jq test(...)"
    # The YAML block keeps the jq string literally; json-decode it the way jq would.
    regex = json.loads(f'"{m.group(1)}"')
    for n in names:
        assert re.search(regex, n), (n, regex)
    for existing in ("YazSes-2.44.0-windows-x64.exe", "yazses_2.44.0_amd64.deb"):
        assert re.search(regex, existing)
    assert not re.search(regex, "SHA256SUMS.txt")


def test_verify_release_assets_checks_every_pack_asset(names):
    mod = _load("verify_release_assets_for_packs", ROOT / "scripts" / "verify-release-assets.py")
    for n in names:
        assert n.endswith(mod.ARTIFACT_SUFFIXES), (n, mod.ARTIFACT_SUFFIXES)


def test_verify_provenance_requires_an_attestation_for_every_pack_asset(names):
    """build-windows.yml attests the packs with a multi-line `subject-path: |`."""
    mod = _load("verify_provenance_for_packs", ROOT / "scripts" / "verify-provenance.py")
    suffixes = mod.attested_suffixes()
    for n in names:
        assert Path(n).suffix in suffixes, (n, sorted(suffixes))
