"""The Settings window must tell a crippled snap install why nothing works.

This is the other half of the application-grid launcher. The launcher is the
only route a GUI user has into YazSes -- they came from App Center, not a
terminal, so they never see `yazses doctor`, the startup log line or the store
description. Without the banner they click the new icon, meet an ordinary
settings window, and still do not know the microphone is not connected.
"""

from __future__ import annotations

import importlib.util

import pytest

from yazses.settingsui.controls import snap_interface_banner
from yazses.system import snap as snapmod


@pytest.fixture
def in_disconnected_snap(monkeypatch):
    monkeypatch.setenv("SNAP_NAME", "yazses")
    monkeypatch.setenv("SNAP", "/snap/yazses/current")
    monkeypatch.setattr(snapmod, "interface_connected", lambda plug, env=None: False)


@pytest.fixture
def in_healthy_snap(monkeypatch):
    monkeypatch.setenv("SNAP_NAME", "yazses")
    monkeypatch.setenv("SNAP", "/snap/yazses/current")
    monkeypatch.setattr(snapmod, "interface_connected", lambda plug, env=None: True)


def test_no_banner_outside_a_snap(monkeypatch) -> None:
    """A pipx user has no interfaces; a permission warning would be nonsense."""
    monkeypatch.delenv("SNAP_NAME", raising=False)
    monkeypatch.delenv("SNAP", raising=False)
    assert snap_interface_banner() is None


def test_no_banner_when_everything_is_connected(in_healthy_snap) -> None:
    assert snap_interface_banner() is None


def test_no_banner_when_the_state_is_unknown(monkeypatch) -> None:
    """An unrun probe must not paint a red banner over a working install."""
    monkeypatch.setenv("SNAP_NAME", "yazses")
    monkeypatch.setattr(snapmod, "interface_connected", lambda plug, env=None: None)
    assert snap_interface_banner() is None


def test_banner_names_both_missing_interfaces(in_disconnected_snap) -> None:
    text = snap_interface_banner()
    assert text is not None
    assert "audio-record" in text
    assert "raw-input" in text


def test_banner_carries_the_exact_commands(in_disconnected_snap) -> None:
    """The user has to copy these; prose about "connecting interfaces" is useless."""
    text = snap_interface_banner()
    assert "sudo snap connect yazses:audio-record" in text
    assert "sudo snap connect yazses:raw-input" in text
    assert "yazses restart" in text


def test_banner_explains_the_symptom_not_just_the_cause(in_disconnected_snap) -> None:
    """"Missing permission" alone does not match what the user is experiencing.

    What they see is an app that launched fine and types nothing, so the banner
    has to connect those two facts or it reads as unrelated pedantry.
    """
    assert "never hear you" in snap_interface_banner()


def test_banner_says_why_the_user_must_do_it(in_disconnected_snap) -> None:
    assert "cannot grant itself" in snap_interface_banner()


def test_banner_contains_no_prose_lines_among_the_commands(in_disconnected_snap) -> None:
    """Only runnable lines are indented, so a copy-paste of the block works."""
    body = snap_interface_banner().split("once:\n\n", 1)[1]
    for line in body.splitlines():
        if line.strip():
            assert line.strip().startswith(("sudo ", "yazses ")), line


# ---------------------------------------------------------------- real window

# NOT a module-level importorskip: that skipped the eight pure tests above as
# well, so the file reported "1 skipped" and covered nothing. Scope the skip to
# the two tests that actually need Qt.
needs_qt = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="the desktop extra (PySide6) is not installed",
)


@needs_qt
def test_the_real_window_builds_with_the_banner(in_disconnected_snap, monkeypatch):
    """Drive the actual Qt window offscreen.

    The pure half can be perfect while the render raises inside a Qt call, where
    nothing is visible -- which is exactly why this project already drives Apply
    offscreen rather than trusting the setters.
    """
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

    from yazses.settingsui.app import SettingsWindow

    app = QApplication.instance() or QApplication([])
    holder = QWidget()
    layout = QVBoxLayout(holder)
    SettingsWindow._add_snap_banner(object.__new__(SettingsWindow), layout)
    labels = [
        layout.itemAt(i).widget().text()
        for i in range(layout.count())
        if isinstance(layout.itemAt(i).widget(), QLabel)
    ]
    assert any("audio-record" in t for t in labels), labels
    assert app is not None


@needs_qt
def test_the_real_window_adds_nothing_when_healthy(in_healthy_snap, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

    from yazses.settingsui.app import SettingsWindow

    QApplication.instance() or QApplication([])
    # `holder` must stay referenced. `QVBoxLayout(QWidget())` lets the temporary
    # widget be collected, which deletes the C++ layout underneath the Python
    # wrapper and raises "Internal C++ object already deleted" on the next call.
    holder = QWidget()
    layout = QVBoxLayout(holder)
    SettingsWindow._add_snap_banner(object.__new__(SettingsWindow), layout)
    assert layout.count() == 0
    assert holder is not None
