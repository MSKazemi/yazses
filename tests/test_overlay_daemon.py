"""Daemon-side wiring for the overlay: status fields + auto-launch gating."""

from yazses.config import Config
from yazses.core.daemon import (
    Daemon,
    overlay_dependency_available,
    should_launch_overlay,
)
from yazses.ipc.protocol import Request
from yazses.platform import get_platform


def _cfg(enabled: bool) -> Config:
    cfg = Config()
    cfg.overlay.enabled = enabled
    return cfg


def test_overlay_enabled_by_default():
    # On by default; the daemon still gates on a display + PySide6 at launch.
    assert Config().overlay.enabled is True


def test_should_launch_overlay_disabled():
    assert should_launch_overlay(_cfg(False), {"DISPLAY": ":0"}, platform="linux") is False


def test_should_launch_overlay_enabled_with_x11():
    assert should_launch_overlay(_cfg(True), {"DISPLAY": ":1"}, platform="linux") is True


def test_should_launch_overlay_enabled_with_wayland():
    assert should_launch_overlay(
        _cfg(True), {"WAYLAND_DISPLAY": "wayland-0"}, platform="linux"
    ) is True


def test_should_launch_overlay_enabled_but_headless():
    """Headless means headless *on Linux/BSD*; Windows and macOS are covered by
    tests/test_graphical_session_gate.py, where the answer is the opposite."""
    assert should_launch_overlay(_cfg(True), {}, platform="linux") is False


def test_status_exposes_audio_level_and_threshold():
    cfg = Config()
    cfg.accessibility.vad_threshold = 0.042
    daemon = Daemon(config=cfg, platform=get_platform())
    daemon._state.audio_level = 0.137

    status = daemon._handle_status(Request(method="status"))

    assert status["audio_level"] == 0.137
    assert status["vad_threshold"] == 0.042


def test_status_audio_level_defaults_to_zero():
    daemon = Daemon(config=Config(), platform=get_platform())
    status = daemon._handle_status(Request(method="status"))
    assert status["audio_level"] == 0.0


def test_overlay_dependency_available_reflects_pyside6(mocker):
    mocker.patch("importlib.util.find_spec", return_value=object())
    assert overlay_dependency_available() is True
    mocker.patch("importlib.util.find_spec", return_value=None)
    assert overlay_dependency_available() is False


def test_maybe_launch_overlay_skips_without_pyside6(mocker):
    """Default-on overlay must not spawn a doomed process when PySide6 is absent."""
    daemon = Daemon(config=_cfg(True), platform=get_platform())
    mocker.patch("yazses.core.daemon.should_launch_overlay", return_value=True)
    mocker.patch("yazses.core.daemon.overlay_dependency_available", return_value=False)
    popen = mocker.patch("yazses.core.daemon.subprocess.Popen")

    daemon._maybe_launch_overlay()

    popen.assert_not_called()
    assert daemon._overlay_proc is None


def test_maybe_launch_overlay_spawns_when_available(mocker):
    daemon = Daemon(config=_cfg(True), platform=get_platform())
    mocker.patch("yazses.core.daemon.should_launch_overlay", return_value=True)
    mocker.patch("yazses.core.daemon.overlay_dependency_available", return_value=True)
    popen = mocker.patch("yazses.core.daemon.subprocess.Popen")

    daemon._maybe_launch_overlay()

    popen.assert_called_once()
