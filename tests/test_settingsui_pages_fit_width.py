"""A long drop-down entry must not push a settings page into a sideways scrollbar.

A QComboBox asks for the width of its widest item. The microphone box holds
"Follow the system default (currently <the device's full ALSA name>)", about 800 px at
16 pt, so the Audio and Speech pages grew a horizontal scrollbar on a window that was
otherwise wide enough. The width policy has to be set when the box is built (Qt caches
the hint), and the long entry is then elided in the box and shown whole in the list.

Invariants only, relative to the window's own viewport; no pixel values and no fonts
beyond "larger than default", so a CI machine with other fonts reads the same.
Known and not covered here: the Features page and the Hands-free camera rows still
scroll sideways at large sizes.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QScrollArea  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.platform import get_platform  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402

_LONG_NAME = "HD-Audio Generic: ALC257 Analog (hw:1,0) " * 3
_LONG_DEVICE = f"Follow the system default (currently {_LONG_NAME})"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Rec:
    def load(self):
        return Config()

    def write(self, section, key, value, quote):
        pass

    def probe(self, modules):
        return []


def _window(qapp, point_size: float, monkeypatch):
    """Needs the ``restore_font`` fixture: the application font is process-wide."""
    from yazses.audio.devices import InputDevice

    # A real machine's sound card, with the long ALSA name real machines have.
    monkeypatch.setattr(
        SettingsWindow,
        "_probe_devices",
        lambda self: ([InputDevice(0, _LONG_NAME, 2, True)], _LONG_NAME),
    )
    font = qapp.font()
    font.setPointSizeF(point_size)
    qapp.setFont(font)
    rec = _Rec()
    win = SettingsWindow(
        build_settings_model(Config()),
        SettingsController(rec.load, rec.write, rec.probe),
    )
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    win._win.resize(win._win.minimumSize())
    win._win.show()
    qapp.processEvents()
    return win


@pytest.fixture
def restore_font(qapp):
    saved = qapp.font()
    yield
    qapp.setFont(saved)


@pytest.mark.parametrize("page", ["audio", "speech"])
def test_a_long_dropdown_entry_does_not_make_the_page_scroll_sideways(
    qapp, restore_font, monkeypatch, page
):
    win = _window(qapp, 16.0, monkeypatch)
    win._shell.select(page)
    qapp.processEvents()
    area = win._shell.stack.currentWidget().findChildren(QScrollArea)[0]
    content = area.widget()
    assert content.minimumSizeHint().width() <= area.viewport().width(), page
    assert area.horizontalScrollBar().maximum() == 0, page
    win._win.close()


def test_a_combo_is_not_as_wide_as_its_longest_entry(qapp, restore_font, monkeypatch):
    win = _window(qapp, 16.0, monkeypatch)
    combos = win._win.findChildren(QComboBox)
    assert combos
    mic = win._mic_box
    assert mic.findText(_LONG_DEVICE) >= 0, "the long entry must really be in the box"
    long_width = mic.fontMetrics().horizontalAdvance(_LONG_DEVICE)
    assert mic.minimumSizeHint().width() < long_width
    assert mic.sizeHint().width() < long_width
    win._win.close()


def test_the_hotkey_box_stays_content_sized(qapp, restore_font, monkeypatch):
    """The compact policy is for the free-text-ish boxes, not the fixed key list."""
    win = _window(qapp, 10.0, monkeypatch)
    assert win._hotkey_box.sizeAdjustPolicy() != QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
    win._win.close()


# ---- the General page says which key "auto" is ------------------------------------


def test_auto_hotkey_names_the_platform_default_in_the_page_text(qapp, restore_font):
    rec = _Rec()
    cfg = Config()
    cfg.hotkey.key = "auto"
    win = SettingsWindow(
        build_settings_model(cfg), SettingsController(rec.load, rec.write, rec.probe)
    )
    default = get_platform().default_hotkey
    assert default
    texts = [label.text() for label in win._win.findChildren(QLabel)]
    assert any("auto" in t and default in t for t in texts), texts
    win._win.close()


def test_an_explicit_hotkey_adds_no_auto_note(qapp, restore_font):
    rec = _Rec()
    cfg = Config()
    cfg.hotkey.key = "left_alt"
    win = SettingsWindow(
        build_settings_model(cfg), SettingsController(rec.load, rec.write, rec.probe)
    )
    assert win._hotkey_note.text() == ""
    # Choosing auto in the box brings the note back, naming the default.
    win._hotkey_box.setCurrentText("auto")
    assert get_platform().default_hotkey in win._hotkey_note.text()
    win._win.close()


def test_apply_and_the_sidebar_announce_the_ctrl_return_shortcut(qapp, restore_font):
    rec = _Rec()
    win = SettingsWindow(
        build_settings_model(Config()), SettingsController(rec.load, rec.write, rec.probe)
    )
    assert "Ctrl+Return" in win._apply_button.accessibleDescription()
    assert "Ctrl+Return" in win._shell.sidebar.accessibleDescription()
    win._win.close()
