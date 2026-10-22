"""Tests for the platform factory and the Linux and Windows platform bundles."""

from __future__ import annotations

import sys

import pytest

from yazses.platform import (
    PermissionState,
    Platform,
    UnsupportedPlatformError,
    get_platform,
)
from yazses.platform.factory import reset_platform_cache


@pytest.fixture(autouse=True)
def _reset_cache():
    reset_platform_cache()
    yield
    reset_platform_cache()


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific bundle")
def test_factory_returns_linux_platform():
    p = get_platform()
    assert isinstance(p, Platform)
    assert p.name == "linux"
    assert p.default_hotkey == "right_alt"
    # Linux gained a PySide6 QSystemTrayIcon tray backend (top-bar indicator).
    assert p.tray_factory is not None
    assert p.tray_default_enabled is True


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific bundle")
def test_factory_is_cached():
    a = get_platform()
    b = get_platform()
    assert a is b


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific bundle")
def test_paths_are_populated():
    p = get_platform()
    assert p.paths.config_dir.name
    assert p.paths.state_dir.name
    assert p.paths.config_file.name == "config.toml"
    assert p.paths.pid_file.name == "daemon.pid"
    assert p.paths.ipc_socket.name == "daemon.sock"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific bundle")
def test_permissions_returns_known_state():
    p = get_platform()
    state = p.permissions.check_keyboard_capture()
    assert state in {
        PermissionState.OK,
        PermissionState.DENIED,
        PermissionState.UNKNOWN,
    }
    msg = p.permissions.how_to_grant()
    assert "input" in msg.lower()


def test_unsupported_platform_raises(monkeypatch):
    monkeypatch.setattr(sys, "platform", "haiku")
    reset_platform_cache()
    with pytest.raises(UnsupportedPlatformError):
        get_platform()


# ---- The Windows bundle -------------------------------------------------------
#
# The four tests above only ever ran on Linux, so on the windows-latest legs the
# factory's real Windows bundle was never built by a test at all.


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific bundle")
def test_factory_returns_windows_platform():
    from yazses.platform.base import WINDOWS_PLATFORM_NAME

    p = get_platform()
    assert isinstance(p, Platform)
    assert p.name == WINDOWS_PLATFORM_NAME
    # Right Alt is AltGr on many layouts; Right Ctrl types nothing (docs/windows-install.md).
    assert p.default_hotkey == "right_ctrl"
    assert p.tray_factory is not None
    assert p.tray_default_enabled is True
    # The Windows-only capabilities this bundle is the one place to wire up.
    assert p.update_launcher is not None
    assert p.pointer_factory is not None
    assert p.click_observer_factory is not None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific bundle")
def test_windows_factory_is_cached():
    assert get_platform() is get_platform()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific bundle")
def test_windows_paths_are_machine_local_not_roaming():
    """platform/windows/paths.py: a roaming profile would sync the PID file to another
    PC, and `yazses status` there would report on a daemon that is not running."""
    import os
    from pathlib import Path

    p = get_platform()
    local = Path(os.environ["LOCALAPPDATA"]).resolve()
    for d in (p.paths.config_dir, p.paths.state_dir, p.paths.data_dir):
        assert d.resolve().is_relative_to(local), f"{d} is not under %LOCALAPPDATA%"
    assert p.paths.config_file.name == "config.toml"
    assert p.paths.pid_file.name == "daemon.pid"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific bundle")
def test_windows_ipc_is_a_per_user_named_pipe():
    import getpass

    from yazses.platform.windows.ipc import _pipe_name_from_path

    name = _pipe_name_from_path(get_platform().paths.ipc_socket)
    assert name.startswith(r"\\.\pipe\yazses-")
    assert getpass.getuser() in name


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific bundle")
def test_windows_permissions_return_known_states():
    p = get_platform()
    known = {PermissionState.OK, PermissionState.DENIED, PermissionState.UNKNOWN}
    assert p.permissions.check_keyboard_capture() in known
    # Keyboard capture needs no grant on Windows; the remedy is about elevation.
    assert "administrator" in p.permissions.how_to_grant().lower()
