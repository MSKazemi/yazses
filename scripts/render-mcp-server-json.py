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

Checked against (2026-10-30): the server.json schema
``https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`` (the
current released schema; vendored for the tests under
``tests/fixtures/mcp_registry/``), and the registry's publishing docs and PyPI
ownership check at ``modelcontextprotocol/registry`` commit ``72042e51`` / release
``v1.8.6``: ``docs/modelcontextprotocol-io/package-types.mdx`` (PyPI section),
``docs/reference/server-json/official-registry-requirements.md`` and
``internal/validators/registries/mcpname.go``, whose boundary rule
:func:`contains_mcp_name_token` ports.

Usage
-----
    python3 scripts/render-mcp-server-json.py                 # -> dist/server.json
    python3 scripts/render-mcp-server-json.py --out-dir /tmp/x
    python3 scripts/render-mcp-server-json.py --out-dir x --expect-tag v2.47.0 --check-readme

``--expect-tag`` refuses to render unless ``pyproject.toml``'s version is the tag's,
exactly as ``scripts/build-mcpb.py`` does. ``--check-readme`` refuses unless
``README.md`` (the PyPI description) carries the ownership marker in a form the
registry accepts, so a publish can never be attempted for a release whose PyPI page
would fail the ownership check.

Publishing is an outward-facing release step. It is either run by hand by the owner
with the registry's ``mcp-publisher``, or by the ``publish-mcp-registry`` job of
``release.yml``, which is off until the owner sets the repository variable
``MCP_REGISTRY_PUBLISH`` to ``true``. The steps are in ``packaging/README.md``
("MCP registry").

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


#: The PyPI description the registry reads (``[project] readme`` in pyproject.toml).
README_REL = "README.md"

_SERVER_NAME_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/-"
)


def ownership_marker(server: dict[str, Any]) -> str:
    """The line the PyPI README must contain for the registry to accept ``server``."""
    return f"mcp-name: {server['name']}"


def _is_boundary(rest: str) -> bool:
    if not rest or rest[0] not in _SERVER_NAME_CHARS:
        return True
    return rest.startswith("-->") or rest.startswith("--!>")


def contains_mcp_name_token(content: str, server_name: str) -> bool:
    """Whether ``content`` carries ``mcp-name: <server_name>`` as the registry reads it.

    A port of ``containsMCPNameToken`` in the registry's
    ``internal/validators/registries/mcpname.go``: the name must be followed by the end
    of the text, a character that cannot continue a server name (whitespace, ``<``), or
    an HTML comment close. ``mcp-name: io.github.MSKazemi/yazses.`` (a sentence's full
    stop) does not count. Pure.
    """
    token = f"mcp-name: {server_name}"
    start = content.find(token)
    while start >= 0:
        if _is_boundary(content[start + len(token):]):
            return True
        start = content.find(token, start + 1)
    return False


def check_readme(server: dict[str, Any], root: Path = ROOT) -> None:
    """Refuse unless the README carries the ownership marker for ``server``."""
    text = (root / README_REL).read_text(encoding="utf-8")
    if not contains_mcp_name_token(text, server["name"]):
        raise ValueError(
            f"{README_REL} does not carry the registry ownership marker "
            f"'{ownership_marker(server)}' followed by a boundary; the registry would "
            "reject the publish"
        )


def check_pypi_release(server: dict[str, Any], pypi: dict[str, Any]) -> None:
    """Refuse unless PyPI's JSON for a release is the one the registry will accept.

    ``pypi`` is the body of ``https://pypi.org/pypi/<name>/<version>/json``, the URL the
    registry's PyPI validator fetches (``internal/validators/registries/pypi.go``): its
    ``info.version`` must be the package version in ``server`` and its
    ``info.description`` must carry the ownership marker. The release job polls this
    before publishing, because a version PyPI has only just accepted can take a moment
    to appear there. Pure.
    """
    info = pypi.get("info") or {}
    package = server["packages"][0]
    if info.get("name") != package["identifier"] or info.get("version") != package["version"]:
        raise ValueError(
            f"PyPI answered for {info.get('name')!r} {info.get('version')!r}, "
            f"not {package['identifier']!r} {package['version']!r}"
        )
    if not contains_mcp_name_token(info.get("description") or "", server["name"]):
        raise ValueError(
            f"the PyPI description of {package['identifier']} {package['version']} does not "
            f"carry '{ownership_marker(server)}'"
        )


def render(root: Path = ROOT, expect_tag: str | None = None) -> dict[str, Any]:
    """``server.json`` for the tree at ``root``, version filled in. Pure apart from reads.

    With ``expect_tag``, refuses unless the tree's version is that tag's.
    """
    version = _mcpb.project_version(root / "pyproject.toml")
    if expect_tag is not None:
        _mcpb.check_tag(version, expect_tag)
    template = json.loads((root / TEMPLATE_REL).read_text(encoding="utf-8"))
    return _mcpb.render_manifest(template, version)


def write(out_dir: Path, root: Path = ROOT, expect_tag: str | None = None,
          require_marker: bool = False) -> Path:
    """Write ``<out_dir>/server.json``. Same input, same bytes.

    Every check runs before anything is written, so a refusal leaves no file behind
    for a later step to publish.
    """
    server = render(root, expect_tag=expect_tag)
    if require_marker:
        check_readme(server, root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "server.json"
    path.write_text(json.dumps(server, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out-dir", type=Path, default=ROOT / "dist",
        help="where to write server.json (default: dist/)",
    )
    parser.add_argument(
        "--expect-tag", metavar="TAG", default=None,
        help="refuse unless pyproject's version is this tag's (e.g. v2.47.0)",
    )
    parser.add_argument(
        "--check-readme", action="store_true",
        help="refuse unless README.md carries the registry ownership marker",
    )
    parser.add_argument(
        "--check-pypi-json", metavar="FILE", type=Path, default=None,
        help="write nothing; exit 0 only if FILE (PyPI's JSON for the release) carries "
             "this version and the ownership marker",
    )
    args = parser.parse_args(argv)
    try:
        if args.check_pypi_json is not None:
            pypi = json.loads(args.check_pypi_json.read_text(encoding="utf-8"))
            check_pypi_release(render(expect_tag=args.expect_tag), pypi)
            print("PyPI serves this release with the ownership marker", file=sys.stderr)
            return 0
        path = write(args.out_dir, expect_tag=args.expect_tag,
                     require_marker=args.check_readme)
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(path)
    server = json.loads(path.read_text(encoding="utf-8"))
    print(f"The PyPI README of {server['version']} must contain: {ownership_marker(server)}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
