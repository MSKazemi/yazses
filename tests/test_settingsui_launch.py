"""The settings window's launch gate (pure — no Qt, no display)."""
from yazses.settingsui.launch import has_display


def test_x11_session_has_a_display():
    assert has_display({"DISPLAY": ":0"}) is True


def test_wayland_session_has_a_display():
    assert has_display({"WAYLAND_DISPLAY": "wayland-0"}) is True


def test_bare_ssh_session_has_none():
    """No DISPLAY = Qt would abort() with a plugin dump; we must refuse first."""
    assert has_display({"TERM": "xterm", "SSH_CONNECTION": "..."}) is False


def test_empty_display_does_not_count():
    assert has_display({"DISPLAY": "", "WAYLAND_DISPLAY": ""}) is False


def test_explicit_qt_platform_is_honoured():
    """`QT_QPA_PLATFORM=offscreen` is how the headless smoke tests drive it."""
    assert has_display({"QT_QPA_PLATFORM": "offscreen"}) is True
