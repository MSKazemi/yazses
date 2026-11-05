"""`scripts/build-mcpb.py`: the one-click MCP bundle (ADR-032 §1, #638).

What is pinned, and why each one matters to a user:

* **The bundle runs the installed `yazses`, and ships nothing else.** Three entries:
  `manifest.json`, `icon.png` and a short Node launcher that runs `yazses mcp-server`
  and, when `yazses` is not on PATH, prints the install URL and exits 127 (#638). A
  bundle that carried YazSes or a runtime would be a second install with no model, no
  permission and no updater, which ADR-032 rejects by name.
* **The version comes from `pyproject.toml`**, shown here with a fabricated tree whose
  version no release ever had, so the check cannot pass by coincidence.
* **The tools the manifest advertises are the tools the server registers**, derived
  from `mcp/server.py::build_tools`, so the extension page cannot list a tool the
  server lacks (the same drift #641 found in `--help`).
* **Byte-for-byte reproducible**, so the release checksum vouches for a build anyone
  can repeat.

Nothing here touches the network or runs a client: an MCP client actually installing
the bundle is a test-day check on a real desktop.
"""
from __future__ import annotations

import ast
import dataclasses
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from yazses.config import Config
from yazses.mcp.server import build_tools

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build-mcpb.py"
TEMPLATE = ROOT / "packaging" / "mcpb" / "manifest.template.json"


def _load():
    spec = importlib.util.spec_from_file_location("build_mcpb", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["build_mcpb"] = module
    spec.loader.exec_module(module)
    return module


mcpb = _load()


def _pyproject_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _every_registered_tool() -> dict[str, str]:
    """name -> description, with every boolean `[mcp]` switch on."""
    cfg = Config()
    for field in dataclasses.fields(cfg.mcp):
        if isinstance(getattr(cfg.mcp, field.name), bool):
            object.__setattr__(cfg.mcp, field.name, True)
    return {tool.name: tool.description for tool in build_tools(cfg)}


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    return mcpb.build(tmp_path_factory.mktemp("mcpb"))


def _manifest(bundle: Path) -> dict:
    with zipfile.ZipFile(bundle) as zf:
        return json.loads(zf.read("manifest.json").decode("utf-8"))


# --- the artifact -------------------------------------------------------------


def test_the_bundle_is_named_for_the_project_version(built: Path) -> None:
    assert built.name == f"yazses-{_pyproject_version()}.mcpb"
    assert zipfile.is_zipfile(built)


def test_the_bundle_holds_a_manifest_an_icon_and_the_launcher_and_nothing_else(built: Path) -> None:
    """No wheel, no runtime, no model: the bundle contains no YazSes, only the launcher."""
    with zipfile.ZipFile(built) as zf:
        assert sorted(zf.namelist()) == ["icon.png", "manifest.json", "server/launcher.js"]
        assert zf.read("icon.png")[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_manifest_version_is_the_project_version(built: Path) -> None:
    assert _manifest(built)["version"] == _pyproject_version()


def test_the_manifest_runs_the_installed_mcp_server(built: Path) -> None:
    """The manifest runs the bundled launcher, and the launcher runs a bare `yazses`
    resolved on the user's PATH — never a copy of YazSes inside the bundle."""
    server = _manifest(built)["server"]
    assert server["type"] == "node"
    assert server["entry_point"] == "server/launcher.js"
    assert server["mcp_config"]["command"] == "node"
    assert server["mcp_config"]["args"] == ["${__dirname}/server/launcher.js"]
    with zipfile.ZipFile(built) as zf:
        launcher = zf.read("server/launcher.js").decode("utf-8")
    assert 'spawn("yazses", ["mcp-server"' in launcher


def test_the_manifest_points_at_the_install_page(built: Path) -> None:
    """ADR-032 §1: without `yazses` installed the bundle cannot work, so the text a
    client shows for it must say where to get YazSes."""
    manifest = _manifest(built)
    install = "https://mskazemi.com/yazses/get-started.html"
    assert install in manifest["description"]
    assert install in manifest["long_description"]


def test_the_manifest_icon_is_in_the_bundle(built: Path) -> None:
    with zipfile.ZipFile(built) as zf:
        assert _manifest(built)["icon"] in zf.namelist()


def test_the_advertised_tools_are_the_registered_tools(built: Path) -> None:
    """Names and descriptions both, derived from `build_tools` with every switch on."""
    advertised = {t["name"]: t["description"] for t in _manifest(built)["tools"]}
    assert advertised == _every_registered_tool()


def test_ask_human_is_described_as_opt_in(built: Path) -> None:
    """The extension page lists ask_human, which a default install does not offer, so
    the page has to say how it is turned on."""
    assert "`[mcp] ask_human = true`" in _manifest(built)["long_description"]


def test_two_builds_are_byte_identical(tmp_path: Path, built: Path) -> None:
    again = mcpb.build(tmp_path)
    assert again.read_bytes() == built.read_bytes()


def test_every_entry_has_the_fixed_timestamp_and_mode(built: Path) -> None:
    with zipfile.ZipFile(built) as zf:
        for info in zf.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0), info.filename
            assert info.external_attr >> 16 == 0o100644, info.filename
            assert info.compress_type == zipfile.ZIP_STORED, info.filename


def test_no_temporary_file_is_left_beside_the_bundle(built: Path) -> None:
    assert sorted(p.name for p in built.parent.iterdir()) == [built.name]


# --- the launcher: a missing `yazses` fails with the install URL (#638) ------------

INSTALL_URL = "https://mskazemi.com/yazses/get-started.html"
LAUNCHER = ROOT / "packaging" / "mcpb" / "launcher.js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def _extract_launcher(built: Path, tmp_path: Path) -> Path:
    out = tmp_path / "bundle"
    with zipfile.ZipFile(built) as zf:
        zf.extract("server/launcher.js", out)
    return out / "server" / "launcher.js"


def test_the_launcher_in_the_bundle_is_the_source_file(built: Path) -> None:
    with zipfile.ZipFile(built) as zf:
        assert zf.read("server/launcher.js") == LAUNCHER.read_bytes()


def test_the_install_url_in_the_launcher_is_the_one_in_the_manifest(built: Path) -> None:
    assert INSTALL_URL in LAUNCHER.read_text(encoding="utf-8")
    assert INSTALL_URL in _manifest(built)["description"]


@needs_node
def test_the_launcher_with_yazses_off_path_prints_the_install_url_and_exits_127(
    built: Path, tmp_path: Path
) -> None:
    """The real launcher, run by node with an EMPTY PATH so `yazses` cannot be found."""
    launcher = _extract_launcher(built, tmp_path)
    # An empty PATH, but not an empty environment: on Windows a process started without
    # SystemRoot cannot initialise (node aborted with status 134 on the hosted runner before
    # it ever ran the launcher), so those variables are carried over. `yazses` is still not
    # findable because PATH is empty.
    env = {"PATH": ""}
    for name in ("SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP"):
        if name in os.environ:
            env[name] = os.environ[name]
    result = subprocess.run(
        [NODE, str(launcher)],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 127
    assert INSTALL_URL in result.stderr
    assert "PATH" in result.stderr
    assert result.stdout == "", "stdout is the MCP channel; the hint must not go there"


@pytest.mark.skipif(sys.platform == "win32", reason="the fake yazses is a POSIX shell script")
@needs_node
def test_the_launcher_runs_the_installed_yazses_and_passes_its_status_through(
    built: Path, tmp_path: Path
) -> None:
    """With `yazses` on PATH the launcher is transparent: it runs `yazses mcp-server`,
    forwards stdout, and returns the command's own exit status."""
    launcher = _extract_launcher(built, tmp_path)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "yazses"
    fake.write_text('#!/bin/sh\necho "args:$*"\nexit 3\n', encoding="utf-8")
    fake.chmod(0o755)
    result = subprocess.run(
        [NODE, str(launcher)],
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout.strip() == "args:mcp-server"
    assert result.returncode == 3
    assert INSTALL_URL not in result.stderr


# --- the version really comes from pyproject ---------------------------------


def _fake_tree(tmp_path: Path, version: str) -> Path:
    root = tmp_path / "tree"
    (root / "packaging" / "mcpb").mkdir(parents=True)
    shutil.copy(TEMPLATE, root / "packaging" / "mcpb" / "manifest.template.json")
    for source in mcpb.EXTRA_FILES.values():
        (root / source).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / source, root / source)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "yazses"\nversion = "{version}"\n', encoding="utf-8"
    )
    return root


def test_the_version_is_read_from_the_tree_being_built(tmp_path: Path) -> None:
    root = _fake_tree(tmp_path, "97.5.3")
    bundle = mcpb.build(tmp_path / "out", root=root)
    assert bundle.name == "yazses-97.5.3.mcpb"
    assert _manifest(bundle)["version"] == "97.5.3"


@pytest.mark.parametrize("bad", ["2.44", "2.44.0rc1", "v2.44.0", ""])
def test_a_non_release_version_is_refused(tmp_path: Path, bad: str) -> None:
    root = _fake_tree(tmp_path, bad)
    with pytest.raises(ValueError):
        mcpb.build(tmp_path / "out", root=root)


# --- the release build refuses a tag that is not the version -----------------


def test_a_matching_tag_builds(tmp_path: Path) -> None:
    root = _fake_tree(tmp_path, "97.5.3")
    bundle = mcpb.build(tmp_path / "out", root=root, expect_tag="v97.5.3")
    assert bundle.name == "yazses-97.5.3.mcpb"


@pytest.mark.parametrize("tag", ["v97.5.4", "97.5.3", "v97.5.3-rc1", "V97.5.3", ""])
def test_a_tag_that_is_not_v_version_is_refused_and_nothing_is_written(
    tmp_path: Path, tag: str
) -> None:
    """The release job passes the pushed tag; a tag on an unbumped commit must not ship
    a bundle whose manifest names the previous release."""
    root = _fake_tree(tmp_path, "97.5.3")
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="does not match"):
        mcpb.build(out, root=root, expect_tag=tag)
    assert not out.exists() or not any(out.iterdir())


def test_main_reports_a_tag_mismatch_without_a_traceback(tmp_path: Path, capsys) -> None:
    tag = f"v{_pyproject_version()}.0"  # never a valid X.Y.Z tag, so never a match
    assert mcpb.main(["--out-dir", str(tmp_path), "--expect-tag", tag]) == 1
    assert "does not match" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.mcpb"))


def test_main_with_the_matching_tag_writes_the_bundle(tmp_path: Path, capsys) -> None:
    tag = f"v{_pyproject_version()}"
    assert mcpb.main(["--out-dir", str(tmp_path), "--expect-tag", tag]) == 0
    assert Path(capsys.readouterr().out.strip()).name == f"yazses-{_pyproject_version()}.mcpb"


# --- the template -------------------------------------------------------------


def test_the_template_carries_no_literal_version() -> None:
    """A literal version would be one more manifest to bump each release, and
    tests/test_packaging_manifest_versions.py would rightly demand a reader for it."""
    text = TEMPLATE.read_text(encoding="utf-8")
    assert not re.search(r'"version"\s*:\s*"\d+\.\d+\.\d+"', text)
    assert json.loads(text)["version"] == mcpb.VERSION_TOKEN


def test_an_unfilled_placeholder_is_refused() -> None:
    with pytest.raises(ValueError, match="@OTHER@"):
        mcpb.render_manifest({"version": "@VERSION@", "x": ["@OTHER@"]}, "1.2.3")


def test_render_fills_the_version_everywhere_and_leaves_the_rest() -> None:
    out = mcpb.render_manifest({"version": "@VERSION@", "n": 3, "l": ["v@VERSION@"]}, "1.2.3")
    assert out == {"version": "1.2.3", "n": 3, "l": ["v1.2.3"]}


# --- the script itself --------------------------------------------------------


def test_the_script_imports_only_the_standard_library_and_nothing_networked() -> None:
    """It runs under a bare python3 in a release job, and it has no business fetching
    anything: everything it packs is already in the checkout."""
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    imported.discard("__future__")
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)
    assert not imported & {"urllib", "http", "socket", "ssl", "ftplib", "subprocess"}, imported
    assert "yazses" not in imported


def test_main_writes_into_the_given_directory(tmp_path: Path, capsys) -> None:
    assert mcpb.main(["--out-dir", str(tmp_path)]) == 0
    printed = Path(capsys.readouterr().out.strip())
    assert printed.parent == tmp_path
    assert printed.is_file()
