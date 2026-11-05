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


def _page_min_width(qapp, page: str, device: str, monkeypatch) -> int:
    from yazses.audio.devices import InputDevice

    monkeypatch.setattr(
        SettingsWindow, "_probe_devices", lambda self: ([InputDevice(0, device, 2, True)], device)
    )
    rec = _Rec()
    win = SettingsWindow(
        build_settings_model(Config()), SettingsController(rec.load, rec.write, rec.probe)
    )
    # The Speech page's drop-downs hold model, language and backend names; give each an
    # entry of the same length, as a custom model or an unusual locale would be.
    for box in (win._model_box, win._language_box, win._profile_box, win._backend_box,
                win._compute_box, win._guard_box, win._consent_box):
        box.addItem(device)
    win._win.resize(win._win.minimumSize())
    win._win.show()
    win._shell.select(page)
    qapp.processEvents()
    area = win._shell.stack.currentWidget().findChildren(QScrollArea)[0]
    width = area.widget().minimumSizeHint().width()
    win._win.close()
    return width


@pytest.mark.parametrize("page", ["audio", "speech"])
def test_a_page_is_no_wider_for_a_long_device_name(qapp, restore_font, monkeypatch, page):
    """The width a page asks for must not depend on how long a device is called.

    Whether a page *fits* depends on the font (it differs by tens of pixels between
    DejaVu, Liberation and Noto), so that is not asserted. What the fix guarantees, in
    any font, is that the same page asks for the same width with a three-letter device
    and with a 120-character one.
    """
    font = qapp.font()
    font.setPointSizeF(16.0)
    qapp.setFont(font)
    short = _page_min_width(qapp, page, "Mic", monkeypatch)
    long = _page_min_width(qapp, page, "x" * 120, monkeypatch)
    assert long == short, page


def test_no_settings_dropdown_asks_for_more_than_the_compact_width(
    qapp, restore_font, monkeypatch
):
    """Every drop-down the window builds (bar the fixed key list) is capped, whatever it holds.

    Compared with a fresh compact combo in the same font, so the font cancels out.
    """
    from yazses.settingsui.app import _compact_combo

    font = qapp.font()
    font.setPointSizeF(16.0)
    qapp.setFont(font)
    win = _window(qapp, 16.0, monkeypatch)
    cap = _compact_combo().minimumSizeHint().width()
    capped = [
        c for c in win._win.findChildren(QComboBox) if c is not win._hotkey_box
    ]
    assert capped
    for combo in capped:
        assert combo.minimumSizeHint().width() <= cap, combo.accessibleName()
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
