#!/usr/bin/env python3
"""Render ``server.json`` for the official MCP registry — ADR-032 §2.

The registry (``registry.modelcontextprotocol.io``) stores metadata only: one
``server.json`` per server, pointing at a package on a public registry. Ours points at
PyPI's ``yazses``, run over stdio with the argument ``mcp-server``.

The file is rendered from ``packaging/mcp-registry/server.template.json`` with the
version from ``pyproject.toml``, rather than committed with a version in it, so it is
not one more manifest a release has to remember to bump. The version must be one that
is already on PyPI **and** whose PyPI description (the README) carries the ownership
marker ``mcp-name: <server name>``; the registry checks both when it accepts a publish.

Usage
-----
    python3 scripts/render-mcp-server-json.py                 # -> dist/server.json
    python3 scripts/render-mcp-server-json.py --out-dir /tmp/x

Publishing is an outward-facing release step that the owner runs by hand with the
registry's ``mcp-publisher``; this script only writes the file. The steps are in
``packaging/README.md`` ("MCP registry").

Standard library only, and no network. It reuses the version reader and the
placeholder check of ``scripts/build-mcpb.py``, so the two artifacts cannot disagree
about what a release version is.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
#: Relative to the repository root, so a test can render from a fabricated tree.
TEMPLATE_REL = "packaging/mcp-registry/server.template.json"
TEMPLATE = ROOT / TEMPLATE_REL


def _load_build_mcpb():
    path = Path(__file__).resolve().parent / "build-mcpb.py"
    spec = importlib.util.spec_from_file_location("build_mcpb", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_mcpb = _load_build_mcpb()
VERSION_TOKEN = _mcpb.VERSION_TOKEN


def ownership_marker(server: dict[str, Any]) -> str:
    """The line the PyPI README must contain for the registry to accept ``server``."""
    return f"mcp-name: {server['name']}"


def render(root: Path = ROOT) -> dict[str, Any]:
    """``server.json`` for the tree at ``root``, version filled in. Pure apart from reads."""
    version = _mcpb.project_version(root / "pyproject.toml")
    template = json.loads((root / TEMPLATE_REL).read_text(encoding="utf-8"))
    return _mcpb.render_manifest(template, version)


def write(out_dir: Path, root: Path = ROOT) -> Path:
    """Write ``<out_dir>/server.json``. Same input, same bytes."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "server.json"
    path.write_text(json.dumps(render(root), indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "dist",
        help="where to write server.json (default: dist/)",
    )
    args = parser.parse_args(argv)
    path = write(args.out_dir)
    print(path)
    server = json.loads(path.read_text(encoding="utf-8"))
    print(f"The PyPI README of {server['version']} must contain: {ownership_marker(server)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
