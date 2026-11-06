"""The `.mcpb` manifest against the MCP Bundle spec's own JSON schema, offline (#638).

ADR-032 §1 asked that the bundle manifest be "checked against the spec's `MANIFEST.md`
at the time it is written". #659 did that by hand. This makes it mechanical: the
manifest that `scripts/build-mcpb.py` puts into the bundle is validated against a
verbatim copy of the schema the spec publishes for the manifest version we declare, so
a field the spec does not have, a server type it does not know, or a platform it does
not list fails here rather than in a user's client at install time.

`tests/test_build_mcpb.py` pins the rest: what the bundle contains, that it runs the
installed `yazses mcp-server`, that its tools are the ones the server registers, and
that it is byte-for-byte reproducible.

Source:   modelcontextprotocol/mcpb, schemas/mcpb-manifest-v0.3.schema.json at commit
          70fe3b34cd6dff1b3bba046638edc72a6467a4fb (fetched 2026-11-06).
Currency: at that commit `MANIFEST.md` says "Current version: `0.3`" (last updated
          2025-12-02) and `schemas/mcpb-manifest-latest.schema.json` is byte-identical
          to the v0.3 file. A v0.4 schema exists; it adds the `uv` server type, which a
          bundle that runs an already-installed command does not need.
Licence:  MIT (the mcpb repository's LICENSE), compatible with ours.
          Vendored byte-for-byte apart from one added final newline.

To move to a newer manifest version: vendor the new schema verbatim, update
SCHEMA_FILE and SCHEMA_CANONICAL_SHA256, and `manifest_version` in
`packaging/mcpb/manifest.template.json`. The hash is over the parsed JSON, so a CRLF
checkout does not change it, and an edit made to let a field through does.

Nothing here touches the network or runs a client.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

from tests.json_schema_subset import errors

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-mcpb.py"
TEMPLATE = ROOT / "packaging" / "mcpb" / "manifest.template.json"
SCHEMA_FILE = ROOT / "tests" / "fixtures" / "mcpb" / "mcpb-manifest-v0.3.schema.json"
SCHEMA_CANONICAL_SHA256 = "6b729725938f87eecd8ed9d9bf3be47b13fe97a12646ea5f6bdab96f0bffcfc2"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_mcpb_schema_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["build_mcpb_schema_check"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest(tmp_path_factory) -> dict:
    """The manifest exactly as it ships: read back out of a freshly built bundle."""
    bundle = _load_builder().build(tmp_path_factory.mktemp("mcpb-schema"))
    with zipfile.ZipFile(bundle) as zf:
        return json.loads(zf.read("manifest.json").decode("utf-8"))


def test_the_vendored_schema_is_the_published_one(schema: dict) -> None:
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == SCHEMA_CANONICAL_SHA256
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"


def test_the_manifest_declares_the_version_of_the_vendored_schema(
    manifest: dict, schema: dict
) -> None:
    """A manifest that says 0.4 while we check it against 0.3 would prove nothing."""
    declared = schema["properties"]["manifest_version"]["const"]
    assert manifest["manifest_version"] == declared
    template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert template["manifest_version"] == declared


def test_the_shipped_manifest_satisfies_the_spec_schema(manifest: dict, schema: dict) -> None:
    assert errors(schema, manifest, schema) == []


def test_the_manifest_uses_no_deprecated_alias(manifest: dict) -> None:
    """The schema still accepts `dxt_version`, marked `@deprecated` in favour of
    `manifest_version`; a client may drop the alias."""
    assert "dxt_version" not in manifest


def _set(path: tuple, value):
    def mutate(m: dict) -> None:
        node = m
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return mutate


def _drop(path: tuple):
    def mutate(m: dict) -> None:
        node = m
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
    return mutate


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (_drop(("author",)), "missing 'author'"),
        (_drop(("server", "mcp_config", "command")), "missing 'command'"),
        (_set(("manifest_version",), "0.4"), "is not '0.3'"),
        (_set(("server", "type"), "uv"), "not in ['python', 'node', 'binary']"),
        (_set(("compatibility", "platforms"), ["linux", "freebsd"]), "'freebsd' not in"),
        (_set(("homepage",), "mskazemi.com/yazses"), "is not a uri"),
        (_set(("author", "email"), "not-an-address"), "is not an email address"),
        (_set(("transport",), "stdio"), "unexpected 'transport'"),
        (_set(("tools",), [{"name": "transcribe", "input_schema": {}}]),
         "unexpected 'input_schema'"),
        (_set(("server", "mcp_config", "args"), ["mcp-server", 1]), "not of type string"),
    ],
)
def test_the_schema_check_rejects_what_the_spec_rejects(
    manifest: dict, schema: dict, mutate, expected: str
) -> None:
    """The offline check is not vacuous: each mutation breaks one rule of the spec."""
    broken = copy.deepcopy(manifest)
    mutate(broken)
    found = errors(schema, broken, schema)
    assert any(expected in e for e in found), found


def test_a_platform_override_is_checked_through_its_ref(manifest: dict, schema: dict) -> None:
    """`platform_overrides` reuses `command`/`args`/`env` by `$ref`; the walk follows it."""
    broken = copy.deepcopy(manifest)
    broken["server"]["mcp_config"]["platform_overrides"] = {"win32": {"args": "mcp-server"}}
    found = errors(schema, broken, schema)
    assert any("platform_overrides.win32.args: not of type array" in e for e in found), found


def test_an_unimplemented_keyword_fails_loudly() -> None:
    """A newer schema with a keyword the walk does not know must not pass by default."""
    with pytest.raises(AssertionError, match="not implemented"):
        errors({"uniqueItems": True}, [1, 1], {})
