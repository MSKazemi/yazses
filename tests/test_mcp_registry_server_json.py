"""`scripts/render-mcp-server-json.py`: the MCP registry entry (ADR-032 §2, #639).

The registry stores one `server.json` per server, pointing at a package on a public
registry. Ours must describe the package this repository actually publishes, run the
way it actually runs, so every field a client acts on is pinned against the source
that owns it rather than against a copy:

* the package name and the repository URL against `pyproject.toml`;
* the argument `mcp-server` against the CLI's registered commands;
* the version against `pyproject.toml`, through a fabricated tree whose version no
  release ever had;
* the namespace against the GitHub owner of the repository, which is what the
  registry's GitHub login proves;
* the ownership marker against the name in the file, and its presence in README.md
  (the PyPI description) under the registry's own boundary rule;
* the whole file against a vendored copy of the registry's published JSON schema.

Nothing here contacts the registry or PyPI. What only the registry can check — that
the version is on PyPI with the marker in its description, and that the publisher's
login owns `io.github.MSKazemi/` — happens at publish time (packaging/README.md).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import typer.main as tm

import yazses.cli as cli_mod

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "render-mcp-server-json.py"
TEMPLATE = ROOT / "packaging" / "mcp-registry" / "server.template.json"
GUIDE = ROOT / "docs" / "how-to" / "connect-mcp-client.md"
PACKAGING_README = ROOT / "packaging" / "README.md"


def _load():
    spec = importlib.util.spec_from_file_location("render_mcp_server_json", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["render_mcp_server_json"] = module
    spec.loader.exec_module(module)
    return module


registry = _load()


def _pyproject() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]


@pytest.fixture(scope="module")
def server() -> dict:
    return registry.render()


def _package(server: dict) -> dict:
    packages = server["packages"]
    assert len(packages) == 1, "one package: PyPI's yazses"
    return packages[0]


def test_the_version_is_the_project_version(server: dict) -> None:
    assert server["version"] == _pyproject()["version"]
    assert _package(server)["version"] == _pyproject()["version"]


def test_the_package_is_the_one_this_repository_publishes_to_pypi(server: dict) -> None:
    package = _package(server)
    assert package["registryType"] == "pypi"
    assert package["registryBaseUrl"] == "https://pypi.org"
    assert package["identifier"] == _pyproject()["name"]


def test_the_package_name_is_also_a_console_script(server: dict) -> None:
    """A client that runs a PyPI package (for example with `uvx <identifier>`) runs the
    command of the same name, so that command has to exist."""
    assert _package(server)["identifier"] in _pyproject()["scripts"]


def test_it_runs_over_stdio_with_the_mcp_server_command(server: dict) -> None:
    """stdio only (ADR-020 §2), and the argument must be a command the CLI has."""
    package = _package(server)
    assert package["transport"] == {"type": "stdio"}
    assert package["packageArguments"] == [{"type": "positional", "value": "mcp-server"}]
    assert "mcp-server" in tm.get_command(cli_mod.app).commands


def test_the_repository_is_the_projects_repository(server: dict) -> None:
    assert server["repository"]["url"] == _pyproject()["urls"]["Repository"]
    assert server["repository"]["source"] == "github"


def test_the_namespace_belongs_to_the_repository_owner(server: dict) -> None:
    """`io.github.<owner>/` is the namespace a GitHub login can publish under."""
    match = re.fullmatch(r"https://github\.com/([^/]+)/([^/]+)", server["repository"]["url"])
    assert match, server["repository"]["url"]
    assert server["name"] == f"io.github.{match.group(1)}/{match.group(2)}"


def test_the_description_is_short(server: dict) -> None:
    """The registry caps descriptions (100 characters at the time of writing)."""
    assert 0 < len(server["description"]) <= 100, len(server["description"])


def test_the_owner_instructions_name_this_server(server: dict) -> None:
    """The publishing steps tell the owner which marker to put in the README, and the
    user guide names the entry to search for. Both must name the file's server."""
    marker = registry.ownership_marker(server)
    assert marker == "mcp-name: io.github.MSKazemi/yazses"
    assert marker in PACKAGING_README.read_text(encoding="utf-8")
    assert server["name"] in GUIDE.read_text(encoding="utf-8")


def test_the_template_carries_no_literal_version() -> None:
    """Rendered at release time, so there is no committed version to go stale, and
    tests/test_packaging_manifest_versions.py has nothing here to police."""
    text = TEMPLATE.read_text(encoding="utf-8")
    assert not re.search(r"\d+\.\d+\.\d+", text)
    assert text.count(registry.VERSION_TOKEN) == 2


# --- the version really comes from the tree being rendered -------------------


def _fake_tree(tmp_path: Path, version: str) -> Path:
    root = tmp_path / "tree"
    (root / "packaging" / "mcp-registry").mkdir(parents=True)
    shutil.copy(TEMPLATE, root / "packaging" / "mcp-registry" / "server.template.json")
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "yazses"\nversion = "{version}"\n', encoding="utf-8"
    )
    return root


def test_the_version_is_read_from_the_tree(tmp_path: Path) -> None:
    out = registry.render(_fake_tree(tmp_path, "97.5.3"))
    assert out["version"] == "97.5.3"
    assert out["packages"][0]["version"] == "97.5.3"


def test_a_non_release_version_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        registry.render(_fake_tree(tmp_path, "2.44.0.dev1"))


def test_write_is_deterministic_and_lands_in_the_given_directory(tmp_path: Path) -> None:
    first = registry.write(tmp_path / "a")
    second = registry.write(tmp_path / "b")
    assert first == tmp_path / "a" / "server.json"
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8")) == registry.render()


def test_main_prints_the_path_and_the_marker(tmp_path: Path, capsys) -> None:
    assert registry.main(["--out-dir", str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert Path(captured.out.strip()) == tmp_path / "server.json"
    assert "mcp-name: io.github.MSKazemi/yazses" in captured.err


# --- the file against the registry's own schema, offline -----------------------
#
# The registry publishes one JSON schema per dated release. The template's `$schema`
# names the current one, and a verbatim copy of it is vendored under
# tests/fixtures/mcp_registry/ so the check runs offline and without `jsonschema`
# (a dependency of the optional `mcp` SDK only, not of a base or dev install).
#
# Source:   https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json
# Fetched:  2026-10-30. The registry's docs at modelcontextprotocol/registry commit
#           72042e51 still name 2025-12-11 as the released schema (everything newer
#           is the CHANGELOG's "Draft (Unreleased)" section).
# Licence:  Apache-2.0 / MIT (the MCP project's LICENSE), compatible with ours.
#
# To move to a newer schema: vendor the new file verbatim, update SCHEMA_FILE and
# SCHEMA_CANONICAL_SHA256, and the template's `$schema`. The hash is over the parsed
# JSON, so a CRLF checkout on Windows does not change it, and an edit made to let a
# field through does.

SCHEMA_FILE = ROOT / "tests" / "fixtures" / "mcp_registry" / "server.schema.2025-12-11.json"
SCHEMA_CANONICAL_SHA256 = "64cff5eeae54d30932207dfb38324e12eeaeb4abaa09f73dc42c9a9ca319f76e"

#: Keywords that annotate and never reject. Anything else the walk meets that it does
#: not implement fails the test rather than passing silently.
_ANNOTATIONS = frozenset({
    "$comment", "$id", "$schema", "definitions", "description", "example", "examples",
    "default", "title",
})
_JSON_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "null": lambda v: v is None,
}


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))


def _is_uri(value: str) -> bool:
    parts = urlsplit(value)
    return bool(parts.scheme) and bool(parts.netloc or parts.path)


def _errors(node: dict, value, root: dict, at: str = "$") -> list[str]:
    """Draft-07 validation of the keywords the registry's schema uses. Small on purpose."""
    errors: list[str] = []
    for key, rule in node.items():
        if key in _ANNOTATIONS:
            continue
        if key == "$ref":
            assert rule.startswith("#/definitions/"), rule
            errors += _errors(root["definitions"][rule.rsplit("/", 1)[1]], value, root, at)
        elif key == "type":
            types = [rule] if isinstance(rule, str) else rule
            if not any(_JSON_TYPES[t](value) for t in types):
                errors.append(f"{at}: not of type {rule}")
        elif key == "required":
            if isinstance(value, dict):
                errors += [f"{at}: missing {name!r}" for name in rule if name not in value]
        elif key == "properties":
            if isinstance(value, dict):
                for name, sub in rule.items():
                    if name in value:
                        errors += _errors(sub, value[name], root, f"{at}.{name}")
        elif key == "additionalProperties":
            if isinstance(value, dict):
                for name in (k for k in value if k not in node.get("properties", {})):
                    if rule is False:
                        errors.append(f"{at}: unexpected {name!r}")
                    elif isinstance(rule, dict):
                        errors += _errors(rule, value[name], root, f"{at}.{name}")
        elif key == "items":
            if isinstance(value, list):
                for i, item in enumerate(value):
                    errors += _errors(rule, item, root, f"{at}[{i}]")
        elif key == "pattern":
            if isinstance(value, str) and not re.search(rule, value):
                errors.append(f"{at}: {value!r} does not match {rule}")
        elif key == "minLength":
            if isinstance(value, str) and len(value) < rule:
                errors.append(f"{at}: shorter than {rule}")
        elif key == "maxLength":
            if isinstance(value, str) and len(value) > rule:
                errors.append(f"{at}: longer than {rule}")
        elif key == "enum":
            if value not in rule:
                errors.append(f"{at}: {value!r} not in {rule}")
        elif key == "const":
            if value != rule:
                errors.append(f"{at}: {value!r} is not {rule!r}")
        elif key == "not":
            if not _errors(rule, value, root, at):
                errors.append(f"{at}: matches a forbidden schema {rule}")
        elif key == "anyOf":
            branches = [_errors(sub, value, root, at) for sub in rule]
            if all(branches):
                errors.append(f"{at}: matches none of anyOf: {branches}")
        elif key == "allOf":
            for sub in rule:
                errors += _errors(sub, value, root, at)
        elif key == "format":
            if rule != "uri":
                raise AssertionError(f"{at}: format {rule!r} is not implemented here")
            if isinstance(value, str) and not _is_uri(value):
                errors.append(f"{at}: {value!r} is not a uri")
        else:
            raise AssertionError(f"{at}: schema keyword {key!r} is not implemented here")
    return errors


def test_the_vendored_schema_is_the_published_one(schema: dict) -> None:
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == SCHEMA_CANONICAL_SHA256
    assert schema["$id"] == (
        "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    )


def test_the_template_names_the_vendored_schema(server: dict, schema: dict) -> None:
    """`mcp-publisher` rejects a file without `$schema`, and warns on a deprecated one."""
    assert server["$schema"] == schema["$id"]


def test_the_rendered_file_satisfies_the_registry_schema(server: dict, schema: dict) -> None:
    assert _errors(schema, server, schema) == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda s: s.pop("name"), "missing 'name'"),
        (lambda s: s.__setitem__("name", "yazses"), "does not match"),
        (lambda s: s.__setitem__("description", "x" * 101), "longer than 100"),
        (lambda s: s.__setitem__("websiteUrl", "not a url"), "is not a uri"),
        (lambda s: s["packages"][0].__setitem__("version", "latest"), "forbidden"),
        (lambda s: s["packages"][0].pop("transport"), "missing 'transport'"),
        (lambda s: s["packages"][0]["transport"].__setitem__("type", "carrier-pigeon"),
         "none of anyOf"),
        (lambda s: s["packages"][0]["packageArguments"][0].__setitem__("type", "flag"),
         "none of anyOf"),
    ],
)
def test_the_schema_check_rejects_what_the_registry_rejects(
    server: dict, schema: dict, mutate, expected: str
) -> None:
    """The offline check is not vacuous: each of these breaks one rule of the schema."""
    broken = json.loads(json.dumps(server))
    mutate(broken)
    errors = _errors(schema, broken, schema)
    assert any(expected in e for e in errors), errors


def test_the_package_is_on_a_registry_the_official_registry_accepts(server: dict) -> None:
    """official-registry-requirements.md: a PyPI package must use `https://pypi.org`
    exactly. The schema alone allows any URI there."""
    package = _package(server)
    assert (package["registryType"], package["registryBaseUrl"]) == ("pypi", "https://pypi.org")


# --- the ownership marker the registry reads from the PyPI description ----------


def test_the_pypi_description_is_the_readme() -> None:
    """The registry reads PyPI's `info.description`, which is `[project] readme`."""
    assert _pyproject()["readme"] == registry.README_REL == "README.md"


def test_the_readme_carries_the_ownership_marker(server: dict) -> None:
    text = (ROOT / registry.README_REL).read_text(encoding="utf-8")
    assert registry.contains_mcp_name_token(text, server["name"])
    registry.check_readme(server)  # the release job's guard agrees


@pytest.mark.parametrize(
    ("text", "accepted"),
    [
        # The forms the registry's mcpname.go documents as accepted.
        ("<!-- mcp-name: io.github.MSKazemi/yazses -->", True),
        ("<!-- mcp-name: io.github.MSKazemi/yazses-->", True),
        ("mcp-name: io.github.MSKazemi/yazses", True),
        ("mcp-name: io.github.MSKazemi/yazses\nmore", True),
        ("<p>mcp-name: io.github.MSKazemi/yazses</p>", True),
        # A prefix of a longer name, or a name glued to a full stop, is not the token.
        ("mcp-name: io.github.MSKazemi/yazses-pro", False),
        ("Listed as mcp-name: io.github.MSKazemi/yazses.", False),
        ("mcp-name:io.github.MSKazemi/yazses", False),
        # ... unless a proper occurrence appears later.
        ("mcp-name: io.github.MSKazemi/yazses-pro\nmcp-name: io.github.MSKazemi/yazses", True),
    ],
)
def test_the_marker_boundary_matches_the_registrys(text: str, accepted: bool) -> None:
    assert registry.contains_mcp_name_token(text, "io.github.MSKazemi/yazses") is accepted


# --- the release-time guards ------------------------------------------------------


def test_a_tag_that_is_not_the_version_is_refused(tmp_path: Path) -> None:
    root = _fake_tree(tmp_path, "97.5.3")
    assert registry.render(root, expect_tag="v97.5.3")["version"] == "97.5.3"
    with pytest.raises(ValueError, match="does not match"):
        registry.render(root, expect_tag="v97.5.2")


def test_a_readme_without_the_marker_writes_nothing(tmp_path: Path) -> None:
    root = _fake_tree(tmp_path, "97.5.3")
    (root / "README.md").write_text(
        "# YazSes\n\nmcp-name: io.github.MSKazemi/yazses.\n", encoding="utf-8"
    )
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="ownership marker"):
        registry.write(out, root, require_marker=True)
    assert not (out / "server.json").exists()


def test_main_refuses_a_wrong_tag_with_exit_1(tmp_path: Path, capsys) -> None:
    assert registry.main(["--out-dir", str(tmp_path), "--expect-tag", "v0.0.1"]) == 1
    assert "does not match" in capsys.readouterr().err
    assert not (tmp_path / "server.json").exists()


@pytest.mark.parametrize(
    ("info", "why"),
    [
        ({"name": "yazses", "version": "0.0.1"}, "not 'yazses'"),
        ({"name": "yazses-fork"}, "not 'yazses'"),
        ({"name": "yazses", "description": "mcp-name: io.github.MSKazemi/yazses-pro"},
         "does not carry"),
        ({"name": "yazses", "description": None}, "does not carry"),
    ],
)
def test_a_pypi_answer_the_registry_would_reject_is_refused(
    server: dict, info: dict, why: str
) -> None:
    info = {"version": server["version"], **info}
    with pytest.raises(ValueError, match=why):
        registry.check_pypi_release(server, {"info": info})


def test_the_pypi_answer_for_this_release_is_accepted(server: dict) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    registry.check_pypi_release(
        server, {"info": {"name": "yazses", "version": server["version"], "description": readme}}
    )


def test_main_with_the_release_flags_renders_this_tree(tmp_path: Path) -> None:
    tag = f"v{_pyproject()['version']}"
    assert registry.main(["--out-dir", str(tmp_path), "--expect-tag", tag, "--check-readme"]) == 0
    assert json.loads((tmp_path / "server.json").read_text(encoding="utf-8")) == registry.render()
