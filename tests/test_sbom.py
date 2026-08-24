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


# --- component scope ---------------------------------------------------------------
#
# `uv.lock` is the development closure. Emitted without scopes, CycloneDX reads every
# component as `required`, so the SBOM claimed a user installing YazSes receives pytest,
# mypy, ruff, mkdocs and jiwer -- 283 components for 16 declared runtime dependencies.
# A reviewer feeding that to a vulnerability scanner gets advisories against a toolchain
# nobody but the maintainer runs, and no way to tell which ones are real.

CYCLONEDX_SCOPES = {"required", "optional", "excluded"}


def _components() -> list[dict[str, str]]:
    return json.loads(SBOM.read_text(encoding="utf-8"))["components"]


def _scopes() -> dict[str, set[str]]:
    """Name -> every scope emitted under it.

    A set, not a string, because a name is not unique: `scipy` is locked twice, for two
    Python versions. Keying by name and taking the last write silently dropped one
    component -- which is how the first draft of the count guard below "passed" against a
    number one lower than the file's own.
    """
    scopes: dict[str, set[str]] = {}
    for c in _components():
        scopes.setdefault(c["name"], set()).add(c.get("scope", ""))
    return scopes


def _declared() -> dict[str, list[str]]:
    """`[project]` dependencies and extras, read from pyproject rather than listed here."""
    import re
    import tomllib

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    strip = lambda spec: re.split(r"[\[<>=!~;\s]", spec, maxsplit=1)[0].strip().lower()  # noqa: E731
    return {
        "base": [strip(d) for d in project["dependencies"]],
        "extras": [strip(d) for v in project.get("optional-dependencies", {}).values() for d in v],
    }


def test_every_component_declares_a_scope() -> None:
    """An absent scope is not neutral -- CycloneDX defaults it to `required`."""
    missing = sorted(c["name"] for c in _components() if not c.get("scope"))
    assert not missing, f"unclassified, so silently declared required: {missing}"


def test_the_scope_vocabulary_is_cyclonedx_and_all_three_are_used() -> None:
    values = {c.get("scope", "") for c in _components()}
    assert values <= CYCLONEDX_SCOPES, f"not a CycloneDX scope: {values - CYCLONEDX_SCOPES}"
    assert values == CYCLONEDX_SCOPES, (
        f"only {sorted(values)} used — a classification collapsed to one bucket"
    )


def test_every_declared_runtime_dependency_is_required() -> None:
    """Derived from pyproject: a new runtime dependency is covered the day it is added."""
    scopes = _scopes()
    wrong = {
        n: sorted(scopes.get(n, {"(absent)"}))
        for n in _declared()["base"]
        if scopes.get(n) != {"required"}
    }
    assert not wrong, f"declared in [project.dependencies] but not scoped required: {wrong}"


def test_no_extra_is_demoted_to_the_maintainer_toolchain() -> None:
    """An opt-in feature's dependency ships to users who enable it; `excluded` denies that."""
    scopes = _scopes()
    wrong = {n: sorted(scopes[n]) for n in _declared()["extras"] if "excluded" in scopes.get(n, set())}
    assert not wrong, f"shipped as an extra but declared excluded: {wrong}"


def test_the_toolchain_is_not_declared_as_shipped() -> None:
    """The concrete over-declaration this scope field was added to end."""
    scopes = _scopes()
    for tool in ("pytest", "mypy", "ruff", "mkdocs", "jiwer", "pytest-mock"):
        assert scopes.get(tool) == {"excluded"}, f"{tool}: {sorted(scopes.get(tool, []))}, not excluded"


def test_a_package_reached_only_through_a_dependencys_extra_is_classified() -> None:
    """`cairosvg` is reachable only as `mkdocs-material[imaging]`.

    Two separate walk bugs stranded it: the root spells the request `extras` while a
    package spells it `extra`, and `pkg[extra]` installs `pkg` as well as the extra.
    Stranded means scopeless means required -- an image toolchain declared as a runtime
    dependency of a dictation daemon.
    """
    assert _scopes().get("cairosvg") == {"excluded"}


def test_scope_is_derived_from_the_lock_not_from_a_list(tmp_path: Path) -> None:
    """A synthetic lock: precedence, both extras spellings, and the base-plus-extra edge."""
    gen = _load_generator()
    lock = {
        "package": [
            {
                "name": "yazses",
                "metadata": {
                    "requires-dist": [
                        {"name": "runtime-dep"},
                        {"name": "shared"},
                        {"name": "heavy", "marker": "extra == 'gpu'"},
                    ],
                    "requires-dev": {"dev": [{"name": "tool", "extras": ["imaging"]}]},
                },
            },
            {"name": "runtime-dep", "dependencies": [{"name": "transitive"}]},
            {"name": "transitive"},
            {"name": "shared"},
            {"name": "heavy", "dependencies": [{"name": "shared"}, {"name": "gpu-only"}]},
            {"name": "gpu-only"},
            {
                "name": "tool",
                "dependencies": [{"name": "tool-base"}],
                "optional-dependencies": {"imaging": [{"name": "renderer", "extra": ["svg"]}]},
            },
            {"name": "tool-base"},
            {"name": "renderer", "optional-dependencies": {"svg": [{"name": "svg-backend"}]}},
            {"name": "svg-backend"},
        ]
    }
    assert gen.classify_scopes(lock) == {
        "runtime-dep": "required",
        "transitive": "required",
        "shared": "required",  # reachable both ways; the strongest claim wins
        "heavy": "optional",
        "gpu-only": "optional",
        "tool": "excluded",
        "tool-base": "excluded",  # `tool[imaging]` installs plain `tool` too
        "renderer": "excluded",
        "svg-backend": "excluded",  # an extra requested by a dependency, spelled `extra`
    }


def test_the_privacy_statement_scope_counts_match_the_sbom() -> None:
    """Three numbers in a user-facing document, next to a file that changes every release.

    A published count that quietly drifts is worse than no count: the privacy statement is
    read precisely by people who are checking. The table is parsed rather than trusted, and
    a missing row fails here rather than passing on an empty match.
    """
    import re
    from collections import Counter

    text = (REPO_ROOT / "docs" / "privacy-statement.md").read_text(encoding="utf-8")
    documented = {
        scope: int(count)
        for scope, count in re.findall(r"^\| `(required|optional|excluded)` \| (\d+) \|", text, re.M)
    }
    assert set(documented) == CYCLONEDX_SCOPES, (
        f"the scope table lost a row — parsed {sorted(documented)}"
    )
    assert documented == dict(Counter(c["scope"] for c in _components())), (
        "docs/privacy-statement.md states scope counts that the SBOM no longer has"
    )


def test_a_name_locked_twice_contributes_both_resolutions_edges() -> None:
    """`scipy` is in `uv.lock` twice, once per Python version, and it will not be the last.

    Today both entries reach the same packages, so this is the only thing that fails when
    the merge is removed -- a mutation of the generator leaves the real SBOM unchanged.
    That is exactly why it is asserted on a synthetic lock: the day two resolutions differ,
    keying by name would drop one entry's dependencies, and whatever only it reached would
    be emitted with no scope, which CycloneDX reads as required.
    """
    gen = _load_generator()
    lock = {
        "package": [
            {"name": "yazses", "metadata": {"requires-dist": [{"name": "twice"}]}},
            {"name": "twice", "version": "1", "dependencies": [{"name": "old-only"}]},
            {"name": "twice", "version": "2", "dependencies": [{"name": "new-only"}]},
            {"name": "old-only"},
            {"name": "new-only"},
        ]
    }
    assert gen.classify_scopes(lock) == {
        "twice": "required",
        "old-only": "required",
        "new-only": "required",
    }
