#!/usr/bin/env python3
"""Generate a CycloneDX SBOM for YazSes from `uv.lock`.

Why an SBOM, for a project like this
------------------------------------
"Runs entirely on your machine" is a supply-chain claim as much as a privacy one: it is
only as true as the packages underneath it. Anyone evaluating this for a hospital, a
law firm, a newsroom or an air-gapped network is asked by their own policy to enumerate
what they are installing, and today the honest answer -- "read `uv.lock`" -- fails that
request. This produces the machine-readable inventory those reviews expect, which removes
a real blocker to installing rather than merely arguing about one.

It reads **`uv.lock`, not the current environment**, so the output describes what a user
actually resolves to rather than whatever happens to be installed on the machine that ran
it. That also makes it reproducible: same lock file, byte-identical SBOM.

The lock is the *development* closure, though, and a user installs a small part of it, so
every component carries a derived CycloneDX ``scope`` -- see `classify_scopes`. Without it
the SBOM asserted that `pytest`, `mypy` and `mkdocs` ship to users, and a reviewer running
it through a vulnerability scanner had no way to tell.

Usage
-----
    python scripts/gen-sbom.py                      # write sbom.cdx.json
    python scripts/gen-sbom.py -o - | jq .          # stdout
    python scripts/gen-sbom.py --check              # verify the committed copy is current

Stdlib only (`tomllib` is 3.11+), so it runs in a release job with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "uv.lock"
PYPROJECT = ROOT / "pyproject.toml"
DEFAULT_OUT = ROOT / "sbom.cdx.json"


def _project_version() -> str:
    with PYPROJECT.open("rb") as fh:
        return str(tomllib.load(fh)["project"]["version"])


def _purl(name: str, version: str) -> str:
    """Package URL for a PyPI distribution (purl spec: pkg:pypi/<name>@<version>)."""
    return f"pkg:pypi/{quote(name.lower().replace('_', '-'))}@{quote(version)}"


def _hashes(pkg: dict[str, Any]) -> list[dict[str, str]]:
    """SHA-256 of the sdist, when the lock records one.

    Only the sdist hash is emitted. A package resolves to a different wheel per platform
    and Python version, so listing one wheel's digest here would assert something false
    for most readers -- an SBOM that is confidently wrong is worse than one that is
    quiet. `uv.lock` remains the per-artifact source of truth.
    """
    sdist = pkg.get("sdist")
    if isinstance(sdist, dict):
        digest = sdist.get("hash", "")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            return [{"alg": "SHA-256", "content": digest.removeprefix("sha256:")}]
    return []


def _requested_extras(entry: dict[str, Any]) -> list[str]:
    """Extras an edge asks for, as `[""]` when it asks for none.

    `uv.lock` spells this two ways and both are load-bearing: a package's own dependency
    entries say `extra = [...]`, while the root's `requires-dist`/`requires-dev` entries
    say `extras = [...]`. Reading only the singular missed `mkdocs-material[imaging]` and
    left its six-package image toolchain scopeless -- i.e. declared required.
    """
    extras = entry.get("extra") or entry.get("extras") or []
    return list(extras) or [""]


def classify_scopes(lock: dict[str, Any]) -> dict[str, str]:
    """Map every locked package to a CycloneDX ``scope``.

    `uv.lock` is a *development* closure: it holds the runtime dependencies, every
    optional extra, and the `dev`/`benchmark`/`docs` groups, all flattened together.
    Emitted without scopes, CycloneDX treats each component as **required** -- so the
    SBOM declared that installing YazSes brings in `pytest`, `mypy`, `ruff`, `mkdocs`
    and `jiwer`. It does not. 16 runtime dependencies are declared; 283 components
    were published as if a user received all of them.

    That is not a cosmetic overstatement. An SBOM is read to answer "what is in my
    installation, and which advisories apply to me?" Over-declaring produces
    advisories against a maintainer's toolchain that no user ever runs, and the
    reviewer -- a hospital, a law firm, an air-gapped network, the audiences this
    file was written for -- has no way to tell the difference.

    * ``required`` -- reachable from a dependency with no ``extra ==`` marker. What
      ``pip install yazses`` actually pulls in, platform markers included, because an
      SBOM must describe every platform the artifact supports.
    * ``optional`` -- reachable only via an extra. Real, shipped, opt-in.
    * ``excluded`` -- reachable only from a dependency group. Present in the lock so
      builds are reproducible; never installed by a user.

    Derived from the lock rather than listed here: a new extra or group is classified
    the day it is added, and one that is removed stops being claimed.
    """
    # A name can be locked more than once -- `scipy` resolves to two versions for
    # different Python versions -- so the edges are merged rather than the later entry
    # winning. Keying by name alone would drop one resolution's dependencies silently,
    # and anything reachable only through it would come out unclassified, i.e. required.
    packages: dict[str, dict[str, Any]] = {}
    for pkg in lock.get("package", []):
        name = pkg.get("name")
        if not name:
            continue
        merged = packages.setdefault(name, {"dependencies": [], "optional-dependencies": {}})
        merged["dependencies"] += pkg.get("dependencies") or []
        for extra, deps in (pkg.get("optional-dependencies") or {}).items():
            merged["optional-dependencies"].setdefault(extra, []).extend(deps)
        if pkg.get("metadata"):
            merged["metadata"] = pkg["metadata"]
    root = packages.get("yazses", {}).get("metadata", {})

    def closure(seeds: list[dict[str, Any]]) -> set[str]:
        """Names reachable from `seeds`, following the extras each edge actually asks for.

        A node is `(name, extra)`, not just a name: `lightning` depends on `fsspec[http]`,
        and plain `fsspec` does not pull in `aiohttp`. Walking names alone left 23 packages
        -- `aiohttp`, `cairosvg`, the CUDA runtime libraries -- reachable from nothing, and
        an unclassified component is emitted with no scope, which CycloneDX reads as
        **required**. The bug would have declared `mkdocs-material`'s image toolchain a
        runtime dependency of a dictation daemon.
        """
        seen: set[str] = set()
        visited: set[tuple[str, str]] = set()
        stack = [(e["name"], x) for e in seeds for x in _requested_extras(e) if e.get("name")]
        while stack:
            name, extra = stack.pop()
            if (name, extra) in visited or name not in packages:
                continue
            visited.add((name, extra))
            seen.add(name)
            pkg = packages[name]
            # `pkg[extra]` installs `pkg` too, so the base list is always followed; the
            # extra only adds. Following the extra *instead* stranded `pymdown-extensions`
            # and three siblings, which are plain dependencies of `mkdocs-material`.
            deps = list(pkg.get("dependencies") or [])
            if extra:
                deps += (pkg.get("optional-dependencies") or {}).get(extra) or []
            stack.extend(
                (dep["name"], x)
                for dep in deps
                for x in _requested_extras(dep)
                if dep.get("name")
            )
        return seen

    dist = root.get("requires-dist") or []
    runtime = [e for e in dist if "extra == " not in (e.get("marker") or "")]
    extras = [e for e in dist if "extra == " in (e.get("marker") or "")]
    groups = [e for g in (root.get("requires-dev") or {}).values() for e in g]

    required = closure(runtime)
    optional = closure(extras) - required
    excluded = closure(groups) - required - optional

    scopes = {name: "required" for name in required}
    scopes.update({name: "optional" for name in optional})
    scopes.update({name: "excluded" for name in excluded})
    return scopes


def build_sbom(lock_text: str, version: str) -> dict[str, Any]:
    """Assemble the CycloneDX document. Pure, so it is testable without the filesystem."""
    lock = tomllib.loads(lock_text)
    scopes = classify_scopes(lock)
    components: list[dict[str, Any]] = []

    for pkg in lock.get("package", []):
        name = pkg.get("name")
        pkg_version = pkg.get("version")
        if not name or not pkg_version:
            continue
        if name == "yazses":  # the subject of the SBOM, not a component of itself
            continue
        component: dict[str, Any] = {
            "type": "library",
            "name": name,
            "version": pkg_version,
            "purl": _purl(name, pkg_version),
            "bom-ref": _purl(name, pkg_version),
        }
        # Only emitted when known. CycloneDX defaults an absent scope to `required`,
        # so guessing here would restate the very error this classification fixes.
        scope = scopes.get(name)
        if scope:
            component["scope"] = scope
        digests = _hashes(pkg)
        if digests:
            component["hashes"] = digests
        components.append(component)

    components.sort(key=lambda c: (c["name"].lower(), c["version"]))

    # No timestamp and no serial number: both would change on every run and make the
    # committed copy impossible to diff or to verify with --check. The version of the
    # subject component is what dates this document.
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "yazses",
                "version": version,
                "purl": _purl("yazses", version),
                "bom-ref": _purl("yazses", version),
                "description": (
                    "Offline, on-device voice dictation and speech-to-text for Linux, "
                    "macOS and Windows."
                ),
                "licenses": [{"license": {"id": "Apache-2.0"}}],
                "externalReferences": [
                    {"type": "website", "url": "https://mskazemi.com/yazses/"},
                    {"type": "vcs", "url": "https://github.com/MSKazemi/yazses"},
                    {"type": "distribution", "url": "https://pypi.org/project/yazses/"},
                ],
            },
            "tools": [{"name": "gen-sbom.py", "vendor": "YazSes"}],
        },
        "components": components,
    }


def render(sbom: dict[str, Any]) -> str:
    return json.dumps(sbom, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUT), help="'-' for stdout")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed SBOM is stale (for CI)",
    )
    args = parser.parse_args(argv)

    text = render(build_sbom(LOCK.read_text(encoding="utf-8"), _project_version()))

    if args.check:
        target = Path(args.output)
        if not target.exists():
            print(f"ERROR: {target.name} is missing — run scripts/gen-sbom.py", file=sys.stderr)
            return 1
        if target.read_text(encoding="utf-8") != text:
            print(
                f"ERROR: {target.name} is out of date with uv.lock — "
                "run scripts/gen-sbom.py",
                file=sys.stderr,
            )
            return 1
        print(f"OK — {target.name} matches uv.lock.")
        return 0

    if args.output == "-":
        sys.stdout.write(text)
        return 0

    Path(args.output).write_text(text, encoding="utf-8")
    count = len(json.loads(text)["components"])
    print(f"Wrote {args.output} — {count} components.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
