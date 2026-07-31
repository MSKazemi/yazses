"""Tray auto-launch gating + factory wiring."""
from dataclasses import replace

from yazses.config import Config, TrayConfig
from yazses.platform import get_platform
from yazses.tray.launch import should_launch_tray, tray_dependency_available


def _cfg(enabled=True):
    return replace(Config(), tray=TrayConfig(enabled=enabled))


def test_launch_requires_enabled_and_display():
    assert should_launch_tray(_cfg(True), {"DISPLAY": ":0"}) is True
    assert should_launch_tray(_cfg(True), {"WAYLAND_DISPLAY": "wayland-0"}) is True
    assert should_launch_tray(_cfg(True), {}) is False           # no desktop
    assert should_launch_tray(_cfg(False), {"DISPLAY": ":0"}) is False  # disabled


def test_dependency_available_is_bool():
    assert isinstance(tray_dependency_available(), bool)


def test_linux_platform_has_tray_factory():
    p = get_platform()
    if p.name == "linux":
        assert p.tray_factory is not None
        assert p.tray_default_enabled is True
        from yazses.platform.base import TrayBackend

        assert isinstance(p.tray_factory(), TrayBackend)
