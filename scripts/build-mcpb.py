#!/usr/bin/env python3
"""Build the YazSes MCP Bundle (``.mcpb``) — ADR-032 §1.

An MCP Bundle is a zip with a ``manifest.json`` that describes a local MCP server; a
desktop client installs it by double-click or drag-and-drop. The YazSes bundle
**contains no YazSes**: its manifest runs the ``yazses mcp-server`` command that is
already installed on the machine. The model, the daemon, the user's config and the
microphone permission all belong to that install, and a second copy inside a client's
extension directory would be updated by nobody.

So the bundle is two files: ``manifest.json``, rendered from
``packaging/mcpb/manifest.template.json`` with the version from ``pyproject.toml``,
and ``icon.png``. Nothing else goes in, and ``tests/test_build_mcpb.py`` holds that.

Usage
-----
    python3 scripts/build-mcpb.py                  # -> dist/yazses-<version>.mcpb
    python3 scripts/build-mcpb.py --out-dir /tmp/x

**Deterministic.** Entries are written in sorted order, stored (not deflated, so the
bytes do not depend on the zlib build), with a fixed 1980-01-01 timestamp and fixed
permissions. Two builds of one commit are byte-identical on any machine, which is what
lets the release checksum file vouch for it.

Standard library only, and no network: it runs under a bare ``python3`` in a release
job with nothing installed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
#: Relative to the repository root, so a test can build from a fabricated tree.
TEMPLATE_REL = "packaging/mcpb/manifest.template.json"
TEMPLATE = ROOT / TEMPLATE_REL
#: Bundle path -> source file, relative to the repository root. The manifest's
#: ``icon`` field names the bundle path.
EXTRA_FILES: dict[str, str] = {"icon.png": "contrib/icons/yazses-256.png"}

#: The placeholder the template carries wherever the release version belongs. Not a
#: literal version, so `tests/test_packaging_manifest_versions.py` does not see a
#: manifest that drifts: there is nothing in the template to go stale.
VERSION_TOKEN = "@VERSION@"
_PLACEHOLDER = re.compile(r"@[A-Z_]+@")
_RELEASE_VERSION = re.compile(r"^\d+\.\d+\.\d+$")

#: 1980-01-01 is the earliest timestamp a zip entry can carry.
FIXED_DATE_TIME = (1980, 1, 1, 0, 0, 0)
_FILE_MODE = 0o100644


def project_version(pyproject: Path = PYPROJECT) -> str:
    """``[project] version`` from ``pyproject.toml``, refused unless it is X.Y.Z."""
    with pyproject.open("rb") as fh:
        version = tomllib.load(fh)["project"]["version"]
    if not isinstance(version, str) or not _RELEASE_VERSION.match(version):
        raise ValueError(f"pyproject version {version!r} is not a release version (X.Y.Z)")
    return version


def _substitute(node: Any, version: str) -> Any:
    if isinstance(node, dict):
        return {key: _substitute(value, version) for key, value in node.items()}
    if isinstance(node, list):
        return [_substitute(value, version) for value in node]
    if isinstance(node, str):
        return node.replace(VERSION_TOKEN, version)
    return node


def _leftover_placeholders(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [p for value in node.values() for p in _leftover_placeholders(value)]
    if isinstance(node, list):
        return [p for value in node for p in _leftover_placeholders(value)]
    if isinstance(node, str):
        return _PLACEHOLDER.findall(node)
    return []


def render_manifest(template: dict[str, Any], version: str) -> dict[str, Any]:
    """The template with the version filled in. Pure.

    Refuses a template that still carries a placeholder afterwards: a bundle whose
    manifest says ``@SOMETHING@`` would install and then show it to the user.
    """
    manifest = _substitute(template, version)
    leftover = _leftover_placeholders(manifest)
    if leftover:
        raise ValueError(f"unfilled placeholders in the manifest template: {sorted(set(leftover))}")
    return manifest


def bundle_entries(root: Path, version: str) -> dict[str, bytes]:
    """Bundle path -> bytes, for everything that goes into the ``.mcpb``."""
    template = json.loads((root / TEMPLATE_REL).read_text(encoding="utf-8"))
    manifest = render_manifest(template, version)
    entries = {
        "manifest.json": (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    }
    for bundle_path, source in EXTRA_FILES.items():
        entries[bundle_path] = (root / source).read_bytes()
    return entries


def write_bundle(path: Path, entries: dict[str, bytes]) -> Path:
    """Write ``entries`` as a deterministic zip at ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=FIXED_DATE_TIME)
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3  # Unix, so every reader takes the mode bits as written
            info.external_attr = _FILE_MODE << 16
            zf.writestr(info, entries[name])
    tmp.replace(path)
    return path


def build(out_dir: Path, root: Path = ROOT) -> Path:
    """Build ``<out_dir>/yazses-<version>.mcpb`` from the tree at ``root``."""
    version = project_version(root / "pyproject.toml")
    return write_bundle(out_dir / f"yazses-{version}.mcpb", bundle_entries(root, version))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "dist",
        help="where to write yazses-<version>.mcpb (default: dist/)",
    )
    args = parser.parse_args(argv)
    path = build(args.out_dir)
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
