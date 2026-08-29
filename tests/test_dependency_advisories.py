"""The published "not exploitable here" assessments must stay true.

`.github/SECURITY.md` records an assessment for each known advisory in a
dependency that has no patch available. An assessment is a public claim about
this codebase — the same class of claim as a changelog entry, and this project has
already shipped changelog entries describing code that was never on `main`. A
claim nothing checks is a claim that quietly becomes false.

So each assessment gets a test. If the reasoning that makes an advisory harmless
here stops holding, the suite fails and the assessment gets rewritten — rather
than a reader trusting a paragraph that stopped being true.

---

**GHSA / Dependabot #1 — `diskcache <= 5.6.3`, unsafe pickle deserialization.**
No patched version exists upstream.

`diskcache` reaches this project only as a transitive dependency of
`llama-cpp-python`. The assessment rests on two facts, and this file pins both:

1. `llama-cpp-python` is **opt-in** — it appears only in the `slm`, `notes` and
   `all` extras, never in `project.dependencies`. A default install never
   downloads `diskcache` at all.
2. YazSes **never constructs a llama-cpp cache**. The vulnerability is in
   unpickling a cache file; `llama_cpp` only reads one if a caller installs a
   cache object via `Llama.set_cache(...)`. Nothing here does, so nothing here
   ever deserializes a cache.

If either changes, the published assessment is wrong and this test says so.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "yazses" if (ROOT / "yazses").is_dir() else ROOT / "src" / "yazses"
SECURITY_POLICY = ROOT / ".github" / "SECURITY.md"

#: The package whose transitive dependency carries the advisory.
VULNERABLE_VIA = "llama-cpp-python"

#: Symbols that would mean this project deserializes a llama-cpp cache.
CACHE_APIS = ("set_cache", "LlamaCache", "LlamaDiskCache", "LlamaRAMCache")


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_the_vulnerable_package_is_never_a_base_dependency():
    """Fact 1: a default install must not pull `llama-cpp-python` in at all."""
    base = _pyproject()["project"].get("dependencies", [])
    offenders = [d for d in base if VULNERABLE_VIA in d]
    assert not offenders, (
        f"{VULNERABLE_VIA} became a base dependency ({offenders}), so every install "
        f"now ships `diskcache`, which has an unpatched pickle-deserialization "
        f"advisory. The assessment in .github/SECURITY.md says the opposite. Either "
        f"revert this or rewrite the assessment."
    )


def test_the_vulnerable_package_is_still_reachable_only_through_extras():
    """Guard the guard: if nothing references it, the test above proves nothing."""
    extras = _pyproject()["project"].get("optional-dependencies", {})
    carriers = [name for name, deps in extras.items()
                if any(VULNERABLE_VIA in d for d in deps)]
    assert carriers, (
        f"no extra declares {VULNERABLE_VIA} any more. If the dependency is gone "
        f"entirely, delete its assessment from .github/SECURITY.md and delete this "
        f"file — a stale assessment is worse than none."
    )


def _cache_api_uses() -> list[str]:
    """Every place the shipped code touches a llama-cpp cache object."""
    hits = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - fails loudly elsewhere
            continue
        rel = path.relative_to(SRC).as_posix()
        for node in ast.walk(tree):
            # `llama.set_cache(...)` / `LlamaDiskCache(...)`
            if isinstance(node, ast.Attribute) and node.attr in CACHE_APIS:
                hits.append(f"{rel}: .{node.attr}")
            elif isinstance(node, ast.Name) and node.id in CACHE_APIS:
                hits.append(f"{rel}: {node.id}")
            # a direct `import diskcache`
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "diskcache":
                        hits.append(f"{rel}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] == "diskcache":
                    hits.append(f"{rel}: from {node.module}")
    return hits


def test_nothing_deserializes_a_llama_cpp_cache():
    """Fact 2: the advisory needs an unpickle, and this code never performs one."""
    hits = _cache_api_uses()
    assert not hits, (
        "this project now touches a llama-cpp cache or `diskcache` directly:\n  "
        + "\n  ".join(hits)
        + "\n\nThe advisory for `diskcache <= 5.6.3` is unsafe pickle "
        "deserialization, and .github/SECURITY.md tells readers YazSes never "
        "deserializes such a cache. Re-do the assessment before shipping this: a "
        "cache file is attacker-controlled the moment anything else can write to "
        "the cache directory."
    )


def test_the_scanner_would_actually_notice():
    """A detector that cannot fire is a clean bill of health that means nothing.

    `test_nothing_deserializes_a_llama_cpp_cache` passes trivially if the AST walk
    is broken, which is the failure mode that matters for a security guard — it
    reports "all clear" forever. Feed it a module that does the thing and confirm
    it is seen.
    """
    tree = ast.parse("import diskcache\nllm.set_cache(LlamaDiskCache('/tmp/c'))\n")
    found = {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    } | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }
    assert found & set(CACHE_APIS), "the AST patterns no longer match a real call"


@pytest.mark.parametrize("marker", ["diskcache", VULNERABLE_VIA])
def test_the_assessment_is_actually_published(marker):
    """The tests above are only meaningful if a reader can find the reasoning."""
    assert SECURITY_POLICY.is_file(), "the security policy moved or was deleted"
    text = SECURITY_POLICY.read_text(encoding="utf-8")
    assert marker in text, (
        f"`{marker}` is guarded by tests but not mentioned in "
        f".github/SECURITY.md. Someone reviewing the open Dependabot alert has "
        f"nowhere to read why it is not exploitable here."
    )


# ---------------------------------------------------------------------------
# Dependabot #9 -- `setuptools < 83.0.0`, MANIFEST.in exclusion bypass in sdist
#
# Different in kind from the diskcache advisory above: a patched release exists.
# The alert stays open because the `voiceprint-resemblyzer` extra pins
# `setuptools<81` so that `pkg_resources` remains importable for `webrtcvad`.
# The published assessment says the advisory cannot reach this project anyway,
# and rests on three facts. Each is pinned below, because "we build with
# hatchling" and "there is no MANIFEST.in" are exactly the sort of fact that a
# later packaging change flips without anyone rereading the security policy.
# ---------------------------------------------------------------------------

#: The release that patches Dependabot alert #9. The lock must resolve at or above
#: it — not merely avoid naming a pin.
SETUPTOOLS_PATCHED = (83, 0, 0)


def test_the_project_is_not_built_with_setuptools():
    """Fact 1: the vulnerable sdist builder is not the one that packages YazSes."""
    build = _pyproject()["build-system"]
    assert build["build-backend"] == "hatchling.build", (
        f"the build backend changed to {build['build-backend']!r}. The security "
        "policy tells readers the setuptools sdist advisory cannot apply because "
        "setuptools does not build this project. Re-do that assessment."
    )
    assert not any("setuptools" in r for r in build["requires"]), (
        f"setuptools entered build-system.requires ({build['requires']}), so it "
        "now participates in building this package."
    )


def test_there_is_no_manifest_in_to_bypass():
    """Fact 2: the advisory is a bypass of exclusions declared in `MANIFEST.in`."""
    assert not (ROOT / "MANIFEST.in").is_file(), (
        "a MANIFEST.in appeared. The published assessment says there are no "
        "exclusion rules for the setuptools advisory to bypass, and that is no "
        "longer true. Either remove it or rewrite .github/SECURITY.md."
    )


def _locked_version(package: str) -> tuple[int, ...]:
    """The version `uv.lock` resolves for `package`, as a comparable tuple."""
    text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    for block in re.split(r"\n\[\[package\]\]\n", text):
        if re.search(rf'^name = "{re.escape(package)}"$', block, re.M):
            m = re.search(r'^version = "([^"]+)"', block, re.M)
            assert m, f"{package} block in uv.lock has no version"
            return tuple(int(p) for p in re.findall(r"\d+", m.group(1))[:3])
    raise AssertionError(f"{package} is not in uv.lock at all")


def test_the_resolved_setuptools_is_at_or_above_the_patched_release():
    """Fact 3, and it has to be asked of the **resolution**, not the declaration.

    This test used to read `project.dependencies` and `optional-dependencies` and
    assert that only the `voiceprint-resemblyzer` extra named a setuptools pin. Its
    docstring stated the property correctly — *"a base install must never be held
    below the patched release"* — and then checked something that cannot establish
    it, so it passed for the entire time the property was false.

    `uv.lock` is a **universal** resolution: one version per package for the whole
    workspace, with no notion of "only inside that extra". The extra's `setuptools<81`
    therefore held everybody. `uv export --no-dev` — no extras at all — emitted
    `setuptools==80.10.2`, because core `ctranslate2` requires setuptools and there
    was a single entry to satisfy. `scripts/build-macos.sh` and
    `scripts/build-windows.ps1` build the shipped .dmg and .exe from that lock, so it
    reached release artifacts too.

    Three documents asserted the opposite in three different words — pyproject.toml
    ("a base install never sees the pin"), `.github/dependabot.yml` ("the exposure is
    bounded to voiceprint-resemblyzer"), and `.github/SECURITY.md` ("not one YazSes
    creates"). All three were written from the declaration, which is exactly what the
    old test read. A guard cannot catch a mistake it shares.
    """
    got = _locked_version("setuptools")
    assert got >= SETUPTOOLS_PATCHED, (
        f"uv.lock resolves setuptools {'.'.join(map(str, got))}, below the patched "
        f"{'.'.join(map(str, SETUPTOOLS_PATCHED))} (Dependabot #9). A pin anywhere "
        "in this workspace — including inside an opt-in extra — lands on every "
        "install and in the shipped macOS and Windows bundles, because the lock is "
        "one resolution for everything. If an extra truly needs an older setuptools, "
        "it belongs in that user's environment, not in this file."
    )


def test_the_setuptools_assessment_is_actually_published():
    text = SECURITY_POLICY.read_text(encoding="utf-8")
    assert "setuptools" in text and "MANIFEST.in" in text, (
        "the setuptools advisory is guarded by tests but not assessed in "
        ".github/SECURITY.md, so a reader looking at the open Dependabot alert "
        "has nowhere to read why it is not exploitable here."
    )
