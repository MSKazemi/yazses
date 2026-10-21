"""`yazses packs install --from <file>` (ADR-028 question 5, Phase 2): offline install.

The only trust anchor is the SHA-256 in **this build's embedded index**. These tests
build real ``.yazpack`` files in ``tmp_path`` and run the real transaction (real
extractor, real ABI match) with an injected probe. Every network primitive is replaced
by one that fails the test, so a pass also proves nothing reached the network.
"""
from __future__ import annotations

import json
import shutil
import socket
import types
import urllib.request
from pathlib import Path

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from tests.packs_fixtures import (
    OTHER_BUILD_ID,
    FakeRuntime,
    asset_name,
    base,
    build_pack,
    entry_dict,
    index_dict,
)
from yazses.packs import manage
from yazses.packs.context import PackContext
from yazses.packs.layout import COMPLETE, PackLayout
from yazses.packs.manifest import parse_index
from yazses.packs.policy import Capability
from yazses.system import installer_update

COMPONENT = "b-" + "a" * 12
runner = CliRunner()


def _no_network(*_a, **_k):
    raise AssertionError("an offline --from install reached a network primitive")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Every way this code base could reach the network fails the test."""
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    monkeypatch.setattr(installer_update.urllib.request, "build_opener", _no_network)
    monkeypatch.setattr(installer_update, "fetch_checksums", _no_network)
    monkeypatch.setattr(installer_update, "download_verified", _no_network)
    monkeypatch.setattr("yazses.packs.fetch.fetch_checksums", _no_network)
    monkeypatch.setattr("yazses.packs.fetch.download_verified", _no_network)
    monkeypatch.setattr("yazses.packs.fetch.fetch_pack", _no_network)


class World:
    def __init__(self, tmp_path: Path, *, entry_over: dict | None = None,
                 index_pack=None, **pack_kwargs) -> None:
        self.tmp = tmp_path
        self.carry = tmp_path / "usb"
        self.pack = build_pack(self.carry / asset_name("parakeet"), **pack_kwargs)
        listed = index_pack or self.pack
        entry = {**listed.entry(), **(entry_over or {})}
        self.index = parse_index(json.dumps(index_dict(entry)))
        self.layout = PackLayout.under(tmp_path / "data")
        self.probed: list[str] = []
        self.ctx = PackContext(
            runtime=FakeRuntime(), layout=self.layout, frozen=True,
            capability=Capability(True), index=self.index, base=base(),
        )

    def probe(self, name, staged):
        self.probed.append(name)
        assert (staged / "pack.json").is_file()
        return True, ""

    def run(self, path: Path | None = None, **kw):
        kw.setdefault("probe", self.probe)
        return manage.install_from_file(self.ctx, path or self.pack.path, **kw)

    @property
    def tree(self) -> Path:
        return self.layout.pack_dir(COMPONENT, "parakeet")

    def leftovers(self) -> list[str]:
        out: list[str] = []
        for d in (self.layout.staging, self.layout.downloads):
            if d.is_dir():
                out += [p.name for p in d.iterdir()]
        return out


def _refused(w: World, result, step: str) -> None:
    assert not result.ok, result.message
    assert result.step == step, (result.step, result.message)
    assert "Nothing was installed" in result.message or "nothing was installed" in result.message
    assert not w.tree.exists()
    assert w.leftovers() == [], w.leftovers()
    assert w.pack.path.is_file(), "the user's own file is never deleted"


def test_a_good_file_installs_offline_and_the_users_file_is_kept(tmp_path) -> None:
    w = World(tmp_path)
    result = w.run()
    assert result.ok, result.message
    assert (w.tree / "site" / "fakepkg_parakeet" / "core.py").is_file()
    assert (w.tree / COMPLETE).read_text(encoding="utf-8") == f"sha256 {w.pack.sha256}\n"
    assert w.probed == ["parakeet"], "the import probe still runs"
    assert w.leftovers() == [], "the copy in downloads/ is deleted after the install"
    assert w.pack.path.is_file(), "the file the user carried here is left alone"


def test_a_name_that_matches_the_file_is_accepted(tmp_path) -> None:
    w = World(tmp_path)
    assert w.run(name="parakeet").ok


def test_a_name_that_disagrees_with_the_file_is_refused(tmp_path) -> None:
    w = World(tmp_path)
    result = w.run(name="diarization")
    _refused(w, result, "check")
    assert "is the parakeet add-on, not diarization" in result.message


def test_a_wrong_hash_is_refused_and_nothing_is_installed(tmp_path) -> None:
    w = World(tmp_path, entry_over={"sha256": "c" * 64})
    result = w.run()
    _refused(w, result, "download")
    assert "did not match the checksum built into this copy" in result.message
    assert w.probed == [], "a refused file is never unpacked or probed"


def test_a_truncated_file_is_refused_by_its_size_before_any_copy(tmp_path) -> None:
    w = World(tmp_path)
    short = tmp_path / "short" / w.pack.path.name
    short.parent.mkdir()
    short.write_bytes(w.pack.path.read_bytes()[:-10])
    result = w.run(short)
    _refused(w, result, "download")
    assert f"{w.pack.size - 10:,} bytes" in result.message


def test_a_renamed_file_is_refused_even_with_the_right_hash(tmp_path) -> None:
    """The spec: the file name must equal the expected asset name."""
    w = World(tmp_path)
    renamed = tmp_path / "parakeet.yazpack"
    shutil.copyfile(w.pack.path, renamed)
    result = w.run(renamed)
    _refused(w, result, "check")
    assert "parakeet.yazpack is not an add-on file of this copy" in result.message
    assert asset_name("parakeet") in result.message, "it names the file it accepts"


def test_an_unknown_name_from_another_version_says_which_version(tmp_path) -> None:
    w = World(tmp_path)
    other = tmp_path / asset_name("parakeet", version="2.43.0")
    shutil.copyfile(w.pack.path, other)
    result = w.run(other)
    _refused(w, result, "check")
    assert "for YazSes 2.43.0, and this is YazSes 2.44.0" in result.message


def test_a_file_built_for_another_build_id_says_so(tmp_path) -> None:
    """Same file name, another build's pack: the hash differs, and the refusal names the
    build rather than calling the file damaged."""
    good = build_pack(tmp_path / "good" / asset_name("parakeet"))
    w = World(tmp_path, index_pack=good,
              manifest_over={"base_build_id": OTHER_BUILD_ID})
    result = w.run()
    _refused(w, result, "download")
    assert "made for a different build of YazSes" in result.message
    assert "b" * 12 in result.message and "a" * 12 in result.message


def test_another_build_id_is_refused_even_if_the_index_hash_matched(tmp_path) -> None:
    """Defence in depth: the ABI match after extraction still runs on a --from file."""
    w = World(tmp_path, manifest_over={"base_build_id": OTHER_BUILD_ID})
    result = w.run()
    _refused(w, result, "match")
    assert "does not belong to this copy" in result.message
    assert w.probed == []


def test_a_path_traversal_inside_the_archive_is_refused(tmp_path) -> None:
    """The hash matches (the index lists this very file), so only the archive validation
    stands between the member and the disk — and it still runs."""
    w = World(tmp_path, extra_members={"../evil.py": b"import os\n"})
    result = w.run()
    _refused(w, result, "extract")
    assert "was refused" in result.message
    assert not list(tmp_path.rglob("evil.py")), "the member was never written anywhere"


def test_a_missing_file_is_refused(tmp_path) -> None:
    w = World(tmp_path)
    result = w.run(tmp_path / "nowhere" / asset_name("parakeet"))
    assert not result.ok and result.step == "check"
    assert "is not a file" in result.message


def test_cancel_leaves_no_trace(tmp_path) -> None:
    w = World(tmp_path)
    result = w.run(cancel=lambda: True)
    assert not result.ok and result.step == "cancelled"
    assert w.leftovers() == [] and not w.tree.exists()


@pytest.mark.parametrize("over", [
    {"capability": Capability(False, "this process is elevated")},
    {"index": None, "index_error": "this build carries no add-on index"},
    {"base_problems": ("python 3.13 != 3.12",)},
])
def test_a_context_that_cannot_install_refuses_before_reading_the_file(tmp_path, over) -> None:
    w = World(tmp_path)
    w.ctx = PackContext(**{**w.ctx.__dict__, **over})
    result = w.run()
    assert not result.ok and result.step == "check"
    assert not w.layout.root.exists(), "nothing was created on disk"


def test_entry_for_file_is_exact_and_pure() -> None:
    index = parse_index(json.dumps(index_dict(entry_dict("parakeet"))))
    entry, problem = manage.entry_for_file(index, asset_name("parakeet"))
    assert entry is not None and entry.name == "parakeet" and problem == ""
    for name in (asset_name("parakeet").upper(), asset_name("parakeet") + ".zip",
                 "x" + asset_name("parakeet")):
        assert manage.entry_for_file(index, name)[0] is None, name


# ---- the CLI ------------------------------------------------------------------------

@pytest.fixture
def cli_world(monkeypatch, tmp_path):
    w = World(tmp_path)
    monkeypatch.setattr("yazses.packs.context.load_context", lambda **k: w.ctx)
    monkeypatch.setattr(manage, "subprocess_probe", lambda runtime: w.probe)
    return w


def _out(result) -> str:
    try:
        return result.output + result.stderr
    except ValueError:
        return result.output


def test_cli_from_installs_without_a_name_or_a_prompt(cli_world) -> None:
    result = runner.invoke(cli.app, ["packs", "install", "--from", str(cli_world.pack.path)])
    assert result.exit_code == 0, _out(result)
    assert "add-on is installed" in _out(result)
    assert "yazses restart" in _out(result)
    assert cli_world.tree.is_dir()


def test_cli_from_with_a_wrong_file_exits_one_and_says_why(cli_world, tmp_path) -> None:
    bad = tmp_path / "renamed.yazpack"
    shutil.copyfile(cli_world.pack.path, bad)
    result = runner.invoke(cli.app, ["packs", "install", "--from", str(bad)])
    assert result.exit_code == 1
    assert "not an add-on file of this copy" in _out(result)
    assert not cli_world.tree.exists()


def test_cli_without_a_name_or_from_is_a_usage_error(cli_world) -> None:
    result = runner.invoke(cli.app, ["packs", "install"])
    assert result.exit_code == 2
    assert "--from" in _out(result)


def test_cli_by_name_still_downloads_through_the_ordinary_install(cli_world, monkeypatch) -> None:
    seen: list[str] = []

    def fake_install(ctx, entry, *, progress=None, cancel=None):
        seen.append(entry.name)
        return types.SimpleNamespace(ok=True, message="installed", title="", steps=[])

    monkeypatch.setattr(manage, "install", fake_install)
    result = runner.invoke(cli.app, ["packs", "install", "parakeet", "--yes"])
    assert result.exit_code == 0, _out(result)
    assert seen == ["parakeet"]


def test_a_failed_download_tells_the_user_about_the_offline_route() -> None:
    """The #310 case: a firewall blocks github.com. The steps a failed download prints
    name the exact file and the command that installs it without the network."""
    from yazses.packs.fetch import manual_steps

    index = parse_index(json.dumps(index_dict(entry_dict("parakeet"))))
    steps = manual_steps(index, index.packs[0])
    assert any(asset_name("parakeet") in s and "/releases/download/v2.44.0/" in s
               for s in steps)
    assert any("yazses packs install --from" in s and asset_name("parakeet") in s
               for s in steps)
