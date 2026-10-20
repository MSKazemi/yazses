"""The ``PackRuntime`` seam (ADR-028 §2, AGENTS.md rule 6): every OS backend satisfies
the Protocol, the factory dispatches without building a ``Platform``, nothing under
``packs/`` reads ``sys.platform``, and the Windows backend fails closed on elevation."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import yazses
from yazses.cameraperm.matrix import PACKAGE_PROFILES
from yazses.platform.base import PACK_INDEX_NAME, PackRuntime
from yazses.platform.factory import get_pack_runtime
from yazses.platform.linux.packs import UnsupportedPackRuntime
from yazses.platform.macos.packs import MacosPackRuntime
from yazses.platform.windows.packs import WindowsPackRuntime

PACKS = Path(yazses.__file__).resolve().parent / "packs"


@pytest.mark.parametrize("impl", [WindowsPackRuntime, UnsupportedPackRuntime, MacosPackRuntime])
def test_every_backend_satisfies_the_protocol(impl) -> None:
    assert isinstance(impl(), PackRuntime)


@pytest.mark.parametrize(
    ("platform", "cls", "supported"),
    [("win32", WindowsPackRuntime, True), ("darwin", MacosPackRuntime, False),
     ("linux", UnsupportedPackRuntime, False), ("freebsd14", UnsupportedPackRuntime, False)],
)
def test_the_factory_dispatches_on_the_platform(monkeypatch, platform, cls, supported) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    runtime = get_pack_runtime()
    assert type(runtime) is cls and runtime.supported() is supported


def test_nothing_under_packs_reads_sys_platform() -> None:
    files = sorted(PACKS.glob("*.py"))
    assert files, "guard the guard: the packs package was not found"
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == "platform"
                    and isinstance(node.value, ast.Name) and node.value.id == "sys"):
                pytest.fail(f"{path.name}:{node.lineno} reads sys.platform; ask PackRuntime")


def test_windows_elevation_fails_closed(monkeypatch) -> None:
    import yazses.platform.windows.permissions as perms

    monkeypatch.setattr(perms, "is_elevated", lambda: None)
    assert WindowsPackRuntime().is_elevated() is True
    monkeypatch.setattr(perms, "is_elevated", lambda: False)
    assert WindowsPackRuntime().is_elevated() is False

    def boom():
        raise RuntimeError("no token")

    monkeypatch.setattr(perms, "is_elevated", boom)
    assert WindowsPackRuntime().is_elevated() is True


def test_windows_index_and_probe_paths_when_frozen(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "_internal"), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "YazSesApp.exe"))
    rt = WindowsPackRuntime()
    assert rt.embedded_index_path() == tmp_path / "_internal" / PACK_INDEX_NAME
    argv = rt.probe_command("parakeet", tmp_path / "staged")
    assert argv == [str(tmp_path / "yazses-cli.exe"), "--cli", "packs", "probe", "parakeet",
                    "--staged", str(tmp_path / "staged")]


def test_windows_has_no_index_when_not_frozen(monkeypatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert WindowsPackRuntime().embedded_index_path() is None


def test_the_index_name_is_the_one_the_build_embeds() -> None:
    assert PACK_INDEX_NAME == "yazses-packs-index.json"


def test_only_the_windows_installer_profile_can_add_packs() -> None:
    """Phase 1 is the Inno `.exe` (winget rides with it). A frozen bundle still cannot
    pip-install: `can_add_packs` never implies `can_add_runtime`."""
    capable = {p.key for p in PACKAGE_PROFILES if p.can_add_packs}
    assert capable == {"windows-exe"}
    assert all(not p.can_add_runtime for p in PACKAGE_PROFILES if p.can_add_packs)


def test_the_windows_spec_registers_the_runtime_hook() -> None:
    """Without this line the hook file is dead code and no add-on ever loads."""
    root = Path(__file__).resolve().parents[1]
    spec = (root / "packaging/windows/yazses.spec").read_text(encoding="utf-8")
    assert 'runtime_hooks=[str(Path(SPECPATH) / "rthook_yazses_packs.py")]' in spec
    assert (root / "packaging/windows/rthook_yazses_packs.py").is_file()
