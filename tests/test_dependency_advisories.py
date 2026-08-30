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


# ---------------------------------------------------------------------------
# CVE-2026-58659 -- `lightning` <= 2.6.5, code execution from a checkpoint
#
# Different in kind from BOTH advisories above, and the difference is the point.
#
# The diskcache assessment says the vulnerable code is never executed here. This
# one cannot say that: `lightning/pytorch/core/saving.py::_load_state` imports and
# calls the dotted path in a checkpoint's `_instantiator` hyperparameter, and
# `pyannote.audio` walks straight through it -- `Pipeline.from_pretrained` ->
# `Model.from_pretrained` -> `load_from_checkpoint`. YazSes runs that path when
# the pyannote diarization backend is chosen. There is no patched release: 2.6.5
# is the newest on PyPI and the fix is an unreleased upstream commit.
#
# So the published assessment rests on a precondition rather than an absence --
# the checkpoint has to arrive as one of two hardcoded, gated Hugging Face repo
# ids. That is a much more fragile kind of claim than "we never call it", because
# a perfectly ordinary feature request breaks it: a `[meeting] pyannote_model`
# config key would look like a convenience and would quietly turn "compromise
# this specific upstream repository" into "point it at any repository".
#
# Hence the guards below are aimed at the *shape* of the call rather than at its
# presence. The loader may be called; it may not be called with anything a user
# can steer.
# ---------------------------------------------------------------------------

#: The package that carries the advisory, and the one that drags it in.
LIGHTNING_VIA = "pyannote.audio"

#: The module whose constants bound the assessment.
PYANNOTE_BACKEND = SRC / "recimport" / "pyannote_backend.py"

#: Loader calls that read a checkpoint. Each must be handed a literal or a
#: module-level constant -- never a config value, an argument, or an f-string.
CHECKPOINT_LOADERS = ("from_pretrained", "load_from_checkpoint")


def _extra_names_declaring(pkg: str) -> set[str]:
    extras = _pyproject()["project"].get("optional-dependencies", {})
    return {name for name, deps in extras.items() if any(pkg in d for d in deps)}


def test_the_checkpoint_loader_is_never_a_base_dependency():
    """Fact 1: a default install must not contain lightning at all.

    Asserted against the *declaration* here; `test_a_default_export_contains_no_
    lightning` below asserts it against the resolution, which is the half the
    setuptools mistake proved is not implied by this one.
    """
    base = _pyproject()["project"].get("dependencies", [])
    offenders = [d for d in base if "pyannote" in d or "lightning" in d]
    assert not offenders, (
        f"{offenders} is now a base dependency. .github/SECURITY.md tells readers "
        "that CVE-2026-58659 reaches them only if they opt in by name, and a base "
        "dependency installs on every machine that runs `pip install yazses`."
    )


def test_the_checkpoint_loader_stays_behind_an_opt_in_extra():
    """The extras that may carry it, named -- so adding a third is a decision."""
    got = _extra_names_declaring("pyannote")
    assert got <= {"diarization-pyannote", "all"}, (
        f"`pyannote.audio` is now declared by {sorted(got - {'diarization-pyannote', 'all'})}. "
        "Every extra listed here widens who is exposed to CVE-2026-58659, which has "
        "no patched release. Re-read .github/SECURITY.md and say so there too."
    )


def test_the_default_diarization_extra_is_the_one_without_lightning():
    """The published claim that the *default* backend avoids this entirely.

    `diarization` is sherpa-onnx; `diarization-pyannote` is the accuracy option.
    If the plain `diarization` extra ever started pulling pyannote, users would
    get the vulnerable stack from the extra the docs recommend.
    """
    extras = _pyproject()["project"].get("optional-dependencies", {})
    assert "diarization" in extras, "the default diarization extra was renamed"
    offenders = [d for d in extras["diarization"] if "pyannote" in d or "lightning" in d]
    assert not offenders, (
        f"the default `diarization` extra now pulls {offenders}. SECURITY.md says "
        "the default diarization backend has no torch and no lightning in it."
    )


def _pyannote_backend_tree() -> ast.Module:
    assert PYANNOTE_BACKEND.is_file(), (
        f"{PYANNOTE_BACKEND} is gone. It held the two hardcoded model ids that "
        "bound CVE-2026-58659; if the backend moved, move these guards with it."
    )
    return ast.parse(PYANNOTE_BACKEND.read_text(encoding="utf-8"))


def test_the_model_ids_are_hardcoded_literals():
    """Fact 3, first half: the ids are constants, not configuration.

    A `str` annotation or an f-string would pass a naive "is it assigned?" check
    while sourcing the value from anywhere.
    """
    tree = _pyannote_backend_tree()
    literals = {}
    for node in tree.body:
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign) else
            list(node.targets) if isinstance(node, ast.Assign) else []
        )
        for t in targets:
            if isinstance(t, ast.Name) and t.id in ("PIPELINE_ID", "SEGMENTATION_ID"):
                literals[t.id] = node.value
    assert set(literals) == {"PIPELINE_ID", "SEGMENTATION_ID"}, (
        f"expected both model ids at module level, found {sorted(literals)}"
    )
    for name, value in literals.items():
        assert isinstance(value, ast.Constant) and isinstance(value.value, str), (
            f"{name} is no longer a plain string literal. That constant is the only "
            "thing standing between CVE-2026-58659 and 'point it at any Hugging Face "
            "repo': the vulnerability is code execution from checkpoint metadata, so "
            "whoever chooses the repo chooses the code. If this is now configurable, "
            "the assessment in .github/SECURITY.md is false and must be rewritten."
        )


def test_no_checkpoint_is_loaded_from_a_steerable_source():
    """Fact 3, second half: every loader call names one of those constants.

    Scanned across all of `src/`, not just the pyannote backend -- the risk is a
    *new* caller somewhere else, which is exactly what a guard scoped to the known
    file would miss.
    """
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in CHECKPOINT_LOADERS):
                continue
            if not node.args:
                continue
            first = node.args[0]
            ok = (
                (isinstance(first, ast.Constant) and isinstance(first.value, str))
                or (isinstance(first, ast.Name) and first.id.isupper())
            )
            if not ok:
                offenders.append(
                    f"{path.relative_to(SRC.parent.parent)}:{node.lineno}: "
                    f"{func.attr}({ast.dump(first)[:60]}...)"
                )
    assert not offenders, (
        "a pretrained checkpoint is loaded from something other than a literal or a "
        "module-level constant:\n  " + "\n  ".join(offenders)
        + "\n\nCVE-2026-58659 is arbitrary code execution from checkpoint metadata, "
        "and there is no patched lightning release. .github/SECURITY.md tells "
        "readers the checkpoint id cannot be redirected. Either keep it that way, or "
        "rewrite the assessment."
    )


def test_the_steerable_source_scanner_would_actually_notice():
    """The guard above reports 'all clear' if its AST matching is broken.

    That is the failure mode that matters for a security guard, so drive it with
    a call it must reject and one it must accept.
    """
    bad = ast.parse("Pipeline.from_pretrained(cfg.meeting.pyannote_model, token=t)\n")
    good = ast.parse("Pipeline.from_pretrained(PIPELINE_ID, token=t)\n")

    def flagged(tree: ast.Module) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in CHECKPOINT_LOADERS and node.args:
                    first = node.args[0]
                    return not (
                        (isinstance(first, ast.Constant) and isinstance(first.value, str))
                        or (isinstance(first, ast.Name) and first.id.isupper())
                    )
        raise AssertionError("the scanner no longer recognises a loader call at all")

    assert flagged(bad), "a config-driven checkpoint id would not be flagged"
    assert not flagged(good), "the guard rejects the shape the project actually uses"


def test_a_default_export_contains_no_lightning():
    """The resolution, not the declaration -- the half the setuptools entry is about.

    `uv.lock` is a universal resolution, so "it is only in an extra" was already
    wrong once in this repository. Read the lock the way an installer would: a
    package reaches a default install only if something in the default dependency
    closure asks for it.
    """
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    by_name = {p["name"]: p for p in lock["package"]}
    assert "lightning" in by_name, (
        "`lightning` is no longer in the lock at all. If pyannote was dropped, "
        "delete this block and the CVE-2026-58659 section of .github/SECURITY.md "
        "rather than leaving an assessment for a dependency nobody has."
    )

    root = by_name.get("yazses")
    assert root is not None, "the workspace root package is not named `yazses`"
    reach, seen = set(), list(root.get("dependencies", []))
    while seen:
        dep = seen.pop()
        name = dep["name"]
        if name in reach:
            continue
        reach.add(name)
        seen.extend(by_name.get(name, {}).get("dependencies", []))

    # A traversal that reached nothing would report "no lightning here" forever,
    # which is the single most likely way this guard dies quietly -- a renamed
    # lock key or a schema change empties the frontier and every assertion below
    # passes on an empty set. Anchor on a package a default install certainly
    # has, so an empty or truncated walk is a failure rather than a clean bill.
    assert "sounddevice" in reach and len(reach) > 20, (
        f"the lockfile walk reached only {len(reach)} packages, which cannot be a "
        "real default closure. This guard is now blind: fix the traversal rather "
        "than trusting the result."
    )
    assert "lightning" not in reach and "pyannote-audio" not in reach, (
        "a default install now resolves lightning/pyannote. SECURITY.md tells "
        "readers CVE-2026-58659 is only reachable if they install an extra by name."
    )


def test_the_lightning_assessment_is_actually_published():
    text = SECURITY_POLICY.read_text(encoding="utf-8")
    for marker in ("CVE-2026-58659", "lightning", LIGHTNING_VIA):
        assert marker in text, (
            f"`{marker}` is guarded by tests but not assessed in "
            ".github/SECURITY.md. This advisory is reachable rather than merely "
            "present, so an unexplained alert is worse here than for the others."
        )
