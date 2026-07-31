"""Tests for the platform factory and the Linux platform bundle."""

from __future__ import annotations

import sys

import pytest

from yazses.platform import (
    Platform,
    PermissionState,
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
