"""What `detect_profile_key` and the eye-eval provenance collector decide per OS.

Two modules read `sys.platform` directly -- `cameraperm.matrix.detect_profile_key` and
`eyeeval.provenance` -- which AGENTS.md rule 6 reserves for the platform seam. Moving them
behind `platform/base.py::HostBackend` must not change a single answer, so this file pins the
answers *first*, through the same entry points the callers use, with `sys.platform`, the
`platform` module, `/etc/os-release` and the filesystem faked. It passed against the code as
it was before the seam existed and must pass unchanged after.

The fakes target the outermost stable surface -- `sys.platform`, `sys.frozen`,
`sys.executable`, `platform.*`, `Path.read_text` -- rather than any helper that the move
renames, so the same assertions hold on both sides of the refactor.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

import pytest

from yazses.cameraperm.matrix import detect_profile_key
from yazses.eyeeval import provenance

OS_RELEASE = "/etc/os-release"


@pytest.fixture
def fake_os(monkeypatch):
    """Return a setter: ``fake_os("win32")`` makes this process look like that OS."""

    def _set(name: str, *, frozen: bool = False, executable: str | None = None) -> None:
        monkeypatch.setattr(sys, "platform", name)
        if frozen:
            monkeypatch.setattr(sys, "frozen", True, raising=False)
        elif hasattr(sys, "frozen"):
            monkeypatch.delattr(sys, "frozen")
        if executable is not None:
            monkeypatch.setattr(sys, "executable", executable)

    return _set


@pytest.fixture
def os_release(monkeypatch):
    """Serve a fake ``/etc/os-release`` (or its absence) without touching the real file."""
    real = Path.read_text

    def _install(content: str | None) -> None:
        def fake(self, *args, **kwargs):
            if str(self) == OS_RELEASE:
                if content is None:
                    raise FileNotFoundError(OS_RELEASE)
                return content
            return real(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", fake)

    return _install


# --------------------------------------------------------- cameraperm.matrix.detect_profile_key

NO_PACKAGING_ENV: dict[str, str] = {}


def test_a_frozen_windows_exe_with_an_appx_manifest_beside_it_is_msix(fake_os, tmp_path):
    (tmp_path / "AppxManifest.xml").write_text("<Package/>", encoding="utf-8")
    fake_os("win32", frozen=True, executable=str(tmp_path / "yazses.exe"))
    assert detect_profile_key(NO_PACKAGING_ENV) == "windows-msix"


def test_a_frozen_windows_exe_without_one_is_a_plain_exe(fake_os, tmp_path):
    fake_os("win32", frozen=True, executable=str(tmp_path / "yazses.exe"))
    assert detect_profile_key(NO_PACKAGING_ENV) == "windows-exe"


def test_an_unfrozen_windows_python_is_a_source_install_even_beside_a_manifest(fake_os, tmp_path):
    (tmp_path / "AppxManifest.xml").write_text("<Package/>", encoding="utf-8")
    fake_os("win32", frozen=False, executable=str(tmp_path / "python.exe"))
    assert detect_profile_key(NO_PACKAGING_ENV) == "source"


@pytest.mark.parametrize(
    ("platform_name", "frozen", "expected"),
    [
        ("darwin", True, "macos-app"),
        ("darwin", False, "source"),
        ("linux", True, "source"),
        ("linux", False, "source"),
        ("freebsd14", True, "source"),
    ],
)
def test_the_other_platforms(fake_os, tmp_path, platform_name, frozen, expected):
    # A manifest next to the interpreter must be ignored off Windows.
    (tmp_path / "AppxManifest.xml").write_text("<Package/>", encoding="utf-8")
    fake_os(platform_name, frozen=frozen, executable=str(tmp_path / "yazses"))
    assert detect_profile_key(NO_PACKAGING_ENV) == expected


def test_confinement_still_outranks_freezing_and_the_override_outranks_all(fake_os, tmp_path):
    fake_os("win32", frozen=True, executable=str(tmp_path / "yazses.exe"))
    assert detect_profile_key({"SNAP_NAME": "yazses"}) == "snap"
    assert detect_profile_key({"FLATPAK_ID": "com.mskazemi.YazSes"}) == "flatpak"
    assert detect_profile_key({"YAZSES_PACKAGE_FORMAT": "macos-app"}) == "macos-app"


# --------------------------------------------------------- eyeeval.provenance: the OS bucket


def test_windows_is_named_windows_with_its_build_number(fake_os, monkeypatch):
    fake_os("win32")
    monkeypatch.setattr(platform, "version", lambda: "10.0.22631")
    assert provenance._os_name_version() == ("Windows", "10.0.22631")


def test_windows_falls_back_to_the_release_when_the_version_is_empty(fake_os, monkeypatch):
    fake_os("win32")
    monkeypatch.setattr(platform, "version", lambda: "")
    monkeypatch.setattr(platform, "release", lambda: "11")
    assert provenance._os_name_version() == ("Windows", "11")


def test_macos_is_named_macos_with_mac_ver(fake_os, monkeypatch):
    fake_os("darwin")
    monkeypatch.setattr(platform, "mac_ver", lambda: ("14.5", ("", "", ""), "arm64"))
    assert provenance._os_name_version() == ("macOS", "14.5")


def test_macos_falls_back_to_the_release_when_mac_ver_is_empty(fake_os, monkeypatch):
    fake_os("darwin")
    monkeypatch.setattr(platform, "mac_ver", lambda: ("", ("", "", ""), ""))
    monkeypatch.setattr(platform, "release", lambda: "23.5.0")
    assert provenance._os_name_version() == ("macOS", "23.5.0")


def test_linux_reads_the_distribution_from_os_release(fake_os, os_release):
    fake_os("linux")
    os_release('NAME="Ubuntu"\nVERSION_ID="24.04"\nVERSION="24.04 LTS"\n')
    assert provenance._os_name_version() == ("Ubuntu", "24.04")


def test_linux_without_a_version_id_uses_version_then_unknown(fake_os, os_release):
    fake_os("linux")
    os_release('NAME=Arch Linux\nVERSION="rolling"\n')
    assert provenance._os_name_version() == ("Arch Linux", "rolling")
    os_release("NAME=Void\n")
    assert provenance._os_name_version() == ("Void", "unknown")


def test_a_system_with_no_os_release_is_named_by_platform_system(fake_os, os_release, monkeypatch):
    """The BSDs and any unrecognised OS take this path."""
    fake_os("freebsd14")
    os_release(None)
    monkeypatch.setattr(platform, "system", lambda: "FreeBSD")
    monkeypatch.setattr(platform, "release", lambda: "14.1-RELEASE")
    assert provenance._os_name_version() == ("FreeBSD", "14.1-RELEASE")
    monkeypatch.setattr(platform, "system", lambda: "")
    monkeypatch.setattr(platform, "release", lambda: "")
    assert provenance._os_name_version() == ("unknown", "unknown")


# --------------------------------------------------------- eyeeval.provenance: the session


def test_windows_and_macos_fix_the_session_type_when_the_environment_is_not_supplied(fake_os):
    fake_os("win32")
    assert provenance.session_type() == "windows"
    fake_os("darwin")
    assert provenance.session_type() == "macos"


def test_a_supplied_environment_is_the_only_input_even_on_windows_and_macos(fake_os):
    """`session_type(env)` is pure: the OS must not leak into a call that passed the world in."""
    for name in ("win32", "darwin"):
        fake_os(name)
        assert provenance.session_type({}) == "headless"
        assert provenance.session_type({"XDG_SESSION_TYPE": "x11"}) == "x11"


def test_linux_decides_the_session_from_the_environment(fake_os, monkeypatch):
    fake_os("linux")
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert provenance.session_type() == "wayland_kde"
    monkeypatch.delenv("XDG_SESSION_TYPE")
    assert provenance.session_type() == "headless"


# --------------------------------------------------------- eyeeval.provenance: RAM


def test_ram_comes_from_sysconf_where_the_os_has_it(fake_os, monkeypatch):
    fake_os("linux")
    values = {"SC_PHYS_PAGES": 4_000_000, "SC_PAGE_SIZE": 4096}
    monkeypatch.setattr(os, "sysconf", lambda name: values[name], raising=False)
    assert provenance._ram_gb() == round(4_000_000 * 4096 / 1e9, 1)


def test_ram_is_none_not_zero_when_nothing_can_say(fake_os, monkeypatch):
    for name in ("linux", "darwin", "win32"):
        fake_os(name)

        def refuse(_name):
            raise ValueError("no sysconf here")

        monkeypatch.setattr(os, "sysconf", refuse, raising=False)
        assert provenance._ram_gb() is None, name
