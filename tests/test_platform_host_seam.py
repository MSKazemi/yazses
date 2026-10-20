"""`describe_host()` is the one place a module learns which OS it is on.

`cameraperm.matrix.detect_profile_key` and `eyeeval.provenance` both used to branch on
`sys.platform` themselves, which AGENTS.md rule 6 reserves for the platform seam. The
behaviour they must keep is pinned in `test_host_facts_characterisation.py`; this file pins
the seam that now carries it: the `HostBackend` Protocol in `platform/base.py`, one
implementation per OS family, the dispatch in `platform/factory.py`, and a source-level guard
that the two callers (and any later caller of `describe_host`) stay off `sys.platform`.
"""
from __future__ import annotations

import ast
import dataclasses
import platform
import sys
from pathlib import Path

import pytest

from yazses.platform import HostBackend, HostInfo, describe_host
from yazses.platform.linux.host import LinuxHost
from yazses.platform.macos.host import MacosHost
from yazses.platform.windows.host import WindowsHost

SRC = Path(__file__).resolve().parent.parent / "src" / "yazses"
#: Modules that were moved off `sys.platform` by this seam and must stay off it.
SEAM_CALLERS = (SRC / "cameraperm" / "matrix.py", SRC / "eyeeval" / "provenance.py")


@pytest.mark.parametrize("impl", [LinuxHost, MacosHost, WindowsHost])
def test_every_backend_satisfies_the_protocol(impl) -> None:
    assert isinstance(impl(), HostBackend)


@pytest.mark.parametrize("impl", [LinuxHost, MacosHost, WindowsHost])
def test_every_backend_describes_the_running_process_without_raising(impl) -> None:
    """Describing a host must never fail a run, and must name the platform it saw."""
    info = impl().describe()
    assert isinstance(info, HostInfo)
    assert info.platform_name == sys.platform
    assert info.os_name and info.os_version
    assert info.ram_gb is None or info.ram_gb > 0


def test_the_description_carries_no_identifier_of_the_machine_or_person() -> None:
    """Shaped by what `METRICS.md` forbids collecting: no field can hold a hostname, user,
    serial, MAC or device UUID, so a backend cannot be written to leak one."""
    names = {f.name for f in dataclasses.fields(HostInfo)}
    assert names == {
        "platform_name", "os_name", "os_version", "ram_gb", "fixed_session_type", "msix_packaged",
    }
    for name in names:
        for forbidden in ("host", "user", "serial", "mac_", "uuid", "email"):
            assert forbidden not in name.replace("platform_name", ""), name


def test_the_factory_dispatches_on_the_platform(monkeypatch) -> None:
    monkeypatch.setattr(platform, "version", lambda: "10.0.1")
    monkeypatch.setattr(platform, "mac_ver", lambda: ("14.5", ("", "", ""), ""))
    for name, os_name, fixed in (
        ("win32", "Windows", "windows"),
        ("darwin", "macOS", "macos"),
    ):
        monkeypatch.setattr(sys, "platform", name)
        info = describe_host()
        assert (info.platform_name, info.os_name, info.fixed_session_type) == (name, os_name, fixed)
    for name in ("linux", "freebsd14", "someos1"):
        monkeypatch.setattr(sys, "platform", name)
        info = describe_host()
        assert info.platform_name == name
        assert info.fixed_session_type is None, "Linux/BSD session type depends on the environment"
        assert info.msix_packaged is False


def test_only_windows_can_be_msix_packaged(monkeypatch, tmp_path) -> None:
    (tmp_path / "AppxManifest.xml").write_text("<Package/>", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "yazses.exe"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert WindowsHost().describe().msix_packaged is True
    assert MacosHost().describe().msix_packaged is False
    assert LinuxHost().describe().msix_packaged is False
    monkeypatch.delattr(sys, "frozen")
    assert WindowsHost().describe().msix_packaged is False, "an unfrozen interpreter is no MSIX"


def test_an_os_with_no_backend_is_described_not_refused(monkeypatch) -> None:
    """`get_platform()` raises `UnsupportedPlatformError` there; a bug report still needs a
    description of what it ran on."""
    monkeypatch.setattr(sys, "platform", "plan9")
    monkeypatch.setattr(platform, "system", lambda: "Plan9")
    monkeypatch.setattr(platform, "release", lambda: "4")
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    info = describe_host()
    assert (info.platform_name, info.os_name, info.os_version) == ("plan9", "Plan9", "4")


# ------------------------------------------------------------ the callers stay off sys.platform


def _platform_reads(path: Path) -> list[int]:
    """Line numbers where this file reads ``sys.platform`` (attribute access on ``sys``)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "platform"
        and isinstance(node.value, ast.Name)
        and node.value.id == "sys"
    ]


@pytest.mark.parametrize("path", SEAM_CALLERS, ids=lambda p: p.name)
def test_a_seam_caller_does_not_read_sys_platform(path: Path) -> None:
    assert path.is_file(), f"{path} moved: this guard would be blind"
    assert _platform_reads(path) == [], (
        f"{path.name} reads sys.platform again; ask yazses.platform.describe_host() "
        f"(AGENTS.md rule 6)"
    )


def test_the_guard_does_see_a_sys_platform_read(tmp_path: Path) -> None:
    """Red-proof for the scanner above: it finds what it is meant to find."""
    probe = tmp_path / "probe.py"
    probe.write_text("import sys\nif sys.platform == 'win32':\n    pass\n", encoding="utf-8")
    assert _platform_reads(probe) == [2]
