"""Tray auto-launch gating + factory wiring."""
from dataclasses import replace

from yazses.config import Config, TrayConfig
from yazses.platform import get_platform
from yazses.tray.launch import should_launch_tray, tray_dependency_available


def _cfg(enabled=True):
    return replace(Config(), tray=TrayConfig(enabled=enabled))


def test_launch_requires_enabled_and_display():
    """The X11/Wayland half. `platform` is pinned because "no variables" only means
    "no desktop" on Linux/BSD -- on Windows and macOS it is the normal state, and
    leaving it to `sys.platform` made this file assert the opposite thing depending
    on which CI leg ran it. See tests/test_graphical_session_gate.py."""
    linux = {"platform": "linux"}
    assert should_launch_tray(_cfg(True), {"DISPLAY": ":0"}, **linux) is True
    assert should_launch_tray(_cfg(True), {"WAYLAND_DISPLAY": "wayland-0"}, **linux) is True
    assert should_launch_tray(_cfg(True), {}, **linux) is False           # no desktop
    assert should_launch_tray(_cfg(False), {"DISPLAY": ":0"}, **linux) is False  # disabled


def test_dependency_available_is_bool():
    assert isinstance(tray_dependency_available(), bool)


def test_linux_platform_has_tray_factory():
    p = get_platform()
    if p.name == "linux":
        assert p.tray_factory is not None
        assert p.tray_default_enabled is True
        from yazses.platform.base import TrayBackend

        assert isinstance(p.tray_factory(), TrayBackend)
