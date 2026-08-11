#!/usr/bin/env python3
"""Generate a CycloneDX SBOM for YazSes from `uv.lock`.

Why an SBOM, for a project like this
------------------------------------
"Runs entirely on your machine" is a supply-chain claim as much as a privacy one: it is
only as true as the 228 packages underneath it. Anyone evaluating this for a hospital, a
law firm, a newsroom or an air-gapped network is asked by their own policy to enumerate
what they are installing, and today the honest answer -- "read `uv.lock`" -- fails that
request. This produces the machine-readable inventory those reviews expect, which removes
a real blocker to installing rather than merely arguing about one.

It reads **`uv.lock`, not the current environment**, so the output describes what a user
actually resolves to rather than whatever happens to be installed on the machine that ran
it. That also makes it reproducible: same lock file, byte-identical SBOM.

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


def build_sbom(lock_text: str, version: str) -> dict[str, Any]:
    """Assemble the CycloneDX document. Pure, so it is testable without the filesystem."""
    lock = tomllib.loads(lock_text)
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
