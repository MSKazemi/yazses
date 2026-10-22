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
* the ownership marker the owner is told to add to the README against the name in
  the file, so the instructions cannot name a server that is not the one published.

Nothing here contacts the registry or PyPI. Whether the registry accepts the file is
checked by the owner with `mcp-publisher`, by hand (packaging/README.md).
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path

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
